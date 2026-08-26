from __future__ import annotations

import hashlib
import io
import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import frappe
from frappe import _
from frappe.core.doctype.access_log.access_log import make_access_log
from frappe.core.doctype.file.utils import find_file_by_url
from frappe.utils import get_system_timezone, now_datetime
from werkzeug.exceptions import Forbidden
from werkzeug.http import dump_options_header
from werkzeug.wrappers import Response

from lex.client_access import get_portal_user, has_matter_access
from lex.portal_audit import create_portal_audit_event


WATERMARK_VERSION = "2"
MAX_SOURCE_BYTES = 100 * 1024 * 1024
MAX_PAGES = 1000
PDF_CONTENT_TYPE = "application/pdf"
FOOTER_HEIGHT = 45.0


@dataclass(frozen=True)
class WatermarkIdentity:
	user: str
	full_name: str
	portal_user: str | None = None
	client: str | None = None
	primary_role: str | None = None
	user_type: str | None = None


@dataclass(frozen=True)
class WatermarkContext:
	matter: str | None = None
	client: str | None = None
	label: str | None = None


def enforce_pdf_private_storage(doc, method=None):
	"""Force every Frappe-managed PDF into private storage before it is saved.

	Public files are served by Werkzeug/nginx before Frappe permissions and hooks
	are evaluated. Moving managed PDFs to ``/private/files`` closes that raw-URL
	bypass while leaving images, spreadsheets and other intentionally public
	website assets unchanged.
	"""
	if doc.is_folder or not _looks_like_pdf(doc.file_name or doc.file_url):
		return
	if doc.is_remote_file:
		frappe.throw(
			_("Remote PDF links cannot be protected. Upload the PDF into Lexocrates private storage."),
			frappe.ValidationError,
		)
	if doc.is_private and str(doc.file_url or "").startswith("/private/files/"):
		return
	if not str(doc.file_url or "").startswith("/files/"):
		frappe.throw(_("PDF must be stored as a private Lexocrates File."), frappe.ValidationError)
	doc.is_private = 1
	doc.handle_is_private_changed()


def ensure_all_pdfs_private():
	"""One-time/idempotent migration guard for pre-existing public PDF records."""
	if not frappe.db.exists("DocType", "File"):
		return
	rows = frappe.get_all(
		"File",
		filters={"is_folder": 0, "is_private": 0, "file_name": ["like", "%.pdf"]},
		pluck="name",
		limit_page_length=0,
	)
	for file_id in rows:
		file_doc = frappe.get_doc("File", file_id)
		file_doc.is_private = 1
		file_doc.save(ignore_permissions=True)


def install_private_pdf_download_guard():
	"""Route direct private-PDF URLs through the personalized download service.

	Frappe handles ``/private/files`` before it dispatches a whitelisted method,
	so a normal method override cannot protect copied private-file URLs. This
	idempotent request hook replaces only Frappe's private file response function;
	non-PDF files keep the framework's original behavior.
	"""
	import frappe.utils.response as response_module

	current = response_module.download_private_file
	if getattr(current, "_lexocrates_pdf_guard", False):
		return

	def guarded_download_private_file(path: str):
		file_doc = find_file_by_url(path, name=frappe.form_dict.get("fid"))
		if get_portal_user():
			if not file_doc:
				raise Forbidden(_("You don't have permission to access this file"))
			_enforce_portal_download_policy(file_doc)
		if _looks_like_pdf(path):
			if not file_doc:
				raise Forbidden(_("You don't have permission to access this file"))
			return _watermarked_response(file_doc)
		return current(path)

	guarded_download_private_file._lexocrates_pdf_guard = True
	guarded_download_private_file._lexocrates_original = current
	response_module.download_private_file = guarded_download_private_file


def download_private_pdf_response(path: str) -> Response:
	"""Authorize and return a personalized PDF for a direct private-file URL."""
	if frappe.session.user == "Guest":
		raise Forbidden(_("You don't have permission to access this file"))

	file_doc = find_file_by_url(path, name=frappe.form_dict.get("fid"))
	if not file_doc:
		raise Forbidden(_("You don't have permission to access this file"))
	_enforce_portal_download_policy(file_doc)
	return _watermarked_response(file_doc)


