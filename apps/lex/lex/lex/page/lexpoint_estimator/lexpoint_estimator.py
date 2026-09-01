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
from lex.work_intake import _parse_ai_json_object


ALLOWED_ESTIMATE_EXTENSIONS = {".csv", ".docx", ".pdf", ".txt"}
PRIORITIES = ("Low", "Medium", "High", "Urgent")
DEFAULT_JURISDICTIONS = ("India", "Canada", "United Kingdom", "United States", "Multi-Jurisdiction")


@frappe.whitelist()
def get_estimator_bootstrap() -> dict:
	_require_system_user()
	ai_route = _estimation_ai_route_status()
	return {
		"service_types": sorted(DEFAULT_SERVICE_BY_INTAKE),
		"priorities": list(PRIORITIES),
		"jurisdictions": list(DEFAULT_JURISDICTIONS),
		"allowed_extensions": sorted(ALLOWED_ESTIMATE_EXTENSIONS),
		"max_upload_bytes": get_max_file_size(),
		"ai_enabled": bool(ai_route.get("ready")),
		"ai_route": ai_route,
		"currency": _setting("quote_currency", "USD"),
		"recent_estimates": _recent_estimates(),
		"disclaimer": _(
			"Internal preview only. This tool does not create or update a Customer, Matter, Job, quote, wallet, invoice, or payment."
		),
	}


@frappe.whitelist()
def test_estimation_ai_connection() -> dict:
	"""Run a minimal governed request through the exact estimator route."""
	_require_system_user()
	route = _estimation_ai_route_status()
	if not route.get("ready"):
		frappe.throw(route.get("message") or _("Standalone estimation AI is not configured."), frappe.ValidationError)
	from lex.ai_gateway import STANDALONE_ESTIMATION_USE_CASE, invoke_ai_gateway

	with _standalone_ai_gateway_call():
		result = invoke_ai_gateway(
			use_case=STANDALONE_ESTIMATION_USE_CASE,
			prompt_text='Return only this JSON object: {"status":"ready"}',
			provider=None,
			model=None,
			credential_name=None,
			is_high_risk=0,
			max_tokens=60,
		)
	return {
		"status": "success",
		"provider": result.get("provider"),
		"model": result.get("model"),
		"credential_name": result.get("credential_name"),
		"ai_execution": result.get("ai_execution"),
		"message": _("Standalone estimation AI route responded successfully."),
	}


@frappe.whitelist()
def rerun_estimate_with_ai(estimate: str) -> dict:
	"""Create a new immutable AI-assisted estimate from an already-clean source file."""
	_require_system_user()
	source = frappe.get_doc("LPO Standalone Estimate", estimate)
	roles = set(frappe.get_roles(frappe.session.user))
	if (
		frappe.session.user != "Administrator"
		and source.requested_by != frappe.session.user
		and not roles.intersection({"System Manager", "LPO_Admin", "LPO_Manager"})
	):
		frappe.throw(_("You cannot re-run this estimate."), frappe.PermissionError)
	file_name = frappe.db.get_value(
		"File",
		{"file_url": source.source_document, "is_folder": 0, "custom_lex_scan_status": "Clean"},
		"name",
		order_by="creation desc",
	)
	if not file_name:
		frappe.throw(_("The original private source file is unavailable."), frappe.DoesNotExistError)
	file_doc = frappe.get_doc("File", file_name)
	if file_doc.custom_lex_scan_status != "Clean":
		frappe.throw(_("Only a previously clean source file can be re-estimated."), frappe.PermissionError)
	content = file_doc.get_content()
	if isinstance(content, str):
		content = content.encode()
	return _estimate_uploaded_content(
		filename=source.file_name or file_doc.file_name,
		content=content,
		service_type=source.service_type,
		jurisdiction=source.jurisdiction,
		priority=source.priority,
		expected_outcome=source.expected_outcome,
		detailed_instructions=source.detailed_instructions,
		use_ai=1,
	)


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
		ai_profile, ai_note = _standalone_estimation_profile_with_ai(context, extracted, 1, word_count)
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
		"ai_execution": record.ai_execution,
		"analysis_provider": record.analysis_provider,
		"analysis_model": record.analysis_model,
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


def _estimation_ai_route_status() -> dict:
	if not frappe.db.exists("DocType", "LPO AI Settings"):
		return {"ready": False, "message": _("LPO AI Settings is not installed.")}
	settings = frappe.get_single("LPO AI Settings")
	if not settings.meta.has_field("enable_standalone_estimation") or not cint(settings.enable_standalone_estimation):
		return {"ready": False, "message": _("Standalone estimation AI is disabled in LPO AI Settings.")}
	try:
		from lex.ai_gateway import STANDALONE_ESTIMATION_USE_CASE
		from lex.lex.doctype.lpo_ai_settings.lpo_ai_settings import resolve_ai_route

		provider, model, credential_name = resolve_ai_route(None, None, STANDALONE_ESTIMATION_USE_CASE)
		return {
			"ready": True,
			"provider": provider,
			"model": model,
			"credential_name": credential_name,
			"message": _("Connected to {0} using {1}.").format(provider, model),
		}
	except Exception as exc:
		return {
			"ready": False,
			"message": _("LPO AI route is not ready: {0}").format(str(exc)[:240]),
		}


