from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import zipfile
from datetime import timedelta
from xml.etree import ElementTree

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, getdate, now_datetime, nowdate
from frappe.utils.file_manager import save_file

from lex.client_access import get_portal_user, has_portal_capability
from lex.portal_audit import create_portal_audit_event


ALLOWED_UPLOAD_EXTENSIONS = {".csv", ".doc", ".docx", ".jpeg", ".jpg", ".pdf", ".png", ".txt"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
INTERNAL_ROLES = {"System Manager", "LPO_Admin", "LPO_Manager", "Lexocrates Finance", "Accounts Manager"}
DEFAULT_SLA_VERSION = "CLIENT-INTAKE-SLA-1.0"
DEFAULT_SLA_TERMS = """Client Intake Service Level Agreement

1. Documents remain encrypted/private and are scanned before processing.
2. The preliminary timeline is not the operational SLA. The operational SLA starts only after clean documents, confirmed scope and successful funding.
3. AI-assisted extraction may be used only within the approved Lexocrates processing environment; low-confidence output is reviewed by Legal Operations.
4. A generated quote records fixed price, required LexPoints, confirmed scope and delivery timeline. The client may fund it with existing LexPoints, the recommended LexPack, or the fixed quote directly.
5. Material scope changes require a revised quote and delivery timeline.
6. Lexocrates retains an immutable audit trail of SLA acceptance, documents, quote, funding, execution, QA, approval and delivery.
"""
BASE_POINTS = {
	"Contract Review": 35,
	"Legal Research": 30,
	"Document Review": 28,
	"Due Diligence": 55,
	"Compliance Review": 42,
	"Litigation Support": 60,
	"Drafting": 45,
	"Summarization": 20,
	"Other": 40,
}
BASE_HOURS = {
	"Contract Review": 48,
	"Legal Research": 48,
	"Document Review": 36,
	"Due Diligence": 96,
	"Compliance Review": 72,
	"Litigation Support": 96,
	"Drafting": 72,
	"Summarization": 24,
	"Other": 72,
}


@frappe.whitelist()
def create_work_intake(
	intake_title: str,
	service_type: str,
	jurisdiction: str,
	priority: str,
	expected_outcome: str,
	preliminary_details: str,
	requested_delivery_date: str | None = None,
	confidentiality_level: str = "Confidential",
):
	actor = _require_portal_user()
	if not has_portal_capability("can_create_matters"):
		frappe.throw(_("You are not authorized to submit new work."), frappe.PermissionError)
	if requested_delivery_date and get_datetime(requested_delivery_date) <= now_datetime():
		frappe.throw(_("Requested Delivery Date must be in the future."), frappe.ValidationError)
	sla_version, sla_terms, sla_document = _sla_snapshot()
	values = {
		"doctype": "Lexocrates Work Intake",
		"intake_title": (intake_title or "").strip(),
		"client": actor.client,
		"portal_user": actor.name,
		"submitted_by": frappe.session.user,
		"status": "SLA Pending",
		"created_on": now_datetime(),
		"service_type": service_type,
		"jurisdiction": (jurisdiction or "").strip(),
		"priority": priority,
		"requested_delivery_date": requested_delivery_date or None,
		"expected_outcome": (expected_outcome or "").strip(),
		"preliminary_details": (preliminary_details or "").strip(),
		"confidentiality_level": confidentiality_level,
		"sla_version": sla_version,
		"sla_document_snapshot": sla_document,
		"sla_terms_snapshot": sla_terms,
		"sla_snapshot_hash": _sla_hash(sla_terms, sla_document),
		"currency": _setting("quote_currency", "USD"),
	}
	if service_type not in BASE_POINTS:
		frappe.throw(_("Choose a supported Service Type."), frappe.ValidationError)
	if priority not in {"Low", "Medium", "High", "Urgent"}:
		frappe.throw(_("Choose a valid priority."), frappe.ValidationError)
	with _service_writes():
		doc = frappe.get_doc(values).insert(ignore_permissions=True)
	_audit(doc, "Work Intake Created", {"service_type": service_type, "status": doc.status})
	return {"name": doc.name, "status": doc.status, "route": "/client-portal#new-matter"}


@frappe.whitelist()
def accept_sla(intake: str, accepted: int = 0):
	doc, actor = _require_intake_access(intake)
	if not cint(accepted):
		frappe.throw(_("Confirm that you reviewed and accept the SLA Document."), frappe.ValidationError)
	if doc.status not in {"SLA Pending", "Documents Pending"}:
		frappe.throw(_("The SLA can only be accepted before document processing starts."), frappe.ValidationError)
	if not doc.sla_accepted:
		with _service_writes():
			doc.sla_accepted = 1
			doc.sla_accepted_by = frappe.session.user
			doc.sla_accepted_on = now_datetime()
			doc.status = "Documents Pending"
			doc.save(ignore_permissions=True)
		_audit(doc, "Client Intake SLA Accepted", {"version": doc.sla_version, "hash": doc.sla_snapshot_hash})
	return {"name": doc.name, "status": doc.status, "upload_unlocked": True}


@frappe.whitelist()
def upload_document(intake: str, filename: str, content: str):
	doc, actor = _require_intake_access(intake)
	if not actor or not actor.can_upload_documents:
		frappe.throw(_("Your client role cannot upload documents."), frappe.PermissionError)
	if not doc.sla_accepted:
		frappe.throw(_("Review and accept the SLA Document before uploading files."), frappe.PermissionError)
	if doc.status not in {"Documents Pending", "Security Review", "Analysis Pending", "Operations Review"}:
		frappe.throw(_("Documents are locked after the quote is issued."), frappe.PermissionError)
	filename = os.path.basename((filename or "").strip())
	extension = os.path.splitext(filename)[1].lower()
	if not filename or extension not in ALLOWED_UPLOAD_EXTENSIONS:
		frappe.throw(_("This file type is not allowed."), frappe.ValidationError)
	decoded = _decode_upload(content)
	file_doc = save_file(filename, decoded, "Lexocrates Work Intake", doc.name, is_private=1)
	from lex.file_quarantine import scan_and_validate_inbound_file

	scan = scan_and_validate_inbound_file(file_doc.name)
	_refresh_document_state(doc)
	_audit(
		doc,
		"Work Intake Document Uploaded",
		{"file": file_doc.name, "file_name": file_doc.file_name, "scan_status": scan["status"]},
	)
	return {
		"name": file_doc.name,
		"file_name": file_doc.file_name,
		"scan_status": scan["status"],
		"quarantine_passed": scan["quarantine_passed"],
		"intake_status": doc.status,
	}


@frappe.whitelist()
def save_detailed_instructions(intake: str, detailed_instructions: str):
	doc, actor = _require_intake_access(intake)
	if not doc.sla_accepted:
		frappe.throw(_("Accept the SLA before adding detailed instructions."), frappe.PermissionError)
	if doc.status not in {"Documents Pending", "Security Review", "Analysis Pending", "Operations Review"}:
		frappe.throw(_("Detailed instructions are locked after quote issue."), frappe.PermissionError)
	text = (detailed_instructions or "").strip()
	if len(frappe.utils.strip_html(text)) < 20:
		frappe.throw(_("Provide enough detail for scope and quote analysis."), frappe.ValidationError)
	with _service_writes():
		doc.detailed_instructions = text
		doc.save(ignore_permissions=True)
	_audit(doc, "Work Intake Detailed Instructions Updated", {"characters": len(text)})
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def analyze_documents(intake: str):
	doc, actor = _require_intake_access(intake)
	if not doc.sla_accepted:
		frappe.throw(_("SLA acceptance is required before analysis."), frappe.PermissionError)
	files = _intake_files(doc.name)
	if not files:
		frappe.throw(_("Upload at least one document before analysis."), frappe.ValidationError)
	if len(frappe.utils.strip_html(doc.detailed_instructions or "")) < 20:
		frappe.throw(_("Add detailed instructions before starting analysis."), frappe.ValidationError)
	_refresh_document_state(doc, files)
	if doc.security_status != "Clean":
		return {
			"name": doc.name,
			"status": doc.status,
			"security_status": doc.security_status,
			"message": _("All documents must pass security scanning before extraction and analysis."),
		}

	with _service_writes():
		doc.status = "Analysis Pending"
		doc.analysis_status = "Pending"
		doc.extraction_status = "Pending"
		doc.save(ignore_permissions=True)

	chunks = []
	unsupported = 0
	for row in files:
		text = _extract_file_text(frappe.get_doc("File", row.name))
		if text:
			chunks.append(f"[{row.file_name}]\n{text}")
		else:
			unsupported += 1
	extracted = "\n\n".join(chunks)[:100000]
	word_count = len(extracted.split())
	confidence = _analysis_confidence(files, chunks, unsupported, word_count)
	threshold = flt(_setting("low_confidence_threshold", 72))
	low_confidence = confidence < threshold
	ai_result, ai_error = _run_governed_ai_analysis(doc, extracted)
	if ai_error or (ai_result and ai_result.get("requires_human_review")):
		low_confidence = True

	ai_estimate, ai_estimate_note = _estimate_lexpoints_with_ai(doc, extracted, len(files), word_count)
	if ai_estimate:
		points = ai_estimate["lexpoints"]
		hours = ai_estimate["delivery_hours"] or BASE_HOURS.get(doc.service_type, 72)
		estimate_method = "AI"
	else:
		points, hours = _calculate_estimate(doc, word_count, len(files))
		estimate_method = "Formula"

	quote_amount = flt(points * flt(_setting("direct_quote_rate_per_point", 3)), 2)
	scope = _scope_summary(doc, len(files), word_count)
	recommended = _recommend_plan(doc.client, points)
	with _service_writes():
		doc.reload()
		doc.extracted_text = extracted
		doc.extraction_status = "Complete" if chunks and not unsupported else ("Partial" if chunks else "Failed")
		doc.analysis_status = "Operations Review" if low_confidence else "Complete"
		doc.analysis_confidence = confidence
		doc.low_confidence = int(low_confidence)
		doc.analysis_provider = (
			f"Governed AI Gateway · {_setting('intake_ai_provider', 'OpenAI')}/{_setting('intake_ai_model', 'gpt-4o')}"
			if ai_result else "Lexocrates Secure Extraction & Estimation Engine v1 (AI gateway not enabled)"
		)
		doc.ai_execution = ai_result.get("ai_execution") if ai_result else None
		base_summary = (
			f"Analyzed {len(files)} clean document(s), extracted approximately {word_count:,} words, "
			f"and estimated {points} LexPoints via {estimate_method.lower()} pricing"
			+ (f" ({ai_estimate['reasoning']})" if ai_estimate and ai_estimate.get("reasoning") else "") + ". "
			+ ("Low confidence requires Legal Operations review." if low_confidence else "Confidence passed the configured auto-quote threshold.")
		)
		doc.analysis_summary = (
			f"{base_summary}\n\nGoverned AI analysis:\n{ai_result.get('response_text', '')[:6000]}" if ai_result
			else f"{base_summary}\n\n{ai_error}" if ai_error else base_summary
		)
		doc.required_lexpoints = points
		doc.quoted_amount = quote_amount
		doc.delivery_timeline_hours = hours
		doc.scope_summary = scope
		doc.estimate_method = estimate_method
		doc.quote_version = cint(doc.quote_version) + 1
		doc.quote_valid_until = add_days(nowdate(), cint(_setting("quote_validity_days", 7)))
		doc.recommended_plan = recommended
		if low_confidence:
			doc.quote_status = "Operations Review"
			doc.status = "Operations Review"
			doc.pricing_approval_status = "Not Required"
		else:
			doc.quote_issued_by = frappe.session.user
			doc.quote_issued_on = now_datetime()
			_route_quote_for_approval(doc)
		doc.save(ignore_permissions=True)
	if not low_confidence:
		_notify_ceo_of_pending_pricing(doc)
	_audit(
		doc,
		"Work Intake Analysis Completed",
		{
			"confidence": confidence,
			"low_confidence": low_confidence,
			"required_lexpoints": points,
			"estimate_method": estimate_method,
			"ai_estimate_note": ai_estimate_note,
		},
	)
	return _intake_row(doc, actor)


@frappe.whitelist()
def issue_quote(
	intake: str,
	required_lexpoints: int,
	quoted_amount: float,
	delivery_timeline_hours: int,
	scope_summary: str,
	review_notes: str | None = None,
):
	_require_internal()
	doc = frappe.get_doc("Lexocrates Work Intake", intake)
	if doc.status not in {"Operations Review", "Analysis Pending", "Quote Ready", "Pending CEO Approval"}:
		frappe.throw(_("This intake is not awaiting quote review."), frappe.ValidationError)
	if cint(required_lexpoints) <= 0 or flt(quoted_amount) <= 0 or cint(delivery_timeline_hours) <= 0:
		frappe.throw(_("Quote points, amount and delivery hours must be positive."), frappe.ValidationError)
	with _service_writes():
		doc.required_lexpoints = cint(required_lexpoints)
		doc.quoted_amount = flt(quoted_amount, 2)
		doc.delivery_timeline_hours = cint(delivery_timeline_hours)
		doc.scope_summary = (scope_summary or "").strip()
		doc.operations_review_notes = (review_notes or "").strip()
		doc.low_confidence = 0
		doc.analysis_status = "Complete"
		doc.estimate_method = "Manual (Operations)"
		doc.quote_version = cint(doc.quote_version) + 1
		doc.quote_valid_until = add_days(nowdate(), cint(_setting("quote_validity_days", 7)))
		doc.recommended_plan = _recommend_plan(doc.client, cint(required_lexpoints))
		doc.quote_issued_by = frappe.session.user
		doc.quote_issued_on = now_datetime()
		_route_quote_for_approval(doc)
		doc.save(ignore_permissions=True)
	_notify_ceo_of_pending_pricing(doc)
	_audit(doc, "Work Intake Quote Issued", {"quote_version": doc.quote_version, "required_lexpoints": doc.required_lexpoints})
	return {"name": doc.name, "status": doc.status, "quote_status": doc.quote_status}


@frappe.whitelist()
def approve_quote_pricing(intake: str, decision: str, notes: str | None = None):
	"""CEO signs off on (or rejects) the estimated price before the client can fund the matter."""
	if frappe.session.user != "Administrator" and "CEO" not in frappe.get_roles(frappe.session.user):
		frappe.throw(_("Only the CEO role can approve or reject matter pricing."), frappe.PermissionError)
	doc = frappe.get_doc("Lexocrates Work Intake", intake)
	if doc.pricing_approval_status != "Pending CEO Approval":
		frappe.throw(_("This intake is not awaiting pricing approval."), frappe.ValidationError)
	if decision not in {"Approved", "Rejected"}:
		frappe.throw(_("Decision must be Approved or Rejected."), frappe.ValidationError)
	if decision == "Rejected" and not (notes or "").strip():
		frappe.throw(_("Provide a reason when rejecting a quote."), frappe.MandatoryError)
	with _service_writes():
		doc.pricing_approval_status = decision
		doc.pricing_approved_by = frappe.session.user
		doc.pricing_approved_on = now_datetime()
		if decision == "Approved":
			doc.pricing_rejection_reason = None
			doc.quote_status = "Ready"
			doc.status = "Quote Ready"
		else:
			doc.pricing_rejection_reason = (notes or "").strip()
			doc.quote_status = "Operations Review"
			doc.status = "Operations Review"
		doc.save(ignore_permissions=True)
	_audit(
		doc,
		"Matter Pricing Approval Decision",
		{"decision": decision, "notes": notes, "quoted_amount": doc.quoted_amount, "required_lexpoints": doc.required_lexpoints},
	)
	return {"intake": doc.name, "status": doc.status, "pricing_approval_status": doc.pricing_approval_status}


@frappe.whitelist()
def fund_with_existing_lexpoints(intake: str):
	doc, actor = _require_intake_access(intake)
	_require_funding_authority(actor, "Existing LexPoints")
	_validate_ready_quote(doc)
	available = _available_lexpoints(doc.client)
	if available < flt(doc.required_lexpoints):
		frappe.throw(
			_("Available balance is {0} LexPoints; this work requires {1}.").format(
				cint(available), cint(doc.required_lexpoints)
			),
			frappe.ValidationError,
		)
	with _service_writes():
		doc.funding_route = "Existing LexPoints"
		doc.funding_status = "Funded"
		doc.funded_on = now_datetime()
		doc.quote_status = "Accepted"
		doc.status = "Funded"
		doc.save(ignore_permissions=True)
	return _confirm_funded_intake(doc)


def prepare_lexpack_purchase(intake: str, plan: str, actor=None):
	doc, actor = _require_intake_access(intake, actor=actor)
	_require_funding_authority(actor, "Recommended LexPack")
	_validate_ready_quote(doc)
	if doc.recommended_plan != plan:
		frappe.throw(_("Purchase the LexPack recommended for this confirmed quote."), frappe.ValidationError)
	plan_points = cint(frappe.db.get_value("LexPack Plan", plan, "lexpoints"))
	if _available_lexpoints(doc.client) + plan_points < cint(doc.required_lexpoints):
		frappe.throw(_("The selected LexPack does not fully fund this quote."), frappe.ValidationError)
	with _service_writes():
		doc.funding_route = "Recommended LexPack"
		doc.funding_status = "Payment Pending"
		doc.status = "Funding Pending"
		doc.failure_reason = None
		doc.save(ignore_permissions=True)
	return doc, actor


def link_lexpack_purchase(intake: str, purchase: str):
	doc = frappe.get_doc("Lexocrates Work Intake", intake)
	with _service_writes():
		doc.lexpack_purchase = purchase
		doc.save(ignore_permissions=True)


def complete_lexpack_funding(purchase_doc):
	if not purchase_doc.get("work_intake"):
		return None
	doc = frappe.get_doc("Lexocrates Work Intake", purchase_doc.work_intake)
	if doc.lexpack_purchase and doc.lexpack_purchase != purchase_doc.name:
		return None
	try:
		if _available_lexpoints(doc.client) < flt(doc.required_lexpoints):
			with _service_writes():
				doc.funding_status = "Payment Pending"
				doc.failure_reason = _("LexPack was credited, but another reservation used the remaining balance. Add capacity to finish funding.")
				doc.save(ignore_permissions=True)
			return {"intake": doc.name, "status": doc.status}
		with _service_writes():
			doc.funding_route = "Recommended LexPack"
			doc.funding_status = "Funded"
			doc.funded_on = now_datetime()
			doc.quote_status = "Accepted"
			doc.status = "Funded"
			doc.failure_reason = None
			doc.save(ignore_permissions=True)
		return _confirm_funded_intake(doc)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"LexPack intake funding {doc.name}")
		return {"intake": doc.name, "status": doc.status}


