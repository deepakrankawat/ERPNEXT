from __future__ import annotations

import io
from datetime import datetime

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.file_manager import save_file

from lex.pdf_watermark import (
	WatermarkContext,
	WatermarkIdentity,
	_watermarked_response,
	build_watermarked_pdf,
	install_private_pdf_download_guard,
	secure_pdf_download_url,
	watermark_system_user_pdf_response,
)


class TestPDFWatermark(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_every_page_contains_personalized_evidence_without_changing_source(self):
		from pypdf import PdfReader

		source = _source_pdf()
		source_snapshot = bytes(source)
		result, evidence = build_watermarked_pdf(
			source,
			identity=WatermarkIdentity(
				user="reviewer@example.com",
				full_name="Aarav Reviewer",
				portal_user="LPU-2026-00001",
				client="TEST-CLIENT",
				primary_role="Senior Legal Associate",
				user_type="System User",
			),
			context=WatermarkContext(matter="MAT-2026-00001", label="Job JOB-2026-00001 | Matter MAT-2026-00001"),
			download_id="DL-20260824-TEST000001",
			downloaded_on=datetime(2026, 8, 24, 18, 30, 15),
		)

		self.assertEqual(source, source_snapshot)
		self.assertNotEqual(result, source)
		self.assertTrue(result.startswith(b"%PDF-"))
		reader = PdfReader(io.BytesIO(result))
		self.assertEqual(len(reader.pages), 2)
		source_reader = PdfReader(io.BytesIO(source))
		for index, page in enumerate(reader.pages):
			text = page.extract_text() or ""
			self.assertIn("Aarav Reviewer", text)
			self.assertIn("reviewer@example.com", text)
			self.assertIn("Role: Senior Legal Associate", text)
			self.assertIn("DL-20260824-TEST000001", text)
			self.assertGreater(float(page.mediabox.height), float(source_reader.pages[index].mediabox.height))
		self.assertEqual(evidence["page_count"], 2)
		self.assertNotEqual(evidence["source_checksum"], evidence["download_checksum"])
		self.assertFalse(evidence["signed_source"])
		self.assertEqual(evidence["primary_role"], "Senior Legal Associate")
		self.assertEqual(evidence["user_type"], "System User")

	def test_generated_pdf_response_is_watermarked_for_system_user(self):
		from pypdf import PdfReader
		from werkzeug.wrappers import Request, Response

		request = Request.from_values("/api/method/frappe.utils.print_format.download_pdf")
		response = Response(_source_pdf(), content_type="application/pdf")
		response.headers["Content-Disposition"] = 'inline; filename="LPOJ-TEST.pdf"'
		watermark_system_user_pdf_response(response, request=request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.headers["X-Lexocrates-Watermark-Version"], "2")
		self.assertEqual(response.headers["Cache-Control"], "private, no-store, max-age=0")
		self.assertNotEqual(response.get_data(), _source_pdf())
		for page in PdfReader(io.BytesIO(response.get_data())).pages:
			text = page.extract_text() or ""
			self.assertIn("User ID: Administrator", text)
			self.assertIn("Role: Administrator", text)

	def test_generated_pdf_response_is_not_watermarked_twice(self):
		from werkzeug.wrappers import Request, Response

		request = Request.from_values("/api/method/frappe.utils.print_format.download_pdf")
		response = Response(_source_pdf(), content_type="application/pdf")
		watermark_system_user_pdf_response(response, request=request)
		first = response.get_data()
		first_id = response.headers["X-Lexocrates-Download-ID"]
		watermark_system_user_pdf_response(response, request=request)
		self.assertEqual(response.get_data(), first)
		self.assertEqual(response.headers["X-Lexocrates-Download-ID"], first_id)

	def test_generated_invalid_pdf_fails_closed_for_system_user(self):
		from werkzeug.wrappers import Request, Response

		request = Request.from_values("/api/method/frappe.utils.print_format.download_pdf")
		response = Response(b"not a pdf", content_type="application/pdf")
		watermark_system_user_pdf_response(response, request=request)
		self.assertEqual(response.status_code, 422)
		self.assertEqual(response.content_type, "application/json")
		self.assertNotIn(b"not a pdf", response.get_data())
		self.assertNotIn("Content-Disposition", response.headers)

	def test_generated_pdf_resolves_system_users_business_role(self):
		from pypdf import PdfReader
		from werkzeug.wrappers import Request, Response

		user = "pdf.role.watermark.test@lexocrates.test"
		if not frappe.db.exists("User", user):
			account = frappe.get_doc({
				"doctype": "User",
				"email": user,
				"first_name": "Watermark Role Tester",
				"user_type": "System User",
				"enabled": 1,
				"send_welcome_email": 0,
			}).insert(ignore_permissions=True)
			account.add_roles("LPO_Analyst")
		try:
			frappe.set_user(user)
			response = Response(_source_pdf(), content_type="application/pdf")
			watermark_system_user_pdf_response(
				response,
				request=Request.from_values("/api/method/frappe.utils.print_format.download_pdf"),
			)
			text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(response.get_data())).pages)
			self.assertIn(f"User ID: {user}", text)
			self.assertIn("Role: LPO_Analyst", text)
		finally:
			frappe.set_user("Administrator")

	def test_after_request_does_not_change_generated_pdf_for_website_user(self):
		from werkzeug.wrappers import Request, Response

		user = "pdf.website.watermark.test@lexocrates.test"
		if not frappe.db.exists("User", user):
			frappe.get_doc({
				"doctype": "User",
				"email": user,
				"first_name": "Website Watermark Tester",
				"user_type": "Website User",
				"enabled": 1,
				"send_welcome_email": 0,
			}).insert(ignore_permissions=True)
		source = _source_pdf()
		try:
			frappe.set_user(user)
			response = Response(source, content_type="application/pdf")
			watermark_system_user_pdf_response(
				response,
				request=Request.from_values("/api/method/frappe.utils.print_format.download_pdf"),
			)
			self.assertEqual(response.get_data(), source)
			self.assertNotIn("X-Lexocrates-Watermark-Version", response.headers)
		finally:
			frappe.set_user("Administrator")

	def test_password_protected_pdf_fails_closed(self):
		from pypdf import PdfWriter

		writer = PdfWriter()
		writer.add_blank_page(width=595, height=842)
		writer.encrypt("secret-password")
		buffer = io.BytesIO()
		writer.write(buffer)
		with self.assertRaises(frappe.ValidationError):
			build_watermarked_pdf(
				buffer.getvalue(),
				identity=WatermarkIdentity(user="Administrator", full_name="Administrator"),
				download_id="DL-20260824-ENCRYPTED1",
			)

	def test_frappe_managed_pdf_is_forced_into_private_storage(self):
		file_doc = save_file(
			fname="public-pdf-must-be-protected.pdf",
			content=_source_pdf(),
			dt=None,
			dn=None,
			is_private=0,
		)
		self.assertEqual(file_doc.is_private, 1)
		self.assertTrue(file_doc.file_url.startswith("/private/files/"))

		public_text = save_file(
			fname="public-non-pdf-control.txt",
			content=b"Public non-PDF control file",
			dt=None,
			dn=None,
			is_private=0,
		)
		self.assertEqual(public_text.is_private, 0)
		self.assertTrue(public_text.file_url.startswith("/files/"))

	def test_download_response_is_audited_and_original_file_is_unchanged(self):
		from pypdf import PdfReader

		source = _source_pdf()
		file_doc = save_file(
			fname="protected-download-test.pdf",
			content=source,
			dt=None,
			dn=None,
			is_private=1,
		)
		response = _watermarked_response(file_doc)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.content_type, "application/pdf")
		self.assertEqual(response.headers["Cache-Control"], "private, no-store, max-age=0")
		self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
		self.assertIn("attachment", response.headers["Content-Disposition"])
		self.assertTrue(response.headers["X-Lexocrates-Download-ID"].startswith("DL-"))
		self.assertEqual(file_doc.get_content(), source)
		self.assertEqual(len(PdfReader(io.BytesIO(response.get_data())).pages), 2)

		audit = frappe.get_all(
			"Lexocrates Portal Audit Event",
			filters={"action": "Protected PDF Download", "object_type": "File", "object_id": file_doc.name},
			fields=["name", "event_hash", "new_value"],
			order_by="creation desc",
			limit=1,
		)
		self.assertEqual(len(audit), 1)
		self.assertTrue(audit[0].event_hash)
		self.assertIn(response.headers["X-Lexocrates-Download-ID"], audit[0].new_value)

	def test_private_download_guard_is_idempotent(self):
		import frappe.utils.response as response_module

		install_private_pdf_download_guard()
		first = response_module.download_private_file
		install_private_pdf_download_guard()
		self.assertIs(response_module.download_private_file, first)
		self.assertTrue(getattr(first, "_lexocrates_pdf_guard", False))

	def test_unauthorized_users_cannot_resolve_a_private_pdf(self):
		from lex.pdf_watermark import _resolve_downloadable_file
		from werkzeug.exceptions import Forbidden

		file_doc = save_file(
			fname="administrator-only-watermark-test.pdf",
			content=_source_pdf(),
			dt=None,
			dn=None,
			is_private=1,
		)
		try:
			for user_type in ("Website User", "System User"):
				with self.subTest(user_type=user_type):
					user = f"pdf.unauthorized.{frappe.scrub(user_type)}@example.com"
					if not frappe.db.exists("User", user):
						frappe.get_doc({
							"doctype": "User",
							"email": user,
							"first_name": f"Unauthorized {user_type}",
							"user_type": user_type,
							"enabled": 1,
							"send_welcome_email": 0,
						}).insert(ignore_permissions=True)
					frappe.set_user(user)
					with self.assertRaises(Forbidden):
						_resolve_downloadable_file(file_id=file_doc.name)
		finally:
			frappe.set_user("Administrator")

	def test_secure_download_url_uses_opaque_file_id(self):
		url = secure_pdf_download_url("FILE name/+with unsafe")
		self.assertEqual(
			url,
			"/api/method/lex.pdf_watermark.download_watermarked_pdf?file_id=FILE+name%2F%2Bwith+unsafe",
		)


def _source_pdf() -> bytes:
	from reportlab.lib.pagesizes import A4, landscape
	from reportlab.pdfgen import canvas

	buffer = io.BytesIO()
	c = canvas.Canvas(buffer, pagesize=A4)
	c.setFont("Helvetica-Bold", 18)
	c.drawString(72, 770, "Lexocrates source document")
	c.setFont("Helvetica", 11)
	c.drawString(72, 742, "The original stored file must remain unchanged.")
	c.showPage()
	c.setPageSize(landscape(A4))
	c.setFont("Helvetica-Bold", 18)
	c.drawString(72, 520, "Landscape evidence page")
	c.drawString(72, 490, "Personalized watermark required on every page.")
	c.save()
	return buffer.getvalue()
