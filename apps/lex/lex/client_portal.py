from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, now_datetime, nowdate

from lex.client_access import (
	can_approve_deliverables,
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
	client = _client_details(portal_user.client) or frappe._dict(
		{"name": portal_user.client, "customer_name": _("Client Workspace"), "default_currency": "CAD"}
	)
	from lex.work_intake import portal_intakes

	hidden_intakes, hidden_jobs, hidden_matters = _hidden_client_records(portal_user.client)
	# Optional dashboard data must never make an otherwise authenticated client
	# lose access to the Matter and Job intake workspace.  This also lets a
	# partially migrated commercial add-on fail safely while its traceback is
	# retained for administrators in Error Log.
	intakes = _safe_dashboard_section("work intakes", lambda: portal_intakes(portal_user), [])
	matters = _safe_dashboard_section("matters", lambda: frappe.get_list(
		"LPO Matter",
		fields=[
			"name", "matter_title", "status", "practice_area", "billing_method", "end_date",
			"modified", "confidentiality_level", "matter_nature", "represented_party_name",
			"our_side_role", "counterparty_name", "counterparty_role", "opposing_counsel", "client_deleted",
		],
		order_by="modified desc",
		limit_page_length=100,
	), [])
	matters = [row for row in matters if row.name not in hidden_matters and not row.client_deleted]
	for matter in matters:
		matter.can_client_delete = bool(
			portal_user.can_create_matters and _matter_can_client_delete(matter.name)
		)
	jobs = _safe_dashboard_section("jobs", lambda: frappe.get_list(
		"LPO Job",
		fields=[
			"name", "job_title", "engagement", "job_status", "priority", "due_date", "modified",
			"job_type", "delivery_document", "client_approval_status", "client_approved_on",
			"work_intake", "estimate_status", "quote_version", "required_legal_capacity", "quoted_amount",
			"currency", "funding_route", "funding_status", "sla_started_on", "delivery_due_on",
			"confirmed_delivery_date", "sla_paused", "total_paused_minutes", "completed_on",
			"indicative_turnaround_snapshot", "service_level", "assignment_confirmation",
			"delivery_notes", "task_description",
		],
		order_by="due_date asc",
		limit_page_length=100,
	), [])
	jobs = [row for row in jobs if row.name not in hidden_jobs and row.job_status != "Cancelled"]
	matter_titles = {row.name: row.matter_title for row in matters}
	for job in jobs:
		# Keep the document names internally for access checks, but return the
		# readable Matter title for all client-facing labels.
		job.matter_title = matter_titles.get(job.engagement) or _("Matter")
	job_titles = {row.name: row.job_title for row in jobs}
	client_deleted_jobs = {
		row.get("job") for row in intakes
		if row.get("client_deleted") and row.get("job")
	}
	for intake in intakes:
		intake.matter_title = matter_titles.get(intake.get("matter")) or _("Matter pending")
		intake.job_title = job_titles.get(intake.get("job")) or _("Draft Job pending")
	for job in jobs:
		job.client_deleted = job.name in client_deleted_jobs
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
				and can_approve_deliverables()
				and has_matter_access(job.engagement, "approve")
			)
			else None
		)
	open_jobs = sum(row.job_status not in {"Delivered", "Completed", "Cancelled"} for row in jobs)
	wallet, transactions = _safe_dashboard_section("wallet", lambda: _wallet_data(portal_user), (None, []))
	for transaction in transactions:
		transaction.matter_title = matter_titles.get(transaction.matter) or ""
	from lex.lexpack import get_lexpack_portal_data

	lexpack = _safe_dashboard_section(
		"LexPack", lambda: get_lexpack_portal_data(portal_user),
		{"plans": [], "purchases": [], "payment_enabled": False, "purchase_access": False},
	)
	from lex.pilot import pilot_offer_for_client

	pilot = _safe_dashboard_section("complimentary pilot", lambda: pilot_offer_for_client(portal_user.client), None)
	portal_users = _safe_dashboard_section("portal users", lambda: _portal_users(portal_user), [])
	audit_events = _safe_dashboard_section("audit events", lambda: frappe.get_all(
		"Lexocrates Portal Audit Event",
		filters={"client": portal_user.client},
		fields=["name", "event_timestamp", "action", "result", "object_type", "object_id", "user"],
		order_by="event_timestamp desc",
		limit_page_length=100,
	), [])
	hidden_audit_objects = hidden_intakes | hidden_jobs | hidden_matters
	audit_events = [row for row in audit_events if row.object_id not in hidden_audit_objects][:15]
	documents = _safe_dashboard_section(
		"documents", lambda: _documents(matters, jobs, intakes, portal_user), []
	) if portal_user.can_upload_documents or matters or intakes else []
	invoices = _safe_dashboard_section("invoices", lambda: _invoices(portal_user.client), []) if portal_user.billing_access else []
	approvals = [
		row for row in jobs
		if row.job_status == "Ready for Delivery"
		and row.client_approval_status not in {"Approved"}
		and has_matter_access(row.engagement, "approve")
	] if can_approve_deliverables() else []
	assignment_confirmations = _safe_dashboard_section(
		"assignment confirmations",
		lambda: _assignment_confirmations(jobs, matter_titles, job_titles),
		[],
	)
	scope_changes = _safe_dashboard_section(
		"scope changes",
		lambda: _scope_changes(jobs, matter_titles, job_titles),
		[],
	)
	correction_requests = _safe_dashboard_section(
		"correction requests",
		lambda: _correction_requests(jobs, matter_titles, job_titles),
		[],
	)
	deadlines = _safe_dashboard_section(
		"deadlines",
		lambda: _upcoming_deadlines(matters, jobs, intakes),
		[],
	)
	# Deliberately not routed through _safe_dashboard_section: that helper's
	# fallback values are meant to degrade a display widget gracefully, but this
	# is a compliance gate — falling back to "Accepted" on error would silently
	# let a client bypass SLA acceptance. Fail closed (an explicit "Error"
	# status) instead, and log it like every other section.
	try:
		master_sla = _master_sla_status(portal_user)
	except Exception:
		frappe.log_error(title="Client Portal Dashboard: master SLA", message=frappe.get_traceback())
		master_sla = {"status": "Error"}

	pending_confirmations = sum(
		1 for row in assignment_confirmations if row.get("client_decision") == "Pending"
	)
	pending_scope_changes = sum(
		1 for row in scope_changes if row.get("status") == "Pending Client Approval"
	)
	info_holds = sum(
		1 for row in intakes if row.get("status") == "Pending Client Information"
	)

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
			"can_provide_instructions", "can_provide_binding_instructions",
			"billing_access", "lexpack_view_access", "lexpack_purchase_access", "approval_authority",
			"user_management_authority", "report_access",
		)},
		"metrics": {
			"active_intakes": sum(row.get("status") not in {"Matter Confirmed", "Cancelled"} for row in intakes),
			"authorized_matters": len(matters),
			"open_jobs": open_jobs,
			"approvals": len(approvals),
			"pending_confirmations": pending_confirmations,
			"pending_scope_changes": pending_scope_changes,
			"info_holds": info_holds,
			"documents": len(documents),
			"legal_capacity": wallet.current_balance if wallet else None,
		},
		"onboarding": _onboarding(intakes, matters, jobs),
		"intakes": intakes,
		"matters": matters,
		"jobs": jobs,
		"documents": documents,
		"approvals": approvals,
		"assignment_confirmations": assignment_confirmations,
		"scope_changes": scope_changes,
		"correction_requests": correction_requests,
		"deadlines": deadlines,
		"invoices": invoices,
		"reports": _report_catalog(portal_user),
		"wallet": wallet,
		"transactions": transactions,
		"lexpack": lexpack,
		"pilot": pilot,
		"portal_users": portal_users,
		"audit_events": audit_events,
		"master_sla": master_sla,
	}