@frappe.whitelist()
def download_watermarked_pdf(file_id: str | None = None, file_url: str | None = None):
	"""Download an authorized File as an audited, personalized PDF copy."""
	file_doc = _resolve_downloadable_file(file_id=file_id, file_url=file_url)
	if not _is_pdf_file(file_doc):
		frappe.throw(_("The selected file is not a PDF."), frappe.ValidationError)
	return _watermarked_response(file_doc)


@frappe.whitelist(allow_guest=True)
def secure_download_file(file_url: str):
	"""Compatibility replacement for Frappe's generic download_file endpoint."""
	file_doc = _resolve_downloadable_file(file_url=file_url)
	if _is_pdf_file(file_doc):
		if frappe.session.user == "Guest":
			raise Forbidden(_("Sign in to download a protected PDF."))
		return _watermarked_response(file_doc)

	frappe.local.response.filename = os.path.basename(file_doc.file_name or file_url)
	frappe.local.response.filecontent = file_doc.get_content()
	frappe.local.response.type = "download"


def watermark_system_user_pdf_response(response: Response, request=None):
	"""Personalize generated PDF responses for authenticated System Users.

	Stored File downloads are protected earlier by ``_watermarked_response``.
	This request hook closes the other important path: PDFs generated on demand by
	Frappe/ERPNext print formats and reports.  It deliberately transforms the
	response in memory, never the source document or a stored File.

	Frappe swallows exceptions raised by ``after_request`` hooks, so this method
	must fail closed itself.  A personalization failure is converted into an error
	response instead of allowing the original, unwatermarked PDF to leave the app.
	"""
	if not _is_pdf_response(response):
		return
	if response.headers.get("X-Lexocrates-Watermark-Version"):
		return
	if request is not None and request.method == "HEAD":
		return

	download_id = _new_download_id()
	identity = WatermarkIdentity(
		user=getattr(getattr(frappe, "session", None), "user", None) or "Unknown",
		full_name=getattr(getattr(frappe, "session", None), "user", None) or "Unknown",
		primary_role="Unknown",
		user_type="System User",
	)
	context = WatermarkContext(label="Lexocrates generated PDF")
	object_type = None
	object_id = None
	try:
		if not _is_current_user_system_user():
			return
		identity = _current_identity()
		context, object_type, object_id = _request_pdf_context(request)
		source = response.get_data()
		watermarked, evidence = build_watermarked_pdf(
			source,
			identity=identity,
			context=context,
			download_id=download_id,
		)
		response.set_data(watermarked)
		_apply_protected_response_headers(response, download_id, len(watermarked))
		make_access_log(
			doctype=object_type,
			document=object_id,
			method=getattr(request, "path", None) or "Generated PDF",
			file_type="pdf",
		)
		create_portal_audit_event(
			client=context.client,
			user=identity.user,
			matter=context.matter,
			action="Protected PDF Download",
			object_type=object_type,
			object_id=object_id,
			new_value={
				**evidence,
				"primary_role": identity.primary_role,
				"source": "Generated PDF response",
				"request_path": getattr(request, "path", None),
			},
			details="Generated PDF personalized in memory; no source document or stored File was modified.",
		)
		_commit_pdf_audit()
	except Exception as exc:
		_record_generated_pdf_failure(
			identity=identity,
			context=context,
			object_type=object_type,
			object_id=object_id,
			download_id=download_id,
			request=request,
			error=exc,
		)
		_fail_closed_pdf_response(response, download_id)


@frappe.whitelist()
def get_secure_pdf_download_url(file_id: str | None = None, file_url: str | None = None) -> str:
	"""Return an already-authorized URL suitable for Desk and portal links."""
	file_doc = _resolve_downloadable_file(file_id=file_id, file_url=file_url)
	if not _is_pdf_file(file_doc):
		return file_doc.unique_url
	return secure_pdf_download_url(file_doc.name)


