import hashlib
import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.file_manager import save_file

from lex.file_quarantine import release_internally_generated_file
from lex.lex.doctype.lpo_matter.test_lpo_matter import (
	_make_customer,
	_make_matter,
)
from lex.lex.doctype.lpo_job.test_lpo_job import _make_job


class TestLPOQAReview(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		customer = _make_customer()
		self.engagement = _make_matter(customer)
		self.job = _make_job(self.engagement.name)
		self.reviewer = _make_manager_user()
		source_content = b"QA-controlled source artifact"
		source_file = save_file("_test_qa_source.txt", source_content, "LPO Job", self.job.name, is_private=1)
		release_internally_generated_file(
			source_file.name,
			expected_checksum=hashlib.sha256(source_content).hexdigest(),
		)
		self.job.source_document = source_file.file_url
		self.job.save()
		self.job.job_status = "Activated"
		self.job.save()
		self.job.assigned_analyst = "Administrator"
		self.job.job_status = "Assigned"
		self.job.save()
		self.job.job_status = "In Progress"
		self.job.save()
		content = b"QA-controlled delivery artifact"
		file_doc = save_file("_test_qa_delivery.txt", content, "LPO Job", self.job.name, is_private=1)
		release_internally_generated_file(
			file_doc.name,
			expected_checksum=hashlib.sha256(content).hexdigest(),
		)
		self.job.delivery_document = file_doc.file_url
		self.job.job_status = "QA Review"
		self.job.save()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_review_inherits_job_context_and_completes(self):
		frappe.set_user(self.reviewer)
		review = frappe.get_doc(
			{
				"doctype": "LPO QA Review",
				"job": self.job.name,
				"reviewer": self.reviewer,
				"review_status": "Approved",
				"score": 96,
			}
		).insert()

		self.assertEqual(review.engagement, self.engagement.name)
		self.assertEqual(review.customer, self.engagement.customer)
		self.assertTrue(review.completed_on)
		self.assertTrue(review.reviewer_independent)
		self.assertEqual(review.reviewed_document, self.job.delivery_document)
		self.assertEqual(review.reviewed_document_checksum, self.job.delivery_document_checksum)
		self.assertEqual(frappe.db.get_value("LPO Job", self.job.name, "job_status"), "Ready for Delivery")
		self.assertEqual(frappe.db.get_value("LPO SOP Run", {"job_id": self.job.name}, "status"), "Completed")

	def test_job_execution_controls_are_pinned_and_evidenced(self):
		execution = frappe.get_doc(
			"LPO Workflow Execution",
			{"subject_type": "LPO Job", "subject_id": self.job.name},
		)
		self.assertEqual(str(execution.workflow_version), str(self.job.workflow_version_snapshot))
		self.assertEqual(execution.status, "Running")
		statuses = {row["job_status"] for row in json.loads(execution.execution_log_json)}
		self.assertTrue({"Assigned", "In Progress", "QA Review"}.issubset(statuses))
		sop_run = frappe.get_doc("LPO SOP Run", {"job_id": self.job.name})
		completed_ids = {row["step_id"] for row in json.loads(sop_run.completed_steps_json)}
		self.assertTrue({"scope", "sources", "deliverable"}.issubset(completed_ids))
		self.assertNotIn("qa", completed_ids)

	def test_changes_required_need_corrective_actions(self):
		frappe.set_user(self.reviewer)
		review = frappe.get_doc(
			{
				"doctype": "LPO QA Review",
				"job": self.job.name,
				"reviewer": self.reviewer,
				"review_status": "Changes Required",
			}
		)
		with self.assertRaises(frappe.ValidationError):
			review.insert()

	def test_changes_required_returns_job_to_execution(self):
		frappe.set_user(self.reviewer)
		frappe.get_doc(
			{
				"doctype": "LPO QA Review",
				"job": self.job.name,
				"reviewer": self.reviewer,
				"review_status": "Changes Required",
				"corrective_actions": "Correct the cited authority and regenerate the deliverable.",
			}
		).insert()

		self.assertEqual(frappe.db.get_value("LPO Job", self.job.name, "job_status"), "In Progress")

	def test_assigned_analyst_cannot_review_own_deliverable(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({
				"doctype": "LPO QA Review",
				"job": self.job.name,
				"reviewer": "Administrator",
				"review_status": "Approved",
			}).insert()

	def test_qa_approval_rejects_stale_delivery_version(self):
		frappe.set_user(self.reviewer)
		review = frappe.get_doc({
			"doctype": "LPO QA Review",
			"job": self.job.name,
			"reviewer": self.reviewer,
			"review_status": "In Review",
		}).insert()
		frappe.set_user("Administrator")
		content = b"Regenerated QA delivery artifact"
		file_doc = save_file("_test_qa_delivery_v2.txt", content, "LPO Job", self.job.name, is_private=1)
		release_internally_generated_file(
			file_doc.name,
			expected_checksum=hashlib.sha256(content).hexdigest(),
		)
		self.job.reload()
		self.job.delivery_document = file_doc.file_url
		self.job.save()
		frappe.set_user(self.reviewer)
		review.reload()
		review.review_status = "Approved"
		with self.assertRaises(frappe.ValidationError):
			review.save()

	def test_clearing_delivery_invalidates_sop_evidence(self):
		self.job.job_status = "In Progress"
		self.job.delivery_document = None
		self.job.save()

		sop_run = frappe.get_doc("LPO SOP Run", {"job_id": self.job.name})
		completed_ids = {row["step_id"] for row in json.loads(sop_run.completed_steps_json)}
		self.assertNotIn("deliverable", completed_ids)


def _make_manager_user():
	email = f"qa-manager-{frappe.generate_hash(length=10).lower()}@example.invalid"
	return frappe.get_doc({
		"doctype": "User",
		"email": email,
		"first_name": "Independent",
		"last_name": "QA Manager",
		"enabled": 1,
		"user_type": "System User",
		"send_welcome_email": 0,
		"roles": [{"role": "LPO_Manager"}],
	}).insert(ignore_permissions=True).name