@frappe.whitelist()
def create_direct_quote_order(intake: str):
	doc, actor = _require_intake_access(intake)
	_require_funding_authority(actor, "Direct Quote")
	_validate_ready_quote(doc)
	from lex import lexpack

	settings = lexpack._get_settings(require_enabled=True)
	exchange_rate = lexpack._resolve_exchange_rate(doc.currency, settings.company)
	payload = {
		"amount": lexpack._minor_units(doc.quoted_amount, doc.currency),
		"currency": doc.currency,
		"receipt": doc.name,
		"notes": {"work_intake": doc.name, "client": doc.client, "funding_route": "Direct Quote"},
	}
	with _service_writes():
		doc.funding_route = "Direct Quote"
		doc.funding_status = "Payment Pending"
		doc.status = "Funding Pending"
		doc.exchange_rate = exchange_rate
		doc.failure_reason = None
		doc.save(ignore_permissions=True)
	try:
		order = lexpack._razorpay_request("POST", "/orders", settings, payload)
		lexpack._validate_order_response(order, payload)
		_set_values(doc, razorpay_order_id=order["id"])
	except Exception as exc:
		_set_values(doc, funding_status="Failed", failure_reason=lexpack._safe_gateway_error(exc))
		raise
	_audit(doc, "Direct Quote Razorpay Order Created", {"amount": doc.quoted_amount, "currency": doc.currency})
	return _checkout_payload(doc, actor, settings, payload)


