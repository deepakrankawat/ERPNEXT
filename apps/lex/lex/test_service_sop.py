import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch

from lex.service_sop import (
	PROFILES,
	copy_intake_snapshot_to_job,
	normalize_controls,
	populate_review_checklist,
	required_review_stages,
	set_turnaround,
	validate_intake_payload,
	validate_delivery_reviews,
	validate_execution,
	validate_review,
	validate_review_checklist,
)


class TestServiceSOP(FrappeTestCase):
	def _verified_controls(self, service, *, include_delivery=False):
		config = PROFILES[service]
		types = list(config["start_controls"])
		if include_delivery:
			types.extend(config["delivery_controls"])
		return [
			frappe._dict(
				control_type=control_type,
				control_detail="Verified test control",
				source_reference="Source / clause / order",
				event_date=frappe.utils.today() if control_type != "Review Protocol" else None,
				independently_verified=1,
				verified_by="Administrator",
				verification_date=frappe.utils.now_datetime(),
				status="Verified",
			)
			for control_type in types
		]

	def _execution_job(self, service, *, status="In Progress", delivery=False):
		return frappe._dict(
			job_type=service, job_status=status, engagement="TEST-MATTER",
			service_sop_preconditions_verified=1, service_sop_coordinator="Administrator",
			service_sop_data_residency_checked=1, service_sop_work_log="Verified and started.",
			peer_reviewer="peer@example.com", supervising_counsel="counsel@example.com",
			service_sop_review_tier="Filing/Court-Facing",
			service_sop_controls=self._verified_controls(service, include_delivery=delivery),
			service_sop_archive_complete=1 if delivery else 0,
			service_sop_archive_note="Saved in the Matter folder." if delivery else None,
			service_sop_delivery_cover_note="Scope, assumptions and outstanding items stated." if delivery else None,
		)

	def test_each_service_rejects_missing_service_instructions(self):
		for service in PROFILES:
			with self.assertRaises(frappe.MandatoryError):
				validate_intake_payload(service, {})

	def test_each_service_accepts_a_complete_server_side_intake(self):
		for service, config in PROFILES.items():
			details = {key: "verified test value" for key in config["fields"]}
			if service == "Drafting":
				details["review_tier"] = "Filing/Court-Facing"
			self.assertEqual(validate_intake_payload(service, details), details)

	def test_intake_snapshot_and_ai_restriction_are_copied_to_each_job(self):
		for service, config in PROFILES.items():
			details = {key: "verified test value" for key in config["fields"]}
			if service == "Drafting":
				details["review_tier"] = "Routine"
			intake = frappe._dict(service_sop_details=frappe.as_json(details), no_ai_tools=1)
			job = frappe._dict(job_type=service, service_sop_complexity_tier="Standard")
			copy_intake_snapshot_to_job(job, intake)
			self.assertEqual(job.service_sop_code, config["code"])
			self.assertEqual(job.service_sop_coordinator_role, config["coordinator"])
			self.assertEqual(job.ai_processing_allowed, 0)
			self.assertEqual(job.service_sop_client_prohibits_ai, 1)

	def test_drafting_requires_a_valid_review_tier(self):
		details = {key: "provided" for key in PROFILES["Drafting"]["fields"]}
		details["review_tier"] = "Invalid"
		with self.assertRaises(frappe.ValidationError):
			validate_intake_payload("Drafting", details)

	def test_drafting_review_tiers_have_the_required_gates(self):
		routine = frappe._dict(job_type="Drafting", service_sop_review_tier="Routine")
		client = frappe._dict(job_type="Drafting", service_sop_review_tier="Client-Facing")
		filing = frappe._dict(job_type="Drafting", service_sop_review_tier="Filing/Court-Facing")
		self.assertEqual(required_review_stages(routine), ("Self Review", "Final QC"))
		self.assertIn("Peer Review", required_review_stages(client))
		self.assertIn("Supervising Counsel Review", required_review_stages(filing))

	def test_document_review_requires_qc_sampling(self):
		job = frappe._dict(job_type="Document Review")
		self.assertIn("QC Sampling", required_review_stages(job))

	def test_all_sop_turnaround_profiles_are_deterministic(self):
		for service, config in PROFILES.items():
			standard = frappe._dict(job_type=service, service_sop_complexity_tier="Standard")
			complex_job = frappe._dict(job_type=service, service_sop_complexity_tier="Complex")
			urgent = frappe._dict(job_type=service, service_sop_complexity_tier="Urgent")
			set_turnaround(standard)
			set_turnaround(complex_job)
			set_turnaround(urgent)
			self.assertEqual(standard.service_sop_target_business_days, config["standard_days"])
			self.assertEqual(complex_job.service_sop_target_business_days, config["complex_days"])
			self.assertEqual(urgent.service_sop_target_business_days, 0)

	def test_all_sops_block_work_without_execution_evidence(self):
		for service in PROFILES:
			job = frappe._dict(job_type=service, job_status="In Progress")
			with self.assertRaises(frappe.ValidationError):
				validate_execution(job)

	def test_all_sops_allow_work_after_execution_evidence(self):
		for service in PROFILES:
			job = self._execution_job(service)
			with patch("lex.service_sop._matter_conflict_cleared", return_value=True):
				validate_execution(job)

	def test_delivery_is_blocked_until_archive_evidence_is_saved(self):
		job = self._execution_job("Litigation Support", status="Ready for Delivery")
		with patch("lex.service_sop._matter_conflict_cleared", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				validate_execution(job)
			job.service_sop_controls = self._verified_controls("Litigation Support", include_delivery=True)
			job.service_sop_archive_complete = 1
			job.service_sop_archive_note = "Saved in the Matter folder."
			job.service_sop_delivery_cover_note = "Scope and outstanding items stated."
			validate_execution(job)

	def test_execution_requires_the_profile_control_register(self):
		job = self._execution_job("Document Review")
		job.service_sop_controls = []
		with patch("lex.service_sop._matter_conflict_cleared", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				validate_execution(job)

	def test_control_register_gets_the_correct_service_warning_intervals(self):
		job = self._execution_job("Contract Review")
		normalize_controls(job)
		self.assertEqual(job.service_sop_controls[0].warning_intervals, "90 / 60 / 30 business days")
		job = self._execution_job("Litigation Support")
		normalize_controls(job)
		self.assertEqual(job.service_sop_controls[0].warning_intervals, "14 / 7 / 2 business days")

	def test_client_ai_prohibition_and_ai_verification_are_enforced(self):
		job = self._execution_job("Compliance Review")
		job.service_sop_client_prohibits_ai = 1
		job.service_sop_ai_used = 1
		with patch("lex.service_sop._matter_conflict_cleared", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				validate_execution(job)
		job.service_sop_client_prohibits_ai = 0
		with patch("lex.service_sop._matter_conflict_cleared", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				validate_execution(job)
		job.service_sop_ai_verification_note = "Primary regulator sources checked by reviewer."
		with patch("lex.service_sop._matter_conflict_cleared", return_value=True):
			validate_execution(job)

	def test_peer_review_cannot_skip_self_review(self):
		job = frappe._dict(job_type="Contract Review", name="TEST-SOP-JOB", peer_reviewer="peer@example.com")
		review = frappe._dict(review_stage="Peer Review", review_status="Approved", reviewer="peer@example.com")
		with patch("lex.service_sop.frappe.db.exists", return_value=False):
			with self.assertRaises(frappe.ValidationError):
				validate_review(review, job)
		with patch("lex.service_sop.frappe.db.exists", return_value=True):
			validate_review(review, job)

	def test_document_review_qc_sampling_cannot_skip_prior_reviews(self):
		job = frappe._dict(job_type="Document Review", name="TEST-SOP-JOB")
		review = frappe._dict(review_stage="QC Sampling", review_status="Approved", reviewer="qc@example.com")
		with patch("lex.service_sop.frappe.db.exists", return_value=False):
			with self.assertRaises(frappe.ValidationError):
				validate_review(review, job)
		with patch("lex.service_sop.frappe.db.exists", return_value=True) as exists:
			validate_review(review, job)
			self.assertEqual(exists.call_count, 2)  # Self Review and Peer Review

	def test_delivery_requires_every_service_review_stage(self):
		for service in PROFILES:
			job = frappe._dict(job_type=service, name="TEST-SOP-JOB", service_sop_review_tier="Filing/Court-Facing")
			with patch("lex.service_sop.frappe.db.exists", return_value=False):
				with self.assertRaises(frappe.ValidationError):
					validate_delivery_reviews(job)
			with patch("lex.service_sop.frappe.db.exists", return_value=True):
				validate_delivery_reviews(job)

	def test_service_self_review_checklist_is_seeded_and_required(self):
		job = frappe._dict(job_type="Contract Review")
		review = frappe.get_doc({"doctype": "LPO QA Review", "review_stage": "Self Review", "review_status": "Draft"})
		populate_review_checklist(review, job)
		self.assertEqual(len(review.qa_checklist), 3)
		review.review_status = "Approved"
		with self.assertRaises(frappe.ValidationError):
			validate_review_checklist(review, job)
		for row in review.qa_checklist:
			row.confirmed = 1
			row.result = "Pass"
		validate_review_checklist(review, job)
