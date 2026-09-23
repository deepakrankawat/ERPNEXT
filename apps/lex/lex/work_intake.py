from __future__ import annotations

import hashlib
import io
import os
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, getdate, now_datetime, nowdate
from frappe.utils.file_manager import save_file

from lex.client_access import get_portal_user, has_matter_access, has_portal_capability
from lex.pdf_watermark import add_secure_download_url, secure_download_url_for_file_url
from lex.portal_audit import create_portal_audit_event


# The fixed-price estimator bills only exact native PDF pages.  Accepting other
# source formats here would let a client complete an upload that cannot advance
# to an estimate, so the client/Desk Job-document contract is PDF-only.
ALLOWED_UPLOAD_EXTENSIONS = {".pdf"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
INTERNAL_ROLES = {"System Manager", "LPO_Admin", "LPO_Manager", "Lexocrates Finance", "Accounts Manager"}
DEFAULT_SLA_VERSION = "CLIENT-INTAKE-SLA-1.0"
DEFAULT_SLA_TERMS = """Client Intake Service Level Agreement

1. Documents remain encrypted/private and are scanned before processing.
2. The preliminary timeline is not the operational SLA. The operational SLA starts only after clean documents, confirmed scope and successful funding.
3. AI-assisted extraction may be used only within the approved Lexocrates processing environment; low-confidence output is reviewed by Legal Operations.
4. A generated quote records an internal effort estimate, confirmed fixed price, required Legal Capacity and delivery timeline. The client may use existing Legal Capacity, a LexPack, or pay the fixed quote directly.
5. Material scope changes require a revised quote and delivery timeline.
6. Lexocrates retains an immutable audit trail of SLA acceptance, documents, quote, funding, execution, QA, approval and delivery.
"""
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

# Operational service types pre-date the fixed-rate Lextimator catalogue.  This
# mapping is deliberately static: neither OCR nor AI classification is allowed
# to select or alter the billable service.
FIXED_PRICING_SERVICE_BY_INTAKE_TYPE = {
	"Contract Review": "Contract Review",
	"Legal Research": "Legal Research & Writing",
	"Document Review": "eDiscovery & Document Review",
	"Due Diligence": "Legal Operations Support",
	"Compliance Review": "Compliance & Regulatory Support",
	"Litigation Support": "Litigation Support",
	"Drafting": "Paralegal & Virtual Legal Assistance",
	"Summarization": "Legal Research & Writing",
	"Other": "Legal Operations Support",
}

# The portal prices work using these client-facing catalogue names, while the
# existing Work Intake and LPO Job DocTypes store a shorter operational type.
# Normalize at the API boundary *before* Frappe validates either Select field.
INTAKE_TYPE_BY_PRICING_SERVICE = {
	"Legal Research & Writing": "Legal Research",
	"Litigation Support": "Litigation Support",
	"Contract Lifecycle Management (CLM)": "Contract Review",
	"Contract Review": "Contract Review",
	"eDiscovery & Document Review": "Document Review",
	"Compliance & Regulatory Support": "Compliance Review",
	"Paralegal & Virtual Legal Assistance": "Drafting",
	"Legal Operations Support": "Other",
}


def normalize_intake_service_type(service_type: str | None) -> str:
	"""Return the permitted operational service type for portal/API input."""
	value = (service_type or "").strip()
	return INTAKE_TYPE_BY_PRICING_SERVICE.get(value, value)


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
	from lex.instant_estimator import _estimate_currency_for_client
	service_type = normalize_intake_service_type(service_type)

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
		"jurisdiction": (jurisdiction or "Canada").strip(),
		"priority": priority,
		"requested_delivery_date": requested_delivery_date or None,
		"expected_outcome": (expected_outcome or "").strip(),
		"preliminary_details": (preliminary_details or "").strip(),
		"detailed_instructions": (preliminary_details or "").strip(),
		"confidentiality_level": confidentiality_level,
		"sla_version": sla_version,
		"sla_document_snapshot": sla_document,
		"sla_terms_snapshot": sla_terms,
		"sla_snapshot_hash": _sla_hash(sla_terms, sla_document),
		# A client's registered country determines the quotation currency.  The
		# browser never submits or selects the stored currency.
		"currency": _estimate_currency_for_client(actor.client)[0],
		"selected_pricing_service": FIXED_PRICING_SERVICE_BY_INTAKE_TYPE.get(service_type),
	}
	if service_type not in FIXED_PRICING_SERVICE_BY_INTAKE_TYPE:
		frappe.throw(_("Choose a supported Service Type."), frappe.ValidationError)
	if priority not in {"Low", "Medium", "High", "Urgent"}:
		frappe.throw(_("Choose a valid priority."), frappe.ValidationError)
	if len(frappe.utils.strip_html(values["detailed_instructions"])) < 20:
		frappe.throw(_("Provide at least 20 characters of preliminary details."), frappe.ValidationError)
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
		else now_datetime() + timedelta(hours=BASE_HOURS.get(service_type, 72))
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
	if not _is_internal() and (not actor or not actor.can_upload_documents):
		frappe.throw(_("Your client role cannot upload documents."), frappe.PermissionError)
	return _upload_intake_document(doc, actor, filename, content)