@frappe.whitelist()
def verify_direct_quote_payment(
	intake: str,
	razorpay_payment_id: str,
	razorpay_order_id: str,
	razorpay_signature: str,
):
	doc, actor = _require_intake_access(intake)
	_require_funding_authority(actor, "Direct Quote")
	from lex import lexpack

	settings = lexpack._get_settings(require_enabled=True)
	if not doc.razorpay_order_id or doc.razorpay_order_id != razorpay_order_id:
		frappe.throw(_("Razorpay order mismatch."), frappe.PermissionError)
	if not lexpack._checkout_signature_is_valid(
		doc.razorpay_order_id, razorpay_payment_id, razorpay_signature, settings.get_password("key_secret")
	):
		frappe.throw(_("Payment verification failed."), frappe.PermissionError)
	payment = lexpack._razorpay_request("GET", f"/payments/{razorpay_payment_id}", settings)
	_validate_direct_payment(doc, payment, require_captured=False)
	_set_values(doc, razorpay_payment_id=razorpay_payment_id, signature_verified=1, failure_reason=None)
	if payment.get("status") != "captured":
		return {"intake": doc.name, "status": "Payment Pending", "message": _("Payment will be confirmed after capture.")}
	return complete_direct_payment(doc, payment, source="checkout")


def handle_direct_webhook(event: str, event_id: str | None, payment: dict, order_id: str):
	name = frappe.db.get_value("Lexocrates Work Intake", {"razorpay_order_id": order_id}, "name")
	if not name:
		return None
	doc = frappe.get_doc("Lexocrates Work Intake", name)
	from lex import lexpack

	settings = lexpack._get_settings(require_enabled=True)
	if event in {"payment.captured", "order.paid"}:
		if not payment.get("id"):
			payments = lexpack._razorpay_request("GET", f"/orders/{order_id}/payments", settings)
			payment = next((row for row in payments.get("items", []) if row.get("status") == "captured"), {})
		_validate_direct_payment(doc, payment, require_captured=True)
		_set_values(doc, razorpay_payment_id=payment["id"], gateway_event_id=event_id, failure_reason=None)
		return complete_direct_payment(doc, payment, source="webhook")
	if event == "payment.failed" and doc.funding_status != "Funded":
		failure = (payment.get("error_description") or payment.get("error_reason") or _("Razorpay reported a failed payment."))[:500]
		_set_values(doc, funding_status="Failed", gateway_event_id=event_id, failure_reason=failure)
		return {"status": "failed", "intake": doc.name}
	return {"status": "ignored", "event": event, "intake": doc.name}