def secure_pdf_download_url(file_id: str) -> str:
	return "/api/method/lex.pdf_watermark.download_watermarked_pdf?" + urlencode({"file_id": file_id})


def secure_download_url_for_file_url(file_url: str | None) -> str | None:
	if not file_url or not _looks_like_pdf(file_url):
		return file_url
	file_id = frappe.db.get_value("File", {"file_url": file_url}, "name")
	return secure_pdf_download_url(file_id) if file_id else file_url


def add_secure_download_url(row: Any) -> Any:
	"""Attach a secure URL to a File row without replacing its canonical URL."""
	file_name = _value(row, "file_name")
	file_url = _value(row, "file_url")
	file_id = _value(row, "name")
	url = secure_pdf_download_url(file_id) if _looks_like_pdf(file_name or file_url) else file_url
	if isinstance(row, dict):
		row["download_url"] = url
	else:
		row.download_url = url
	return row


def build_watermarked_pdf(
	source: bytes,
	*,
	identity: WatermarkIdentity,
	context: WatermarkContext | None = None,
	download_id: str,
	downloaded_on=None,
) -> tuple[bytes, dict]:
	"""Create a non-destructive personalized access copy and its evidence data."""
	if not source or len(source) > MAX_SOURCE_BYTES:
		frappe.throw(_("PDF is empty or exceeds the 100 MB protected-download limit."), frappe.ValidationError)
	if not source.lstrip().startswith(b"%PDF-"):
		frappe.throw(_("The file content is not a valid PDF."), frappe.ValidationError)

	try:
		from pypdf import PdfReader, PdfWriter, Transformation
	except ImportError:
		frappe.throw(_("PDF watermark dependency is unavailable. Install pypdf."), frappe.ValidationError)

	try:
		reader = PdfReader(io.BytesIO(source), strict=False)
		if reader.is_encrypted and reader.decrypt("") == 0:
			frappe.throw(
				_("This PDF is password protected and cannot be safely personalized."),
				frappe.ValidationError,
			)
		page_count = len(reader.pages)
		if not page_count or page_count > MAX_PAGES:
			frappe.throw(_("PDF page count is outside the protected-download limit."), frappe.ValidationError)

		signed_source = _has_digital_signature(reader)
		context = context or WatermarkContext()
		downloaded_on = downloaded_on or now_datetime()
		local_timestamp = downloaded_on.strftime("%d %b %Y %H:%M:%S")
		timezone_label = get_system_timezone() or "server time"
		lines = _watermark_lines(
			identity=identity,
			context=context,
			download_id=download_id,
			timestamp=f"{local_timestamp} {timezone_label}",
			signed_source=signed_source,
		)

		writer = PdfWriter()
		overlay_cache: dict[tuple[float, float], Any] = {}
		active_content_removed = False
		for source_page in reader.pages:
			try:
				source_page.transfer_rotation_to_content()
			except AttributeError:
				pass
			width = float(source_page.mediabox.width)
			height = float(source_page.mediabox.height)
			if width <= 0 or height <= 0:
				frappe.throw(_("PDF contains an invalid page size."), frappe.ValidationError)
			origin_x = float(source_page.mediabox.left)
			origin_y = float(source_page.mediabox.bottom)
			source_page.add_transformation(
				Transformation().translate(tx=-origin_x, ty=FOOTER_HEIGHT - origin_y),
				expand=False,
			)
			_translate_page_annotations(source_page, tx=-origin_x, ty=FOOTER_HEIGHT - origin_y)
			protected_height = height + FOOTER_HEIGHT
			source_page.mediabox.lower_left = (0, 0)
			source_page.mediabox.upper_right = (width, protected_height)
			source_page.cropbox.lower_left = (0, 0)
			source_page.cropbox.upper_right = (width, protected_height)
			key = (round(width, 3), round(protected_height, 3))
			if key not in overlay_cache:
				overlay_cache[key] = _overlay_page(width, protected_height, lines)
			active_content_removed = _remove_page_javascript(source_page) or active_content_removed
			source_page.merge_page(overlay_cache[key])
			writer.add_page(source_page)

		metadata = dict(reader.metadata or {})
		metadata.update({
			"/Producer": "Lexocrates Protected PDF Service",
			"/Subject": f"Personalized access copy {download_id}",
			"/LexocratesDownloadID": download_id,
			"/LexocratesWatermarkVersion": WATERMARK_VERSION,
		})
		writer.add_metadata({key: str(value) for key, value in metadata.items() if key and value is not None})
		output = io.BytesIO()
		writer.write(output)
		result = output.getvalue()
		if not result.startswith(b"%PDF-"):
			raise ValueError("watermarked output does not have a PDF signature")
	except frappe.ValidationError:
		raise
	except Exception as exc:
		frappe.throw(
			_("The PDF could not be safely personalized: {0}").format(str(exc)[:180]),
			frappe.ValidationError,
		)

	evidence = {
		"download_id": download_id,
		"watermark_version": WATERMARK_VERSION,
		"source_checksum": hashlib.sha256(source).hexdigest(),
		"download_checksum": hashlib.sha256(result).hexdigest(),
		"page_count": page_count,
		"signed_source": signed_source,
		"active_content_removed": active_content_removed,
		"user": identity.user,
		"full_name": identity.full_name,
		"primary_role": identity.primary_role,
		"user_type": identity.user_type,
		"portal_user": identity.portal_user,
		"timestamp": str(downloaded_on),
		"timezone": timezone_label,
	}
	return result, evidence


