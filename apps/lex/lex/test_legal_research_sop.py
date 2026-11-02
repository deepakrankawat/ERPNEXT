import frappe
from frappe.tests.utils import FrappeTestCase

from lex.legal_research_sop import (
	AI_REVIEW_CHECKS,
	SELF_REVIEW_REQUIRED_CHECKS,
	legal_research_turnaround,
	validate_execution,
	validate_generated_memo,
	validate_intake,
	validate_intake_payload,
	validate_self_review_checklist,
)


class TestLegalResearchSOP(FrappeTestCase):
	def test_legal_research_intake_requires_service_specific_fields(self):
		intake = frappe._dict(service_type="Legal Research")
		with self.assertRaises(frappe.MandatoryError):
			validate_intake(intake)

	def test_other_services_do_not_receive_legal_research_gate(self):
		validate_intake(frappe._dict(service_type="Contract Review"))

	def test_execution_requires_research_evidence_at_qa(self):
		job = frappe._dict(job_type="Legal Research", job_status="QA Review", research_log=[])
		with self.assertRaises(frappe.ValidationError):
			validate_execution(job)

	def test_self_review_rejects_incomplete_appendix_a(self):
		review = frappe._dict(review_stage="Self Review", qa_checklist=[])
		job = frappe._dict(job_type="Legal Research", research_log=[])
		with self.assertRaises(frappe.ValidationError):
			validate_self_review_checklist(review, job)

	def test_self_review_accepts_all_non_ai_appendix_a_checks(self):
		review = frappe._dict(
			review_stage="Self Review",
			qa_checklist=[frappe._dict(check_name=name, confirmed=1, result="Pass") for name in SELF_REVIEW_REQUIRED_CHECKS],
		)
		job = frappe._dict(job_type="Legal Research", research_log=[])
		validate_self_review_checklist(review, job)

	def test_ai_research_requires_verification_checks(self):
		review = frappe._dict(
			review_stage="Self Review",
			qa_checklist=[frappe._dict(check_name=name, confirmed=1, result="Pass") for name in SELF_REVIEW_REQUIRED_CHECKS],
		)
		job = frappe._dict(
			job_type="Legal Research",
			research_log=[frappe._dict(ai_assisted=1)],
		)
		with self.assertRaises(frappe.ValidationError):
			validate_self_review_checklist(review, job)
		for name in AI_REVIEW_CHECKS:
			review.qa_checklist.append(frappe._dict(check_name=name, confirmed=1, result="Pass"))
		validate_self_review_checklist(review, job)

	def test_api_intake_cannot_fall_back_to_generic_fields(self):
		with self.assertRaises(frappe.MandatoryError):
			validate_intake_payload({"service_type": "Legal Research"})

	def test_urgent_turnaround_requires_written_confirmation(self):
		deadline, note = legal_research_turnaround("Urgent")
		self.assertIsNone(deadline)
		self.assertIn("written", note)

	def test_generated_memo_requires_sop_sections(self):
		with self.assertRaises(frappe.ValidationError):
			validate_generated_memo("# Issue\nA question only")
		validate_generated_memo("# Issue\nA\n# Brief Answer\nA\n# Facts\nA\n# Analysis\nA\n# Conclusion\nA\n# Sources\nA")
