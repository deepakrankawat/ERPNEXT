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

from lex.client_access import get_portal_user, has_matter_access, has_portal_capability
from lex.pdf_watermark import add_secure_download_url, secure_download_url_for_file_url
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
	matter: str | None = None,
	matter_title: str | None = None,
	matter_nature: str = "Advisory",
	represented_party_name: str | None = None,
	our_side_role: str | None = None,
	counterparty_name: str | None = None,
	counterparty_role: str | None = None,
	opposing_counsel: str | None = None,
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
	parent = _resolve_intake_matter(
		actor,
		matter=matter,
		matter_title=matter_title or intake_title,
		matter_nature=matter_nature,
		represented_party_name=represented_party_name,
		our_side_role=our_side_role,
		counterparty_name=counterparty_name,
		counterparty_role=counterparty_role,
		opposing_counsel=opposing_counsel,
		service_type=service_type,
		jurisdiction=jurisdiction,
		preliminary_details=preliminary_details,
		confidentiality_level=confidentiality_level,
	)
	values["matter"] = parent.name
	with _service_writes(), _portal_service_writes():
		doc = frappe.get_doc(values).insert(ignore_permissions=True)
		draft_due = (
			get_datetime(requested_delivery_date)
			if requested_delivery_date
			else now_datetime() + timedelta(hours=BASE_HOURS[service_type])
		)
		job = frappe.get_doc({
			"doctype": "LPO Job",
			"job_title": (intake_title or "").strip(),
			"engagement": parent.name,
			"work_intake": doc.name,
			"job_type": service_type,
			"job_status": "Draft",
			"priority": priority,
			"task_description": (
				f"Expected outcome:\n{(expected_outcome or '').strip()}\n\n"
				f"Preliminary details:\n{(preliminary_details or '').strip()}"
			),
			"received_at": now_datetime(),
			"due_date": draft_due,
			"job_billing_method": None,
			"estimate_status": "Not Requested",
			"funding_status": "Not Started",
			"qa_required": 1,
		}).insert(ignore_permissions=True)
		doc.job = job.name
		doc.save(ignore_permissions=True)
	_audit(
		doc,
		"Draft Job Intake Created",
		{"service_type": service_type, "status": doc.status, "matter": parent.name, "job": job.name},
	)
	return {
		"name": doc.name,
		"status": doc.status,
		"matter": parent.name,
		"job": job.name,
		"route": "/client-portal#new-matter",
	}


def _resolve_intake_matter(actor, **values):
	matter_name = (values.get("matter") or "").strip()
	if matter_name:
		parent = frappe.get_doc("LPO Matter", matter_name)
		if parent.customer != actor.client or not has_matter_access(parent.name, "view"):
			frappe.throw(_("You cannot submit work under this Matter."), frappe.PermissionError)
		if parent.status in {"On Hold", "Completed", "Closed"}:
			frappe.throw(
				_("New work cannot be submitted while Matter {0} is {1}.").format(parent.name, parent.status),
				frappe.ValidationError,
			)
		return parent

	matter_title = (values.get("matter_title") or "").strip()
	if not matter_title:
		frappe.throw(_("Matter Title is required when creating a new Matter."), frappe.MandatoryError)
	customer_name = frappe.db.get_value("Customer", actor.client, "customer_name") or actor.client
	portal_permissions = frappe.db.get_value(
		"Lexocrates Portal User",
		actor.name,
		["can_upload_documents", "can_comment", "approval_authority", "billing_access"],
		as_dict=True,
	) or frappe._dict()
	with _portal_service_writes():
		return frappe.get_doc({
			"doctype": "LPO Matter",
			"matter_title": matter_title,
			"customer": actor.client,
			"status": "Active",
			"matter_model": "Project",
			"matter_manager": "Administrator",
			"matter_nature": values.get("matter_nature") or "Advisory",
			"represented_party_name": (values.get("represented_party_name") or customer_name).strip(),
			"our_side_role": (values.get("our_side_role") or "").strip(),
			"counterparty_name": (values.get("counterparty_name") or "").strip(),
			"counterparty_role": (values.get("counterparty_role") or "").strip(),
			"opposing_counsel": (values.get("opposing_counsel") or "").strip(),
			"billing_method": "Job Based",
			"practice_area": _practice_area(values.get("service_type")),
			"jurisdictions": (values.get("jurisdiction") or "").strip(),
			"description": (values.get("preliminary_details") or "").strip(),
			"start_date": nowdate(),
			"standard_turnaround_hours": BASE_HOURS.get(values.get("service_type"), 72),
			"sla_warning_hours": 8,
			"confidentiality_level": values.get("confidentiality_level") or "Confidential",
			"authorized_portal_users": [{
				"portal_user": actor.name,
				"user": actor.user,
				"can_view": 1,
				"can_upload": cint(portal_permissions.can_upload_documents),
				"can_comment": cint(portal_permissions.can_comment),
				"can_approve": cint(portal_permissions.approval_authority not in {None, "", "None"}),
				"can_view_billing": cint(portal_permissions.billing_access),
			}],
		}).insert(ignore_permissions=True)


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
	if doc.funding_status in {"Payment Pending", "Funded"} or doc.status in {"Funding Pending", "Funded", "Matter Confirmed"}:
		frappe.throw(
			_("This funded scope is locked. Create a new Draft Job under the same Matter for additional documents or scope."),
			frappe.PermissionError,
		)
	if not doc.job or not frappe.db.exists("LPO Job", doc.job):
		frappe.throw(_("A Draft Job is required before documents can be uploaded."), frappe.ValidationError)
	job = frappe.get_doc("LPO Job", doc.job)
	if job.job_status != "Draft":
		frappe.throw(_("Documents can only be added while the Job is in Draft."), frappe.PermissionError)
	filename = os.path.basename((filename or "").strip())
	extension = os.path.splitext(filename)[1].lower()
	if not filename or extension not in ALLOWED_UPLOAD_EXTENSIONS:
		frappe.throw(_("This file type is not allowed."), frappe.ValidationError)
	decoded = _decode_upload(content)
	# This controlled endpoint performs the scan synchronously so quote state can
	# be updated atomically. Suppress the generic after-commit scanner to avoid a
	# second worker overwriting the just-completed result.
	is_primary = not bool(job.source_document)
	with _service_writes():
		file_doc = save_file(
			filename,
			decoded,
			"LPO Job",
			job.name,
			is_private=1,
			df="source_document" if is_primary else None,
		)
	from lex.file_quarantine import scan_and_validate_inbound_file

	scan = scan_and_validate_inbound_file(file_doc.name)
	file_doc.reload()
	with _portal_service_writes():
		job.reload()
		job.append("job_documents", {
			"file": file_doc.name,
			"file_name": file_doc.file_name,
			"document_role": "Source" if is_primary else "Supporting",
			"scan_status": scan["status"],
			"checksum": file_doc.get("custom_lex_checksum"),
			"document_version": 1,
			"included_in_estimate": 1,
			"uploaded_by": frappe.session.user,
			"uploaded_on": now_datetime(),
		})
		if scan["status"] == "Clean" and is_primary:
			job.source_document = file_doc.file_url
		job.save(ignore_permissions=True)
	_invalidate_unfunded_estimate(doc)
	_refresh_document_state(doc)
	_audit(
		doc,
		"Work Intake Document Uploaded",
		{"file": file_doc.name, "file_name": file_doc.file_name, "scan_status": scan["status"]},
	)
	result = {
		"name": file_doc.name,
		"file_name": file_doc.file_name,
		"scan_status": scan["status"],
		"quarantine_passed": scan["quarantine_passed"],
		"intake_status": doc.status,
	}
	if scan["status"] == "Clean" and len(frappe.utils.strip_html(doc.detailed_instructions or "")) >= 20:
		try:
			result["estimate"] = _process_documents(doc, actor, estimate_only=True)
		except Exception as exc:
			frappe.log_error(frappe.get_traceback(), f"Automatic Job estimate {doc.name}")
			result["estimate_error"] = str(exc)[:300]
	return result