def _watermarked_response(file_doc) -> Response:
	if frappe.session.user in {None, "", "Guest"}:
		raise Forbidden(_("Sign in to download a protected PDF."))
	if not _is_pdf_file(file_doc):
		frappe.throw(_("The selected file is not a PDF."), frappe.ValidationError)

	identity = _current_identity()
	context = _file_context(file_doc, identity)
	download_id = _new_download_id()
	source = file_doc.get_content()
	try:
		watermarked, evidence = build_watermarked_pdf(
			source,
			identity=identity,
			context=context,
			download_id=download_id,
		)
	except Exception as exc:
		create_portal_audit_event(
			client=context.client or identity.client,
			portal_user=identity.portal_user,
			user=identity.user,
			matter=context.matter,
			action="Protected PDF Download",
			object_type="File",
			object_id=file_doc.name,
			new_value={
				"download_id": download_id,
				"watermark_version": WATERMARK_VERSION,
				"file_name": file_doc.file_name,
				"file_url": file_doc.file_url,
			},
			result="Failure",
			details=f"Protected PDF generation failed: {str(exc)[:180]}",
		)
		_commit_pdf_audit()
		raise

	make_access_log(doctype="File", document=file_doc.name, file_type="pdf")
	create_portal_audit_event(
		client=context.client or identity.client,
		portal_user=identity.portal_user,
		user=identity.user,
		matter=context.matter,
		action="Protected PDF Download",
		object_type="File",
		object_id=file_doc.name,
		new_value={
			**evidence,
			"file_name": file_doc.file_name,
			"file_url": file_doc.file_url,
			"attached_to_doctype": file_doc.attached_to_doctype,
			"attached_to_name": file_doc.attached_to_name,
		},
		details=(
			"Personalized access copy generated in memory; the original stored PDF was not modified."
			+ (" Source contained a digital-signature field; downloaded copy is marked as an access copy." if evidence["signed_source"] else "")
		),
	)
	_commit_pdf_audit()

	filename = _protected_filename(file_doc.file_name or os.path.basename(file_doc.file_url or "document.pdf"))
	response = Response(watermarked, content_type=PDF_CONTENT_TYPE)
	response.headers["Content-Disposition"] = dump_options_header("attachment", {"filename": filename})
	_apply_protected_response_headers(response, download_id, len(watermarked))
	response.headers["Content-Security-Policy"] = "sandbox"
	response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
	return response