def complete_direct_payment(doc, payment: dict, source: str):
	frappe.db.sql("select name from `tabLexocrates Work Intake` where name=%s for update", doc.name)
	doc.reload()
	if doc.funding_status == "Funded" and doc.matter and doc.job:
		return _funding_result(doc, duplicate=True)
	_validate_direct_payment(doc, payment, require_captured=True)
	from lex import lexpack

	settings = lexpack._get_settings(require_enabled=True)
	if not doc.sales_invoice:
		invoice = _create_direct_invoice(doc, settings)
		_set_values(doc, sales_invoice=invoice.name)
	if not doc.payment_entry:
		payment_entry = _create_direct_payment_entry(doc, settings, payment)
		_set_values(doc, payment_entry=payment_entry.name)
	_set_values(
		doc,
		funding_route="Direct Quote",
		funding_status="Funded",
		funded_on=now_datetime(),
		quote_status="Accepted",
		status="Funded",
		failure_reason=None,
	)
	result = _confirm_funded_intake(doc)
	_audit(doc, "Direct Quote Paid", {"source": source, "amount": doc.quoted_amount, "currency": doc.currency})
	return result


def portal_intakes(actor=None):
	actor = actor or _require_portal_user()
	filters = {"client": actor.client}
	if actor.matter_access_scope != "All Client Matters":
		filters["portal_user"] = actor.name
	rows = frappe.get_all(
		"Lexocrates Work Intake",
		filters=filters,
		fields=[
			"name", "intake_title", "status", "created_on", "service_type", "jurisdiction", "priority",
			"requested_delivery_date", "expected_outcome", "preliminary_details", "detailed_instructions", "confidentiality_level",
			"sla_version", "sla_document_snapshot", "sla_terms_snapshot", "sla_snapshot_hash", "sla_accepted", "sla_accepted_by", "sla_accepted_on",
			"document_count", "clean_document_count", "security_status", "extraction_status", "analysis_status",
			"analysis_confidence", "low_confidence", "analysis_provider", "ai_execution", "analysis_summary", "operations_review_notes",
			"quote_version", "quote_status", "quoted_amount", "currency", "required_lexpoints", "scope_summary",
			"estimate_method", "pricing_approval_status", "pricing_rejection_reason",
			"delivery_timeline_hours", "quote_valid_until", "recommended_plan", "funding_route", "funding_status",
			"lexpack_purchase", "wallet_reservation", "failure_reason", "sales_invoice", "payment_entry",
			"matter", "job", "sla_started_on", "delivery_due_on",
		],
		order_by="created_on desc",
		limit_page_length=100,
	)
	return [_intake_row(frappe._dict(row), actor) for row in rows]