@frappe.whitelist()
def save_detailed_instructions(intake: str, detailed_instructions: str):
	doc, actor = _require_intake_access(intake)
	if not doc.sla_accepted:
		frappe.throw(_("Accept the SLA before adding detailed instructions."), frappe.PermissionError)
	if doc.funding_status in {"Payment Pending", "Funded"} or doc.status in {"Funding Pending", "Funded", "Matter Confirmed"}:
		frappe.throw(_("Detailed instructions are locked after funding starts."), frappe.PermissionError)
	text = (detailed_instructions or "").strip()
	if len(frappe.utils.strip_html(text)) < 20:
		frappe.throw(_("Provide enough detail for scope and quote analysis."), frappe.ValidationError)
	with _service_writes():
		doc.detailed_instructions = text
		doc.save(ignore_permissions=True)
	_invalidate_unfunded_estimate(doc)
	_audit(doc, "Work Intake Detailed Instructions Updated", {"characters": len(text)})
	files = _intake_files(doc.name)
	if files and all((row.custom_lex_scan_status or "Pending") == "Clean" for row in files):
		return _process_documents(doc, actor, estimate_only=True)
	return {"name": doc.name, "status": doc.status, "estimate_pending_documents": True}


@frappe.whitelist()
def request_cost_estimate(intake: str):
	"""Allow a portal client to request only the governed commercial estimate.

	The client cannot trigger the broader legal-analysis workflow.  Document
	classification may use the controlled AI gateway, but only to propose
	observable pricing factors; Frappe remains the pricing authority.
	"""
	doc, actor = _require_intake_access(intake)
	return _process_documents(doc, actor, estimate_only=True)


@frappe.whitelist()
def analyze_documents(intake: str):
	"""Run the internal Legal Operations analysis and estimation workflow."""
	_require_internal()
	doc, actor = _require_intake_access(intake)
	return _process_documents(doc, actor, estimate_only=False)