def _master_sla_status(portal_user):
	from lex.lex.doctype.master_service_level_agreement.master_service_level_agreement import (
		get_latest_accepted,
		get_or_create_pending_master_sla,
	)

	accepted = get_latest_accepted(portal_user.client)
	if accepted:
		return {
			"status": "Accepted",
			"name": accepted.name,
			"version": accepted.version,
			"effective_date": str(accepted.effective_date) if accepted.effective_date else None,
			"accepted_by_name": accepted.accepted_by_name,
			"accepted_by_designation": accepted.accepted_by_designation,
			"acceptance_datetime": str(accepted.acceptance_datetime) if accepted.acceptance_datetime else None,
		}
	if not portal_user.can_create_matters:
		# Only a user who could actually hit the create_work_intake() gate needs
		# (and should trigger provisioning of) a pending Master SLA record.
		return {"status": "Not Applicable"}
	doc = get_or_create_pending_master_sla(portal_user.client)
	return {
		"status": doc.status,
		"name": doc.name,
		"version": doc.version,
		"terms_html": doc.terms_html,
		"client_legal_name": doc.client_legal_name or portal_user.client,
		"prefill_email": frappe.db.get_value("User", frappe.session.user, "email") or frappe.session.user,
	}


def _safe_dashboard_section(label: str, loader, fallback):
	"""Keep the client workspace available when a non-auth dashboard panel fails."""
	try:
		return loader()
	except Exception:
		frappe.log_error(
			title=f"Client Portal Dashboard: {label}",
			message=frappe.get_traceback(),
		)
		return fallback


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
			"name", "status", "capacity_currency", "current_balance", "reserved_balance", "total_purchased", "total_topped_up",
			"total_consumed", "current_pricing_tier", "rolling_12_month_spend",
		],
		as_dict=True,
	)
	transactions = []
	if wallet:
		wallet.requires_legal_capacity_reconciliation = bool(
			not wallet.get("capacity_currency")
			and any(flt(wallet.get(fieldname)) for fieldname in ("current_balance", "reserved_balance", "total_purchased", "total_consumed"))
		)
		transactions = frappe.get_all(
			"Lexocrates Wallet Transaction",
			filters={"wallet": wallet.name},
			fields=[
				"name", "transaction_type", "currency", "legal_capacity_amount", "posted_on", "matter",
				"available_balance_after",
			],
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
	matter_titles = {row.name: row.matter_title for row in matters}
	jobs_by_name = {row.name: row for row in jobs}
	intakes_by_name = {row.name: row for row in (intakes or [])}
	client_users = frappe.get_all(
		"Lexocrates Portal User",
		filters={"client": portal_user.client},
		pluck="user",
		limit_page_length=0,
	)
	file_fields = [
		"name", "file_name", "file_url", "file_size", "is_private", "owner",
		"attached_to_doctype", "attached_to_name", "modified", "custom_lex_scan_status",
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
		if row.attached_to_doctype == "LPO Job":
			job = jobs_by_name.get(row.attached_to_name)
			row.linked_record_title = (job.get("job_title") if job else None) or _("Work item")
			row.linked_record_type = _("Job")
			row.linked_matter_title = matter_titles.get(job.get("engagement")) if job else None
		elif row.attached_to_doctype == "Lexocrates Work Intake":
			intake = intakes_by_name.get(row.attached_to_name)
			job = jobs_by_name.get(intake.get("job")) if intake else None
			row.linked_record_title = (
				(job.get("job_title") if job else None)
				or (intake.get("intake_title") if intake else None)
				or _("Work item")
			)
			row.linked_record_type = _("Job") if job else _("Work intake")
			row.linked_matter_title = matter_titles.get(
				(job.get("engagement") if job else intake.get("matter") if intake else None)
			)
		# Attachment IDs are used only while this server function builds the
		# authorized document response. Do not expose Matter, Job or Intake IDs
		# in the client portal payload.
		row.pop("attached_to_name", None)
		row.pop("attached_to_doctype", None)
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
	if can_approve_deliverables():
		items.append({"label": "Approvals", "section": "approvals", "icon": "check"})
	if portal_user.report_access not in {None, "", "None"}:
		items.append({"label": "Reports", "section": "reports", "icon": "chart"})
	items.append({"label": "Messages", "section": "messages", "icon": "message"})
	if portal_user.billing_access:
		items.append({"label": "Billing", "section": "billing", "icon": "invoice"})
	if portal_user.lexpack_view_access:
		items.append({"label": "LexPack", "section": "wallet", "icon": "wallet"})
	if portal_user.user_management_authority:
		items.append({"label": "Team & Access", "section": "users", "icon": "users"})
		items.append({"label": "Organization", "section": "organization", "icon": "settings"})
	items.append({"label": "Support", "href": "mailto:support@lexocrates.com", "icon": "help"})
	return items


def _assignment_confirmations(jobs, matter_titles, job_titles):
	job_names = [row.name for row in jobs if row.get("name")]
	if not job_names or not frappe.db.exists("DocType", "LPO Assignment Confirmation"):
		return []
	rows = frappe.get_all(
		"LPO Assignment Confirmation",
		filters={"job": ["in", job_names]},
		fields=[
			"name", "job", "matter", "service", "jurisdiction", "confirmation_version",
			"scope_summary", "document_volume", "deliverables_summary", "assumptions",
			"exclusions", "client_requested_date", "confirmed_delivery_date", "service_level",
			"indicative_turnaround_snapshot", "fixed_quote", "currency", "lexpack_capacity_deduction",
			"issued_date", "superseded_by", "client_decision", "approved_on", "change_request_notes",
		],
		order_by="issued_date desc",
		limit_page_length=100,
	)
	visible = []
	can_approve = can_approve_deliverables()
	for row in rows:
		if row.get("superseded_by"):
			continue
		row.matter_title = matter_titles.get(row.matter) or _("Matter")
		row.job_title = job_titles.get(row.job) or _("Assignment")
		row.can_decide = bool(can_approve and has_matter_access(row.matter, "approve"))
		visible.append(row)
	return visible


def _scope_changes(jobs, matter_titles, job_titles):
	job_names = [row.name for row in jobs if row.get("name")]
	if not job_names or not frappe.db.exists("DocType", "LPO Assignment Scope Change"):
		return []
	rows = frappe.get_all(
		"LPO Assignment Scope Change",
		filters={"job": ["in", job_names]},
		fields=[
			"name", "job", "matter", "status", "requested_on", "original_scope",
			"requested_change", "reason", "additional_price", "additional_lexpack_deduction",
			"currency", "existing_delivery_date", "revised_delivery_date",
			"client_approval", "client_approved_on", "rejection_reason",
		],
		order_by="requested_on desc",
		limit_page_length=100,
	)
	for row in rows:
		row.matter_title = matter_titles.get(row.matter) or _("Matter")
		row.job_title = job_titles.get(row.job) or _("Assignment")
		row.can_approve = bool(has_matter_access(row.matter, "scope_change"))
	return rows


def _correction_requests(jobs, matter_titles, job_titles):
	job_names = [row.name for row in jobs if row.get("name")]
	if not job_names or not frappe.db.exists("DocType", "LPO Correction Request"):
		return []
	rows = frappe.get_all(
		"LPO Correction Request",
		filters={"job": ["in", job_names]},
		fields=[
			"name", "job", "matter", "correction_request_date", "status",
			"issue_description", "within_original_scope", "verified_lexocrates_error",
			"correction_cost", "currency", "routed_to_scope_change", "resolution_notes",
		],
		order_by="correction_request_date desc",
		limit_page_length=100,
	)
	for row in rows:
		row.matter_title = matter_titles.get(row.matter) or _("Matter")
		row.job_title = job_titles.get(row.job) or _("Assignment")
	return rows


def _upcoming_deadlines(matters, jobs, intakes):
	items = []
	for job in jobs:
		if job.job_status in {"Completed", "Cancelled"}:
			continue
		target = job.get("confirmed_delivery_date") or job.get("delivery_due_on") or job.get("due_date")
		if target:
			items.append({
				"kind": "Confirmed Delivery" if job.get("confirmed_delivery_date") else "Target Delivery",
				"title": job.job_title,
				"subtitle": job.matter_title,
				"date": str(target),
				"status": "SLA Paused" if job.get("sla_paused") else job.job_status,
				"priority": job.priority,
				"job": job.name,
				"matter": job.engagement,
			})
	for matter in matters:
		if matter.status in {"Completed", "Closed"} or not matter.get("end_date"):
			continue
		items.append({
			"kind": "Matter Milestone",
			"title": matter.matter_title,
			"subtitle": matter.practice_area or _("Legal Matter"),
			"date": str(matter.end_date),
			"status": matter.status,
			"priority": "Medium",
			"matter": matter.name,
		})
	for intake in intakes:
		if intake.get("status") in {"Quote Ready", "Funding Pending"} and intake.get("quote_valid_until"):
			items.append({
				"kind": "Quote Expiry",
				"title": intake.get("intake_title"),
				"subtitle": intake.get("matter_title") or _("Pending Quote"),
				"date": str(intake.get("quote_valid_until")),
				"status": intake.get("status"),
				"priority": intake.get("priority") or "Medium",
				"intake": intake.get("name"),
			})
	items.sort(key=lambda row: str(row.get("date") or ""))
	return items[:25]


@frappe.whitelist()
def create_matter(
	practice_area: str,
	jurisdictions: str,
	description: str,
	engagement_title: str | None = None,
	matter_title: str | None = None,
	billing_method: str = "Quoted Price",
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
def delete_matter(matter: str):
	"""Soft-delete an empty client Matter after all of its Jobs are cancelled."""
	portal_user = _require_portal_user()
	if not portal_user.can_create_matters:
		frappe.throw(_("You are not authorized to delete Matters."), frappe.PermissionError)
	doc = frappe.get_doc("LPO Matter", matter)
	if doc.customer != portal_user.client or not has_matter_access(doc.name, "view"):
		frappe.throw(_("You cannot access this Matter."), frappe.PermissionError)
	frappe.db.sql("select name from `tabLPO Matter` where name=%s for update", doc.name)
	doc.reload()
	if doc.client_deleted:
		return {"name": doc.name, "deleted": True, "duplicate": True}
	if not _matter_can_client_delete(doc.name):
		frappe.throw(
			_("Delete or cancel every unpaid Job in this Matter before deleting the Matter. Paid, funded, active or completed Jobs cannot be removed from the Client Portal."),
			frappe.PermissionError,
		)
	previous = {"status": doc.status, "client_deleted": False}
	doc.status = "Closed"
	doc.client_deleted = 1
	doc.client_deleted_on = now_datetime()
	doc.client_deleted_by = frappe.session.user
	previous_flag = getattr(frappe.flags, "lexocrates_portal_service", False)
	frappe.flags.lexocrates_portal_service = True
	try:
		doc.save(ignore_permissions=True)
	finally:
		frappe.flags.lexocrates_portal_service = previous_flag
	create_portal_audit_event(
		client=portal_user.client,
		portal_user=portal_user.name,
		matter=doc.name,
		action="Client Matter Soft Deleted",
		object_type="LPO Matter",
		object_id=doc.name,
		previous_value=previous,
		new_value={"status": "Closed", "client_deleted": True, "record_retained": True},
		details="Client removed an empty Matter from the Client Portal; the internal record was retained.",
	)
	return {"name": doc.name, "deleted": True, "duplicate": False}


def _matter_can_client_delete(matter: str) -> bool:
	return not (
		frappe.db.exists("LPO Job", {"engagement": matter, "job_status": ["!=", "Cancelled"]})
		or frappe.db.exists("Lexocrates Work Intake", {"matter": matter, "status": ["!=", "Cancelled"]})
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
	if (
		job_doc.job_status != "Ready for Delivery"
		or not can_approve_deliverables()
		or not has_matter_access(job_doc.engagement, "approve")
	):
		frappe.throw(_("This deliverable is not available for your approval."), frappe.PermissionError)
	job_doc.client_approval_status = decision
	job_doc.client_approved_by = frappe.session.user
	job_doc.client_approved_on = now_datetime()
	job_doc.client_approval_notes = (notes or "").strip()
	job_doc.delivery_receipt_status = "Acknowledged" if decision == "Approved" else "Rejected"
	job_doc.delivery_acknowledged_by = frappe.session.user
	job_doc.delivery_acknowledged_on = now_datetime()
	job_doc.job_status = "Completed" if decision == "Approved" else "In Progress"
	if decision == "Changes Requested":
		# A rejected artifact cannot satisfy the next delivery/QA cycle.
		job_doc.delivery_document = None
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
		_hidden_intakes, _hidden_jobs, hidden_matters = _hidden_client_records(portal_user.client)
		rows = frappe.get_list(
			"LPO Matter", fields=["name", "matter_title", "practice_area", "status", "end_date"],
			order_by="modified desc", limit_page_length=500,
		)
		rows = [row for row in rows if row.name not in hidden_matters]
		for row in rows:
			row.pop("name", None)
		columns = ["matter_title", "practice_area", "status", "end_date"]
	elif report_name == "Financial Summary":
		rows = _invoices(portal_user.client)
		columns = ["posting_date", "due_date", "status", "currency", "grand_total", "outstanding_amount"]
	else:
		hidden_intakes, hidden_jobs, hidden_matters = _hidden_client_records(portal_user.client)
		hidden_audit_objects = hidden_intakes | hidden_jobs | hidden_matters
		rows = frappe.get_all(
			"Lexocrates Portal Audit Event", filters={"client": portal_user.client},
			fields=["event_timestamp", "action", "result", "object_type", "object_id", "user"],
			order_by="event_timestamp desc", limit_page_length=1000,
		)
		rows = [row for row in rows if row.object_id not in hidden_audit_objects][:500]
		for row in rows:
			row.pop("object_id", None)
		columns = ["event_timestamp", "action", "result", "object_type", "user"]
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


def _hidden_client_records(client: str):
	"""Return retained cancellations that must not surface in the Client Portal."""
	rows = frappe.get_all(
		"Lexocrates Work Intake",
		filters={"client": client, "status": "Cancelled"},
		fields=["name", "job"],
		limit_page_length=1000,
	)
	matters = set(frappe.get_all(
		"LPO Matter", filters={"customer": client, "client_deleted": 1}, pluck="name", limit_page_length=1000,
	))
	return {row.name for row in rows}, {row.job for row in rows if row.job}, matters


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
