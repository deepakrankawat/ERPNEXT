from __future__ import annotations

import base64
import binascii
import os

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_datetime, now_datetime, nowdate
from frappe.utils.file_manager import save_file

from lex.client_access import (
	get_portal_user,
	has_matter_access,
	has_portal_capability,
)
from lex.portal_audit import create_portal_audit_event


ALLOWED_UPLOAD_EXTENSIONS = {
	".csv", ".doc", ".docx", ".jpeg", ".jpg", ".pdf", ".png", ".ppt", ".pptx",
	".txt", ".xls", ".xlsx",
}
MAX_PORTAL_UPLOAD_BYTES = 10 * 1024 * 1024


@frappe.whitelist()
def get_portal_dashboard():
	portal_user = _require_portal_user()
	client = _client_details(portal_user.client)
	from lex.work_intake import portal_intakes

	intakes = portal_intakes(portal_user)
	matters = frappe.get_list(
		"LPO Matter",
		fields=[
			"name", "matter_title", "status", "practice_area", "billing_method", "end_date",
			"modified", "confidentiality_level",
		],
		order_by="modified desc",
		limit_page_length=100,
	)
	jobs = frappe.get_list(
		"LPO Job",
		fields=[
			"name", "job_title", "engagement", "job_status", "priority", "due_date", "modified",
			"job_type", "delivery_document", "client_approval_status", "client_approved_on",
		],
		order_by="due_date asc",
		limit_page_length=100,
	)
	open_jobs = sum(row.job_status not in {"Delivered", "Completed", "Cancelled"} for row in jobs)
	wallet, transactions = _wallet_data(portal_user)
	from lex.lexpack import get_lexpack_portal_data

	lexpack = get_lexpack_portal_data(portal_user)
	portal_users = _portal_users(portal_user)
	audit_events = frappe.get_all(
		"Lexocrates Portal Audit Event",
		filters={"client": portal_user.client},
		fields=["name", "event_timestamp", "action", "result", "object_type", "object_id", "user"],
		order_by="event_timestamp desc",
		limit_page_length=15,
	)
	documents = _documents(matters, jobs, intakes) if portal_user.can_upload_documents or matters or intakes else []
	invoices = _invoices(portal_user.client) if portal_user.billing_access else []
	approvals = [
		row for row in jobs
		if row.job_status == "Ready for Delivery"
		and row.client_approval_status not in {"Approved"}
	] if portal_user.approval_authority not in {None, "", "None"} else []

	return {
		"profile": {
			"name": portal_user.name,
			"full_name": frappe.db.get_value("User", portal_user.user, "full_name"),
			"email": portal_user.user,
			"portal_role": portal_user.portal_role,
			"department": frappe.db.get_value(
				"Lexocrates Client Department", portal_user.get("department"), "department_name"
			) if portal_user.get("department") else None,
			"mfa_required": bool(portal_user.get("mfa_required")),
			"mfa_enabled": bool(portal_user.get("mfa_enabled")),
		},
		"client": client,
		"navigation": _navigation(portal_user),
		"permissions": {fieldname: portal_user.get(fieldname) for fieldname in (
			"matter_access_scope", "can_create_matters", "can_upload_documents", "can_comment",
			"billing_access", "lexpack_view_access", "lexpack_purchase_access", "approval_authority",
			"user_management_authority", "report_access",
		)},
		"metrics": {
			"active_intakes": sum(row.get("status") not in {"Matter Confirmed", "Cancelled"} for row in intakes),
			"authorized_matters": len(matters),
			"open_jobs": open_jobs,
			"approvals": len(approvals),
			"documents": len(documents),
			"lexpoints": wallet.current_balance if wallet else None,
		},
		"onboarding": _onboarding(intakes, matters, jobs),
		"intakes": intakes,
		"matters": matters,
		"jobs": jobs,
		"documents": documents,
		"approvals": approvals,
		"invoices": invoices,
		"reports": _report_catalog(portal_user),
		"wallet": wallet,
		"transactions": transactions,
		"lexpack": lexpack,
		"portal_users": portal_users,
		"audit_events": audit_events,
	}