def _process_documents(doc, actor, *, estimate_only: bool):
	if not doc.sla_accepted:
		frappe.throw(_("SLA acceptance is required before cost estimation."), frappe.PermissionError)
	files = _intake_files(doc.name)
	if not files:
		frappe.throw(_("Upload at least one document before requesting a cost estimate."), frappe.ValidationError)
	if len(frappe.utils.strip_html(doc.detailed_instructions or "")) < 20:
		frappe.throw(_("Add detailed instructions before requesting a cost estimate."), frappe.ValidationError)
	_refresh_document_state(doc, files)
	if doc.security_status != "Clean":
		return {
			"name": doc.name,
			"status": doc.status,
			"security_status": doc.security_status,
			"message": _("All documents must pass security scanning before cost estimation."),
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
	# Client Website Users may request commercial estimation only.  The wider
	# legal/risk analysis is an internal Operations capability and is never run
	# from the client-facing endpoint.
	ai_result, ai_error = (None, None) if estimate_only else _run_governed_ai_analysis(doc, extracted)
	if ai_error or (ai_result and ai_result.get("requires_human_review")):
		low_confidence = True

	ai_profile, ai_estimate_note = _estimation_profile_with_ai(doc, extracted, len(files), word_count)
	from lex.lexpoint_estimation import calculate_estimate

	estimation = calculate_estimate(doc, files, extracted, ai_profile=ai_profile)
	points = estimation["lexpoints"]
	hours = estimation["delivery_hours"]
	estimate_method = "AI-Assisted Formula" if ai_profile else "Formula"
	if cint(estimation.get("requires_human_review")):
		low_confidence = True
	if ai_profile:
		confidence = min(confidence, flt(estimation.get("confidence") or confidence))
		if cint(ai_profile.get("requires_human_review")):
			low_confidence = True
		estimation_settings = frappe.get_single("LPO LexPoint Settings")
		if (
			flt(estimation.get("document_type_confidence")) < flt(estimation_settings.classification_confidence)
			or flt(estimation.get("jurisdiction_confidence")) < flt(estimation_settings.jurisdiction_confidence)
		):
			low_confidence = True

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
		routed_ai = ai_profile or ai_result or {}
		routed_label = "/".join(filter(None, [routed_ai.get("provider"), routed_ai.get("model")]))
		if routed_ai.get("credential_name"):
			routed_label = f"{routed_ai['credential_name']} - {routed_label}"
		doc.analysis_provider = (
			"Lexocrates Governed Cost Estimation Engine"
			if estimate_only
			else (
				f"Governed AI Gateway - {routed_label}"
				if ai_result or ai_profile else "Lexocrates Secure Extraction & Estimation Engine v1 (AI gateway not enabled)"
			)
		)
		doc.ai_execution = (
			(ai_profile or {}).get("ai_execution") or (ai_result or {}).get("ai_execution")
		)
		base_summary = (
			f"Analyzed {len(files)} clean document(s), extracted approximately {word_count:,} words, "
			f"and estimated {points} LexPoints via {estimate_method.lower()} pricing"
			+ f" ({estimation['explanation']})"
			+ ". "
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
		auto_approved = False
		if low_confidence:
			doc.quote_status = "Operations Review"
			doc.status = "Operations Review"
			doc.pricing_approval_status = "Not Required"
		else:
			doc.quote_issued_by = frappe.session.user
			doc.quote_issued_on = now_datetime()
			auto_approved = _route_quote_for_approval(doc, ai_profile=ai_profile)
		doc.save(ignore_permissions=True)
	estimate = _create_analysis_estimate(
		doc,
		files=files,
		extracted=extracted,
		word_count=word_count,
		ai_result=ai_result,
		estimation=estimation,
	)
	with _service_writes():
		doc.reload()
		doc.ai_estimate_reference_doctype = "LPO AI Document Estimate"
		doc.ai_document_estimate = estimate.name
		doc.save(ignore_permissions=True)
	_sync_job_commercial(doc)
	if auto_approved:
		_audit(
			doc,
			"AI Estimate Auto-Approved by CEO Policy",
			{
				"ai_execution": doc.ai_execution,
				"confidence": confidence,
				"required_lexpoints": points,
				"quoted_amount": quote_amount,
				"policy_authorized_by": doc.pricing_approved_by,
				"policy_authorized_on": doc.pricing_approved_on,
			},
		)
	elif not low_confidence:
		_notify_ceo_of_pending_pricing(doc)
	_audit(
		doc,
		"Client Cost Estimate Requested" if estimate_only else "Work Intake Analysis Completed",
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
	_sync_estimate_after_quote(doc)
	_sync_job_commercial(doc)
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
	_sync_estimate_approval(doc, decision, notes)
	_sync_job_commercial(doc)
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
	_sync_job_commercial(doc)
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
	frappe.db.savepoint("lexpack_intake_activation")
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
		_sync_job_commercial(doc)
		result = _confirm_funded_intake(doc)
		frappe.db.release_savepoint("lexpack_intake_activation")
		return result
	except Exception:
		frappe.db.rollback(save_point="lexpack_intake_activation")
		frappe.log_error(frappe.get_traceback(), f"LexPack intake funding {doc.name}")
		with _service_writes():
			doc.reload()
			doc.status = "Funding Pending"
			doc.failure_reason = _("Payment was recorded, but work activation is pending automatic recovery.")
			doc.save(ignore_permissions=True)
		return {"intake": doc.name, "status": doc.status, "activation_pending": True}


def reconcile_funded_intakes(limit: int = 50):
	"""Retry paid/funded intake activation idempotently after transient failures."""
	names = frappe.get_all(
		"Lexocrates Work Intake",
		filters={
			"funding_status": "Funded",
			"status": ["in", ["Funded", "Funding Pending"]],
		},
		pluck="name",
		order_by="modified asc",
		limit_page_length=max(1, min(cint(limit), 200)),
	)
	results = []
	for name in names:
		doc = frappe.get_doc("Lexocrates Work Intake", name)
		if doc.status == "Matter Confirmed" and doc.job:
			continue
		try:
			frappe.db.savepoint("funded_intake_recovery")
			results.append(_confirm_funded_intake(doc))
			frappe.db.release_savepoint("funded_intake_recovery")
		except Exception:
			frappe.db.rollback(save_point="funded_intake_recovery")
			frappe.log_error(frappe.get_traceback(), f"Funded intake recovery {name}")
			with _service_writes():
				doc.reload()
				doc.status = "Funding Pending"
				doc.failure_reason = _("Payment is recorded; automatic work activation will retry.")
				doc.save(ignore_permissions=True)
	return results


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
	_sync_job_commercial(doc)
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
		create_portal_audit_event(
			client=doc.client,
			portal_user=doc.portal_user,
			matter=doc.matter,
			action="Direct Quote Payment Signature Rejected",
			object_type=doc.doctype,
			object_id=doc.name,
			result="Failure",
		)
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
			"analysis_confidence", "low_confidence",
			"quote_version", "quote_status", "quoted_amount", "currency", "required_lexpoints", "scope_summary",
			"estimate_method", "pricing_approval_status",
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
	if doc.funding_status != "Funded":
		frappe.throw(_("Funding must be successful before Job activation."), frappe.ValidationError)
	if doc.status == "Matter Confirmed" and doc.job:
		return _funding_result(doc, duplicate=True)
	if not doc.matter or not frappe.db.exists("LPO Matter", doc.matter):
		actor = frappe.get_doc("Lexocrates Portal User", doc.portal_user)
		matter = _resolve_intake_matter(
			actor,
			matter=None,
			matter_title=doc.intake_title,
			matter_nature="Advisory",
			represented_party_name=None,
			our_side_role=None,
			counterparty_name=None,
			counterparty_role=None,
			opposing_counsel=None,
			service_type=doc.service_type,
			jurisdiction=doc.jurisdiction,
			preliminary_details=doc.preliminary_details,
			confidentiality_level=doc.confidentiality_level,
		)
		with _service_writes():
			doc.matter = matter.name
			doc.save(ignore_permissions=True)
	else:
		matter = frappe.get_doc("LPO Matter", doc.matter)
	if matter.customer != doc.client or matter.status in {"On Hold", "Completed", "Closed"}:
		frappe.throw(_("The selected Matter cannot accept this Job."), frappe.ValidationError)
	if matter.status == "Draft" and matter.billing_method == "Job Based":
		with _portal_service_writes():
			matter.status = "Active"
			matter.save(ignore_permissions=True)
	if not doc.job or not frappe.db.exists("LPO Job", doc.job):
		with _portal_service_writes():
			job = frappe.get_doc({
				"doctype": "LPO Job",
				"job_title": doc.intake_title,
				"engagement": matter.name,
				"work_intake": doc.name,
				"job_type": doc.service_type,
				"job_status": "Draft",
				"priority": doc.priority,
				"task_description": doc.preliminary_details,
				"received_at": now_datetime(),
				"due_date": now_datetime() + timedelta(hours=max(1, cint(doc.delivery_timeline_hours))),
				"qa_required": 1,
			}).insert(ignore_permissions=True)
		with _service_writes():
			doc.job = job.name
			doc.save(ignore_permissions=True)
	else:
		job = frappe.get_doc("LPO Job", doc.job)
	if job.engagement != matter.name or job.work_intake != doc.name:
		frappe.throw(_("The Draft Job does not belong to this Matter and Work Intake."), frappe.ValidationError)
	if job.job_status != "Draft":
		frappe.throw(_("Only a Draft Job can be activated by funding."), frappe.ValidationError)

	start = now_datetime()
	due = start + timedelta(hours=cint(doc.delivery_timeline_hours))
	reservation = None
	if doc.funding_route != "Direct Quote":
		from lex.lex.doctype.lexocrates_wallet_transaction.lexocrates_wallet_transaction import _post_transaction

		reservation = _post_transaction(
			client=doc.client,
			transaction_type="Reservation",
			points=doc.required_lexpoints,
			idempotency_key=f"job-funding:{job.name}",
			matter=matter.name,
			reference_doctype="LPO Job",
			reference_name=job.name,
			description=f"Job funding reservation for {doc.intake_title}",
		)
	with _service_writes():
		doc.reload()
		doc.wallet_reservation = reservation.name if reservation else None
		doc.sla_started_on = start
		doc.delivery_due_on = due
		doc.status = "Matter Confirmed"
		doc.save(ignore_permissions=True)
	files = _intake_files(doc.name)
	primary = next((row.file_url for row in files if row.custom_lex_scan_status == "Clean"), None)
	job.reload()
	job.task_description = f"{doc.expected_outcome}\n\nPreliminary details:\n{doc.preliminary_details}\n\nDetailed instructions:\n{doc.detailed_instructions}\n\nConfirmed scope:\n{doc.scope_summary}"
	job.received_at = start
	job.due_date = due
	job.source_document = primary
	job.intake_estimate = doc.ai_document_estimate
	job.job_billing_method = "Direct Quote" if doc.funding_route == "Direct Quote" else "LexPack"
	job.estimate_status = "Accepted"
	job.quote_version = doc.quote_version
	job.required_lexpoints = doc.required_lexpoints
	job.quoted_amount = doc.quoted_amount
	job.currency = doc.currency
	job.funding_route = doc.funding_route
	job.funding_status = "Funded"
	job.wallet_reservation = doc.wallet_reservation
	job.sales_invoice = doc.sales_invoice
	job.payment_entry = doc.payment_entry
	job.sla_started_on = start
	job.delivery_due_on = due
	job.job_status = "Activated"
	with _portal_service_writes():
		job.save(ignore_permissions=True)
	_activate_document_estimate(doc, matter.name, job.name)
	_audit(
		doc,
		"Funded Work Activated",
		{"funding_route": doc.funding_route, "matter": matter.name, "job": job.name, "sla_started_on": start},
	)
	return _funding_result(doc)


def _intake_row(doc, actor):
	documents = _intake_files(doc.name)
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
	if row.get("quote_status") in {"Ready", "Accepted"}:
		row["cost_estimate_status"] = "Ready"
	elif row.get("status") in {"Operations Review", "Pending CEO Approval"}:
		row["cost_estimate_status"] = "Under Review"
	elif row.get("document_count"):
		row["cost_estimate_status"] = "Pending"
	else:
		row["cost_estimate_status"] = "Not Requested"
	for internal_field in (
		"extraction_status", "extracted_text", "analysis_status", "analysis_confidence", "low_confidence",
		"analysis_provider", "ai_execution", "ai_estimate_reference_doctype", "ai_document_estimate",
		"analysis_summary", "operations_review_notes", "estimate_method",
		"pricing_rejection_reason", "pricing_approved_by", "pricing_approved_on", "quote_issued_by", "quote_issued_on",
	):
		row.pop(internal_field, None)
	row["sla_download_url"] = secure_download_url_for_file_url(row.get("sla_document_snapshot"))
	for document in documents:
		add_secure_download_url(document)
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
	_sync_job_commercial(doc)


def _invalidate_unfunded_estimate(doc):
	doc.reload()
	if doc.funding_status in {"Payment Pending", "Funded"}:
		return
	if doc.ai_document_estimate and frappe.db.exists("LPO AI Document Estimate", doc.ai_document_estimate):
		estimate = frappe.get_doc("LPO AI Document Estimate", doc.ai_document_estimate)
		if estimate.status != "Activated":
			with _estimate_service_writes():
				estimate.status = "Superseded"
				estimate.save(ignore_permissions=True)
	with _service_writes():
		doc.analysis_status = "Not Started"
		doc.extraction_status = "Not Started"
		doc.analysis_confidence = 0
		doc.low_confidence = 0
		doc.quote_status = "Not Generated"
		doc.quoted_amount = 0
		doc.required_lexpoints = 0
		doc.scope_summary = None
		doc.delivery_timeline_hours = 0
		doc.quote_valid_until = None
		doc.recommended_plan = None
		doc.pricing_approval_status = "Not Required"
		doc.funding_route = "Not Selected"
		doc.funding_status = "Not Started"
		doc.ai_document_estimate = None
		doc.save(ignore_permissions=True)
	_sync_job_commercial(doc, estimate_status="Superseded" if doc.quote_version else "Not Requested")


def _job_estimate_status(doc):
	if doc.funding_status == "Funded" or doc.quote_status == "Accepted":
		return "Accepted"
	if doc.quote_status == "Ready":
		return "Ready"
	if doc.status == "Pending CEO Approval" or doc.quote_status == "Pending CEO Approval":
		return "Pending CEO Approval"
	if doc.status == "Operations Review" or doc.quote_status == "Operations Review":
		return "Operations Review"
	if doc.document_count:
		return "Pending"
	return "Not Requested"


def _sync_job_commercial(doc, *, estimate_status=None):
	if not doc.get("job") or not frappe.db.exists("LPO Job", doc.job):
		return
	job = frappe.get_doc("LPO Job", doc.job)
	if job.job_status != "Draft":
		return
	funding_route = doc.funding_route or "Not Selected"
	job.job_billing_method = (
		"Direct Quote" if funding_route == "Direct Quote"
		else "LexPack" if funding_route in {"Existing LexPoints", "Recommended LexPack"}
		else None
	)
	job.estimate_status = estimate_status or _job_estimate_status(doc)
	job.quote_version = doc.quote_version
	job.required_lexpoints = doc.required_lexpoints
	job.quoted_amount = doc.quoted_amount
	job.currency = doc.currency
	job.funding_route = funding_route
	job.funding_status = doc.funding_status
	job.wallet_reservation = doc.wallet_reservation
	job.sales_invoice = doc.sales_invoice
	job.payment_entry = doc.payment_entry
	job.sla_started_on = doc.sla_started_on
	job.delivery_due_on = doc.delivery_due_on
	job.intake_estimate = doc.ai_document_estimate
	with _portal_service_writes():
		job.save(ignore_permissions=True)


def _intake_files(intake):
	fields = ["name", "file_name", "file_url", "file_size", "modified", "custom_lex_scan_status"]
	job = frappe.db.get_value("Lexocrates Work Intake", intake, "job")
	if job:
		rows = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "LPO Job", "attached_to_name": job, "is_folder": 0},
			fields=fields,
			order_by="creation asc",
			limit_page_length=100,
		)
		if rows:
			return rows
	# Backward-compatible read path for intake documents created before the
	# Job-document architecture migration.
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
			provider=None,
			model=None,
			prompt_version=None,
			is_high_risk=0,
			source_corpus=extracted[:50000],
		), None
	except Exception as exc:
		return None, _("Governed AI analysis failed and the intake was routed to Operations Review: {0}").format(str(exc)[:300])


