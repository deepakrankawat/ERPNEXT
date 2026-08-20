from __future__ import annotations

import base64
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from lex import install, work_intake
from lex.lex.doctype.lexocrates_wallet_transaction.lexocrates_wallet_transaction import _post_transaction


class TestUploadFirstWorkIntake(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		install.ensure_lexpack_master_data()
		install.ensure_lexpack_catalog()
		self.client = _make_client()
		self.user = _make_user()
		self.portal_user = _make_portal_user(self.user.name, self.client)
		frappe.set_user(self.user.name)

	def tearDown(self):
		frappe.set_user("Administrator")

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
		analysis = work_intake.analyze_documents(intake["name"])
		# AI intake analysis is disabled by default (LexPack Settings), so the
		# deterministic formula estimates the price, and it must still wait for
		# CEO sign-off before the client can pay (auto_approve_ai_pricing is off).
		self.assertEqual(analysis["estimate_method"], "Formula")
		self.assertEqual(analysis["quote_status"], "Pending CEO Approval")
		self.assertGreater(analysis["required_lexpoints"], 0)
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
		result = work_intake.analyze_documents(intake["name"])
		self.assertEqual(result["status"], "Operations Review")
		self.assertEqual(result["quote_status"], "Operations Review")
		self.assertTrue(result["low_confidence"])

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
		analysis = work_intake.analyze_documents(intake["name"])
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

	def test_auto_approve_setting_skips_ceo_gate(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("LexPack Settings", "auto_approve_ai_pricing", 1)
		self.addCleanup(lambda: frappe.db.set_single_value("LexPack Settings", "auto_approve_ai_pricing", 0))
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
		analysis = work_intake.analyze_documents(intake["name"])
		self.assertEqual(analysis["pricing_approval_status"], "Not Required")
		self.assertEqual(analysis["quote_status"], "Ready")


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
