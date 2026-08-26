# Copyright (c) 2026, Lexocrates and contributors
# For license information, please see license.txt

from __future__ import annotations

import base64
import os
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from lex import ai_document_engine, ai_gateway, install


class TestAIDocumentProcessor(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		install.ensure_lpo_roles()
		ai_document_engine.ensure_default_ai_document_services()
		if frappe.db.exists("DocType", "LPO AI Model Registry"):
			from lex.ai_providers import mark_model_verification

			mark_model_verification("OpenAI", "gpt-4o", True)
		self.workflow_version = frappe.get_doc({
			"doctype": "LPO Workflow Version",
			"version": "TEST-1.0",
			"graph_json": '{"nodes":[{"id":"start","type":"Trigger","is_start":true}],"edges":[]}',
			"status": "Published",
			"approved_by": "Administrator",
		}).insert(ignore_permissions=True)
		self.sop_version = frappe.get_doc({
			"doctype": "LPO SOP Version",
			"version": "TEST-1.0",
			"status": "Effective",
			"steps_json": '[{"step_id":"review","title":"Review deliverable"}]',
		}).insert(ignore_permissions=True)

		# Ensure test client
		self.client_name = "TEST-DOC-CLIENT"
		if not frappe.db.exists("Customer", self.client_name):
			frappe.get_doc({
				"doctype": "Customer",
				"customer_name": self.client_name,
				"customer_type": "Company",
			}).insert(ignore_permissions=True)

		# Ensure test matter
		self.matter_doc = frappe.get_doc({
			"doctype": "LPO Matter",
			"matter_title": "Commercial Contract Review Matter",
			"customer": self.client_name,
			"practice_area": "Corporate & Commercial",
			"jurisdictions": "United States",
			"matter_manager": "Administrator",
			"workflow_version_snapshot": self.workflow_version.name,
			"sop_version_snapshot": self.sop_version.name,
		}).insert(ignore_permissions=True)

		# Ensure test job
		self.job_doc = frappe.get_doc({
			"doctype": "LPO Job",
			"job_title": "Master Services Agreement Review",
			"engagement": self.matter_doc.name,
			"customer": self.client_name,
			"job_type": "Contract Review",
			"job_status": "Draft",
			"assigned_analyst": "Administrator",
			"due_date": frappe.utils.add_days(frappe.utils.nowdate(), 7),
			"task_description": "Analyze MSA for uncapped liability and indemnity risks.",
		}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _advance_job_to_in_progress(self):
		self.job_doc.reload()
		for status in ("Activated", "Assigned", "In Progress"):
			self.job_doc.job_status = status
			self.job_doc.save(ignore_permissions=True)

	def test_system_user_access_control(self):
		"""Verify that only internal system users are permitted, while website/portal users are rejected."""
		# 1. Administrator should succeed
		frappe.set_user("Administrator")
		# Should not throw
		ai_document_engine._ensure_internal_system_user()

		# 2. Guest should fail with AuthenticationError
		frappe.set_user("Guest")
		with self.assertRaises(frappe.AuthenticationError):
			ai_document_engine._ensure_internal_system_user()

		# 3. Portal user without system role should fail with PermissionError
		portal_user_name = "test_portal_only_user@example.com"
		if not frappe.db.exists("User", portal_user_name):
			frappe.get_doc({
				"doctype": "User",
				"email": portal_user_name,
				"first_name": "Portal",
				"last_name": "Client",
				"roles": [{"role": "Lexocrates Read Only User"}],
			}).insert(ignore_permissions=True)

		frappe.set_user(portal_user_name)
		with self.assertRaises(frappe.PermissionError):
			ai_document_engine._ensure_internal_system_user()

	def test_text_extraction(self):
		"""Verify text extraction from plain text and file attachments."""
		frappe.set_user("Administrator")
		sample_text = "Section 1. Indemnification. Party A shall indemnify Party B for all liabilities up to $1,000,000."
		
		# Create a Frappe File
		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": "sample_contract.txt",
			"content": sample_text.encode("utf-8"),
			"attached_to_doctype": "LPO Job",
			"attached_to_name": self.job_doc.name,
			"is_private": 1,
		}).insert(ignore_permissions=True)

		extracted_text, checksum, w_cnt, c_cnt = ai_document_engine.extract_text_from_file(file_doc.file_url)
		self.assertEqual(extracted_text, sample_text)
		self.assertEqual(w_cnt, len(sample_text.split()))
		self.assertEqual(c_cnt, len(sample_text))
		self.assertTrue(len(checksum) == 64)

	def test_pdf_and_docx_text_extraction(self):
		"""PDF and DOCX legal text is extracted instead of being sent as a binary placeholder."""
		from io import BytesIO
		from zipfile import ZIP_DEFLATED, ZipFile

		from pypdf import PdfWriter
		from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

		pdf_buffer = BytesIO()
		writer = PdfWriter()
		page = writer.add_blank_page(width=612, height=792)
		font = DictionaryObject({
			NameObject("/Type"): NameObject("/Font"),
			NameObject("/Subtype"): NameObject("/Type1"),
			NameObject("/BaseFont"): NameObject("/Helvetica"),
		})
		page[NameObject("/Resources")] = DictionaryObject({
			NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
		})
		stream = DecodedStreamObject()
		stream.set_data(b"BT /F1 12 Tf 72 720 Td (Indemnity cap is INR 500000.) Tj ET")
		page[NameObject("/Contents")] = writer._add_object(stream)
		writer.write(pdf_buffer)
		pdf_file = frappe.get_doc({
			"doctype": "File",
			"file_name": "ai_contract.pdf",
			"content": pdf_buffer.getvalue(),
			"attached_to_doctype": "LPO Job",
			"attached_to_name": self.job_doc.name,
			"is_private": 1,
		}).insert(ignore_permissions=True)
		pdf_text, _, _, _ = ai_document_engine.extract_text_from_file(
			pdf_file.file_url, file_doc_name=pdf_file.name
		)
		self.assertIn("Indemnity cap is INR 500000", pdf_text)

		docx_buffer = BytesIO()
		with ZipFile(docx_buffer, "w", ZIP_DEFLATED) as archive:
			archive.writestr("[Content_Types].xml", "<Types/>")
			archive.writestr(
				"word/document.xml",
				'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
				"<w:body><w:p><w:r><w:t>Governing law is India.</w:t></w:r></w:p></w:body></w:document>",
			)
		docx_file = frappe.get_doc({
			"doctype": "File",
			"file_name": "ai_contract.docx",
			"content": docx_buffer.getvalue(),
			"attached_to_doctype": "LPO Job",
			"attached_to_name": self.job_doc.name,
			"is_private": 1,
		}).insert(ignore_permissions=True)
		docx_text, _, _, _ = ai_document_engine.extract_text_from_file(
			docx_file.file_url, file_doc_name=docx_file.name
		)
		self.assertIn("Governing law is India", docx_text)

	def test_service_seeding_and_prompt_interpolation(self):
		"""Verify standard services are seeded and prompt variables are correctly replaced."""
		frappe.set_user("Administrator")
		ai_document_engine.ensure_default_ai_document_services()

		# Check that all 7 services exist
		services = ["SUMMARIZE", "RISK_ANALYSIS", "EXTRACT_METADATA", "REDRAFT_POLISH", "TRANSLATE", "COMPLIANCE_CHECK", "CUSTOM_PROMPT"]
		for s in services:
			self.assertTrue(frappe.db.exists("LPO AI Document Service", s))

		# Test prompt interpolation
		template = "Analyze {{job_title}} under matter {{matter_title}} for {{customer_name}}.\nText: {{document_text}}"
		interpolated = ai_document_engine.interpolate_prompt(
			template=template,
			document_text="Clause 1: Confidentiality is strict.",
			job_doc={"job_title": "NDA Review", "customer_name": "Acme Corp"},
			matter_doc={"matter_title": "Acme IP Matter"},
		)
		self.assertIn("Analyze NDA Review", interpolated)
		self.assertIn("matter Acme IP Matter", interpolated)
		self.assertIn("for Acme Corp", interpolated)
		self.assertIn("Clause 1: Confidentiality is strict.", interpolated)

	@patch("lex.ai_document_engine.invoke_ai_gateway")
	def test_execute_document_service(self, mock_invoke):
		"""Verify running an AI Document service on an LPO Job creates execution records and updates processor."""
		frappe.set_user("Administrator")
		mock_invoke.return_value = {
			"response_text": "### Executive Summary\nThe contract is a standard NDA with 2-year confidentiality duration.",
			"tokens": 42,
			"cost": 0.001,
			"ai_execution": None,
		}

		res = ai_document_engine.process_job_document_service(
			job_id=self.job_doc.name,
			service_code="SUMMARIZE",
			custom_instructions="Focus on confidentiality duration.",
		)

		self.assertEqual(res["status"], "success")
		self.assertEqual(res["service_code"], "SUMMARIZE")
		self.assertIn("Executive Summary", res["output_text"])
		self.assertEqual(res["tokens_consumed"], 42)

		# Verify processor document created and child table populated
		processor = frappe.get_doc("LPO AI Document Processor", res["processor_id"])
		self.assertEqual(processor.job, self.job_doc.name)
		self.assertEqual(len(processor.services_applied), 1)
		self.assertEqual(processor.services_applied[0].service_code, "SUMMARIZE")
		self.assertEqual(processor.services_applied[0].status, "Completed")

	@patch("lex.ai_document_engine.invoke_ai_gateway")
	def test_multi_service_pipeline(self, mock_invoke):
		"""Verify multi-service pipeline chains execution and aggregates deliverable text."""
		frappe.set_user("Administrator")
		mock_invoke.side_effect = [
			{"response_text": "Summary: MSA Agreement between Acme and Beta.", "tokens": 30, "cost": 0.001},
			{"response_text": "Risk: Clause 9 has uncapped indemnity.", "tokens": 25, "cost": 0.001},
		]

		res = ai_document_engine.run_job_document_pipeline(
			job_id=self.job_doc.name,
			service_codes=["SUMMARIZE", "RISK_ANALYSIS"],
			custom_instructions="Highlight high liability items.",
		)

		self.assertEqual(res["status"], "success")
		self.assertEqual(len(res["pipeline_results"]), 2)
		self.assertEqual(res["total_tokens"], 55)
		self.assertIn("Pipeline Step: Executive Summarization", res["combined_output"])
		self.assertIn("Pipeline Step: Risk & Clause Analysis", res["combined_output"])

	@patch("lex.ai_gateway.invoke_ai_gateway")
	def test_job_chat_includes_only_clean_managed_documents(self, mock_invoke):
		"""Job Copilot extracts clean attachments and excludes quarantined files."""
		clean_file = frappe.get_doc({
			"doctype": "File",
			"file_name": "clean_job_context.txt",
			"content": b"Termination requires ninety days written notice.",
			"attached_to_doctype": "LPO Job",
			"attached_to_name": self.job_doc.name,
			"is_private": 1,
		}).insert(ignore_permissions=True)
		pending_file = frappe.get_doc({
			"doctype": "File",
			"file_name": "pending_job_context.txt",
			"content": b"This quarantined text must not reach the provider.",
			"attached_to_doctype": "LPO Job",
			"attached_to_name": self.job_doc.name,
			"is_private": 1,
		}).insert(ignore_permissions=True)
		frappe.db.set_value("File", clean_file.name, "custom_lex_scan_status", "Clean", update_modified=False)
		frappe.db.set_value("File", pending_file.name, "custom_lex_scan_status", "Pending", update_modified=False)

		inventory = ai_gateway.get_job_ai_attachments(self.job_doc.name)
		self.assertEqual(inventory["eligible_count"], 1)
		self.assertEqual(inventory["skipped_count"], 1)

		mock_invoke.return_value = {
			"response_text": "The agreement requires ninety days' written notice.",
			"tokens": 25,
			"ai_execution": "AI-TEST",
		}
		result = ai_gateway.chat_job_ai(
			job_id=self.job_doc.name,
			prompt="What is the termination notice period?",
			provider="OpenAI",
			model="gpt-4o",
			include_job_documents=1,
		)
		provider_prompt = mock_invoke.call_args.kwargs["prompt_text"]
		self.assertIn("ninety days written notice", provider_prompt)
		self.assertNotIn("quarantined text must not reach", provider_prompt)
		self.assertEqual(result["documents_included"][0]["file_name"], clean_file.file_name)
		self.assertEqual(result["documents_skipped"][0]["file_name"], pending_file.file_name)

	def test_complete_job_document(self):
		"""Verify document completion attaches deliverable file and updates Job status."""
		frappe.set_user("Administrator")
		final_text = "# Completed Master Services Agreement Deliverable\n\nAll terms reviewed and approved."
		frappe.db.set_value("LPO Matter", self.matter_doc.name, {
			"status": "Active",
			"quoted_amount": 100,
			"quote_status": "Approved",
		}, update_modified=False)
		self._advance_job_to_in_progress()

		res = ai_document_engine.complete_job_document(
			job_id=self.job_doc.name,
			final_text=final_text,
			update_job_status="Ready for Delivery",
			completion_notes="Final analyst sign-off.",
		)

		self.assertEqual(res["status"], "success")
		self.assertEqual(res["job_status"], "QA Review")
		self.assertTrue(bool(res["delivery_file_url"]))

		# Reload Job and verify deliverable document attachment
		job = frappe.get_doc("LPO Job", self.job_doc.name)
		self.assertEqual(job.job_status, "QA Review")
		self.assertEqual(job.delivery_document, res["delivery_file_url"])
		self.assertTrue(frappe.db.exists("File", {"file_url": job.delivery_document}))
		self.assertTrue(res["pdf_file_url"].endswith(".pdf"))
		self.assertEqual(job.delivery_document_version, res["export_version"])
		export = frappe.get_doc("LPO AI Document Export", {"job": job.name, "export_format": "PDF"})
		self.assertEqual(export.version, res["export_version"])
		self.assertEqual(export.file_checksum, job.delivery_document_checksum)

	def test_complete_job_document_as_pdf_and_docx(self):
		"""Both output creates secure, version-matched PDF and DOCX artifacts."""
		frappe.set_user("Administrator")
		frappe.db.set_value("LPO Matter", self.matter_doc.name, {
			"status": "Active",
			"quoted_amount": 100,
			"quote_status": "Approved",
		}, update_modified=False)
		self._advance_job_to_in_progress()
		final_text = """# Legal Review\n\n## Findings\n\n- Indemnity requires a cap.\n- Confidentiality survives termination.\n\n| Clause | Risk |\n|---|---|\n| Indemnity | High |"""

		res = ai_document_engine.complete_job_document(
			job_id=self.job_doc.name,
			final_text=final_text,
			update_job_status="QA Review",
			completion_notes="Generated for QA in both controlled formats.",
			output_format="Both",
			document_title="Advanced Legal Review",
			page_size="A4",
			document_style="Legal Professional",
			confidentiality_label="Privileged & Confidential",
		)

		self.assertEqual(res["output_format"], "Both")
		self.assertTrue(res["pdf_file_url"].endswith(".pdf"))
		self.assertTrue(res["docx_file_url"].endswith(".docx"))
		self.assertEqual(len(res["artifacts"]), 2)
		for format_name, artifact in res["artifacts"].items():
			file_doc = frappe.get_doc("File", artifact["file_id"])
			self.assertEqual(file_doc.is_private, 1)
			security = frappe.db.get_value(
				"File", file_doc.name, ["custom_lex_scan_status", "custom_lex_checksum"], as_dict=True
			)
			self.assertEqual(security.custom_lex_scan_status, "Clean")
			self.assertEqual(security.custom_lex_checksum, artifact["checksum"])
			self.assertTrue(frappe.db.exists("LPO AI Document Export", artifact["export_record"]))

		processor = frappe.get_doc("LPO AI Document Processor", res["processor_id"])
		self.assertEqual(processor.final_output_pdf, res["pdf_file_url"])
		self.assertEqual(processor.final_output_docx, res["docx_file_url"])
		self.assertEqual(processor.export_version, res["export_version"])

	def test_api_key_resolution_and_diagnostics(self):
		"""Verify multi-source API key resolution (DB, env, site_config) and connection diagnostics."""
		frappe.set_user("Administrator")
		from lex.lex.doctype.lpo_ai_settings.lpo_ai_settings import _get_provider_key, test_ai_provider_connection

		# 1. Test explicit key
		resolved = _get_provider_key(None, "OpenAI", explicit_key="sk-test-explicit-key-123456789")
		self.assertEqual(resolved, "sk-test-explicit-key-123456789")

		# 2. Test environment variable fallback
		with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-env-test-key-987654321"}):
			env_resolved = _get_provider_key(None, "OpenAI")
			self.assertEqual(env_resolved, "sk-env-test-key-987654321")

		# 3. Test connection diagnostic error handling with mock
		with patch("requests.post") as mock_post:
			mock_post.return_value.status_code = 401
			mock_post.return_value.text = "Unauthorized"
			mock_post.return_value.json.return_value = {"error": {"message": "Incorrect API key provided"}}

			test_res = test_ai_provider_connection("OpenAI", api_key="sk-invalid-key-12345", model="gpt-4o")
			self.assertEqual(test_res["status"], "error")
			self.assertEqual(test_res["error_type"], "AUTHENTICATION")
			self.assertIn("HTTP 401", test_res["message"])

		# 4. Test connection diagnostic success handling with mock
		with patch("requests.post") as mock_post:
			mock_post.return_value.status_code = 200
			mock_post.return_value.text = ""
			mock_post.return_value.headers = {"x-request-id": "req-test"}
			mock_post.return_value.json.return_value = {
				"id": "resp-test",
				"output_text": "CONNECTED",
				"usage": {"total_tokens": 2},
			}

			success_res = test_ai_provider_connection("OpenAI", api_key="sk-valid-mock-key-12345", model="gpt-4o")
			self.assertEqual(success_res["status"], "success")
			self.assertIn("CONNECTED", success_res["sample_response"])