def _estimation_profile_with_ai(doc, extracted, document_count, word_count):
	"""Ask governed AI for observable factors; ERP remains the pricing authority."""
	if not cint(_setting("enable_ai_intake_analysis", 0)):
		return None, "AI intake analysis is disabled; using the standard formula."
	if not extracted.strip():
		return None, "No text could be extracted; using the standard formula."
	from lex.ai_gateway import invoke_ai_gateway

	prompt = (
		"You are the evidence-classification component of a governed legal-services estimation system. "
		"Do not calculate LexPoints, price, margin, or make a final commercial decision. Classify only "
		"observable scope factors grounded in the supplied corpus. Respond with ONLY one JSON object "
		"(no prose or markdown) with this exact key structure: "
		'{"document_type":"", "document_type_confidence":0, "alternative_matches":[], '
		'"practice_modules":[], "recommended_service":"", "legal_domain":"", "jurisdiction":"", '
		'"jurisdiction_confidence":0, "language":"", "ocr_quality":"Good|Moderate|Low", '
		'"content_form":"Typed|Handwritten|Mixed|Unknown", "has_tables":false, "has_images":false, '
		'"has_signatures":false, "has_annexures":false, "complexity_score":1, '
		'"risk_level":"Low|Medium|High|Critical", "reviewer_level":"Junior Associate|Senior Associate|Subject Matter Expert|Partner|Mixed Team", '
		'"billing_measure":"pages|documents|hours|jurisdictions|topics|contracts|policies|business units|matters|legal questions|evidence records", '
		'"volume":1, "task_count":1, "confidence":0, "requires_human_review":false, "explanation_factors":[]}.\n\n'
		f"Service type: {doc.service_type}\nJurisdiction: {doc.jurisdiction}\nPriority: {doc.priority}\n"
		f"Document count: {document_count}\nApproximate word count: {word_count}\n"
		f"Expected outcome: {doc.expected_outcome}\n"
		f"Detailed instructions: {frappe.utils.strip_html(doc.detailed_instructions or '')}\n\n"
		f"Document corpus:\n{extracted[:50000]}"
	)
	try:
		with _cost_estimation_gateway_call():
			result = invoke_ai_gateway(
				use_case="Client Work Intake LexPoint Estimation",
				prompt_text=prompt,
				client_id=doc.client,
				provider=None,
				model=None,
				prompt_version=None,
				is_high_risk=0,
				source_corpus=extracted[:50000],
			)
	except Exception as exc:
		return None, f"AI classification failed; using the governed deterministic profile: {str(exc)[:300]}"

	parsed = _parse_ai_json_object(result.get("response_text") or "")
	if not parsed or not parsed.get("recommended_service") or not cint(parsed.get("complexity_score")):
		return None, "AI response did not contain a valid classification profile; using the governed deterministic profile."
	parsed["ai_execution"] = result.get("ai_execution")
	parsed["provider"] = result.get("provider")
	parsed["model"] = result.get("model")
	parsed["credential_name"] = result.get("credential_name")
	parsed["requires_human_review"] = bool(
		cint(parsed.get("requires_human_review")) or result.get("requires_human_review")
	)
	return parsed, None


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


