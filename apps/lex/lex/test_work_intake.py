from __future__ import annotations

import base64
from unittest.mock import patch

import frappe
from frappe.client import get as get_client_document
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from lex import ai_gateway, install, work_intake
from lex.lexpoint_estimation import ensure_default_lexpoint_rules
from lex.lex.doctype.lexocrates_wallet_transaction.lexocrates_wallet_transaction import _post_transaction
from lex.lex.doctype.lexpack_settings.lexpack_settings import set_ai_estimate_auto_approval


class TestUploadFirstWorkIntake(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.ai_policy_snapshot = frappe.db.get_value(
			"LexPack Settings",
			"LexPack Settings",
			[
				"enable_ai_intake_analysis",
				"auto_approve_ai_pricing",
				"auto_approve_ai_pricing_authorized_by",
				"auto_approve_ai_pricing_authorized_on",
			],
			as_dict=True,
		) or {}
		# Every test starts from the production-safe default. Individual tests
		# explicitly opt into AI/policy behavior and tearDown restores live state.
		frappe.db.set_value("LexPack Settings", "LexPack Settings", {
			"enable_ai_intake_analysis": 0,
			"auto_approve_ai_pricing": 0,
			"auto_approve_ai_pricing_authorized_by": None,
			"auto_approve_ai_pricing_authorized_on": None,
		}, update_modified=False)
		install.ensure_lexpack_master_data()
		install.ensure_lexpack_catalog()
		ensure_default_lexpoint_rules()
		self.client = _make_client()
		self.user = _make_user()
		self.portal_user = _make_portal_user(self.user.name, self.client)
		frappe.set_user(self.user.name)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.set_value(
			"LexPack Settings",
			"LexPack Settings",
			dict(self.ai_policy_snapshot),
			update_modified=False,
		)

	def test_sla_acceptance_is_a_hard_upload_gate(self):
		intake = _new_intake()
		with self.assertRaises(frappe.PermissionError):
			work_intake.upload_document(
				intake["name"], "instructions.txt", _text_upload("Confidential instructions")
			)
		doc = frappe.get_doc("Lexocrates Work Intake", intake["name"])
		self.assertFalse(doc.sla_accepted)
		self.assertEqual(doc.document_count, 0)
		self.assertFalse(doc.matter)

	def test_client_ai_access_is_limited_to_cost_estimation(self):
		intake = _new_intake()
		with self.assertRaises(frappe.PermissionError):
			work_intake.analyze_documents(intake["name"])
		with self.assertRaises(frappe.PermissionError):
			ai_gateway.invoke_ai_gateway(
				use_case="Job Legal Copilot",
				prompt_text="Analyze this legal document.",
				client_id=self.client,
			)

	def test_cost_estimate_does_not_run_general_legal_analysis(self):
		intake = _new_intake()
		work_intake.accept_sla(intake["name"], 1)
		work_intake.save_detailed_instructions(
			intake["name"], "Estimate the required scope and commercial effort for this agreement."
		)
		content = " ".join(["agreement obligations liability termination governing law"] * 20)
		with patch("lex.file_quarantine._run_malware_scan", return_value=("Clean", "Unit Test Scanner", "Clean")):
			work_intake.upload_document(intake["name"], "estimate-only.txt", _text_upload(content))
		with (
			patch(
				"lex.work_intake._run_governed_ai_analysis",
				side_effect=AssertionError("client endpoint must not run general legal analysis"),
			),
			patch("lex.work_intake._estimation_profile_with_ai", return_value=(None, "Formula test")),
		):
			result = work_intake.request_cost_estimate(intake["name"])
		self.assertGreater(result["required_lexpoints"], 0)
		self.assertNotIn("analysis_summary", result)
		self.assertNotIn("analysis_confidence", result)
		portal_doc = get_client_document("Lexocrates Work Intake", intake["name"])
		for fieldname in (
			"extracted_text", "analysis_summary", "analysis_provider", "ai_execution",
			"ai_document_estimate", "estimate_method",
		):
			self.assertIsNone(portal_doc.get(fieldname))

	def test_portal_intake_list_serializes_database_rows(self):
		intake = _new_intake()
		rows = work_intake.portal_intakes(self.portal_user)
		row = next(item for item in rows if item["name"] == intake["name"])
		self.assertEqual(row["status"], "SLA Pending")
		self.assertEqual(row["documents"], [])
		self.assertFalse(row["matter"])

	def test_existing_balance_confirms_matter_and_activates_job(self):
		intake = _new_intake()
		work_intake.accept_sla(intake["name"], 1)
		work_intake.save_detailed_instructions(
			intake["name"], "Review every clause and identify material commercial and legal risks."
		)
		content = " ".join(
			["agreement party obligations warranty indemnity liability termination governing law"] * 18
		)
		with patch("lex.file_quarantine._run_malware_scan", return_value=("Clean", "Unit Test Scanner", "Clean")):
			uploaded = work_intake.upload_document(
				intake["name"], "agreement.txt", _text_upload(content)
			)
		self.assertTrue(uploaded["quarantine_passed"])
		analysis = work_intake.request_cost_estimate(intake["name"])
		# AI intake analysis is disabled by default (LexPack Settings), so the
		# deterministic formula estimates the price, and it must still wait for
		# CEO sign-off before the client can pay (auto_approve_ai_pricing is off).
		self.assertEqual(analysis["quote_status"], "Pending CEO Approval")
		self.assertGreater(analysis["required_lexpoints"], 0)
		self.assertNotIn("estimate_method", analysis)
		self.assertNotIn("analysis_summary", analysis)
		self.assertNotIn("ai_execution", analysis)
		self.assertNotIn("extracted_text", analysis)
		self.assertNotIn("analysis_confidence", analysis)
		self.assertEqual(
			frappe.db.get_value("Lexocrates Work Intake", intake["name"], "estimate_method"),
			"Formula",
		)
		estimate_name = frappe.db.get_value("Lexocrates Work Intake", intake["name"], "ai_document_estimate")
		self.assertTrue(estimate_name)
		estimate = frappe.get_doc("LPO AI Document Estimate", estimate_name)
		self.assertEqual(estimate.work_intake, intake["name"])
		self.assertEqual(estimate.estimate_source, "Formula")
		self.assertEqual(estimate.proposed_lexpoints, analysis["required_lexpoints"])
		self.assertEqual(estimate.reviewed_lexpoints, analysis["required_lexpoints"])
		self.assertEqual(estimate.formula_version, "LEXPOINTS-1.0")
		self.assertEqual(estimate.recommended_service, "STANDARD_CONTRACT_REVIEW")
		self.assertTrue(estimate.factor_breakdown_json)
		self.assertTrue(estimate.explanation)
		self.assertFalse(frappe.db.get_value("Lexocrates Work Intake", intake["name"], "matter"))

		frappe.set_user("Administrator")
		_post_transaction(
			client=self.client,
			transaction_type="Purchase",
			points=250,
			idempotency_key=f"test-work-intake-balance:{intake['name']}",
		)
		frappe.set_user(self.user.name)
		with self.assertRaises(frappe.ValidationError):
			work_intake.fund_with_existing_lexpoints(intake["name"])

		frappe.set_user("Administrator")
		approval = work_intake.approve_quote_pricing(intake["name"], "Approved")
		self.assertEqual(approval["status"], "Quote Ready")

		frappe.set_user(self.user.name)
		result = work_intake.fund_with_existing_lexpoints(intake["name"])
		self.assertEqual(result["funding_route"], "Existing LexPoints")
		self.assertTrue(result["wallet_reservation"])
		self.assertTrue(result["sla_started_on"])
		self.assertEqual(frappe.db.get_value("LPO Matter", result["matter"], "status"), "Active")
		self.assertEqual(frappe.db.get_value("LPO Job", result["job"], "job_status"), "Activated")
		self.assertEqual(
			frappe.db.get_value("LPO Job", result["job"], "engagement"),
			result["matter"],
		)
		self.assertEqual(frappe.db.get_value("LPO Job", result["job"], "intake_estimate"), estimate_name)
		estimate.reload()
		self.assertEqual(estimate.status, "Activated")
		self.assertEqual(estimate.matter, result["matter"])
		self.assertEqual(estimate.job, result["job"])

		frappe.set_user("Administrator")
		estimate.actual_lexpoints = max(1, estimate.reviewed_lexpoints - 5)
		estimate.actual_hours = 3.5
		estimate.actual_delivery_hours = 20
		estimate.actual_reviewer = "Administrator"
		estimate.variance_reason = "Reference task completed with fewer review cycles."
		estimate.save()
		self.assertEqual(estimate.variance_lexpoints, -5)
		self.assertLess(estimate.variance_percent, 0)
		self.assertIn(estimate.calibration_status, {"Within Tolerance", "Needs Review"})

	def test_operations_can_edit_estimate_without_changing_ai_evidence(self):
		intake = _new_intake()
		work_intake.accept_sla(intake["name"], 1)
		work_intake.save_detailed_instructions(
			intake["name"], "Review all clauses and estimate legal effort with clear delivery assumptions."
		)
		content = " ".join(["agreement liability indemnity termination warranty governing law"] * 20)
		with patch("lex.file_quarantine._run_malware_scan", return_value=("Clean", "Unit Test Scanner", "Clean")):
			work_intake.upload_document(intake["name"], "estimate-source.txt", _text_upload(content))
		analysis = work_intake.request_cost_estimate(intake["name"])
		estimate_name = frappe.db.get_value("Lexocrates Work Intake", intake["name"], "ai_document_estimate")

		frappe.set_user("Administrator")
		estimate = frappe.get_doc("LPO AI Document Estimate", estimate_name)
		original_proposed = estimate.proposed_lexpoints
		estimate.reviewed_lexpoints = original_proposed + 15
		estimate.reviewed_amount = estimate.proposed_amount + 45
		estimate.reviewed_delivery_hours = estimate.proposed_delivery_hours + 6
		estimate.reviewed_scope = f"{estimate.proposed_scope}\nOperations added a senior-review requirement."
		estimate.review_notes = "Adjusted for senior legal review and additional jurisdiction complexity."
		estimate.save()
		self.assertTrue(estimate.changed_from_proposal)
		self.assertEqual(estimate.status, "Operations Review")
		self.assertEqual(frappe.db.get_value("Lexocrates Work Intake", intake["name"], "quote_status"), "Operations Review")

		with self.assertRaises(frappe.PermissionError):
			fresh = frappe.get_doc("LPO AI Document Estimate", estimate_name)
			fresh.proposed_lexpoints = original_proposed + 99
			fresh.save()

		result = work_intake.apply_document_estimate(estimate_name)
		self.assertEqual(result["quote_status"], "Pending CEO Approval")
		intake_doc = frappe.get_doc("Lexocrates Work Intake", intake["name"])
		self.assertEqual(intake_doc.required_lexpoints, original_proposed + 15)
		self.assertEqual(intake_doc.estimate_method, "Manual (Operations)")
		estimate.reload()
		self.assertEqual(estimate.status, "Pending CEO Approval")
		self.assertTrue(estimate.applied_to_intake_on)

		work_intake.approve_quote_pricing(intake["name"], "Approved")
		estimate.reload()
		self.assertEqual(estimate.status, "Approved")
		self.assertEqual(estimate.approval_status, "Approved")

	def test_low_confidence_routes_to_operations_review(self):
		intake = _new_intake()
		work_intake.accept_sla(intake["name"], 1)
		work_intake.save_detailed_instructions(
			intake["name"], "Review the scanned document and prepare a structured legal risk summary."
		)
		# A valid 1x1 PNG has no extractable legal text, so auto-quoting is blocked.
		png = base64.b64encode(
			base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII=")
		).decode()
		with patch("lex.file_quarantine._run_malware_scan", return_value=("Clean", "Unit Test Scanner", "Clean")):
			work_intake.upload_document(intake["name"], "scan.png", f"data:image/png;base64,{png}")
		result = work_intake.request_cost_estimate(intake["name"])
		self.assertEqual(result["status"], "Operations Review")
		self.assertEqual(result["quote_status"], "Operations Review")
		self.assertNotIn("low_confidence", result)
		self.assertTrue(
			frappe.db.get_value("Lexocrates Work Intake", intake["name"], "low_confidence")
		)

	def test_only_ceo_role_can_decide_pricing_and_rejection_returns_to_review(self):
		intake = _new_intake()
		work_intake.accept_sla(intake["name"], 1)
		work_intake.save_detailed_instructions(
			intake["name"], "Review every clause and identify material commercial and legal risks."
		)
		content = " ".join(
			["agreement party obligations warranty indemnity liability termination governing law"] * 18
		)
		with patch("lex.file_quarantine._run_malware_scan", return_value=("Clean", "Unit Test Scanner", "Clean")):
			work_intake.upload_document(intake["name"], "agreement.txt", _text_upload(content))
		analysis = work_intake.request_cost_estimate(intake["name"])
		self.assertEqual(analysis["pricing_approval_status"], "Pending CEO Approval")

		# The client (no CEO role) must not be able to approve their own quote.
		with self.assertRaises(frappe.PermissionError):
			work_intake.approve_quote_pricing(intake["name"], "Approved")

		frappe.set_user("Administrator")
		result = work_intake.approve_quote_pricing(
			intake["name"], "Rejected", notes="Estimate looks too low for this jurisdiction."
		)
		self.assertEqual(result["status"], "Operations Review")
		self.assertEqual(result["pricing_approval_status"], "Rejected")
		doc = frappe.get_doc("Lexocrates Work Intake", intake["name"])
		self.assertEqual(doc.pricing_rejection_reason, "Estimate looks too low for this jurisdiction.")

		with self.assertRaises(frappe.ValidationError):
			work_intake.approve_quote_pricing(intake["name"], "Approved")

	def test_formula_estimate_cannot_skip_human_gate_when_ai_policy_is_enabled(self):
		frappe.set_user("Administrator")
		frappe.db.set_value("LexPack Settings", "LexPack Settings", {
			"enable_ai_intake_analysis": 1,
			"auto_approve_ai_pricing": 1,
			"auto_approve_ai_pricing_authorized_by": "Administrator",
			"auto_approve_ai_pricing_authorized_on": now_datetime(),
		}, update_modified=False)
		frappe.set_user(self.user.name)

		intake = _new_intake()
		work_intake.accept_sla(intake["name"], 1)
		work_intake.save_detailed_instructions(
			intake["name"], "Review every clause and identify material commercial and legal risks."
		)
		content = " ".join(
			["agreement party obligations warranty indemnity liability termination governing law"] * 18
		)
		with patch("lex.file_quarantine._run_malware_scan", return_value=("Clean", "Unit Test Scanner", "Clean")):
			work_intake.upload_document(intake["name"], "agreement.txt", _text_upload(content))
		with patch("lex.work_intake._estimation_profile_with_ai", return_value=(None, "AI unavailable in test")):
			analysis = work_intake.request_cost_estimate(intake["name"])
		self.assertEqual(analysis["pricing_approval_status"], "Pending CEO Approval")
		self.assertEqual(analysis["quote_status"], "Pending CEO Approval")

	def test_ceo_policy_auto_approves_only_completed_high_confidence_ai_estimate(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("LexPack Settings", "enable_ai_intake_analysis", 1)
		with patch(
			"lex.lex.doctype.lpo_ai_settings.lpo_ai_settings.resolve_ai_route",
			return_value=("OpenAI", "gpt-test", "OpenAI Test"),
		):
			policy = set_ai_estimate_auto_approval(1)
		self.assertTrue(policy["enabled"])
		self.assertEqual(policy["authorized_by"], "Administrator")

		execution = frappe.get_doc({
			"doctype": "LPO AI Execution",
			"client": self.client,
			"correlation_id": f"auto-estimate-{frappe.generate_hash(length=8)}",
			"use_case": "Client Work Intake LexPoint Estimation",
			"provider": "OpenAI",
			"model": "gpt-test",
			"api_credential": "OpenAI Test",
			"status": "Completed",
			"evaluation_status": "Passed",
		}).insert(ignore_permissions=True)
		profile = {
			"document_type": "Commercial Agreement",
			"document_type_confidence": 96,
			"practice_modules": ["Contract Review"],
			"recommended_service": "Standard Contract Review",
			"legal_domain": "Commercial",
			"jurisdiction": "India",
			"jurisdiction_confidence": 95,
			"complexity_score": 45,
			"risk_level": "Medium",
			"reviewer_level": "Senior Associate",
			"volume": 1,
			"task_count": 1,
			"confidence": 94,
			"requires_human_review": False,
			"ai_execution": execution.name,
			"provider": "OpenAI",
			"model": "gpt-test",
			"credential_name": "OpenAI Test",
		}

		frappe.set_user(self.user.name)
		intake = _new_intake()
		work_intake.accept_sla(intake["name"], 1)
		work_intake.save_detailed_instructions(
			intake["name"], "Review every commercial clause and estimate the controlled legal effort."
		)
		content = " ".join(["agreement obligations liability termination governing law warranty"] * 25)
		with patch("lex.file_quarantine._run_malware_scan", return_value=("Clean", "Unit Test Scanner", "Clean")):
			work_intake.upload_document(intake["name"], "ai-estimate.txt", _text_upload(content))
		with patch("lex.work_intake._estimation_profile_with_ai", return_value=(profile, None)):
			result = work_intake.request_cost_estimate(intake["name"])

		self.assertEqual(result["status"], "Quote Ready")
		self.assertEqual(result["quote_status"], "Ready")
		self.assertEqual(result["pricing_approval_status"], "Not Required")
		doc = frappe.get_doc("Lexocrates Work Intake", intake["name"])
		self.assertEqual(doc.estimate_method, "AI-Assisted Formula")
		self.assertEqual(doc.pricing_approved_by, "Administrator")
		self.assertTrue(doc.pricing_approved_on)
		estimate = frappe.get_doc("LPO AI Document Estimate", doc.ai_document_estimate)
		self.assertEqual(estimate.status, "Approved")
		self.assertEqual(estimate.approval_status, "Not Required")
		# The existing funding gate accepts the auto-ready quote immediately.
		work_intake._validate_ready_quote(doc)

	def test_ai_human_review_flag_blocks_auto_approval(self):
		frappe.set_user("Administrator")
		frappe.db.set_value("LexPack Settings", "LexPack Settings", {
			"enable_ai_intake_analysis": 1,
			"auto_approve_ai_pricing": 1,
			"auto_approve_ai_pricing_authorized_by": "Administrator",
			"auto_approve_ai_pricing_authorized_on": now_datetime(),
		}, update_modified=False)
		execution = frappe.get_doc({
			"doctype": "LPO AI Execution",
			"client": self.client,
			"use_case": "Client Work Intake LexPoint Estimation",
			"provider": "OpenAI",
			"model": "gpt-test",
			"status": "Human Review",
			"evaluation_status": "Human Review",
		}).insert(ignore_permissions=True)
		profile = {
			"recommended_service": "Standard Contract Review",
			"document_type_confidence": 95,
			"jurisdiction": "India",
			"jurisdiction_confidence": 95,
			"complexity_score": 40,
			"risk_level": "Medium",
			"reviewer_level": "Senior Associate",
			"confidence": 94,
			"requires_human_review": True,
			"ai_execution": execution.name,
		}

		frappe.set_user(self.user.name)
		intake = _new_intake()
		work_intake.accept_sla(intake["name"], 1)
		work_intake.save_detailed_instructions(
			intake["name"], "Review this agreement and flag uncertainty for controlled human review."
		)
		content = " ".join(["agreement liability indemnity termination governing law"] * 25)
		with patch("lex.file_quarantine._run_malware_scan", return_value=("Clean", "Unit Test Scanner", "Clean")):
			work_intake.upload_document(intake["name"], "review-required.txt", _text_upload(content))
		with patch("lex.work_intake._estimation_profile_with_ai", return_value=(profile, None)):
			result = work_intake.request_cost_estimate(intake["name"])
		self.assertEqual(result["status"], "Operations Review")
		self.assertEqual(result["quote_status"], "Operations Review")

	def test_only_ceo_can_change_ai_auto_approval_policy(self):
		frappe.db.set_single_value("LexPack Settings", "enable_ai_intake_analysis", 1)
		with self.assertRaises(frappe.PermissionError):
			set_ai_estimate_auto_approval(1)
		frappe.set_user("Administrator")
		with patch(
			"lex.lex.doctype.lpo_ai_settings.lpo_ai_settings.resolve_ai_route",
			return_value=("OpenAI", "gpt-test", "OpenAI Test"),
		):
			result = set_ai_estimate_auto_approval(1)
		self.assertTrue(result["enabled"])
		self.assertEqual(result["credential_name"], "OpenAI Test")


def _new_intake():
	return work_intake.create_work_intake(
		intake_title="Test Supplier Agreement Review",
		service_type="Contract Review",
		jurisdiction="India",
		priority="Medium",
		expected_outcome="Risk-marked review memorandum",
		preliminary_details="Review commercial, liability and termination clauses.",
		confidentiality_level="Confidential",
	)


def _text_upload(text):
	return f"data:text/plain;base64,{base64.b64encode(text.encode()).decode()}"


def _make_client():
	suffix = frappe.generate_hash(length=10).lower()
	return frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": f"Work Intake Client {suffix}",
			"customer_type": "Company",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
		}
	).insert(ignore_permissions=True).name


def _make_user():
	email = f"work-intake-{frappe.generate_hash(length=12).lower()}@example.invalid"
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": "Work Intake",
			"last_name": "Client",
			"enabled": 1,
			"user_type": "Website User",
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True)


def _make_portal_user(user, client):
	return frappe.get_doc(
		{
			"doctype": "Lexocrates Portal User",
			"user": user,
			"client": client,
			"portal_role": "Client Administrator",
			"account_status": "Active",
			"matter_access_scope": "All Client Matters",
		}
	).insert(ignore_permissions=True)