def _confirm_funded_intake(doc):
	frappe.db.sql("select name from `tabLexocrates Work Intake` where name=%s for update", doc.name)
	doc.reload()
	if doc.matter and doc.job:
		return _funding_result(doc, duplicate=True)
	if doc.funding_status != "Funded":
		frappe.throw(_("Funding must be successful before Matter confirmation."), frappe.ValidationError)
	start = now_datetime()
	due = start + timedelta(hours=cint(doc.delivery_timeline_hours))
	practice_area = _practice_area(doc.service_type)
	portal_permissions = frappe.db.get_value(
		"Lexocrates Portal User",
		doc.portal_user,
		["can_upload_documents", "can_comment", "approval_authority", "billing_access"],
		as_dict=True,
	) or frappe._dict()
	matter_values = {
		"doctype": "LPO Matter",
		"matter_title": doc.intake_title,
		"customer": doc.client,
		"status": "Draft" if doc.funding_route != "Direct Quote" else "Active",
		"matter_model": "Fixed Fee" if doc.funding_route == "Direct Quote" else "Project",
		"matter_manager": "Administrator",
		"billing_method": "Quoted Price" if doc.funding_route == "Direct Quote" else "LexPack",
		"quoted_amount": doc.quoted_amount if doc.funding_route == "Direct Quote" else 0,
		"quote_status": "Approved" if doc.funding_route == "Direct Quote" else "Not Required",
		"quote_approved_by": doc.submitted_by if doc.funding_route == "Direct Quote" else None,
		"quote_approved_on": doc.funded_on if doc.funding_route == "Direct Quote" else None,
		"lexpoints_estimated": doc.required_lexpoints if doc.funding_route != "Direct Quote" else 0,
		"practice_area": practice_area,
		"jurisdictions": doc.jurisdiction,
		"description": doc.scope_summary,
		"start_date": getdate(start),
		"end_date": getdate(due),
		"standard_turnaround_hours": doc.delivery_timeline_hours,
		"sla_warning_hours": max(1, min(8, cint(doc.delivery_timeline_hours / 6))),
		"confidentiality_level": doc.confidentiality_level,
		"authorized_portal_users": [{
			"portal_user": doc.portal_user,
			"user": doc.submitted_by,
			"can_view": 1,
			"can_upload": cint(portal_permissions.can_upload_documents),
			"can_comment": cint(portal_permissions.can_comment),
			"can_approve": cint(portal_permissions.approval_authority not in {None, "", "None"}),
			"can_view_billing": cint(portal_permissions.billing_access),
		}],
	}
	previous_portal_flag = getattr(frappe.flags, "lexocrates_portal_service", False)
	frappe.flags.lexocrates_portal_service = True
	try:
		matter = frappe.get_doc(matter_values).insert(ignore_permissions=True)
		reservation = None
		if doc.funding_route != "Direct Quote":
			from lex.lex.doctype.lexocrates_wallet_transaction.lexocrates_wallet_transaction import _post_transaction

			reservation = _post_transaction(
				client=doc.client,
				transaction_type="Reservation",
				points=doc.required_lexpoints,
				idempotency_key=f"work-intake-reservation:{doc.name}",
				matter=matter.name,
				reference_doctype="Lexocrates Work Intake",
				reference_name=doc.name,
				description=f"Funding reserved for {doc.intake_title}",
			)
			matter.funding_status = "Funded"
			matter.funding_transaction = reservation.name
			matter.lexpoints_reserved = doc.required_lexpoints
			matter.status = "Active"
			matter.save(ignore_permissions=True)
		files = _intake_files(doc.name)
		primary = next((row.file_url for row in files if row.custom_lex_scan_status == "Clean"), None)
		job = frappe.get_doc({
			"doctype": "LPO Job",
			"job_title": doc.intake_title,
			"engagement": matter.name,
			"job_type": doc.service_type,
			"job_status": "Activated",
			"priority": doc.priority,
			"task_description": f"{doc.expected_outcome}\n\nPreliminary details:\n{doc.preliminary_details}\n\nDetailed instructions:\n{doc.detailed_instructions}\n\nConfirmed scope:\n{doc.scope_summary}",
			"received_at": start,
			"due_date": due,
			"source_document": primary,
			"qa_required": 1,
		}).insert(ignore_permissions=True)
	finally:
		frappe.flags.lexocrates_portal_service = previous_portal_flag
	with _service_writes():
		doc.reload()
		doc.wallet_reservation = reservation.name if reservation else None
		doc.matter = matter.name
		doc.job = job.name
		doc.sla_started_on = start
		doc.delivery_due_on = due
		doc.status = "Matter Confirmed"
		doc.save(ignore_permissions=True)
	_audit(
		doc,
		"Funded Work Activated",
		{"funding_route": doc.funding_route, "matter": matter.name, "job": job.name, "sla_started_on": start},
	)
	return _funding_result(doc)


def _intake_row(doc, actor):
	documents = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Lexocrates Work Intake", "attached_to_name": doc.name, "is_folder": 0},
		fields=["name", "file_name", "file_url", "file_size", "modified", "custom_lex_scan_status"],
		order_by="creation asc",
		limit_page_length=100,
	)
	plan = None
	if doc.get("recommended_plan"):
		plan = frappe.db.get_value(
			"LexPack Plan", doc.recommended_plan,
			["name", "plan_code", "plan_name", "price", "currency", "lexpoints", "self_service", "enterprise_custom"],
			as_dict=True,
		)
	# ``frappe._dict`` returns ``None`` for unknown attributes, so
	# ``hasattr(doc, "as_dict")`` is true even though the value is not callable.
	# Portal list queries return ``frappe._dict`` rows while document APIs return
	# real Document instances; handle both without treating a missing key as a
	# method.
	as_dict = getattr(doc, "as_dict", None)
	row = as_dict() if callable(as_dict) else dict(doc)
	row["documents"] = documents
	row["recommended_plan_details"] = plan
	row["available_lexpoints"] = _available_lexpoints(doc.client)
	row["can_fund_lexpoints"] = bool(actor and actor.lexpack_purchase_access)
	row["can_pay_direct"] = bool(actor and actor.billing_access)
	return row


def _refresh_document_state(doc, files=None):
	files = files or _intake_files(doc.name)
	statuses = [row.custom_lex_scan_status or "Pending" for row in files]
	clean = sum(status == "Clean" for status in statuses)
	if any(status in {"Infected", "Rejected"} for status in statuses):
		security = "Blocked"
		status = "Security Review"
	elif files and clean == len(files):
		security = "Clean"
		status = "Analysis Pending"
	elif any(status == "Scanner Unavailable" for status in statuses):
		security = "Operations Review"
		status = "Security Review"
	else:
		security = "Pending" if files else "Not Started"
		status = "Security Review" if files else "Documents Pending"
	with _service_writes():
		doc.reload()
		doc.document_count = len(files)
		doc.clean_document_count = clean
		doc.security_status = security
		doc.status = status
		doc.save(ignore_permissions=True)