def _upload_intake_document(doc, actor, filename: str, content: str, *, auto_estimate: bool = True):
	"""Store, scan and register one private Job source document.

	The public portal action and the internal Desk estimation action share this
	implementation so both retain the same security scan, lineage and audit trail.
	"""
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
		frappe.throw(_("Upload a PDF Job document before estimating."), frappe.ValidationError)
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
		{
			"file": file_doc.name,
			"file_name": file_doc.file_name,
			"scan_status": scan["status"],
			"upload_channel": "System User Desk" if _is_internal() else "Client Portal",
		},
	)
	result = {
		"name": file_doc.name,
		"file_name": file_doc.file_name,
		"scan_status": scan["status"],
		"quarantine_passed": scan["quarantine_passed"],
		"intake_status": doc.status,
	}
	if auto_estimate and scan["status"] == "Clean" and len(frappe.utils.strip_html(doc.detailed_instructions or "")) >= 20:
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
def get_system_job_estimation_context(job: str) -> dict:
	"""Return the minimum Desk context needed for governed Job estimation."""
	job_doc, intake_doc = _require_system_job_estimation_access(job)
	documents = _intake_files(intake_doc.name)
	return {
		"job": job_doc.name,
		"job_title": job_doc.job_title,
		"intake": intake_doc.name,
		"intake_status": intake_doc.status,
		"sla_accepted": bool(intake_doc.sla_accepted),
		"detailed_instructions": intake_doc.detailed_instructions or "",
		"document_count": len(documents),
		"clean_document_count": sum(
			(row.custom_lex_scan_status or "Pending") == "Clean" for row in documents
		),
		"current_estimate": (
			f"{intake_doc.currency} {flt(intake_doc.quoted_amount, 2):.2f}"
			if flt(intake_doc.quoted_amount) > 0
			else None
		),
		"quoted_amount": flt(intake_doc.quoted_amount, 2),
		"currency": intake_doc.currency,
		"required_legal_capacity": _required_legal_capacity(intake_doc),
		"exact_pdf_page_count": cint(intake_doc.get("exact_pdf_page_count")),
		"selected_pricing_service": intake_doc.get("selected_pricing_service"),
		"estimate_method": intake_doc.estimate_method,
		"quote_status": intake_doc.quote_status,
		"pricing_approval_status": intake_doc.pricing_approval_status,
		"allowed_extensions": sorted(ALLOWED_UPLOAD_EXTENSIONS),
		"max_upload_bytes": MAX_UPLOAD_BYTES,
	}


@frappe.whitelist()
def estimate_system_job(
	job: str,
	detailed_instructions: str | None = None,
	filename: str | None = None,
	content: str | None = None,
) -> dict:
	"""Upload an optional Job document and generate one governed price estimate.

	This is an internal commercial-estimation action. It deliberately runs the
	same estimate-only pipeline used by the portal, not the broader legal AI
	analysis or document-copilot workflow.
	"""
	job_doc, doc = _require_system_job_estimation_access(job)
	if not doc.sla_accepted:
		frappe.throw(
			_("The client must review and accept the SLA before a System User uploads documents or generates pricing."),
			frappe.PermissionError,
		)
	if doc.funding_status in {"Payment Pending", "Funded"} or doc.status in {
		"Funding Pending", "Funded", "Matter Confirmed"
	}:
		frappe.throw(_("The estimate is locked after funding starts."), frappe.PermissionError)
	if job_doc.job_status != "Draft":
		frappe.throw(_("Cost estimation is available only while the Job is in Draft."), frappe.ValidationError)

	instructions = (detailed_instructions or doc.detailed_instructions or "").strip()
	if len(frappe.utils.strip_html(instructions)) < 20:
		frappe.throw(_("Provide at least 20 characters of detailed instructions."), frappe.ValidationError)
	if instructions != (doc.detailed_instructions or ""):
		with _service_writes():
			doc.detailed_instructions = instructions
			doc.save(ignore_permissions=True)
		_invalidate_unfunded_estimate(doc)

	upload = None
	if bool(filename) != bool(content):
		frappe.throw(_("Provide both the document filename and its content."), frappe.ValidationError)
	if filename and content:
		upload = _upload_intake_document(
			doc, None, filename, content, auto_estimate=False
		)
	elif not _intake_files(doc.name):
		frappe.throw(
			_("Upload a document or attach at least one clean source document before estimating."),
			frappe.ValidationError,
		)

	_process_documents(doc, None, estimate_only=True)
	doc.reload()
	return {
		"job": job_doc.name,
		"intake": doc.name,
		"uploaded_document": upload,
		"estimate": None,
		"estimate_status": _job_estimate_status(doc),
		"estimate_method": doc.estimate_method,
		"required_legal_capacity": _required_legal_capacity(doc),
		"quoted_amount": flt(doc.quoted_amount, 2),
		"currency": doc.currency,
		"delivery_timeline_hours": cint(doc.delivery_timeline_hours),
		"scope_summary": doc.scope_summary,
		"analysis_confidence": flt(doc.analysis_confidence, 2),
		"low_confidence": bool(doc.low_confidence),
		"quote_status": doc.quote_status,
		"pricing_approval_status": doc.pricing_approval_status,
		"recommended_plan": doc.recommended_plan,
	}