@frappe.whitelist()
def apply_document_estimate(estimate: str):
	"""Apply editable Operations values to the controlled quote and re-route approval."""
	_require_internal()
	estimate_doc = frappe.get_doc("LPO AI Document Estimate", estimate)
	intake = frappe.get_doc("Lexocrates Work Intake", estimate_doc.work_intake)
	if intake.ai_document_estimate != estimate_doc.name or estimate_doc.status == "Superseded":
		frappe.throw(_("Only the current estimate version can be applied."), frappe.ValidationError)
	if intake.funding_status in {"Payment Pending", "Funded"} or intake.status == "Matter Confirmed":
		frappe.throw(_("The estimate is locked after payment or funding starts."), frappe.PermissionError)
	return issue_quote(
		intake=intake.name,
		required_lexpoints=cint(estimate_doc.reviewed_lexpoints),
		quoted_amount=flt(estimate_doc.reviewed_amount, 2),
		delivery_timeline_hours=cint(estimate_doc.reviewed_delivery_hours),
		scope_summary=estimate_doc.reviewed_scope,
		review_notes=estimate_doc.review_notes,
	)


def _create_analysis_estimate(doc, *, files, extracted, word_count, ai_result, estimation):
	previous_name = doc.get("ai_document_estimate")
	if previous_name and frappe.db.exists("LPO AI Document Estimate", previous_name):
		previous = frappe.get_doc("LPO AI Document Estimate", previous_name)
		if previous.status != "Activated":
			with _estimate_service_writes():
				previous.status = "Superseded"
				previous.save(ignore_permissions=True)
	version = cint(
		frappe.db.sql(
			"select coalesce(max(estimate_version), 0) from `tabLPO AI Document Estimate` where work_intake=%s",
			doc.name,
		)[0][0]
	) + 1
	manifest = [
		{
			"file": row.name,
			"file_name": row.file_name,
			"file_size": cint(row.file_size),
			"scan_status": row.custom_lex_scan_status,
		}
		for row in files
	]
	reasoning = estimation.get("explanation") or ""
	ai_execution = estimation.get("ai_execution") or ((ai_result or {}).get("ai_execution"))
	execution_route = (
		frappe.db.get_value("LPO AI Execution", ai_execution, ["provider", "model"], as_dict=True)
		if ai_execution else None
	) or {}
	status = _estimate_status(doc)
	values = {
		"doctype": "LPO AI Document Estimate",
		"estimate_title": f"{doc.intake_title} - Estimate v{version}",
		"work_intake": doc.name,
		"client": doc.client,
		"portal_user": doc.portal_user,
		"status": status,
		"estimate_version": version,
		"created_on": now_datetime(),
		"document_count": doc.document_count,
		"clean_document_count": doc.clean_document_count,
		"page_count": estimation.get("page_count"),
		"extracted_word_count": word_count,
		"character_count": estimation.get("character_count"),
		"file_size_bytes": estimation.get("file_size_bytes"),
		"source_corpus_hash": hashlib.sha256((extracted or "").encode("utf-8")).hexdigest(),
		"document_manifest_json": json.dumps(manifest, sort_keys=True, separators=(",", ":")),
		"primary_language": estimation.get("primary_language"),
		"ocr_quality": estimation.get("ocr_quality"),
		"content_form": estimation.get("content_form"),
		"has_tables": estimation.get("has_tables"),
		"has_images": estimation.get("has_images"),
		"has_signatures": estimation.get("has_signatures"),
		"has_annexures": estimation.get("has_annexures"),
		"analysis_status": doc.analysis_status,
		"analysis_confidence": doc.analysis_confidence,
		"low_confidence": doc.low_confidence,
		"analysis_provider": execution_route.get("provider") or ("Formula Engine" if not ai_execution else None),
		"analysis_model": execution_route.get("model"),
		"ai_execution": ai_execution,
		"analysis_summary": doc.analysis_summary,
		"ai_reasoning": reasoning,
		"detected_document_type": estimation.get("detected_document_type"),
		"document_type_confidence": estimation.get("document_type_confidence"),
		"alternative_matches": json.dumps(estimation.get("alternative_matches") or [], separators=(",", ":")),
		"practice_module": estimation.get("practice_module"),
		"recommended_service": estimation.get("service_code"),
		"legal_domain": estimation.get("legal_domain"),
		"detected_jurisdiction": estimation.get("detected_jurisdiction"),
		"jurisdiction_confidence": estimation.get("jurisdiction_confidence"),
		"complexity_score": estimation.get("complexity_score"),
		"complexity_classification": estimation.get("complexity_classification"),
		"risk_level": estimation.get("risk_level"),
		"reviewer_level": estimation.get("reviewer_level"),
		"formula_version": estimation.get("formula_version"),
		"billing_measure": estimation.get("billing_measure"),
		"estimated_volume": estimation.get("volume"),
		"task_count": estimation.get("task_count"),
		"base_quantity": estimation.get("base_quantity"),
		"base_lexpoints": estimation.get("base_lexpoints"),
		"billable_units": estimation.get("billable_units"),
		"junior_hours": estimation.get("junior_hours"),
		"senior_hours": estimation.get("senior_hours"),
		"partner_hours": estimation.get("partner_hours"),
		"normal_sla_hours": estimation.get("normal_sla_hours"),
		"fast_track_sla_hours": estimation.get("fast_track_sla_hours"),
		"express_sla_hours": estimation.get("express_sla_hours"),
		"expected_completion": estimation.get("expected_completion"),
		"factor_breakdown_json": json.dumps(estimation.get("factor_breakdown") or {}, sort_keys=True, separators=(",", ":")),
		"explanation": estimation.get("explanation"),
		"estimate_source": doc.estimate_method,
		"proposed_lexpoints": doc.required_lexpoints,
		"proposed_amount": doc.quoted_amount,
		"currency": doc.currency,
		"proposed_delivery_hours": doc.delivery_timeline_hours,
		"proposed_scope": doc.scope_summary,
		"reviewed_lexpoints": doc.required_lexpoints,
		"reviewed_amount": doc.quoted_amount,
		"reviewed_delivery_hours": doc.delivery_timeline_hours,
		"reviewed_scope": doc.scope_summary,
		"approval_status": doc.pricing_approval_status,
		"applied_to_intake_on": now_datetime(),
	}
	with _estimate_service_writes():
		return frappe.get_doc(values).insert(ignore_permissions=True)