def _intake_files(intake):
	fields = ["name", "file_name", "file_url", "file_size", "custom_lex_scan_status"]
	return frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Lexocrates Work Intake", "attached_to_name": intake, "is_folder": 0},
		fields=fields,
		order_by="creation asc",
		limit_page_length=100,
	)


def _extract_file_text(file_doc):
	content = file_doc.get_content()
	if isinstance(content, str):
		content = content.encode("utf-8")
	extension = os.path.splitext((file_doc.file_name or "").lower())[1]
	try:
		if extension in {".txt", ".csv"}:
			return content.decode("utf-8", errors="replace")[:50000]
		if extension == ".docx":
			with zipfile.ZipFile(io.BytesIO(content)) as archive:
				root = ElementTree.fromstring(archive.read("word/document.xml"))
			return " ".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))[:50000]
		if extension == ".pdf":
			try:
				from pypdf import PdfReader
			except ImportError:
				try:
					from PyPDF2 import PdfReader
				except ImportError:
					return ""
			reader = PdfReader(io.BytesIO(content))
			return "\n".join((page.extract_text() or "") for page in reader.pages)[:50000]
	except (OSError, ValueError, KeyError, zipfile.BadZipFile):
		return ""
	return ""


def _analysis_confidence(files, chunks, unsupported, word_count):
	if not chunks:
		return 45
	coverage = len(chunks) / max(1, len(files))
	confidence = 70 + (20 * coverage)
	if word_count < 40:
		confidence -= 15
	if unsupported:
		confidence -= min(20, unsupported * 8)
	return max(0, min(95, round(confidence, 1)))


def _run_governed_ai_analysis(doc, extracted):
	if not cint(_setting("enable_ai_intake_analysis", 0)):
		return None, None
	if not extracted.strip():
		return None, _("AI analysis was not run because no text could be extracted; Operations Review is required.")
	from lex.ai_gateway import invoke_ai_gateway

	prompt = (
		"Analyze this legal work intake for scope, complexity, key risks, missing information and delivery assumptions. "
		"Do not make a final legal conclusion or commercial decision. Ground every factual statement in the provided corpus.\n\n"
		f"Service: {doc.service_type}\nJurisdiction: {doc.jurisdiction}\nExpected outcome: {doc.expected_outcome}\n"
		f"Detailed instructions: {frappe.utils.strip_html(doc.detailed_instructions or '')}\n\nDocument corpus:\n{extracted[:50000]}"
	)
	try:
		return invoke_ai_gateway(
			use_case="Client Work Intake Analysis",
			prompt_text=prompt,
			client_id=doc.client,
			provider=str(_setting("intake_ai_provider", "OpenAI")),
			model=str(_setting("intake_ai_model", "gpt-4o")),
			prompt_version=None,
			is_high_risk=0,
			source_corpus=extracted[:50000],
		), None
	except Exception as exc:
		return None, _("Governed AI analysis failed and the intake was routed to Operations Review: {0}").format(str(exc)[:300])


def _estimate_lexpoints_with_ai(doc, extracted, document_count, word_count):
	"""Ask the governed AI gateway for a LexPoints/delivery-hours estimate.

	Returns (estimate_dict_or_None, note_or_None). A None estimate means the
	caller should fall back to the deterministic _calculate_estimate formula;
	`note` explains why (disabled, empty extraction, call failure, or an
	unparsable response) and is recorded for audit/debugging, not shown raw
	to the client.
	"""
	if not cint(_setting("enable_ai_intake_analysis", 0)):
		return None, "AI intake analysis is disabled; using the standard formula."
	if not extracted.strip():
		return None, "No text could be extracted; using the standard formula."
	from lex.ai_gateway import invoke_ai_gateway

	prompt = (
		"You are a legal-services pricing estimator for a legal process outsourcing company. "
		"Estimate the LexPoints (internal service-capacity units) and delivery hours required to "
		"complete the described work, based only on the service type, priority, jurisdiction, "
		"instructions and document corpus provided. Respond with ONLY one JSON object and nothing else "
		"(no prose, no markdown fences), in exactly this shape: "
		'{"lexpoints": <positive integer>, "delivery_hours": <positive integer>, "reasoning": "<one short sentence>"}.\n\n'
		f"Service type: {doc.service_type}\nJurisdiction: {doc.jurisdiction}\nPriority: {doc.priority}\n"
		f"Document count: {document_count}\nApproximate word count: {word_count}\n"
		f"Expected outcome: {doc.expected_outcome}\n"
		f"Detailed instructions: {frappe.utils.strip_html(doc.detailed_instructions or '')}\n\n"
		f"Document corpus:\n{extracted[:50000]}"
	)
	try:
		result = invoke_ai_gateway(
			use_case="Client Work Intake LexPoint Estimation",
			prompt_text=prompt,
			client_id=doc.client,
			provider=str(_setting("intake_ai_provider", "OpenAI")),
			model=str(_setting("intake_ai_model", "gpt-4o")),
			prompt_version=None,
			is_high_risk=0,
			source_corpus=extracted[:50000],
		)
	except Exception as exc:
		return None, f"AI pricing estimate call failed, using the standard formula: {str(exc)[:300]}"

	parsed = _parse_ai_json_object(result.get("response_text") or "")
	if not parsed or cint(parsed.get("lexpoints", 0)) <= 0:
		return None, "AI response could not be parsed into a valid LexPoints estimate; using the standard formula."
	return {
		"lexpoints": cint(parsed.get("lexpoints")),
		"delivery_hours": cint(parsed.get("delivery_hours") or 0),
		"reasoning": str(parsed.get("reasoning") or "")[:300],
	}, None


def _parse_ai_json_object(text):
	text = (text or "").strip()
	if not text:
		return None
	try:
		return json.loads(text)
	except (ValueError, TypeError):
		pass
	match = re.search(r"\{.*\}", text, re.DOTALL)
	if not match:
		return None
	try:
		return json.loads(match.group(0))
	except (ValueError, TypeError):
		return None