@frappe.whitelist()
def analyze_documents(intake: str):
	"""Run the internal Legal Operations analysis and estimation workflow."""
	_require_internal()
	doc, actor = _require_intake_access(intake)
	return _process_documents(doc, actor, estimate_only=False)


def _process_documents(
	doc,
	actor,
	*,
	estimate_only: bool,
):
	"""Create the authoritative fixed-price estimate from native PDF pages.

	Pricing never reads OCR output, extracted words, file size, AI classification,
	priority or a browser-supplied amount.  The selected service and exact native
	PDF page total are the only billable inputs.
	"""
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
	from decimal import ROUND_CEILING

	from lex.instant_estimator import (
		_estimate_currency_for_client,
		calculate_page_based_pricing,
	)

	page_count = _exact_native_pdf_page_count(files)
	selected_service = _selected_pricing_service(doc)
	currency, _country = _estimate_currency_for_client(doc.client)
	try:
		pricing = calculate_page_based_pricing(
			page_count,
			selected_service,
			currency=currency,
		)
	except ValueError as exc:
		frappe.throw(str(exc), frappe.ValidationError)

	quote_amount = flt(pricing["final_price"], 2)
	delivery_hours = max(1, int(pricing["exact_hours"].to_integral_value(rounding=ROUND_CEILING)))
	scope = _native_pdf_scope_summary(doc, selected_service, page_count)
	recommended = _recommend_plan(doc.client, quote_amount, currency)
	with _service_writes():
		doc.reload()
		# Preserve analysis fields for operational state, but do not extract or
		# inspect document text as a pricing input.
		doc.extracted_text = None
		doc.extraction_status = "Not Started"
		doc.analysis_status = "Complete"
		doc.analysis_confidence = 100
		doc.low_confidence = 0
		doc.analysis_provider = "Lextimator Native PDF Pricing"
		doc.ai_execution = None
		doc.analysis_summary = (
			f"Lextimator calculated the fixed price from {page_count} exact native PDF page(s) "
			f"and the selected service '{selected_service}'."
		)
		doc.quoted_amount = quote_amount
		doc.currency = currency
		doc.required_legal_capacity = quote_amount
		doc.delivery_timeline_hours = delivery_hours
		doc.scope_summary = scope
		doc.estimate_method = "Native PDF Fixed Rate"
		doc.selected_pricing_service = selected_service
		doc.exact_pdf_page_count = page_count
		doc.calculated_hours = str(pricing["exact_hours"])
		doc.fixed_service_rate_cad = flt(pricing["fixed_service_rate_cad"], 2)
		doc.raw_price_cad = flt(pricing["raw_price_cad"], 2)
		doc.final_rounded_price_cad = flt(pricing["final_price_cad"], 2)
		doc.pricing_exchange_rate = flt(pricing["exchange_rate"], 9)
		doc.pricing_exchange_rate_date = pricing["exchange_rate_date"]
		doc.pricing_version = pricing["pricing_version"]
		doc.quote_version = cint(doc.quote_version) + 1
		doc.quote_valid_until = add_days(nowdate(), cint(_setting("quote_validity_days", 7)))
		doc.recommended_plan = recommended
		# Fixed native-page pricing is deterministic and is automatically released.
		doc.quote_issued_by = frappe.session.user
		doc.quote_issued_on = now_datetime()
		doc.pricing_approval_status = "Approved"
		doc.pricing_approved_by = frappe.session.user
		doc.pricing_approved_on = now_datetime()
		doc.pricing_rejection_reason = None
		doc.quote_status = "Ready"
		doc.status = "Quote Ready"
		doc.save(ignore_permissions=True)
	_sync_job_commercial(doc)
	_notify_client_quote_ready(doc)
	_audit(
		doc,
		"Client Cost Estimate Requested" if estimate_only and actor else "Job Fixed Price Generated",
		{
			"exact_pdf_page_count": page_count,
			"selected_service": selected_service,
			"quoted_amount": quote_amount,
			"currency": currency,
			"required_legal_capacity": quote_amount,
			"pricing_version": pricing["pricing_version"],
		},
	)
	return _intake_row(doc, actor)


@frappe.whitelist()
def issue_quote(
	intake: str,
	review_notes: str | None = None,
):
	"""Recalculate the server-side fixed quote for a Draft Job.

	Price, Legal Capacity and delivery hours are intentionally not accepted as
	API parameters.  A Desk user can record a review note, but cannot override
	the deterministic native-PDF pricing calculation.
	"""
	_require_internal()
	doc = frappe.get_doc("Lexocrates Work Intake", intake)
	result = _process_documents(doc, None, estimate_only=True)
	if review_notes:
		with _service_writes():
			doc.reload()
			doc.operations_review_notes = (review_notes or "").strip()
			doc.save(ignore_permissions=True)
	return result


