from __future__ import annotations

import base64
import binascii
import contextlib
import json
import os

import frappe
from frappe import _
from frappe.core.api.file import get_max_file_size
from frappe.utils import cint, flt, now_datetime
from frappe.utils.file_manager import save_file

from lex.ai_document_engine import extract_text_from_file
from lex.file_quarantine import scan_and_validate_inbound_file
from lex.lexpoint_estimation import DEFAULT_SERVICE_BY_INTAKE, calculate_estimate
from lex.portal_audit import create_portal_audit_event
from lex.work_intake import _estimation_profile_with_ai


ALLOWED_ESTIMATE_EXTENSIONS = {".csv", ".docx", ".pdf", ".txt"}
PRIORITIES = ("Low", "Medium", "High", "Urgent")
DEFAULT_JURISDICTIONS = ("India", "Canada", "United Kingdom", "United States", "Multi-Jurisdiction")


@frappe.whitelist()
def get_estimator_bootstrap() -> dict:
	_require_system_user()
	return {
		"service_types": sorted(DEFAULT_SERVICE_BY_INTAKE),
		"priorities": list(PRIORITIES),
		"jurisdictions": list(DEFAULT_JURISDICTIONS),
		"allowed_extensions": sorted(ALLOWED_ESTIMATE_EXTENSIONS),
		"max_upload_bytes": get_max_file_size(),
		"ai_enabled": bool(cint(_setting("enable_ai_intake_analysis", 0))),
		"currency": _setting("quote_currency", "USD"),
		"recent_estimates": _recent_estimates(),
		"disclaimer": _(
			"Internal preview only. This tool does not create or update a Customer, Matter, Job, quote, wallet, invoice, or payment."
		),
	}


@frappe.whitelist()
def upload_standalone_estimate_file() -> dict:
	"""Receive Frappe's native multipart upload and run the isolated estimate.

	The browser sends the binary directly instead of expanding it into a base64
	payload. Frappe and the reverse proxy enforce the site-configured capacity.
	"""
	_require_system_user()
	content = getattr(frappe.local, "uploaded_file", None)
	filename = getattr(frappe.local, "uploaded_filename", None)
	if isinstance(content, str):
		content = content.encode()
	if not content or not filename:
		frappe.throw(_("Select a non-empty document to upload."), frappe.ValidationError)
	return _estimate_uploaded_content(
		filename=filename,
		content=content,
		service_type=frappe.form_dict.get("service_type") or "Other",
		jurisdiction=frappe.form_dict.get("jurisdiction") or "India",
		priority=frappe.form_dict.get("priority") or "Medium",
		expected_outcome=frappe.form_dict.get("expected_outcome"),
		detailed_instructions=frappe.form_dict.get("detailed_instructions"),
		use_ai=frappe.form_dict.get("use_ai", 1),
	)


@frappe.whitelist()
def estimate_document(
	filename: str,
	content: str,
	service_type: str = "Other",
	jurisdiction: str = "India",
	priority: str = "Medium",
	expected_outcome: str | None = None,
	detailed_instructions: str | None = None,
	use_ai: int = 1,
) -> dict:
	"""Backward-compatible data-URL API; the Desk page uses multipart upload."""
	_require_system_user()
	try:
		decoded = base64.b64decode((content or "").split(",", 1)[-1], validate=True)
	except (ValueError, binascii.Error):
		frappe.throw(_("The uploaded file is not valid."), frappe.ValidationError)
	return _estimate_uploaded_content(
		filename=filename,
		content=decoded,
		service_type=service_type,
		jurisdiction=jurisdiction,
		priority=priority,
		expected_outcome=expected_outcome,
		detailed_instructions=detailed_instructions,
		use_ai=use_ai,
	)