def _resolve_downloadable_file(*, file_id: str | None = None, file_url: str | None = None):
	if not file_id and not file_url:
		frappe.throw(_("File ID or file URL is required."), frappe.ValidationError)
	file_doc = None
	if file_id:
		try:
			candidate = frappe.get_doc("File", file_id)
		except frappe.DoesNotExistError:
			raise Forbidden(_("You don't have permission to access this file"))
		if candidate.is_downloadable() and (not file_url or candidate.file_url == file_url):
			file_doc = candidate
	elif file_url:
		file_doc = find_file_by_url(file_url)
	if not file_doc:
		raise Forbidden(_("You don't have permission to access this file"))
	_enforce_portal_download_policy(file_doc)
	return file_doc


def _enforce_portal_download_policy(file_doc):
	"""Apply the client document policy to every protected download path.

	Clients can retrieve their organization's own uploads.  A Job attachment is
	never downloadable unless it is the canonical delivery document and the Job
	is Completed.  Internal System Users retain their normal permissions.
	"""
	portal_user = get_portal_user()
	if not portal_user:
		return
	doctype = file_doc.attached_to_doctype
	name = file_doc.attached_to_name

	if doctype == "LPO Job" and name:
		job = frappe.db.get_value(
			"LPO Job",
			name,
			["customer", "engagement", "job_status", "delivery_document"],
			as_dict=True,
		)
		completed_access = job and job.job_status == "Completed" and has_matter_access(job.engagement, "view")
		approval_preview = job and job.job_status == "Ready for Delivery" and has_matter_access(job.engagement, "approve")
		if not (
			job
			and job.customer == portal_user.client
			and (completed_access or approval_preview)
			and job.delivery_document == file_doc.file_url
		):
			raise Forbidden(_("This deliverable is not available for your current workflow permission."))
		return

	if doctype == "Lexocrates Work Intake" and name:
		intake = frappe.db.get_value(
			"Lexocrates Work Intake", name, ["client", "portal_user"], as_dict=True
		)
		if not (
			intake
			and intake.client == portal_user.client
			and (
				portal_user.matter_access_scope == "All Client Matters"
				or intake.portal_user == portal_user.name
			)
			and _is_client_owned_upload(file_doc, portal_user.client)
		):
			raise Forbidden(_("You don't have permission to access this client upload."))
		return

	if doctype == "LPO Matter" and name:
		if not (
			has_matter_access(name, "view")
			and _is_client_owned_upload(file_doc, portal_user.client)
		):
			raise Forbidden(_("You don't have permission to access this client upload."))
		return

	# The immutable SLA snapshot must remain downloadable before document upload.
	intakes = frappe.get_all(
		"Lexocrates Work Intake",
		filters={"client": portal_user.client, "sla_document_snapshot": file_doc.file_url},
		fields=["name", "portal_user"],
		limit_page_length=20,
	)
	if any(
		portal_user.matter_access_scope == "All Client Matters" or row.portal_user == portal_user.name
		for row in intakes
	):
		return

	raise Forbidden(_("This internal document is not available in the Client Workspace."))


def _is_client_owned_upload(file_doc, client: str) -> bool:
	return bool(
		file_doc.owner
		and frappe.db.exists("Lexocrates Portal User", {"client": client, "user": file_doc.owner})
	)


def _current_identity() -> WatermarkIdentity:
	user = frappe.session.user
	user_row = frappe.db.get_value("User", user, ["full_name", "email", "user_type"], as_dict=True) or {}
	try:
		from lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel import (
			get_user_chat_identity,
		)

		chat_identity = get_user_chat_identity(user)
	except Exception:
		chat_identity = {}
	portal_user = None
	client = None
	if frappe.db.exists("DocType", "Lexocrates Portal User"):
		portal_row = frappe.db.get_value(
			"Lexocrates Portal User",
			{"user": user},
			["name", "client", "full_name"],
			as_dict=True,
		)
		if portal_row:
			portal_user = portal_row.name
			client = portal_row.client
			user_row["full_name"] = portal_row.full_name or user_row.get("full_name")
	return WatermarkIdentity(
		user=user,
		full_name=(chat_identity.get("full_name") or user_row.get("full_name") or user_row.get("email") or user).strip(),
		portal_user=portal_user,
		client=client,
		primary_role=chat_identity.get("primary_role") or user_row.get("user_type") or _("User"),
		user_type=chat_identity.get("user_type") or user_row.get("user_type"),
	)