def _standalone_estimation_profile_with_ai(doc, extracted: str, document_count: int, word_count: int):
	"""Use LPO AI only for evidence classification; ERP formula remains pricing authority."""
	route = _estimation_ai_route_status()
	if not route.get("ready"):
		return None, route.get("message")
	if not (extracted or "").strip():
		return None, _("No text could be extracted; the governed formula fallback was used.")
	from lex.ai_gateway import STANDALONE_ESTIMATION_USE_CASE, invoke_ai_gateway
	service_catalog = frappe.get_all(
		"LPO LexPoint Service Rule",
		filters={"active": 1},
		pluck="service_name",
		order_by="service_family asc, service_name asc",
		limit_page_length=100,
	)
	catalog_json = json.dumps(service_catalog, default=str, separators=(",", ":"))
	document_sample = extracted[:32000]

	prompt = (
		"You are the evidence-classification component of Lexocrates' governed legal-services estimation system. "
		"This is an internal workload classification task, not legal advice and not a request to decide a dispute. "
		"Do not calculate LexPoints, price, margin, or make a commercial decision. Classify only observable "
		"scope factors grounded in the supplied document. Choose recommended_service as the closest exact service name "
		"from the supplied active catalogue. It must reflect the primary requested work and document evidence, not "
		"an incidental keyword. complexity_score MUST be an integer from 1 to 100: 1-25 Routine, 26-50 Moderate, "
		"51-75 Complex, and 76-100 Specialist. Score scope volume, legal issue count, ambiguity, jurisdictions, "
		"stake/risk, annexures and required judgment together. All confidence values MUST be percentages from 0 to "
		"100, never decimals from 0 to 1. Respond with ONLY one JSON object and no markdown: "
		'{"document_type":"", "document_type_confidence":0, "alternative_matches":[], '
		'"practice_modules":[], "recommended_service":"", "legal_domain":"", "jurisdiction":"", '
		'"jurisdiction_confidence":0, "language":"", "ocr_quality":"Good|Moderate|Low", '
		'"content_form":"Typed|Handwritten|Mixed|Unknown", "has_tables":false, "has_images":false, '
		'"has_signatures":false, "has_annexures":false, "complexity_score":1, '
		'"risk_level":"Low|Medium|High|Critical", '
		'"reviewer_level":"Junior Associate|Senior Associate|Subject Matter Expert|Partner|Mixed Team", '
		'"task_count":1, "confidence":0, "requires_human_review":false, "explanation_factors":[]}.'
		f"\n\nService type: {doc.service_type}\nJurisdiction: {doc.jurisdiction}\nPriority: {doc.priority}\n"
		f"Document count: {document_count}\nApproximate word count: {word_count}\n"
		f"Expected outcome: {doc.expected_outcome}\n"
		f"Detailed instructions: {frappe.utils.strip_html(doc.detailed_instructions or '')}\n"
		f"Active governed service catalogue: {catalog_json}\n\n"
		f"Document corpus sample:\n{document_sample}"
	)
	try:
		with _standalone_ai_gateway_call():
			result = invoke_ai_gateway(
				use_case=STANDALONE_ESTIMATION_USE_CASE,
				prompt_text=prompt,
				client_id=None,
				provider=None,
				model=None,
				credential_name=None,
				prompt_version=None,
				is_high_risk=0,
				source_corpus=document_sample,
				max_tokens=900,
			)
	except Exception as exc:
		return None, _("LPO AI classification failed; governed formula fallback used: {0}").format(str(exc)[:300])

	parsed = _parse_ai_json_object(result.get("response_text") or "")
	if not parsed or not parsed.get("recommended_service") or not cint(parsed.get("complexity_score")):
		return None, _("LPO AI returned an invalid classification; governed formula fallback was used.")
	for key in ("confidence", "document_type_confidence", "jurisdiction_confidence"):
		value = flt(parsed.get(key))
		if 0 < value <= 1:
			value *= 100
		parsed[key] = max(0, min(100, value))
	# File/page/document volume and the billing measure are objective catalogue
	# inputs. They must never be supplied by the model or used to alter pricing.
	parsed.pop("volume", None)
	parsed.pop("billing_measure", None)
	parsed.update(
		{
			"ai_execution": result.get("ai_execution"),
			"provider": result.get("provider"),
			"model": result.get("model"),
			"credential_name": result.get("credential_name"),
			"requires_human_review": bool(
				cint(parsed.get("requires_human_review")) or result.get("requires_human_review")
			),
		}
	)
	return parsed, None


@contextlib.contextmanager
def _estimate_service_writes():
	previous = getattr(frappe.flags, "lexocrates_standalone_estimate_service", False)
	frappe.flags.lexocrates_standalone_estimate_service = True
	try:
		yield
	finally:
		frappe.flags.lexocrates_standalone_estimate_service = previous


@contextlib.contextmanager
def _standalone_ai_gateway_call():
	previous = getattr(frappe.flags, "lexocrates_standalone_ai_estimation", False)
	frappe.flags.lexocrates_standalone_ai_estimation = True
	try:
		yield
	finally:
		frappe.flags.lexocrates_standalone_ai_estimation = previous


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
