from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_datetime, now_datetime, nowdate

from lex.client_access import (
	get_portal_user,
	has_matter_access,
	has_portal_capability,
)
from lex.pdf_watermark import (
	add_secure_download_url,
	secure_download_url_for_file_url,
)
from lex.portal_audit import create_portal_audit_event


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
			"modified", "confidentiality_level", "matter_nature", "represented_party_name",
			"our_side_role", "counterparty_name", "counterparty_role", "opposing_counsel",
		],
		order_by="modified desc",
		limit_page_length=100,
	)
	jobs = frappe.get_list(
		"LPO Job",
		fields=[
			"name", "job_title", "engagement", "job_status", "priority", "due_date", "modified",
			"job_type", "delivery_document", "client_approval_status", "client_approved_on",
			"work_intake", "estimate_status", "quote_version", "required_lexpoints", "quoted_amount",
			"currency", "funding_route", "funding_status", "sla_started_on", "delivery_due_on",
		],
		order_by="due_date asc",
		limit_page_length=100,
	)
	for job in jobs:
		# The canonical final deliverable is intentionally unavailable until the
		# operational Job reaches Completed.  Ready-for-Delivery and Delivered are
		# still internal/acknowledgement states, not the client's download gate.
		job.delivery_download_url = (
			secure_download_url_for_file_url(job.delivery_document)
			if job.job_status == "Completed" and job.delivery_document else None
		)
		job.delivery_preview_url = (
			secure_download_url_for_file_url(job.delivery_document)
			if (
				job.job_status == "Ready for Delivery"
				and job.delivery_document
				and portal_user.approval_authority not in {None, "", "None"}
				and has_matter_access(job.engagement, "approve")
			)
			else None
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
	documents = _documents(matters, jobs, intakes, portal_user) if portal_user.can_upload_documents or matters or intakes else []
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


def _documents(matters, jobs, intakes=None, portal_user=None):
	"""Return client-owned uploads plus completed canonical deliverables only."""
	rows = []
	portal_user = portal_user or _require_portal_user()
	client_users = frappe.get_all(
		"Lexocrates Portal User",
		filters={"client": portal_user.client},
		pluck="user",
		limit_page_length=0,
	)
	file_fields = [
		"name", "file_name", "file_url", "file_size", "is_private", "owner",
		"attached_to_doctype", "attached_to_name", "modified",
	]
	for doctype, names in (
		("LPO Job", [row.name for row in jobs]),
		# Historical compatibility only. New uploads are attached exclusively to Jobs.
		("Lexocrates Work Intake", [row.get("name") for row in (intakes or [])]),
	):
		if not names:
			continue
		uploads = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": doctype,
				"attached_to_name": ["in", names],
				"owner": ["in", client_users or [frappe.session.user]],
				"is_folder": 0,
			},
			fields=file_fields,
			order_by="modified desc",
			limit_page_length=200,
		)
		for row in uploads:
			row.portal_document_type = "Client Upload"
		rows.extend(uploads)

	delivery_by_job = {
		row.name: row.delivery_document
		for row in jobs
		if row.job_status == "Completed" and row.delivery_document
	}
	if delivery_by_job:
		deliverables = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "LPO Job",
				"attached_to_name": ["in", list(delivery_by_job)],
				"file_url": ["in", list(delivery_by_job.values())],
				"is_folder": 0,
			},
			fields=file_fields,
			order_by="modified desc",
			limit_page_length=200,
		)
		for row in deliverables:
			if delivery_by_job.get(row.attached_to_name) != row.file_url:
				continue
			row.portal_document_type = "Completed Deliverable"
			rows.append(row)

	# A historical File row can be returned through more than one scoped link.
	rows = list({row.name: row for row in rows}.values())
	rows.sort(key=lambda row: str(row.modified or ""), reverse=True)
	for row in rows:
		add_secure_download_url(row)
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
		_("Use Submit New Work. Select or create the Matter first; its Draft Job is activated only after SLA acceptance, clean Job-document analysis, quote approval and successful funding."),
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
	_require_portal_user()
	frappe.throw(
		_("Matter-level uploads are disabled. Open Submit New Work and upload the document to its Draft Job."),
		frappe.ValidationError,
	)


@frappe.whitelist()
def submit_client_approval(job: str, decision: str, notes: str | None = None):
	portal_user = _require_portal_user()
	if decision not in {"Approved", "Changes Requested"}:
		frappe.throw(_("Choose Approved or Changes Requested."), frappe.ValidationError)
	job_doc = frappe.get_doc("LPO Job", job)
	if job_doc.job_status != "Ready for Delivery" or not has_matter_access(job_doc.engagement, "approve"):
		frappe.throw(_("This deliverable is not available for your approval."), frappe.PermissionError)
	job_doc.client_approval_status = decision
	job_doc.client_approved_by = frappe.session.user
	job_doc.client_approved_on = now_datetime()
	job_doc.client_approval_notes = (notes or "").strip()
	job_doc.delivery_receipt_status = "Acknowledged" if decision == "Approved" else "Rejected"
	job_doc.delivery_acknowledged_by = frappe.session.user
	job_doc.delivery_acknowledged_on = now_datetime()
	job_doc.job_status = "Completed" if decision == "Approved" else "In Progress"
	previous_flag = getattr(frappe.flags, "lexocrates_portal_service", False)
	frappe.flags.lexocrates_portal_service = True
	try:
		job_doc.save(ignore_permissions=True)
	finally:
		frappe.flags.lexocrates_portal_service = previous_flag
	create_portal_audit_event(
		client=portal_user.client,
		portal_user=portal_user.name,
		matter=job_doc.engagement,
		action="Client Approval Submitted",
		object_type="LPO Job",
		object_id=job,
		new_value={"decision": decision, "notes": (notes or "").strip(), "job_status": job_doc.job_status},
	)
	return {"name": job, "decision": decision, "job_status": job_doc.job_status}


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
	if portal_user.mfa_required and not frappe.db.get_single_value("System Settings", "enable_two_factor_auth"):
		frappe.throw(_("Multi-factor authentication is required for this account but is not enabled on the site."), frappe.PermissionError)
	return portal_user