@frappe.whitelist()
def approve_quote_pricing(intake: str, decision: str, notes: str | None = None):
	"""CEO signs off on (or rejects) the estimated price before the client can fund the matter."""
	_require_pricing_authority()
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
	_sync_job_commercial(doc)
	_audit(
		doc,
		"Matter Pricing Approval Decision",
		{"decision": decision, "notes": notes, "quoted_amount": doc.quoted_amount, "required_legal_capacity": doc.required_legal_capacity},
	)
	_post_ceo_approval_decision(doc, decision, notes)
	if decision == "Approved":
		_notify_client_quote_ready(doc)
	return {"intake": doc.name, "status": doc.status, "pricing_approval_status": doc.pricing_approval_status}


@frappe.whitelist()
def submit_chat_pricing(
	intake: str,
	review_notes: str | None = None,
):
	"""Recalculate the authoritative Job quote from the internal chat action."""
	_require_pricing_authority()
	doc = frappe.get_doc("Lexocrates Work Intake", intake)
	return issue_quote(intake=doc.name, review_notes=review_notes)


@frappe.whitelist()
def get_chat_pricing_context(intake: str) -> dict:
	"""Return the current pricing values for the internal chat pricing dialog."""
	_require_pricing_authority()
	doc = frappe.get_doc("Lexocrates Work Intake", intake)
	files = _intake_files(doc.name)
	return {
		"intake": doc.name,
		"matter": doc.matter,
		"job": doc.job,
		"intake_title": doc.intake_title,
		"status": doc.status,
		"quote_status": doc.quote_status,
		"pricing_approval_status": doc.pricing_approval_status,
		"required_legal_capacity": flt(doc.required_legal_capacity, 2),
		"quoted_amount": flt(doc.quoted_amount, 2),
		"currency": doc.currency,
		"delivery_timeline_hours": cint(doc.delivery_timeline_hours),
		"scope_summary": doc.scope_summary or _native_pdf_scope_summary(
			doc, _selected_pricing_service(doc), cint(doc.get("exact_pdf_page_count"))
		),
		"review_notes": doc.operations_review_notes or "",
	}


@frappe.whitelist()
def fund_with_existing_legal_capacity(intake: str):
	doc, actor = _require_intake_access(intake)
	_require_funding_authority(actor, "Existing Legal Capacity")
	_validate_ready_quote(doc)
	_validate_legal_capacity_currency(doc.client, doc.currency)
	available = _available_legal_capacity(doc.client)
	required_capacity = _required_legal_capacity(doc)
	if available < required_capacity:
		frappe.throw(
			_("Available Legal Capacity is {0}; this work requires {1}.").format(
				flt(available, 2), flt(required_capacity, 2)
			),
			frappe.ValidationError,
		)
	with _service_writes():
		doc.funding_route = "Existing Legal Capacity"
		doc.funding_status = "Funded"
		doc.funded_on = now_datetime()
		doc.quote_status = "Accepted"
		doc.status = "Funded"
		doc.save(ignore_permissions=True)
	result = _confirm_funded_intake(doc)
	doc.reload()
	_post_ceo_payment_confirmation(doc)
	return result