def _file_context(file_doc, identity: WatermarkIdentity) -> WatermarkContext:
	doctype = file_doc.attached_to_doctype
	name = file_doc.attached_to_name
	client = identity.client
	matter = None
	label = None
	if doctype == "LPO Matter" and name:
		matter = name
		client = frappe.db.get_value("LPO Matter", name, "customer") or client
		label = f"Matter {name}"
	elif doctype == "LPO Job" and name:
		row = frappe.db.get_value("LPO Job", name, ["engagement", "customer"], as_dict=True) or {}
		matter = row.get("engagement")
		client = row.get("customer") or client
		label = f"Job {name}" + (f" | Matter {matter}" if matter else "")
	elif doctype == "Lexocrates Work Intake" and name:
		row = frappe.db.get_value("Lexocrates Work Intake", name, ["matter", "client"], as_dict=True) or {}
		matter = row.get("matter")
		client = row.get("client") or client
		label = f"Work Intake {name}" + (f" | Matter {matter}" if matter else "")
	elif doctype and name:
		label = f"{doctype} {name}"
	return WatermarkContext(matter=matter, client=client, label=label)


def _watermark_lines(
	*,
	identity: WatermarkIdentity,
	context: WatermarkContext,
	download_id: str,
	timestamp: str,
	signed_source: bool,
) -> dict[str, str]:
	name = _pdf_text(identity.full_name)
	user = _pdf_text(identity.user)
	role = _pdf_text(identity.primary_role or identity.user_type or _("User"))
	return {
		"diagonal": "CONFIDENTIAL",
		"identity": f"User ID: {user} | Role: {role} | Downloaded by: {name or user}",
		"evidence": f"{timestamp} | Download ID: {download_id}",
		"context": _pdf_text(context.label or "Lexocrates protected document"),
		"signature": "SIGNED SOURCE - WATERMARKED ACCESS COPY" if signed_source else "",
	}


def _overlay_page(width: float, height: float, lines: dict[str, str]):
	try:
		from pypdf import PdfReader
		from reportlab.lib.colors import HexColor
		from reportlab.pdfbase.pdfmetrics import stringWidth
		from reportlab.pdfgen import canvas
	except ImportError:
		frappe.throw(_("PDF watermark dependencies are unavailable. Install pypdf and reportlab."), frappe.ValidationError)

	buffer = io.BytesIO()
	c = canvas.Canvas(buffer, pagesize=(width, height), pageCompression=1)
	c.saveState()
	c.setFillColor(HexColor("#253B5B"))
	try:
		c.setFillAlpha(0.085)
	except Exception:
		pass
	c.translate(width / 2, height / 2)
	c.rotate(38)
	diagonal = lines["diagonal"]
	available_diagonal_width = width * 0.82
	natural_width = max(stringWidth(diagonal, "Helvetica-Bold", 1), 1)
	diagonal_size = max(16, min(38, available_diagonal_width / natural_width))
	c.setFont("Helvetica-Bold", diagonal_size)
	diagonal = _fit_text(diagonal, "Helvetica-Bold", diagonal_size, available_diagonal_width, stringWidth)
	c.drawCentredString(0, 0, diagonal)
	c.restoreState()

	band_height = FOOTER_HEIGHT
	c.saveState()
	c.setFillColor(HexColor("#F1F5F9"))
	try:
		c.setFillAlpha(0.93)
	except Exception:
		pass
	c.rect(0, 0, width, band_height, stroke=0, fill=1)
	c.setFillColor(HexColor("#334155"))
	c.setFont("Helvetica-Bold", 6.8)
	identity = _fit_text(lines["identity"], "Helvetica-Bold", 6.8, width - 24, stringWidth)
	c.drawString(12, band_height - 12, identity)
	c.setFont("Helvetica", 6.3)
	evidence = _fit_text(lines["evidence"], "Helvetica", 6.3, width - 24, stringWidth)
	c.drawString(12, band_height - 22, evidence)
	context = lines["context"]
	if lines["signature"]:
		context = f"{lines['signature']} | {context}"
	context = _fit_text(context, "Helvetica", 6.3, width - 24, stringWidth)
	c.drawString(12, band_height - 32, context)
	c.restoreState()
	c.save()
	buffer.seek(0)
	return PdfReader(buffer).pages[0]


