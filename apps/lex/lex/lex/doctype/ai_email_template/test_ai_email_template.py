# Copyright (c) 2026, Lexocrates and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from lex.lex.doctype.ai_email_template.ai_email_template import (
	generate_email_for_lead,
	send_ai_generated_email,
)


class TestAIEmailTemplate(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("Lead", "TEST-LEAD-AI-01"):
			lead = frappe.get_doc({
				"doctype": "Lead",
				"lead_name": "Advocate Ramesh Sharma",
				"first_name": "Ramesh",
				"last_name": "Sharma",
				"company_name": "Sharma Legal Associates",
				"email_id": "ramesh.sharma@example.com",
				"industry": "Legal",
				"territory": "India",
			}).insert(ignore_permissions=True)

		if not frappe.db.exists("AI Email Template", "Test LPO Outreach"):
			tmpl = frappe.get_doc({
				"doctype": "AI Email Template",
				"template_name": "Test LPO Outreach",
				"subject": "Lexocrates & {{ company_name }} Partnership",
				"generate_subject_with_ai": 1,
				"tone": "Consultative & Advisory",
				"target_service": "Contract Review",
				"prompt": "Highlight our 30 pages/hour contract review and complimentary pilot for {{ company_name }}.",
				"max_tokens": 500,
			}).insert(ignore_permissions=True)

	@patch("lex.lex.doctype.ai_email_template.ai_email_template.invoke_ai_gateway")
	def test_generate_email_for_lead(self, mock_invoke):
		mock_invoke.return_value = {
			"ai_execution": "EXEC-001",
			"response_text": (
				"SUBJECT: Streamlining Contract Review for Sharma Legal Associates\n"
				"BODY:\n"
				"<p>Dear Ramesh,</p><p>We specialize in 30 pages/hr contract review with zero overhead.</p>"
			),
			"tokens": 120,
			"provider": "Google Gemini",
		}

		res = generate_email_for_lead(
			lead="TEST-LEAD-AI-01",
			template="Test LPO Outreach",
		)

		self.assertEqual(res["status"], "success")
		self.assertEqual(res["subject"], "Streamlining Contract Review for Sharma Legal Associates")
		self.assertIn("Dear Ramesh", res["body"])
		self.assertEqual(res["lead_name"], "Advocate Ramesh Sharma")
		self.assertEqual(res["company_name"], "Sharma Legal Associates")

	@patch("frappe.core.doctype.communication.email.make")
	def test_send_ai_generated_email(self, mock_make):
		mock_make.return_value = {"name": "COMM-TEST-001"}

		res = send_ai_generated_email(
			lead="TEST-LEAD-AI-01",
			subject="Test Subject",
			body="<p>Test Body</p>",
		)

		self.assertEqual(res["status"], "success")
		self.assertEqual(res["recipient"], "ramesh.sharma@example.com")