def prepare_lexpack_purchase(intake: str, plan: str, actor=None):
	doc, actor = _require_intake_access(intake, actor=actor)
	_require_funding_authority(actor, "Recommended LexPack")
	_validate_ready_quote(doc)
	_validate_legal_capacity_currency(doc.client, doc.currency)
	if doc.recommended_plan != plan:
		frappe.throw(_("Purchase the LexPack recommended for this confirmed quote."), frappe.ValidationError)
	from lex.lexpack import _checkout_pricing_for_plan
	plan_doc = frappe.get_doc("LexPack Plan", plan)
	plan_capacity = _checkout_pricing_for_plan(plan_doc, portal_user=actor, requested_currency=doc.currency)["legal_capacity_amount"]
	if _available_legal_capacity(doc.client) + plan_capacity < _required_legal_capacity(doc):
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
		if _available_legal_capacity(doc.client) < _required_legal_capacity(doc):
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
		doc.reload()
		_post_ceo_payment_confirmation(doc)
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
	# A retry, refresh, or repeated click must reopen the same pending checkout.
	# Creating a second Razorpay order here would invalidate the order ID held by
	# the client and leave unnecessary pending orders in the gateway.
	if doc.funding_status == "Payment Pending" and doc.status == "Funding Pending" and doc.razorpay_order_id:
		return _checkout_payload(doc, actor, settings, payload)
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
	doc.reload()
	_post_ceo_payment_confirmation(doc)
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
			"quote_version", "quote_status", "quoted_amount", "currency", "required_legal_capacity", "scope_summary",
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
			legal_capacity_amount=_required_legal_capacity(doc),
			currency=doc.currency,
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
	job.job_billing_method = "Direct Quote" if doc.funding_route == "Direct Quote" else "LexPack"
	job.estimate_status = "Accepted"
	job.quote_version = doc.quote_version
	job.required_legal_capacity = _required_legal_capacity(doc)
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
			["name", "plan_code", "plan_name", "price", "currency", "discount_percent", "self_service", "enterprise_custom"],
			as_dict=True,
		)
		if plan:
			from lex.lexpack import _checkout_pricing_for_plan
			checkout = _checkout_pricing_for_plan(plan, requested_currency=doc.currency)
			plan.update(checkout)
	# ``frappe._dict`` returns ``None`` for unknown attributes, so
	# ``hasattr(doc, "as_dict")`` is true even though the value is not callable.
	# Portal list queries return ``frappe._dict`` rows while document APIs return
	# real Document instances; handle both without treating a missing key as a
	# method.
	as_dict = getattr(doc, "as_dict", None)
	row = frappe._dict(as_dict() if callable(as_dict) else doc)
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
		"analysis_provider", "ai_execution",
		"analysis_summary", "operations_review_notes", "estimate_method",
		"pricing_rejection_reason", "pricing_approved_by", "pricing_approved_on", "quote_issued_by", "quote_issued_on",
		"selected_pricing_service", "exact_pdf_page_count", "calculated_hours", "fixed_service_rate_cad",
		"raw_price_cad", "final_rounded_price_cad", "pricing_exchange_rate", "pricing_exchange_rate_date",
		"pricing_version",
	):
		row.pop(internal_field, None)
	row["sla_download_url"] = secure_download_url_for_file_url(row.get("sla_document_snapshot"))
	for document in documents:
		add_secure_download_url(document)
	row["documents"] = documents
	row["recommended_plan_details"] = plan
	row["required_legal_capacity"] = _required_legal_capacity(doc)
	row["available_legal_capacity"] = _available_legal_capacity(doc.client)
	row["can_fund_legal_capacity"] = bool(actor and actor.lexpack_purchase_access)
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
	with _service_writes():
		doc.analysis_status = "Not Started"
		doc.extraction_status = "Not Started"
		doc.analysis_confidence = 0
		doc.low_confidence = 0
		doc.quote_status = "Not Generated"
		doc.quoted_amount = 0
		doc.required_legal_capacity = 0
		doc.scope_summary = None
		doc.delivery_timeline_hours = 0
		doc.quote_valid_until = None
		doc.recommended_plan = None
		doc.pricing_approval_status = "Not Required"
		doc.funding_route = "Not Selected"
		doc.funding_status = "Not Started"
		doc.selected_pricing_service = None
		doc.exact_pdf_page_count = 0
		doc.calculated_hours = 0
		doc.fixed_service_rate_cad = 0
		doc.raw_price_cad = 0
		doc.final_rounded_price_cad = 0
		doc.pricing_exchange_rate = 0
		doc.pricing_exchange_rate_date = None
		doc.pricing_version = None
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
		else "LexPack" if funding_route in {"Existing Legal Capacity", "Recommended LexPack"}
		else None
	)
	job.estimate_status = estimate_status or _job_estimate_status(doc)
	job.quote_version = doc.quote_version
	job.required_legal_capacity = _required_legal_capacity(doc)
	job.quoted_amount = doc.quoted_amount
	job.currency = doc.currency
	job.funding_route = funding_route
	job.funding_status = doc.funding_status
	job.wallet_reservation = doc.wallet_reservation
	job.sales_invoice = doc.sales_invoice
	job.payment_entry = doc.payment_entry
	job.sla_started_on = doc.sla_started_on
	job.delivery_due_on = doc.delivery_due_on
	job.selected_pricing_service = doc.get("selected_pricing_service")
	job.exact_pdf_page_count = cint(doc.get("exact_pdf_page_count"))
	job.calculated_hours = doc.get("calculated_hours") or 0
	job.fixed_service_rate_cad = flt(doc.get("fixed_service_rate_cad"), 2)
	job.raw_price_cad = flt(doc.get("raw_price_cad"), 2)
	job.final_rounded_price_cad = flt(doc.get("final_rounded_price_cad"), 2)
	job.pricing_exchange_rate = flt(doc.get("pricing_exchange_rate"), 9)
	job.pricing_exchange_rate_date = doc.get("pricing_exchange_rate_date")
	job.pricing_version = doc.get("pricing_version")
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


def _exact_native_pdf_page_count(files) -> int:
	"""Return a sum of native PDF pages without OCR or text extraction."""
	from pypdf import PdfReader

	total_pages = 0
	pdf_count = 0
	for row in files:
		if not str(row.file_name or "").lower().endswith(".pdf"):
			continue
		try:
			content = frappe.get_doc("File", row.name).get_content()
			if isinstance(content, str):
				content = content.encode("utf-8")
			pages = len(PdfReader(io.BytesIO(content)).pages)
		except Exception as exc:
			frappe.throw(
				_("The source PDF {0} could not be read for native page counting: {1}").format(
					row.file_name, str(exc)[:200]
				),
				frappe.ValidationError,
			)
		if pages <= 0:
			frappe.throw(_("The source PDF {0} has no pages.").format(row.file_name), frappe.ValidationError)
		pdf_count += 1
		total_pages += pages
	if not pdf_count:
		frappe.throw(
			_("Upload at least one clean PDF Job Document before estimating."),
			frappe.ValidationError,
		)
	return total_pages