def _client_details(client_name: str):
	fields = ["name", "customer_name", "default_currency"]
	for fieldname in (
		"custom_lexocrates_client_id", "custom_organization_type", "custom_primary_jurisdiction",
	):
		if frappe.get_meta("Customer").has_field(fieldname):
			fields.append(fieldname)
	return frappe.db.get_value("Customer", client_name, fields, as_dict=True)


def _wallet_data(portal_user):
	if not portal_user.lexpack_view_access:
		return None, []
	wallet = frappe.db.get_value(
		"Lexocrates Client Wallet",
		{"client": portal_user.client},
		[
			"name", "status", "current_balance", "reserved_balance", "total_purchased", "total_topped_up",
			"total_consumed", "current_pricing_tier", "rolling_12_month_spend", "bonus_points_earned",
		],
		as_dict=True,
	)
	transactions = []
	if wallet:
		transactions = frappe.get_all(
			"Lexocrates Wallet Transaction",
			filters={"wallet": wallet.name},
			fields=["name", "transaction_type", "points", "posted_on", "matter", "available_balance_after"],
			order_by="posted_on desc",
			limit_page_length=50,
		)
	return wallet, transactions


def _portal_users(portal_user):
	if not portal_user.user_management_authority:
		return []
	return frappe.get_all(
		"Lexocrates Portal User",
		filters={"client": portal_user.client},
		fields=[
			"name", "full_name", "email", "portal_role", "account_status", "department", "last_login",
			"matter_access_scope", "can_create_matters", "can_upload_documents", "can_comment",
			"billing_access", "lexpack_view_access", "lexpack_purchase_access", "approval_authority",
			"user_management_authority", "report_access", "mfa_required",
		],
		order_by="full_name asc",
		limit_page_length=100,
	)


def _documents(matters, jobs, intakes=None):
	rows = []
	for doctype, names in (
		("Lexocrates Work Intake", [row.get("name") for row in (intakes or [])]),
		("LPO Matter", [row.name for row in matters]),
		("LPO Job", [row.name for row in jobs]),
	):
		if not names:
			continue
		rows.extend(frappe.get_all(
			"File",
			filters={"attached_to_doctype": doctype, "attached_to_name": ["in", names], "is_folder": 0},
			fields=[
				"name", "file_name", "file_url", "file_size", "is_private", "attached_to_doctype",
				"attached_to_name", "modified",
			],
			order_by="modified desc",
			limit_page_length=200,
		))
	rows.sort(key=lambda row: str(row.modified or ""), reverse=True)
	return rows


def _invoices(client: str):
	return frappe.get_all(
		"Sales Invoice",
		filters={"customer": client, "docstatus": ["in", [0, 1]]},
		fields=[
			"name", "posting_date", "due_date", "status", "currency", "grand_total", "outstanding_amount",
		],
		order_by="posting_date desc",
		limit_page_length=100,
	)


def _onboarding(intakes, matters, jobs):
	has_message = bool(frappe.db.exists("Lexocrates Chat Message", {"sender": frappe.session.user}))
	accepted = any(row.get("sla_accepted") for row in intakes)
	has_documents = any(row.get("document_count") for row in intakes)
	has_quote = any(row.get("quote_status") in {"Ready", "Accepted"} for row in intakes)
	funded = any(row.get("funding_status") == "Funded" for row in intakes)
	steps = [
		{"label": "Secure account activated", "complete": True, "section": "overview"},
		{"label": "Submit preliminary work details", "complete": bool(intakes), "section": "new-matter"},
		{"label": "Review and accept SLA", "complete": accepted, "section": "new-matter"},
		{"label": "Upload secure documents", "complete": has_documents, "section": "new-matter"},
		{"label": "Receive scope and quote", "complete": has_quote, "section": "new-matter"},
		{"label": "Fund and activate work", "complete": funded, "section": "new-matter"},
		{"label": "Open secure Messages", "complete": has_message, "section": "messages"},
	]
	return {"completed": sum(cint(row["complete"]) for row in steps), "total": len(steps), "steps": steps}


