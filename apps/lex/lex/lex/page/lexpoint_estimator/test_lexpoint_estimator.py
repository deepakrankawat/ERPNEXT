from __future__ import annotations

import base64
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from lex import install
from lex.lex.page.lexpoint_estimator import lexpoint_estimator
from lex.lexpoint_estimation import ensure_default_lexpoint_rules


def _upload(text: str) -> str:
	return "data:text/plain;base64," + base64.b64encode(text.encode()).decode()


class TestStandaloneLexPointEstimator(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		install.ensure_lexpack_master_data()
		install.ensure_lexpack_catalog()
		ensure_default_lexpoint_rules()

	def test_internal_estimate_is_not_linked_to_any_client_workflow(self):
		tracked_doctypes = (
			"Customer", "LPO Matter", "LPO Job", "Lexocrates Work Intake",
			"Sales Invoice", "Payment Entry", "LexPack Purchase",
		)
		before = {doctype: frappe.db.count(doctype) for doctype in tracked_doctypes}
		content = " ".join(
			["agreement obligations indemnity liability termination governing law confidential"] * 30
		)
		with (
			patch("lex.file_quarantine._run_malware_scan", return_value=("Clean", "Unit Test Scanner", "Clean")),
			patch(
				"lex.lex.page.lexpoint_estimator.lexpoint_estimator._estimation_profile_with_ai",
				return_value=(None, "Formula test"),
			),
		):
			result = lexpoint_estimator.estimate_document(
				filename="independent-contract.txt",
				content=_upload(content),
				service_type="Contract Review",
				jurisdiction="India",
				priority="Medium",
				expected_outcome="Estimate review effort only",
				detailed_instructions="Review all material commercial and legal risk clauses.",
				use_ai=1,
			)

		self.assertGreater(result["estimated_lexpoints"], 0)
		self.assertGreater(result["estimated_price"], 0)
		self.assertGreater(result["delivery_hours"], 0)
		self.assertEqual(result["estimate_source"], "Formula")
		record = frappe.get_doc("LPO Standalone Estimate", result["name"])
		self.assertEqual(record.status, "Complete")
		self.assertEqual(record.scan_status, "Clean")
		self.assertEqual(record.requested_by, "Administrator")
		self.assertFalse(record.meta.has_field("client"))
		self.assertFalse(record.meta.has_field("matter"))
		self.assertFalse(record.meta.has_field("job"))
		self.assertFalse(record.meta.has_field("work_intake"))
		file_row = frappe.db.get_value(
			"File",
			{"attached_to_doctype": record.doctype, "attached_to_name": record.name},
			["is_private", "custom_lex_scan_status"],
			as_dict=True,
		)
		self.assertTrue(file_row.is_private)
		self.assertEqual(file_row.custom_lex_scan_status, "Clean")
		self.assertEqual(before, {doctype: frappe.db.count(doctype) for doctype in tracked_doctypes})

	def test_direct_record_creation_is_blocked(self):
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "LPO Standalone Estimate",
					"estimate_title": "Bypass",
					"status": "Processing",
					"service_type": "Other",
					"jurisdiction": "India",
					"priority": "Medium",
				}
			).insert(ignore_permissions=True)

	def test_unsafe_extension_is_rejected_before_a_record_is_created(self):
		before = frappe.db.count("LPO Standalone Estimate")
		with self.assertRaises(frappe.ValidationError):
			lexpoint_estimator.estimate_document(
				filename="payload.exe",
				content=_upload("not executable"),
				service_type="Other",
			)
		self.assertEqual(before, frappe.db.count("LPO Standalone Estimate"))

	def test_website_user_cannot_open_or_run_the_estimator(self):
		email = "_test_standalone_estimator_website@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "Estimator Website",
					"enabled": 1,
					"user_type": "Website User",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		frappe.set_user(email)
		with self.assertRaises(frappe.PermissionError):
			lexpoint_estimator.get_estimator_bootstrap()
		with self.assertRaises(frappe.PermissionError):
			lexpoint_estimator.estimate_document(
				filename="blocked.txt",
				content=_upload("blocked"),
				service_type="Other",
			)