def _sync_estimate_after_quote(doc):
	name = doc.get("ai_document_estimate")
	if name and frappe.db.exists("LPO AI Document Estimate", name):
		estimate = frappe.get_doc("LPO AI Document Estimate", name)
	else:
		version = cint(
			frappe.db.sql(
				"select coalesce(max(estimate_version), 0) from `tabLPO AI Document Estimate` where work_intake=%s",
				doc.name,
			)[0][0]
		) + 1
		with _estimate_service_writes():
			estimate = frappe.get_doc({
				"doctype": "LPO AI Document Estimate",
				"estimate_title": f"{doc.intake_title} - Manual Estimate v{version}",
				"work_intake": doc.name,
				"client": doc.client,
				"portal_user": doc.portal_user,
				"status": _estimate_status(doc),
				"estimate_version": version,
				"created_on": now_datetime(),
				"document_count": doc.document_count,
				"clean_document_count": doc.clean_document_count,
				"extracted_word_count": len((doc.extracted_text or "").split()),
				"source_corpus_hash": hashlib.sha256((doc.extracted_text or "").encode("utf-8")).hexdigest(),
				"document_manifest_json": "[]",
				"analysis_status": doc.analysis_status,
				"analysis_confidence": doc.analysis_confidence,
				"low_confidence": doc.low_confidence,
				"analysis_provider": doc.analysis_provider,
				"ai_execution": doc.ai_execution,
				"analysis_summary": doc.analysis_summary,
				"estimate_source": "Manual (Operations)",
				"proposed_lexpoints": doc.required_lexpoints,
				"proposed_amount": doc.quoted_amount,
				"currency": doc.currency,
				"proposed_delivery_hours": doc.delivery_timeline_hours,
				"proposed_scope": doc.scope_summary,
				"reviewed_lexpoints": doc.required_lexpoints,
				"reviewed_amount": doc.quoted_amount,
				"reviewed_delivery_hours": doc.delivery_timeline_hours,
				"reviewed_scope": doc.scope_summary,
				"approval_status": doc.pricing_approval_status,
			}).insert(ignore_permissions=True)
		with _service_writes():
			doc.reload()
			doc.ai_estimate_reference_doctype = "LPO AI Document Estimate"
			doc.ai_document_estimate = estimate.name
			doc.save(ignore_permissions=True)
	with _estimate_service_writes():
		estimate.reviewed_lexpoints = doc.required_lexpoints
		estimate.reviewed_amount = doc.quoted_amount
		estimate.reviewed_delivery_hours = doc.delivery_timeline_hours
		estimate.reviewed_scope = doc.scope_summary
		estimate.review_notes = doc.operations_review_notes
		estimate.reviewed_by = frappe.session.user
		estimate.reviewed_on = now_datetime()
		estimate.status = _estimate_status(doc)
		estimate.approval_status = doc.pricing_approval_status
		estimate.applied_to_intake_on = now_datetime()
		estimate.save(ignore_permissions=True)
	return estimate