def _navigation(portal_user):
	items = [{"label": "Dashboard", "section": "overview", "icon": "home"}]
	if portal_user.matter_access_scope != "No Matter Access":
		items.append({"label": "My Matters", "section": "matters", "icon": "briefcase"})
	if portal_user.can_create_matters:
		items.extend((
			{"label": "Submit New Work", "section": "new-matter", "icon": "plus"},
			{"label": "Work Status", "section": "work-requests", "icon": "clipboard"},
		))
	if portal_user.can_upload_documents or portal_user.matter_access_scope != "No Matter Access":
		items.append({"label": "Documents", "section": "documents", "icon": "file"})
	if portal_user.approval_authority not in {None, "", "None"}:
		items.append({"label": "Approvals", "section": "approvals", "icon": "check"})
	if portal_user.report_access not in {None, "", "None"}:
		items.append({"label": "Reports", "section": "reports", "icon": "chart"})
	items.append({"label": "Messages", "section": "messages", "icon": "message"})
	if portal_user.billing_access:
		items.append({"label": "Billing", "section": "billing", "icon": "invoice"})
	if portal_user.lexpack_view_access:
		items.append({"label": "LexPack", "section": "wallet", "icon": "wallet"})
	if portal_user.user_management_authority:
		items.extend((
			{"label": "Team & Access", "section": "users", "icon": "users"},
			{"label": "Organization", "section": "organization", "icon": "settings"},
		))
	items.append({"label": "Support", "href": "mailto:support@lexocrates.com", "icon": "help"})
	return items


@frappe.whitelist()
def create_matter(
	practice_area: str,
	jurisdictions: str,
	description: str,
	engagement_title: str | None = None,
	matter_title: str | None = None,
	billing_method: str = "Quoted Price",
	lexpoints_estimated: float = 0,
):
	_require_portal_user()
	frappe.throw(
		_("Use Submit New Work. A Matter is created only after SLA acceptance, clean document analysis, quote approval and successful funding."),
		frappe.ValidationError,
	)


@frappe.whitelist()
def create_work_request(
	engagement: str,
	job_title: str,
	job_type: str,
	priority: str,
	due_date: str,
	task_description: str,
):
	_require_portal_user()
	frappe.throw(
		_("Submit a new Work Intake so documents, quote and funding are reviewed before a Job is activated."),
		frappe.ValidationError,
	)


@frappe.whitelist()
def upload_matter_document(matter: str, filename: str, content: str):
	portal_user = _require_portal_user()
	if not portal_user.can_upload_documents or not has_matter_access(matter, "upload"):
		frappe.throw(_("You are not authorized to upload documents to this Matter."), frappe.PermissionError)
	filename = os.path.basename((filename or "").strip())
	extension = os.path.splitext(filename)[1].lower()
	if not filename or extension not in ALLOWED_UPLOAD_EXTENSIONS:
		frappe.throw(_("This file type is not allowed."), frappe.ValidationError)
	try:
		encoded = content.split(",", 1)[-1]
		decoded = base64.b64decode(encoded, validate=True)
	except (ValueError, binascii.Error):
		frappe.throw(_("The uploaded file is not valid."), frappe.ValidationError)
	if not decoded or len(decoded) > MAX_PORTAL_UPLOAD_BYTES:
		frappe.throw(_("Upload a non-empty file no larger than 10 MB."), frappe.ValidationError)
	file_doc = save_file(filename, decoded, "LPO Matter", matter, is_private=1)
	from lex.file_quarantine import scan_and_validate_inbound_file

	scan = scan_and_validate_inbound_file(file_doc.name)
	create_portal_audit_event(
		client=portal_user.client,
		portal_user=portal_user.name,
		matter=matter,
		action="Document Uploaded",
		object_type="File",
		object_id=file_doc.name,
		new_value={"file_name": file_doc.file_name, "file_size": file_doc.file_size},
	)
	return {
		"name": file_doc.name,
		"file_name": file_doc.file_name,
		"file_url": file_doc.file_url,
		"file_size": file_doc.file_size,
		"attached_to_doctype": "LPO Matter",
		"attached_to_name": matter,
		"modified": file_doc.modified,
		"scan_status": scan["status"],
		"quarantine_passed": scan["quarantine_passed"],
	}