def _has_digital_signature(reader) -> bool:
	try:
		fields = reader.get_fields() or {}
		for field in fields.values():
			if str(field.get("/FT") or "") == "/Sig":
				return True
		root = reader.trailer.get("/Root")
		return bool(root and root.get("/Perms"))
	except Exception:
		return False


def _remove_page_javascript(page) -> bool:
	"""Remove page/annotation JavaScript while retaining ordinary link annotations."""
	removed = False
	if "/AA" in page:
		del page["/AA"]
		removed = True
	annotations = page.get("/Annots") or []
	for reference in annotations:
		try:
			annotation = reference.get_object()
			if "/AA" in annotation:
				del annotation["/AA"]
				removed = True
			action = annotation.get("/A")
			if action and hasattr(action, "get_object"):
				action = action.get_object()
			if action and str(action.get("/S") or "") == "/JavaScript":
				del annotation["/A"]
				removed = True
		except Exception:
			continue
	return removed


def _translate_page_annotations(page, *, tx: float, ty: float):
	"""Keep link/widget hit boxes aligned after reserving the footer margin."""
	try:
		from pypdf.generic import ArrayObject, FloatObject
	except ImportError:
		return
	for reference in page.get("/Annots") or []:
		try:
			annotation = reference.get_object()
			rect = annotation.get("/Rect")
			if rect and len(rect) == 4:
				annotation["/Rect"] = ArrayObject([
					FloatObject(float(rect[0]) + tx),
					FloatObject(float(rect[1]) + ty),
					FloatObject(float(rect[2]) + tx),
					FloatObject(float(rect[3]) + ty),
				])
			quad_points = annotation.get("/QuadPoints")
			if quad_points and len(quad_points) % 2 == 0:
				annotation["/QuadPoints"] = ArrayObject([
					FloatObject(float(value) + (tx if index % 2 == 0 else ty))
					for index, value in enumerate(quad_points)
				])
		except Exception:
			continue


def _new_download_id() -> str:
	stamp = now_datetime().strftime("%Y%m%d")
	return f"DL-{stamp}-{frappe.generate_hash(length=10).upper()}"


def _is_current_user_system_user() -> bool:
	user = getattr(getattr(frappe, "session", None), "user", None)
	if not user or user == "Guest":
		return False
	return bool(frappe.db.get_value("User", user, "user_type") == "System User")


def _is_pdf_response(response: Response) -> bool:
	if not response or response.status_code < 200 or response.status_code >= 300:
		return False
	content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
	disposition = str(response.headers.get("Content-Disposition") or "").lower()
	return content_type == PDF_CONTENT_TYPE or ".pdf" in disposition


def _request_pdf_context(request) -> tuple[WatermarkContext, str | None, str | None]:
	doctype = str(frappe.form_dict.get("doctype") or "").strip() or None
	name = str(frappe.form_dict.get("name") or "").strip() or None
	if doctype and not frappe.db.exists("DocType", doctype):
		doctype = None
		name = None
	label = f"{doctype} {name}" if doctype and name else "Lexocrates generated PDF"
	if not doctype and request is not None and getattr(request, "path", None):
		label = f"Generated from {request.path}"
	context = WatermarkContext(label=label)
	if doctype == "LPO Matter" and name:
		context = WatermarkContext(
			matter=name,
			client=frappe.db.get_value("LPO Matter", name, "customer"),
			label=label,
		)
	elif doctype == "LPO Job" and name:
		row = frappe.db.get_value("LPO Job", name, ["engagement", "customer"], as_dict=True) or {}
		context = WatermarkContext(
			matter=row.get("engagement"),
			client=row.get("customer"),
			label=label,
		)
	return context, doctype, name