def _estimate_uploaded_content(
	*, filename: str, content: bytes, service_type: str, jurisdiction: str, priority: str,
	expected_outcome: str | None, detailed_instructions: str | None, use_ai: int,
) -> dict:
	"""Persist, scan, extract and estimate a binary already accepted by Frappe."""
	_require_system_user()
	filename = os.path.basename((filename or "").strip())
	extension = os.path.splitext(filename.lower())[1]
	if not filename or extension not in ALLOWED_ESTIMATE_EXTENSIONS:
		frappe.throw(
			_("Upload a PDF, DOCX, TXT, or CSV document."),
			frappe.ValidationError,
		)
	service_type = (service_type or "Other").strip()
	if service_type not in DEFAULT_SERVICE_BY_INTAKE:
		frappe.throw(_("Select a valid service type."), frappe.ValidationError)
	priority = (priority or "Medium").strip().title()
	if priority not in PRIORITIES:
		frappe.throw(_("Select a valid priority."), frappe.ValidationError)
	jurisdiction = (jurisdiction or "India").strip()[:140]
	if not jurisdiction:
		frappe.throw(_("Jurisdiction is required."), frappe.MandatoryError)
	if not content:
		frappe.throw(_("Select a non-empty document to upload."), frappe.ValidationError)
	max_upload_bytes = get_max_file_size()
	if len(content) > max_upload_bytes:
		frappe.throw(
			_("The document exceeds the site upload capacity of {0} MB.").format(
				round(max_upload_bytes / 1024 / 1024)
			),
			frappe.ValidationError,
		)

	context = frappe._dict(
		service_type=service_type,
		jurisdiction=jurisdiction,
		priority=priority,
		requested_delivery_date=None,
		expected_outcome=(expected_outcome or "Internal LexPoint and price estimation only.").strip()[:1000],
		detailed_instructions=(detailed_instructions or "").strip()[:10000],
		client=None,
	)

	with _estimate_service_writes():
		record = frappe.get_doc(
			{
				"doctype": "LPO Standalone Estimate",
				"estimate_title": f"{filename[:95]} - {now_datetime().strftime('%d %b %Y %H:%M')}",
				"status": "Processing",
				"requested_by": frappe.session.user,
				"requested_on": now_datetime(),
				"service_type": service_type,
				"jurisdiction": jurisdiction,
				"priority": priority,
				"file_name": filename,
				"file_size_bytes": len(content),
				"expected_outcome": context.expected_outcome,
				"detailed_instructions": context.detailed_instructions,
			}
		).insert(ignore_permissions=True)
		file_doc = save_file(
			filename,
			content,
			"LPO Standalone Estimate",
			record.name,
			is_private=1,
			df="source_document",
		)

	scan = scan_and_validate_inbound_file(file_doc.name)
	if scan.get("status") != "Clean":
		frappe.throw(
			_("The document remains quarantined because security scanning did not return Clean: {0}").format(
				scan.get("status") or _("Unknown")
			),
			frappe.ValidationError,
		)

	extracted, checksum, word_count, character_count = extract_text_from_file(
		file_doc.file_url,
		max_chars=100000,
		file_doc_name=file_doc.name,
	)
	files = [
		frappe._dict(
			name=file_doc.name,
			file_name=file_doc.file_name,
			file_size=file_doc.file_size or len(content),
		)
	]
	ai_profile = None
	ai_note = None
	if cint(use_ai):
		ai_profile, ai_note = _estimation_profile_with_ai(context, extracted, 1, word_count)
	else:
		ai_note = _("Governed AI classification was not requested; the deterministic formula was used.")

	estimation = calculate_estimate(context, files, extracted, ai_profile=ai_profile)
	rate = flt(_setting("direct_quote_rate_per_point", 3))
	price = flt(cint(estimation["lexpoints"]) * rate, 2)
	currency = _setting("quote_currency", "USD")
	confidence = flt(estimation.get("confidence") or _extraction_confidence(word_count))
	threshold = flt(frappe.db.get_single_value("LPO LexPoint Settings", "auto_quote_confidence") or 72)
	requires_review = bool(cint(estimation.get("requires_human_review")) or confidence < threshold)

	with _estimate_service_writes():
		record.reload()
		record.update(
			{
				"status": "Complete",
				"source_document": file_doc.file_url,
				"source_checksum": checksum or scan.get("checksum"),
				"scan_status": scan.get("status"),
				"page_count": cint(estimation.get("page_count")),
				"word_count": cint(estimation.get("word_count")),
				"character_count": cint(estimation.get("character_count")),
				"estimated_lexpoints": cint(estimation["lexpoints"]),
				"estimated_price": price,
				"currency": currency,
				"delivery_hours": cint(estimation["delivery_hours"]),
				"recommended_service": estimation.get("recommended_service"),
				"billing_measure": estimation.get("billing_measure"),
				"estimated_volume": flt(estimation.get("volume")),
				"estimate_source": "AI-Assisted Formula" if ai_profile else "Formula",
				"detected_document_type": estimation.get("detected_document_type"),
				"complexity_score": cint(estimation.get("complexity_score")),
				"complexity_classification": estimation.get("complexity_classification"),
				"risk_level": estimation.get("risk_level"),
				"reviewer_level": estimation.get("reviewer_level"),
				"confidence": confidence,
				"requires_human_review": cint(requires_review),
				"analysis_note": ai_note,
				"ai_execution": (ai_profile or {}).get("ai_execution"),
				"analysis_provider": (ai_profile or {}).get("provider"),
				"analysis_model": (ai_profile or {}).get("model"),
				"factor_breakdown_json": json.dumps(
					estimation.get("factor_breakdown") or {}, default=str, indent=2, sort_keys=True
				),
				"explanation": estimation.get("explanation"),
			}
		)
		record.save(ignore_permissions=True)

	create_portal_audit_event(
		client=None,
		user=frappe.session.user,
		action="Standalone LexPoint Estimate Completed",
		object_type=record.doctype,
		object_id=record.name,
		new_value={
			"file_checksum": record.source_checksum,
			"lexpoints": record.estimated_lexpoints,
			"price": record.estimated_price,
			"currency": record.currency,
			"estimate_source": record.estimate_source,
		},
		details="Internal sandbox estimate; no Customer, Matter, Job, quote, wallet, invoice, or payment was created.",
	)
	return _serialize(record)