def _selected_pricing_service(doc) -> str:
	"""Resolve and validate the explicitly stored fixed-rate service."""
	from lex.instant_estimator import FIXED_SERVICE_RATES_CAD

	service = str(
		doc.get("selected_pricing_service")
		or FIXED_PRICING_SERVICE_BY_INTAKE_TYPE.get(doc.service_type)
		or ""
	).strip()
	if service not in FIXED_SERVICE_RATES_CAD:
		frappe.throw(_("Select a valid fixed-rate service before estimating."), frappe.ValidationError)
	return service


def _native_pdf_scope_summary(doc, selected_service: str, page_count: int) -> str:
	return (
		f"{selected_service}; {page_count} exact native PDF page(s). "
		f"Requested outcome: {doc.expected_outcome}. "
		f"Client instructions: {frappe.utils.strip_html(doc.detailed_instructions or doc.preliminary_details or '')[:1200]}"
	)


def _notify_ceo_of_pending_pricing(doc):
	"""Notify every user holding the CEO role (in-app + email) that a quote awaits approval."""
	doc.reload()
	if doc.pricing_approval_status != "Pending CEO Approval":
		return
	ceo_users = [
		user for user in frappe.get_all("Has Role", filters={"role": "CEO", "parenttype": "User"}, pluck="parent")
		if user not in ("Administrator", "Guest")
		and frappe.db.get_value("User", user, "enabled")
		and frappe.db.get_value("User", user, "user_type") == "System User"
	]
	if not ceo_users:
		frappe.log_error("No enabled CEO user found to notify for pricing approval.", "Work Intake Pricing Approval")

	link = frappe.utils.get_url(f"/app/lexocrates-work-intake/{doc.name}")
	subject = _("Matter pricing approval needed: {0}").format(doc.intake_title)
	message = _(
		"<p>A new quote is ready for your approval before the client can pay.</p>"
		"<p><b>Matter:</b> {0}<br><b>Client:</b> {1}<br><b>Service type:</b> {2}<br>"
		"<b>Estimated price:</b> {3} {4}<br><b>Legal Capacity required:</b> {5} {4}<br>"
		"<b>Delivery timeline:</b> {6} hours<br><b>Estimate method:</b> {7}</p>"
		"<p><a href=\"{8}\">Open in Lexocrates Desk to approve or reject</a></p>"
	).format(
		frappe.utils.escape_html(doc.intake_title), doc.client, doc.service_type,
		doc.quoted_amount, doc.currency, _required_legal_capacity(doc), doc.delivery_timeline_hours,
		doc.estimate_method or "Native PDF Fixed Rate", link,
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
		{"quoted_amount": doc.quoted_amount, "required_legal_capacity": _required_legal_capacity(doc), "notified": ceo_users},
	)
	_post_ceo_approval_card(doc)


def _post_ceo_approval_card(doc):
	"""Post executive pricing approval cards without exposing them to client chat."""
	try:
		from lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel import ensure_ceo_approval_channel
		from lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message import create_system_message
		from lex.lexocrates_chat_sync import ensure_matter_chat_channel

		channels = [("global", ensure_ceo_approval_channel(), 1)]
		if doc.matter:
			channels.append(("matter", frappe.get_doc("Lexocrates Chat Channel", ensure_matter_chat_channel(doc.matter)), 1))
		channels = [(key, channel, internal_only) for key, channel, internal_only in channels if channel]
		if not channels:
			return

		files = _intake_files(doc.name)
		doc_lines = []
		attachments = []
		for f in files:
			if f.custom_lex_scan_status == "Clean":
				file_url = secure_download_url_for_file_url(f.file_url) or f.file_url
				size_kb = max(1, round((f.file_size or 0) / 1024))
				doc_lines.append(f"- [{f.file_name}]({file_url}) ({size_kb} KB, Clean)")
				attachments.append(file_url)

		docs_text = "\n".join(doc_lines) if doc_lines else "_No clean documents attached._"
		instructions_snippet = (frappe.utils.strip_html(doc.detailed_instructions or doc.preliminary_details or ""))[:300]
		if instructions_snippet:
			instructions_snippet = f"\n> **Instructions:** {instructions_snippet}"

		client_name = frappe.db.get_value("Customer", doc.client, "customer_name") or doc.client
		desk_url = frappe.utils.get_url(f"/app/lexocrates-work-intake/{doc.name}")

		msg = (
			f"### 📋 Matter Pricing Approval Request: [{doc.intake_title}]({desk_url})\n\n"
			f"- **Client:** {client_name} ({doc.client}) | **Submitted by:** {doc.submitted_by or 'Client'}\n"
			f"- **Service Type:** {doc.service_type} | **Jurisdiction:** {doc.jurisdiction or 'N/A'}\n"
			f"- **Estimated Price:** **{flt(doc.quoted_amount):,.2f} {doc.currency}**\n"
			f"- **Legal Capacity Required:** **{flt(_required_legal_capacity(doc)):,.2f} {doc.currency}**\n"
			f"- **Delivery Timeline:** **{cint(doc.delivery_timeline_hours)} hours**\n"
			f"- **Estimate Method:** {doc.estimate_method or 'Formula'}\n"
			f"{instructions_snippet}\n\n"
			f"**Source Documents:**\n{docs_text}\n\n"
			f"_Awaiting CEO approval to release fixed quote to client._"
		)

		for key, channel, internal_only in channels:
			create_system_message(
				channel=channel.name,
				message_text=msg,
				source_doctype="Lexocrates Work Intake",
				source_name=doc.name,
				automation_key=f"ceo_pricing_approval:{doc.name}:{doc.quote_version}:{key}",
				internal_only=internal_only,
			)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"CEO Pricing Approval Chat Notification Failed for {doc.name}")