@frappe.whitelist()
def submit_client_approval(job: str, decision: str, notes: str | None = None):
	portal_user = _require_portal_user()
	if decision not in {"Approved", "Changes Requested"}:
		frappe.throw(_("Choose Approved or Changes Requested."), frappe.ValidationError)
	job_data = frappe.db.get_value(
		"LPO Job", job, ["engagement", "job_status", "job_title"], as_dict=True
	)
	if not job_data or job_data.job_status != "Ready for Delivery" or not has_matter_access(job_data.engagement, "approve"):
		frappe.throw(_("This deliverable is not available for your approval."), frappe.PermissionError)
	frappe.db.set_value("LPO Job", job, {
		"client_approval_status": decision,
		"client_approved_by": frappe.session.user,
		"client_approved_on": now_datetime(),
		"client_approval_notes": (notes or "").strip(),
		"delivery_receipt_status": "Acknowledged" if decision == "Approved" else "Rejected",
		"delivery_acknowledged_by": frappe.session.user,
		"delivery_acknowledged_on": now_datetime(),
	})
	create_portal_audit_event(
		client=portal_user.client,
		portal_user=portal_user.name,
		matter=job_data.engagement,
		action="Client Approval Submitted",
		object_type="LPO Job",
		object_id=job,
		new_value={"decision": decision, "notes": (notes or "").strip()},
	)
	return {"name": job, "decision": decision}


@frappe.whitelist()
def generate_portal_report(report_name: str):
	portal_user = _require_portal_user()
	allowed = {row["name"] for row in _report_catalog(portal_user)}
	if report_name not in allowed:
		frappe.throw(_("This report is not enabled for your account."), frappe.PermissionError)
	if report_name == "Matter Status Report":
		rows = frappe.get_list(
			"LPO Matter", fields=["name", "matter_title", "practice_area", "status", "end_date"],
			order_by="modified desc", limit_page_length=500,
		)
		columns = ["name", "matter_title", "practice_area", "status", "end_date"]
	elif report_name == "Financial Summary":
		rows = _invoices(portal_user.client)
		columns = ["name", "posting_date", "due_date", "status", "currency", "grand_total", "outstanding_amount"]
	else:
		rows = frappe.get_all(
			"Lexocrates Portal Audit Event", filters={"client": portal_user.client},
			fields=["event_timestamp", "action", "result", "object_type", "object_id", "user"],
			order_by="event_timestamp desc", limit_page_length=500,
		)
		columns = ["event_timestamp", "action", "result", "object_type", "object_id", "user"]
	record_report_download(report_name)
	return {"name": report_name, "columns": columns, "rows": rows}


def _report_catalog(portal_user):
	scope = portal_user.report_access
	rows = []
	if scope in {"Matter Reports", "All Client Reports"}:
		rows.append({"name": "Matter Status Report", "description": "Authorized matters and current status"})
	if scope in {"Financial Reports", "All Client Reports"} and portal_user.billing_access:
		rows.append({"name": "Financial Summary", "description": "Invoices and outstanding amounts"})
	if scope in {"Compliance Reports", "All Client Reports"}:
		rows.append({"name": "Portal Audit Report", "description": "Audited organization activity"})
	return rows


@frappe.whitelist()
def record_report_download(report_name: str, matter: str | None = None):
	portal_user = _require_portal_user()
	if portal_user.report_access in {None, "", "None"}:
		frappe.throw(_("Report access is not enabled for your account."), frappe.PermissionError)
	create_portal_audit_event(
		client=portal_user.client,
		portal_user=portal_user.name,
		matter=matter,
		action="Report Download",
		object_type="Report",
		object_id=report_name,
	)
	return {"recorded": True}


def _require_portal_user():
	portal_user = get_portal_user()
	if not portal_user:
		frappe.throw(_("An active Lexocrates Portal User account is required."), frappe.PermissionError)
	return portal_user
