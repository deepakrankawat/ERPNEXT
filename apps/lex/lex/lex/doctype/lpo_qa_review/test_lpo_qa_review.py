import hashlib

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
		customer = _make_customer()
		self.engagement = _make_matter(customer)
		self.job = _make_job(self.engagement.name)
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

	def test_review_inherits_job_context_and_completes(self):
		review = frappe.get_doc(
			{
				"doctype": "LPO QA Review",
				"job": self.job.name,
				"reviewer": "Administrator",
				"review_status": "Approved",
				"score": 96,
			}
		).insert()

		self.assertEqual(review.engagement, self.engagement.name)
		self.assertEqual(review.customer, self.engagement.customer)
		self.assertTrue(review.completed_on)
		self.assertEqual(frappe.db.get_value("LPO Job", self.job.name, "job_status"), "Ready for Delivery")

	def test_changes_required_need_corrective_actions(self):
		review = frappe.get_doc(
			{
				"doctype": "LPO QA Review",
				"job": self.job.name,
				"reviewer": "Administrator",
				"review_status": "Changes Required",
			}
		)
		with self.assertRaises(frappe.ValidationError):
			review.insert()

	def test_changes_required_returns_job_to_execution(self):
		frappe.get_doc(
			{
				"doctype": "LPO QA Review",
				"job": self.job.name,
				"reviewer": "Administrator",
				"review_status": "Changes Required",
				"corrective_actions": "Correct the cited authority and regenerate the deliverable.",
			}
		).insert()

		self.assertEqual(frappe.db.get_value("LPO Job", self.job.name, "job_status"), "In Progress")
