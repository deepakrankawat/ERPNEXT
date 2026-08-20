import frappe
from frappe.tests.utils import FrappeTestCase

from lex.lex.doctype.lpo_matter.test_lpo_matter import (
	_make_customer,
	_make_matter,
)


class TestLPOJob(FrappeTestCase):
	def setUp(self):
		self.customer = _make_customer()
		self.engagement = _make_matter(self.customer)

	def test_parent_engagement_is_mandatory(self):
		job = _make_job(None, insert=False)
		with self.assertRaises(frappe.MandatoryError):
			job.insert()

	def test_job_inherits_engagement_governance(self):
		job = _make_job(self.engagement.name)

		self.assertEqual(job.customer, self.engagement.customer)
		self.assertEqual(job.practice_area, self.engagement.practice_area)
		self.assertEqual(job.jurisdictions, self.engagement.jurisdictions)
		self.assertEqual(job.confidentiality_level, self.engagement.confidentiality_level)

	def test_closed_engagement_rejects_new_jobs(self):
		self.engagement.status = "Closed"
		self.engagement.save()

		with self.assertRaises(frappe.ValidationError):
			_make_job(self.engagement.name)

	def test_engagement_cannot_close_with_open_jobs(self):
		_make_job(self.engagement.name)
		self.engagement.status = "Closed"

		with self.assertRaises(frappe.ValidationError):
			self.engagement.save()


def _make_job(engagement, insert=True, **values):
	doc = frappe.get_doc(
		{
			"doctype": "LPO Job",
			"job_title": "_Test Review Employment Agreement",
			"engagement": engagement,
			"job_type": "Contract Review",
			"job_status": "Draft",
			"priority": "Medium",
			"task_description": "Review the agreement and identify material risks.",
			"received_at": "2026-08-11 09:00:00",
			"due_date": "2026-08-12 09:00:00",
			**values,
		}
	)
	return doc.insert() if insert else doc