def _apply_protected_response_headers(response: Response, download_id: str, content_length: int):
	response.headers["Cache-Control"] = "private, no-store, max-age=0"
	response.headers["Pragma"] = "no-cache"
	response.headers["Expires"] = "0"
	response.headers["X-Content-Type-Options"] = "nosniff"
	response.headers["Vary"] = "Cookie, Authorization"
	response.headers["X-Lexocrates-Download-ID"] = download_id
	response.headers["X-Lexocrates-Watermark-Version"] = WATERMARK_VERSION
	response.headers["Content-Length"] = str(content_length)
	response.headers.pop("Content-Encoding", None)
	response.headers.pop("Accept-Ranges", None)
	response.headers.pop("Content-Range", None)
	response.headers.pop("X-Accel-Redirect", None)


def _record_generated_pdf_failure(
	*, identity, context, object_type, object_id, download_id, request, error
):
	try:
		create_portal_audit_event(
			client=context.client,
			user=identity.user,
			matter=context.matter,
			action="Protected PDF Download",
			object_type=object_type,
			object_id=object_id,
			new_value={
				"download_id": download_id,
				"watermark_version": WATERMARK_VERSION,
				"primary_role": identity.primary_role,
				"source": "Generated PDF response",
				"request_path": getattr(request, "path", None),
			},
			result="Failure",
			details=f"Generated PDF personalization failed closed: {str(error)[:180]}",
		)
		_commit_pdf_audit()
	except Exception:
		frappe.logger("lex.pdf_watermark").error("Could not write PDF failure audit event", exc_info=True)


def _commit_pdf_audit():
	"""Persist access evidence created during GET/after-request processing.

	Frappe rolls back ordinary GET transactions, and generated-PDF after-request
	hooks run after the normal transaction has already synchronized.  At this
	point only the Access Log and immutable PDF audit event are pending.  Tests do
	not commit so their normal rollback isolation remains intact.
	"""
	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()


def _fail_closed_pdf_response(response: Response, download_id: str):
	payload = {
		"exc_type": "ProtectedPDFGenerationError",
		"message": _("The PDF could not be safely personalized. No unwatermarked copy was downloaded."),
		"download_id": download_id,
	}
	response.status_code = 422
	response.mimetype = "application/json"
	response.set_data(json.dumps(payload, default=str))
	response.headers.pop("Content-Disposition", None)
	response.headers.pop("Content-Security-Policy", None)
	response.headers.pop("Cross-Origin-Resource-Policy", None)
	_apply_protected_response_headers(response, download_id, len(response.get_data()))
	response.headers["X-Lexocrates-Watermark-Status"] = "failed-closed"


def _protected_filename(filename: str) -> str:
	base = os.path.basename(filename or "document.pdf")
	stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", os.path.splitext(base)[0]).strip(" ._") or "document"
	return f"{stem}-protected.pdf"


def _fit_text(value: str, font: str, size: float, max_width: float, string_width) -> str:
	value = value.strip()
	if string_width(value, font, size) <= max_width:
		return value
	while len(value) > 8 and string_width(value + "...", font, size) > max_width:
		value = value[:-1]
	return value.rstrip() + "..."


def _pdf_text(value: Any) -> str:
	clean = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()
	# ReportLab's dependency-free Helvetica path supports WinAnsi. The immutable
	# user ID remains present even if a display name contains another script.
	return clean.encode("cp1252", "replace").decode("cp1252")[:180]


def _looks_like_pdf(value: Any) -> bool:
	return str(value or "").split("?", 1)[0].lower().endswith(".pdf")


def _is_pdf_file(file_doc) -> bool:
	return _looks_like_pdf(file_doc.file_name) or _looks_like_pdf(file_doc.file_url)


def _value(row: Any, key: str):
	return row.get(key) if hasattr(row, "get") else getattr(row, key, None)
