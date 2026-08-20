import frappe
from frappe.tests.utils import FrappeTestCase

from lex.lex.doctype.lpo_matter.test_lpo_matter import (
	_make_customer,
	_make_matter,
)
from lex.lex.doctype.lpo_job.test_lpo_job import _make_job


class TestLPOComplianceLog(FrappeTestCase):
	def setUp(self):
		customer = _make_customer()
		self.engagement = _make_matter(customer)
		self.job = _make_job(self.engagement.name)

	def test_log_inherits_job_context(self):
		log = frappe.get_doc(
			{
				"doctype": "LPO Compliance Log",
				"engagement": self.engagement.name,
				"job": self.job.name,
				"compliance_type": "Confidentiality",
				"severity": "High",
				"status": "Open",
				"compliance_owner": "Administrator",
				"description": "Verify restricted document access.",
			}
		).insert()

		self.assertEqual(log.engagement, self.engagement.name)
		self.assertEqual(log.customer, self.engagement.customer)

	def test_resolution_requires_remediation(self):
		log = frappe.get_doc(
			{
				"doctype": "LPO Compliance Log",
				"engagement": self.engagement.name,
				"compliance_type": "AI Governance",
				"severity": "Critical",
				"status": "Resolved",
				"compliance_owner": "Administrator",
				"description": "AI processing required review.",
			}
		)
		with self.assertRaises(frappe.ValidationError):
			log.insert()
