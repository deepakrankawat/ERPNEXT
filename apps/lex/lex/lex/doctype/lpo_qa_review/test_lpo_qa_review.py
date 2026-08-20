import frappe
from frappe.tests.utils import FrappeTestCase

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