def _route_quote_for_approval(doc):
	"""Decide whether a freshly priced quote needs CEO sign-off before it can be funded.

	Called with in-memory field changes only (no save) so it composes cleanly
	into the caller's own _service_writes()/save() block.
	"""
	if cint(_setting("auto_approve_ai_pricing", 0)):
		doc.pricing_approval_status = "Not Required"
		doc.quote_status = "Ready"
		doc.status = "Quote Ready"
	else:
		doc.pricing_approval_status = "Pending CEO Approval"
		doc.pricing_approved_by = None
		doc.pricing_approved_on = None
		doc.pricing_rejection_reason = None
		doc.quote_status = "Pending CEO Approval"
		doc.status = "Pending CEO Approval"


def _notify_ceo_of_pending_pricing(doc):
	"""Notify every user holding the CEO role (in-app + email) that a quote awaits approval."""
	doc.reload()
	if doc.pricing_approval_status != "Pending CEO Approval":
		return
	ceo_users = [
		user for user in frappe.get_all("Has Role", filters={"role": "CEO", "parenttype": "User"}, pluck="parent")
		if user not in ("Administrator", "Guest") and frappe.db.get_value("User", user, "enabled")
	]
	if not ceo_users:
		frappe.log_error("No enabled CEO user found to notify for pricing approval.", "Work Intake Pricing Approval")
		return

	link = frappe.utils.get_url(f"/app/lexocrates-work-intake/{doc.name}")
	subject = _("Matter pricing approval needed: {0}").format(doc.intake_title)
	message = _(
		"<p>A new quote is ready for your approval before the client can pay.</p>"
		"<p><b>Matter:</b> {0}<br><b>Client:</b> {1}<br><b>Service type:</b> {2}<br>"
		"<b>Estimated price:</b> {3} {4}<br><b>Required LexPoints:</b> {5}<br>"
		"<b>Delivery timeline:</b> {6} hours<br><b>Estimate method:</b> {7}</p>"
		"<p><a href=\"{8}\">Open in Lexocrates Desk to approve or reject</a></p>"
	).format(
		frappe.utils.escape_html(doc.intake_title), doc.client, doc.service_type,
		doc.quoted_amount, doc.currency, doc.required_lexpoints, doc.delivery_timeline_hours,
		doc.estimate_method or "Formula", link,
	)
	for user in ceo_users:
		frappe.get_doc({
			"doctype": "Notification Log",
			"for_user": user,
			"type": "Alert",
			"document_type": doc.doctype,
			"document_name": doc.name,
			"subject": subject,
			"email_content": message,
		}).insert(ignore_permissions=True)
	recipient_emails = list(filter(None, (frappe.db.get_value("User", user, "email") for user in ceo_users)))
	if recipient_emails:
		try:
			frappe.sendmail(recipients=recipient_emails, subject=subject, message=message, now=False)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"CEO pricing approval email failed for {doc.name}")
	_audit(
		doc,
		"CEO Pricing Approval Requested",
		{"quoted_amount": doc.quoted_amount, "required_lexpoints": doc.required_lexpoints, "notified": ceo_users},
	)


def _calculate_estimate(doc, word_count, document_count):
	points = BASE_POINTS.get(doc.service_type, 40)
	points += max(0, math.ceil(word_count / 750) - 1) * 4
	points += max(0, document_count - 1) * 5
	if doc.priority == "High":
		points = math.ceil(points * 1.15)
	elif doc.priority == "Urgent":
		points = math.ceil(points * 1.35)
	if "," in (doc.jurisdiction or ""):
		points += 8
	points = max(10, int(math.ceil(points / 5) * 5))
	hours = BASE_HOURS.get(doc.service_type, 72)
	if word_count > 10000:
		hours += 24
	if document_count > 5:
		hours += 24
	if doc.priority == "Urgent":
		hours = max(12, math.ceil(hours * 0.6))
	elif doc.priority == "High":
		hours = max(18, math.ceil(hours * 0.8))
	return points, hours


def _scope_summary(doc, document_count, word_count):
	return (
		f"{doc.service_type} for {doc.jurisdiction}. Review {document_count} client document(s) "
		f"({word_count:,} extracted words) to deliver: {doc.expected_outcome}. "
		f"Client instructions: {frappe.utils.strip_html(doc.detailed_instructions or doc.preliminary_details or '')[:1200]}"
	)


def _recommend_plan(client, required_points):
	available = _available_lexpoints(client)
	if available >= required_points:
		return None
	shortfall = required_points - available
	plans = frappe.get_all(
		"LexPack Plan",
		filters={"status": "Active", "self_service": 1, "enterprise_custom": 0, "lexpoints": [">=", shortfall]},
		fields=["name", "lexpoints", "price", "display_order"],
		order_by="lexpoints asc, display_order asc",
		limit_page_length=1,
	)
	return plans[0].name if plans else None


def _validate_ready_quote(doc):
	if doc.quote_status != "Ready" or doc.status not in {"Quote Ready", "Funding Pending"}:
		frappe.throw(_("A reviewed, current quote is required before funding."), frappe.ValidationError)
	if doc.quote_valid_until and getdate(doc.quote_valid_until) < getdate(nowdate()):
		_set_values(doc, quote_status="Expired")
		frappe.throw(_("This quote expired. Ask Legal Operations to issue a new version."), frappe.ValidationError)


def _validate_direct_payment(doc, payment, require_captured=True):
	from lex import lexpack

	if not payment or payment.get("entity") != "payment" or not payment.get("id"):
		frappe.throw(_("Razorpay payment details are missing."), frappe.ValidationError)
	if payment.get("order_id") != doc.razorpay_order_id:
		frappe.throw(_("Razorpay payment belongs to another order."), frappe.PermissionError)
	if cint(payment.get("amount")) != lexpack._minor_units(doc.quoted_amount, doc.currency):
		frappe.throw(_("Razorpay payment does not match the fixed quote."), frappe.PermissionError)
	if payment.get("currency") != doc.currency:
		frappe.throw(_("Razorpay payment currency does not match the fixed quote."), frappe.PermissionError)
	if require_captured and payment.get("status") != "captured":
		frappe.throw(_("Funding completes only after Razorpay captures the payment."), frappe.ValidationError)