def _post_ceo_approval_decision(doc, decision: str, notes: str | None = None):
	try:
		from lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel import ensure_ceo_approval_channel
		from lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message import create_system_message
		from lex.lexocrates_chat_sync import ensure_matter_chat_channel

		channels = [("global", ensure_ceo_approval_channel(), 1)]
		if doc.matter:
			channels.append(("matter", frappe.get_doc("Lexocrates Chat Channel", ensure_matter_chat_channel(doc.matter)), 1))
		channels = [(key, channel, internal_only) for key, channel, internal_only in channels if channel]
		if not channels:
			return

		desk_url = frappe.utils.get_url(f"/app/lexocrates-work-intake/{doc.name}")
		if decision == "Approved":
			msg = (
				f"✅ **Matter Pricing Approved** for [{doc.intake_title}]({desk_url}) by **{frappe.session.user}**!\n"
				f"- **Approved Amount:** **{flt(doc.quoted_amount):,.2f} {doc.currency}**\n"
				f"- **Delivery Timeline:** **{cint(doc.delivery_timeline_hours)} hours**\n"
				f"Client payment gateway (Razorpay / LexPack) is now **unlocked** on Client Portal."
			)
		else:
			msg = (
				f"❌ **Matter Pricing Rejected** for [{doc.intake_title}]({desk_url}) by **{frappe.session.user}**.\n"
				f"- **Reason:** {notes or 'No reason provided'}\n"
				f"Intake returned to **Operations Review**."
			)

		for key, channel, internal_only in channels:
			create_system_message(
				channel=channel.name,
				message_text=msg,
				source_doctype="Lexocrates Work Intake",
				source_name=doc.name,
				automation_key=f"ceo_pricing_decision:{doc.name}:{doc.quote_version}:{decision.lower()}:{key}",
				internal_only=internal_only,
			)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"CEO Pricing Decision Chat Notification Failed for {doc.name}")


def _post_ceo_payment_confirmation(doc):
	try:
		from lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel import ensure_ceo_approval_channel
		from lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message import create_system_message

		channel = ensure_ceo_approval_channel()
		if not channel:
			return

		desk_url = frappe.utils.get_url(f"/app/lexocrates-work-intake/{doc.name}")
		payment_id_info = f"- **Payment Reference:** `{doc.razorpay_payment_id}`\n" if doc.razorpay_payment_id else ""
		invoice_info = f"- **Sales Invoice:** **{doc.sales_invoice}**\n" if doc.sales_invoice else ""
		entry_info = f"- **Payment Entry:** **{doc.payment_entry}**\n" if doc.payment_entry else ""
		msg = (
			f"🎉 **Work Funded & Activated** for [{doc.intake_title}]({desk_url})!\n"
			f"- **Funding Route:** {doc.funding_route}\n"
			f"- **Amount:** **{flt(doc.quoted_amount):,.2f} {doc.currency}**\n"
			f"{payment_id_info}{invoice_info}{entry_info}"
			f"- **Operational SLA:** Started on `{doc.sla_started_on}` | Delivery due `{doc.delivery_due_on}`\n"
			f"Job **{doc.job}** under Matter **{doc.matter}** is now **Active**."
		)

		create_system_message(
			channel=channel.name,
			message_text=msg,
			source_doctype="Lexocrates Work Intake",
			source_name=doc.name,
			automation_key=f"ceo_payment_confirmed:{doc.name}:{doc.sales_invoice or doc.wallet_reservation or 'funded'}",
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"CEO Payment Confirmation Chat Notification Failed for {doc.name}")


def _outgoing_email_is_ready() -> bool:
	return bool(
		frappe.db.exists(
			"Email Account",
			{"enable_outgoing": 1, "default_outgoing": 1},
		)
	)


def _client_portal_url(section: str = "new-matter") -> str:
	base = str(frappe.conf.get("lexocrates_public_url") or "https://engine.lexocrates.com").rstrip("/")
	return f"{base}/client-portal#{section}"