def _sync_estimate_approval(doc, decision, notes=None):
	name = doc.get("ai_document_estimate")
	if not name or not frappe.db.exists("LPO AI Document Estimate", name):
		return
	estimate = frappe.get_doc("LPO AI Document Estimate", name)
	with _estimate_service_writes():
		estimate.status = "Approved" if decision == "Approved" else "Rejected"
		estimate.approval_status = decision
		estimate.approved_by = frappe.session.user
		estimate.approved_on = now_datetime()
		estimate.rejection_reason = (notes or "").strip() or None
		estimate.save(ignore_permissions=True)


def _estimate_status(doc):
	if doc.status == "Matter Confirmed":
		return "Activated"
	if doc.pricing_approval_status == "Pending CEO Approval":
		return "Pending CEO Approval"
	if doc.pricing_approval_status == "Approved" or (
		doc.pricing_approval_status == "Not Required" and doc.quote_status == "Ready"
	):
		return "Approved"
	if doc.pricing_approval_status == "Rejected":
		return "Rejected"
	return "Operations Review"


class _estimate_service_writes:
	def __enter__(self):
		self.previous = getattr(frappe.flags, "lexocrates_estimate_service", False)
		frappe.flags.lexocrates_estimate_service = True

	def __exit__(self, exc_type, exc_value, traceback):
		frappe.flags.lexocrates_estimate_service = self.previous