def _serialize(record) -> dict:
	return {
		"name": record.name,
		"estimate_title": record.estimate_title,
		"requested_on": record.requested_on,
		"file_name": record.file_name,
		"status": record.status,
		"estimated_lexpoints": cint(record.estimated_lexpoints),
		"estimated_price": flt(record.estimated_price, 2),
		"currency": record.currency,
		"delivery_hours": cint(record.delivery_hours),
		"recommended_service": record.recommended_service,
		"billing_measure": record.billing_measure,
		"estimated_volume": flt(record.estimated_volume),
		"estimate_source": record.estimate_source,
		"detected_document_type": record.detected_document_type,
		"complexity_score": cint(record.complexity_score),
		"complexity_classification": record.complexity_classification,
		"risk_level": record.risk_level,
		"reviewer_level": record.reviewer_level,
		"confidence": flt(record.confidence),
		"requires_human_review": bool(cint(record.requires_human_review)),
		"analysis_note": record.analysis_note,
		"page_count": cint(record.page_count),
		"word_count": cint(record.word_count),
		"explanation": record.explanation,
		"route": f"/app/lpo-standalone-estimate/{record.name}",
	}


def _recent_estimates() -> list[dict]:
	rows = frappe.get_all(
		"LPO Standalone Estimate",
		filters={"requested_by": frappe.session.user},
		fields=[
			"name", "estimate_title", "requested_on", "file_name", "status", "estimated_lexpoints",
			"estimated_price", "currency", "recommended_service", "estimate_source",
		],
		order_by="requested_on desc",
		limit_page_length=10,
	)
	return [
		{
			**row,
			"route": f"/app/lpo-standalone-estimate/{row.name}",
		}
		for row in rows
	]


def _require_system_user():
	user = frappe.session.user
	if user in {None, "", "Guest"}:
		frappe.throw(_("Authentication required."), frappe.AuthenticationError)
	if user != "Administrator" and frappe.db.get_value("User", user, "user_type") != "System User":
		frappe.throw(
			_("The standalone LexPoint Estimator is available only to internal System Users."),
			frappe.PermissionError,
		)


@contextlib.contextmanager
def _estimate_service_writes():
	previous = getattr(frappe.flags, "lexocrates_standalone_estimate_service", False)
	frappe.flags.lexocrates_standalone_estimate_service = True
	try:
		yield
	finally:
		frappe.flags.lexocrates_standalone_estimate_service = previous


def _setting(fieldname, default=None):
	if not frappe.db.exists("DocType", "LexPack Settings"):
		return default
	meta = frappe.get_meta("LexPack Settings")
	if not meta.has_field(fieldname):
		return default
	value = frappe.db.get_single_value("LexPack Settings", fieldname)
	return default if value in {None, ""} else value


def _extraction_confidence(word_count: int) -> float:
	if word_count >= 500:
		return 82
	if word_count >= 100:
		return 75
	if word_count >= 40:
		return 68
	return 45