def _create_direct_invoice(doc, settings):
	item_code = settings.get("direct_quote_item") or settings.selling_item
	if not item_code:
		frappe.throw(_("Configure the Fixed Quote Selling Item in LexPack Settings."), frappe.ValidationError)
	invoice = frappe.new_doc("Sales Invoice")
	invoice.customer = doc.client
	invoice.company = settings.company
	invoice.posting_date = nowdate()
	invoice.due_date = nowdate()
	invoice.currency = doc.currency
	invoice.conversion_rate = flt(doc.exchange_rate) or 1
	invoice.remarks = f"Fixed Quote Work Intake {doc.name}; Razorpay Order {doc.razorpay_order_id}"
	item = {"item_code": item_code, "qty": 1, "rate": doc.quoted_amount, "description": doc.scope_summary[:1000]}
	if settings.get("income_account"):
		item["income_account"] = settings.income_account
	if settings.get("cost_center"):
		item["cost_center"] = settings.cost_center
	invoice.append("items", item)
	invoice.insert(ignore_permissions=True)
	invoice.flags.ignore_permissions = True
	invoice.submit()
	return invoice


def _create_direct_payment_entry(doc, settings, payment):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	entry = get_payment_entry(
		"Sales Invoice", doc.sales_invoice, bank_account=settings.razorpay_clearing_account,
		reference_date=nowdate(), ignore_permissions=True,
	)
	entry.mode_of_payment = settings.mode_of_payment
	entry.reference_no = payment["id"]
	entry.reference_date = nowdate()
	entry.remarks = f"Razorpay direct quote settlement for Work Intake {doc.name}"
	entry.insert(ignore_permissions=True)
	entry.flags.ignore_permissions = True
	entry.submit()
	return entry


def _checkout_payload(doc, actor, settings, payload):
	from lex.lexpack import _checkout_prefill

	return {
		"intake": doc.name,
		"key": settings.key_id,
		"order_id": doc.razorpay_order_id,
		"amount": payload["amount"],
		"currency": doc.currency,
		"name": settings.checkout_name or "Lexocrates Legal Services Pvt. Ltd.",
		"description": f"Fixed quote for {doc.intake_title}",
		"image": "/assets/lex/images/lexocrates-mark-dark.png",
		"prefill": _checkout_prefill(actor),
		"theme": {"color": settings.checkout_theme_color or "#1f2937"},
	}


def _available_lexpoints(client):
	return flt(frappe.db.get_value("Lexocrates Client Wallet", {"client": client}, "current_balance") or 0)


def _practice_area(service_type):
	return {
		"Contract Review": "Contract Review", "Legal Research": "Legal Research",
		"Due Diligence": "Due Diligence", "Compliance Review": "Regulatory & Compliance",
		"Litigation Support": "Litigation Support", "Drafting": "Corporate & Commercial",
		"Document Review": "Corporate & Commercial", "Summarization": "Legal Research",
	}.get(service_type, "Other")


def _sla_snapshot():
	return (
		str(_setting("intake_sla_version", DEFAULT_SLA_VERSION)),
		str(_setting("intake_sla_terms", DEFAULT_SLA_TERMS)),
		_setting("intake_sla_document", None),
	)


def _sla_hash(terms, document_url=None):
	digest = hashlib.sha256((terms or "").encode("utf-8"))
	if document_url:
		file_name = frappe.db.get_value("File", {"file_url": document_url}, "name")
		if file_name:
			content = frappe.get_doc("File", file_name).get_content()
			digest.update(content.encode("utf-8") if isinstance(content, str) else content)
		else:
			digest.update(str(document_url).encode("utf-8"))
	return digest.hexdigest()


def _setting(fieldname, default=None):
	if not frappe.db.exists("DocType", "LexPack Settings") or not frappe.get_meta("LexPack Settings").has_field(fieldname):
		return default
	value = frappe.db.get_single_value("LexPack Settings", fieldname)
	return default if value in {None, ""} else value


def _decode_upload(content):
	import base64
	import binascii

	try:
		decoded = base64.b64decode((content or "").split(",", 1)[-1], validate=True)
	except (ValueError, binascii.Error):
		frappe.throw(_("The uploaded file is not valid."), frappe.ValidationError)
	if not decoded or len(decoded) > MAX_UPLOAD_BYTES:
		frappe.throw(_("Upload a non-empty file no larger than 10 MB."), frappe.ValidationError)
	return decoded


def _require_portal_user():
	actor = get_portal_user()
	if not actor or actor.account_status != "Active":
		frappe.throw(_("An active Lexocrates Portal User account is required."), frappe.PermissionError)
	return actor


def _require_intake_access(intake, actor=None):
	actor = actor or get_portal_user()
	doc = frappe.get_doc("Lexocrates Work Intake", intake)
	if _is_internal():
		return doc, actor
	if not actor or actor.account_status != "Active" or actor.client != doc.client:
		frappe.throw(_("You cannot access this Work Intake."), frappe.PermissionError)
	if actor.matter_access_scope != "All Client Matters" and doc.portal_user != actor.name:
		frappe.throw(_("You cannot access this Work Intake."), frappe.PermissionError)
	return doc, actor


def _require_funding_authority(actor, route):
	if _is_internal():
		return
	if route in {"Existing LexPoints", "Recommended LexPack"} and not (actor and actor.lexpack_purchase_access):
		frappe.throw(_("LexPack purchase authority is required."), frappe.PermissionError)
	if route == "Direct Quote" and not (actor and actor.billing_access):
		frappe.throw(_("Billing access is required for direct quote payment."), frappe.PermissionError)


def _require_internal():
	if not _is_internal():
		frappe.throw(_("Legal Operations authority is required."), frappe.PermissionError)


def _is_internal():
	return frappe.session.user == "Administrator" or bool(set(frappe.get_roles()).intersection(INTERNAL_ROLES))


class _service_writes:
	def __enter__(self):
		self.previous = getattr(frappe.flags, "lexocrates_intake_service", False)
		frappe.flags.lexocrates_intake_service = True

	def __exit__(self, exc_type, exc_value, traceback):
		frappe.flags.lexocrates_intake_service = self.previous


def _set_values(doc, **values):
	with _service_writes():
		doc.update(values)
		doc.save(ignore_permissions=True)


def _audit(doc, action, value):
	create_portal_audit_event(
		client=doc.client,
		portal_user=doc.portal_user,
		matter=doc.matter,
		action=action,
		object_type=doc.doctype,
		object_id=doc.name,
		new_value=value,
	)


def _funding_result(doc, duplicate=False):
	return {
		"intake": doc.name,
		"status": doc.status,
		"funding_status": doc.funding_status,
		"funding_route": doc.funding_route,
		"matter": doc.matter,
		"job": doc.job,
		"wallet_reservation": doc.wallet_reservation,
		"sales_invoice": doc.sales_invoice,
		"payment_entry": doc.payment_entry,
		"sla_started_on": doc.sla_started_on,
		"delivery_due_on": doc.delivery_due_on,
		"duplicate": duplicate,
	}