def _notify_client_quote_ready(doc):
	recipients = []
	if doc.portal_user:
		user = frappe.db.get_value("Lexocrates Portal User", doc.portal_user, "user")
		if user:
			recipients.append(user)
	if doc.matter:
		from lex.client_access import get_authorized_portal_users

		recipients.extend(get_authorized_portal_users(doc.matter))
	recipients = list(dict.fromkeys(filter(None, recipients)))
	emails = list(filter(None, (frappe.db.get_value("User", user, "email") for user in recipients)))
	if not emails or not _outgoing_email_is_ready() or getattr(frappe.flags, "in_test", False):
		return
	message = _(
		"<p>Your Lexocrates job pricing is ready for review and payment.</p>"
		"<p><b>Job:</b> {0}<br><b>Matter:</b> {1}</p>"
		"<p>Log in to the secure Client Portal to view the approved quote and payment options.</p>"
		"<p><a href=\"{2}\">Open Client Portal</a></p>"
	).format(
		frappe.utils.escape_html(doc.job or doc.name),
		frappe.utils.escape_html(doc.matter or ""),
		_client_portal_url("new-matter"),
	)
	try:
		frappe.sendmail(
			recipients=emails,
			subject=_("Lexocrates job pricing is ready: {0}").format(doc.intake_title),
			message=message,
			reference_doctype=doc.doctype,
			reference_name=doc.name,
			delayed=False,
			send_priority=1,
			x_priority=1,
			add_unsubscribe_link=0,
		)
		_audit(doc, "Client Quote Ready Email Queued", {"recipients": recipients})
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"Client quote-ready email failed for {doc.name}")


def _required_legal_capacity(doc) -> float:
	return flt(doc.get("required_legal_capacity") or doc.get("quoted_amount") or 0, 2)


def _recommend_plan(client, required_capacity, currency: str = "CAD"):
	available = _available_legal_capacity(client)
	if available >= required_capacity:
		return None
	shortfall = required_capacity - available
	plans = frappe.get_all(
		"LexPack Plan",
		filters={"status": "Active", "self_service": 1, "enterprise_custom": 0},
		fields=["name", "plan_code", "currency", "price", "display_order", "discount_percent"],
		order_by="display_order asc",
		limit_page_length=50,
	)
	from lex.lexpack import _checkout_pricing_for_plan
	eligible = []
	for plan in plans:
		checkout = _checkout_pricing_for_plan(plan, requested_currency=currency)
		if flt(checkout["legal_capacity_amount"]) >= shortfall and flt(checkout["price"]) <= required_capacity:
			eligible.append((flt(checkout["price"]), cint(plan.display_order), plan.name))
	return min(eligible)[2] if eligible else None


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
		"is_live_order": True,
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


def _available_legal_capacity(client):
	wallet = frappe.db.get_value(
		"Lexocrates Client Wallet", {"client": client}, ["current_balance", "capacity_currency"], as_dict=True
	) or {}
	# Legacy points must never be silently displayed or consumed as currency capacity.
	if flt(wallet.get("current_balance")) and not wallet.get("capacity_currency"):
		return 0
	return flt(wallet.get("current_balance") or 0)


def _validate_legal_capacity_currency(client: str, currency: str):
	wallet = frappe.db.get_value(
		"Lexocrates Client Wallet", {"client": client}, ["current_balance", "capacity_currency"], as_dict=True
	) or {}
	if flt(wallet.get("current_balance")) and not wallet.get("capacity_currency"):
		frappe.throw(
			_("This legacy wallet must be reconciled to Legal Capacity before it can fund work."),
			frappe.ValidationError,
		)
	if wallet.get("capacity_currency") and wallet.capacity_currency != currency:
		frappe.throw(
			_("Available Legal Capacity is held in {0}, but this quote is in {1}.").format(wallet.capacity_currency, currency),
			frappe.ValidationError,
		)


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


def _require_system_job_estimation_access(job: str):
	_require_internal()
	job_doc = frappe.get_doc("LPO Job", job)
	if not frappe.has_permission("LPO Job", ptype="write", doc=job_doc):
		frappe.throw(_("You do not have permission to estimate this Job."), frappe.PermissionError)
	if not job_doc.work_intake or not frappe.db.exists("Lexocrates Work Intake", job_doc.work_intake):
		frappe.throw(
			_("This Job has no governed Work Intake. Create it through the Client Intake workflow before estimating."),
			frappe.ValidationError,
		)
	intake_doc = frappe.get_doc("Lexocrates Work Intake", job_doc.work_intake)
	if intake_doc.job != job_doc.name or intake_doc.matter != job_doc.engagement:
		frappe.throw(_("The Job and Work Intake links are inconsistent."), frappe.ValidationError)
	if intake_doc.client != job_doc.customer:
		frappe.throw(_("The Job and Work Intake must belong to the same client."), frappe.ValidationError)
	return job_doc, intake_doc


def _require_funding_authority(actor, route):
	if _is_internal():
		return
	if route in {"Existing Legal Capacity", "Recommended LexPack"} and not (actor and actor.lexpack_purchase_access):
		frappe.throw(_("LexPack purchase authority is required."), frappe.PermissionError)
	if route == "Direct Quote" and not (actor and actor.billing_access):
		frappe.throw(_("Billing access is required for direct quote payment."), frappe.PermissionError)


def _require_internal():
	if not _is_internal():
		frappe.throw(_("Legal Operations authority is required."), frappe.PermissionError)


def _require_pricing_authority():
	if frappe.session.user == "Administrator":
		return
	if "CEO" not in frappe.get_roles(frappe.session.user):
		frappe.throw(_("Only the CEO role can release client pricing."), frappe.PermissionError)
	if frappe.db.get_value("User", frappe.session.user, "user_type") != "System User":
		frappe.throw(_("Pricing can be released only by an internal System User."), frappe.PermissionError)


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