def _activate_document_estimate(doc, matter: str, job: str):
	name = doc.get("ai_document_estimate")
	if not name or not frappe.db.exists("LPO AI Document Estimate", name):
		return
	estimate = frappe.get_doc("LPO AI Document Estimate", name)
	with _estimate_service_writes():
		estimate.matter = matter
		estimate.job = job
		estimate.status = "Activated"
		estimate.save(ignore_permissions=True)


def _route_quote_for_approval(doc, *, ai_profile=None):
	"""Apply the CEO policy to eligible AI estimates or require individual sign-off.

	Called with in-memory field changes only (no save) so it composes cleanly
	into the caller's own _service_writes()/save() block.
	"""
	policy = _eligible_ai_auto_approval(doc, ai_profile)
	if policy:
		doc.pricing_approval_status = "Not Required"
		doc.pricing_approved_by = policy["authorized_by"]
		doc.pricing_approved_on = now_datetime()
		doc.pricing_rejection_reason = None
		doc.quote_status = "Ready"
		doc.status = "Quote Ready"
		return True
	doc.pricing_approval_status = "Pending CEO Approval"
	doc.pricing_approved_by = None
	doc.pricing_approved_on = None
	doc.pricing_rejection_reason = None
	doc.quote_status = "Pending CEO Approval"
	doc.status = "Pending CEO Approval"
	return False


def _eligible_ai_auto_approval(doc, ai_profile):
	"""Return the active CEO policy only when all immutable safety gates pass."""
	if not cint(_setting("auto_approve_ai_pricing", 0)):
		return None
	if not cint(_setting("enable_ai_intake_analysis", 0)):
		return None
	if doc.estimate_method != "AI-Assisted Formula" or not ai_profile or cint(doc.low_confidence):
		return None
	if cint(ai_profile.get("requires_human_review")):
		return None
	authorized_by = _setting("auto_approve_ai_pricing_authorized_by")
	authorized_on = _setting("auto_approve_ai_pricing_authorized_on")
	if not authorized_by or not authorized_on:
		return None
	if authorized_by != "Administrator" and "CEO" not in frappe.get_roles(authorized_by):
		return None
	if flt(doc.analysis_confidence) < flt(_setting("low_confidence_threshold", 72)):
		return None
	execution_name = ai_profile.get("ai_execution") or doc.ai_execution
	if not execution_name:
		return None
	execution = frappe.db.get_value(
		"LPO AI Execution",
		execution_name,
		["status", "evaluation_status", "provider", "model", "api_credential"],
		as_dict=True,
	)
	if not execution or execution.status != "Completed" or execution.evaluation_status != "Passed":
		return None
	if not execution.provider or not execution.model:
		return None
	return {
		"authorized_by": authorized_by,
		"authorized_on": authorized_on,
		"execution": execution_name,
		"provider": execution.provider,
		"model": execution.model,
		"credential_name": execution.api_credential,
	}


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
	if recipient_emails and _outgoing_email_is_ready():
		try:
			frappe.sendmail(recipients=recipient_emails, subject=subject, message=message, now=False)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"CEO pricing approval email failed for {doc.name}")
	_audit(
		doc,
		"CEO Pricing Approval Requested",
		{"quoted_amount": doc.quoted_amount, "required_lexpoints": doc.required_lexpoints, "notified": ceo_users},
	)


def _outgoing_email_is_ready() -> bool:
	return bool(
		frappe.db.exists(
			"Email Account",
			{"enable_outgoing": 1, "default_outgoing": 1},
		)
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
	if actor.mfa_required and not frappe.db.get_single_value("System Settings", "enable_two_factor_auth"):
		frappe.throw(_("Multi-factor authentication is required for this account but is not enabled on the site."), frappe.PermissionError)
	return actor


def _require_intake_access(intake, actor=None):
	actor = actor or get_portal_user()
	doc = frappe.get_doc("Lexocrates Work Intake", intake)
	if _is_internal():
		return doc, actor
	if not actor or actor.account_status != "Active" or actor.client != doc.client:
		frappe.throw(_("You cannot access this Work Intake."), frappe.PermissionError)
	if actor.mfa_required and not frappe.db.get_single_value("System Settings", "enable_two_factor_auth"):
		frappe.throw(_("Multi-factor authentication is required for this account but is not enabled on the site."), frappe.PermissionError)
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


class _portal_service_writes:
	"""Allow the intake service to update portal-protected Matter and Job records."""

	def __enter__(self):
		self.previous = getattr(frappe.flags, "lexocrates_portal_service", False)
		frappe.flags.lexocrates_portal_service = True

	def __exit__(self, exc_type, exc_value, traceback):
		frappe.flags.lexocrates_portal_service = self.previous


class _cost_estimation_gateway_call:
	"""Unforgeable request-local capability used only by the intake service."""

	def __enter__(self):
		self.previous = getattr(frappe.flags, "lexocrates_client_cost_estimation", False)
		frappe.flags.lexocrates_client_cost_estimation = True

	def __exit__(self, exc_type, exc_value, traceback):
		frappe.flags.lexocrates_client_cost_estimation = self.previous


def _set_values(doc, **values):
	with _service_writes():
		doc.update(values)
		doc.save(ignore_permissions=True)
	_sync_job_commercial(doc)


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
