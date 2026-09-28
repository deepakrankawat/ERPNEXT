"""SLA clock engine: business-day math, SLA start gating, pause/resume, and
the scheduled jobs that watch delivery deadlines.

This module is the one genuinely new "brain" behind the Master SLA / Assignment
SLA Management feature. Everything it touches on `LPO Job` is otherwise governed
by the existing conflict-check, QA and workflow/SOP gates already in the app.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_datetime, get_weekday, now_datetime

from lex.portal_audit import create_portal_audit_event
from lex.work_intake import _portal_service_writes


MANAGEMENT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager"}


def _has_management_access(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)).intersection(MANAGEMENT_ROLES))


def _settings():
	return frappe.get_single("Lexocrates SLA Settings")


def _holiday_dates(holiday_list: str | None) -> set:
	if not holiday_list:
		return set()
	rows = frappe.get_all(
		"Holiday",
		filters={"parent": holiday_list, "parenttype": "Holiday List"},
		pluck="holiday_date",
	)
	return {get_datetime(row).date() for row in rows}


def is_business_day(date, holiday_list: str | None = None) -> bool:
	date = get_datetime(date).date()
	if get_weekday(date) in ("Saturday", "Sunday"):
		return False
	return date not in _holiday_dates(holiday_list)


def add_business_days(start, n: int, holiday_list: str | None = None):
	"""Walk `start` forward `n` business days, skipping weekends and Holiday List dates."""
	if holiday_list is None:
		holiday_list = _settings().get("default_holiday_list")
	current = get_datetime(start)
	remaining = cint(n)
	while remaining > 0:
		current = add_days(current, 1)
		if is_business_day(current, holiday_list):
			remaining -= 1
	return current


def next_business_day(start, holiday_list: str | None = None):
	if holiday_list is None:
		holiday_list = _settings().get("default_holiday_list")
	current = get_datetime(start)
	while not is_business_day(current, holiday_list):
		current = add_days(current, 1)
	return current


# ---------------------------------------------------------------------------
# SLA start gate — spec section 9: 8 conditions must all hold before the SLA
# clock (and "Work Commenced" status) may begin.
# ---------------------------------------------------------------------------

def _documents_clean(job) -> bool:
	if not job.job_documents:
		return bool(job.source_document)
	return all((row.scan_status or "Pending") == "Clean" for row in job.job_documents)


def _conflict_cleared(matter: str) -> bool:
	status = frappe.db.get_value("LPO Matter", matter, "conflict_check_status")
	return status in {"Cleared", "No Match Found"}


def _confirmation_approved(confirmation_name: str) -> bool:
	return frappe.db.get_value("LPO Assignment Confirmation", confirmation_name, "client_decision") == "Approved"


def sla_start_checklist(job) -> dict:
	"""Return each of spec section 9's 8 conditions and whether it currently holds."""
	return {
		"assignment_submitted": job.job_status != "Draft",
		"documents_received_and_clean": _documents_clean(job),
		"conflict_check_completed": _conflict_cleared(job.engagement),
		"scope_and_capacity_review_completed": bool(job.workflow_version_snapshot and job.sop_version_snapshot),
		"quote_or_lexpack_confirmed": job.estimate_status == "Accepted" and job.funding_status == "Funded",
		"confirmed_delivery_date_communicated": bool(job.confirmed_delivery_date),
		"assignment_confirmation_approved": bool(
			job.assignment_confirmation and _confirmation_approved(job.assignment_confirmation)
		),
	}


def try_start_sla(job) -> bool:
	"""Start the SLA clock if, and only if, every spec-section-9 condition holds.

	Safe to call speculatively (e.g. right after Assignment Confirmation approval)
	— it is a no-op and returns False if any condition is not yet satisfied.
	"""
	if job.job_status == "Work Commenced" or job.sla_start_on:
		return True
	checklist = sla_start_checklist(job)
	if not all(checklist.values()):
		return False

	start = now_datetime()
	with _portal_service_writes():
		job.reload()
		job.work_commencement_on = start
		job.sla_start_on = start
		job.job_status = "Work Commenced"
		job.save(ignore_permissions=True)

	create_portal_audit_event(
		client=job.customer,
		user=frappe.session.user,
		matter=job.engagement,
		action="SLA Started",
		object_type="LPO Job",
		object_id=job.name,
		new_value={"sla_start_on": str(start), "confirmed_delivery_date": str(job.confirmed_delivery_date)},
	)
	return True


def retry_pending_sla_starts():
	"""Hourly: self-heal Jobs left Confirmed (e.g. governance snapshots attached
	after funding) by re-running the start gate on a fresh document per Job —
	never inside another Job's own save(), to avoid nested-save recursion."""
	names = frappe.get_all(
		"LPO Job",
		filters={"job_status": "Confirmed", "sla_start_on": ["is", "not set"]},
		pluck="name",
	)
	for name in names:
		try:
			try_start_sla(frappe.get_doc("LPO Job", name))
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"SLA retry start {name}")


def elapsed_sla_minutes(job) -> int:
	if not job.sla_start_on:
		return 0
	end = get_datetime(job.completed_on) if job.completed_on else now_datetime()
	total = (end - get_datetime(job.sla_start_on)).total_seconds() / 60
	return max(0, int(total) - cint(job.total_paused_minutes))


# ---------------------------------------------------------------------------
# Pause / Resume
# ---------------------------------------------------------------------------

PAUSE_REASONS = {
	"Missing Documents", "Clarification of Instructions", "Confirmation of Facts",
	"Additional Information Required", "Client Approval Required", "Jurisdictional Clarification",
	"Access Credentials Required", "Response to Substantive Query", "Other Client Dependency",
}


@frappe.whitelist()
def pause_sla(job: str, reason: str, details: str | None = None, requested_from_client: int = 1):
	if not _has_management_access():
		frappe.throw(_("Only Legal Operations may pause the SLA clock."), frappe.PermissionError)
	if reason not in PAUSE_REASONS:
		frappe.throw(_("Choose a valid pause reason."), frappe.ValidationError)
	job_doc = frappe.get_doc("LPO Job", job)
	if job_doc.job_status not in {"In Progress", "QA Review"}:
		frappe.throw(_("The SLA clock can only be paused while work is in progress."), frappe.ValidationError)
	if job_doc.sla_paused:
		frappe.throw(_("The SLA clock is already paused."), frappe.ValidationError)

	previous_status = job_doc.job_status
	job_doc.append("sla_pause_log", {
		"pause_start": now_datetime(),
		"reason": reason,
		"details": details,
		"requested_from_client": cint(requested_from_client),
		"created_by": frappe.session.user,
	})
	job_doc.sla_paused = 1
	job_doc.set("job_status_before_pause", previous_status)
	job_doc.job_status = "SLA Paused"
	job_doc.save(ignore_permissions=True)

	create_portal_audit_event(
		client=job_doc.customer,
		user=frappe.session.user,
		matter=job_doc.engagement,
		action="SLA Paused",
		object_type="LPO Job",
		object_id=job_doc.name,
		new_value={"reason": reason, "details": details},
	)
	return {"job": job_doc.name, "job_status": job_doc.job_status}


@frappe.whitelist()
def resume_sla(job: str):
	if not _has_management_access():
		frappe.throw(_("Only Legal Operations may resume the SLA clock."), frappe.PermissionError)
	job_doc = frappe.get_doc("LPO Job", job)
	if not job_doc.sla_paused or job_doc.job_status != "SLA Paused":
		frappe.throw(_("The SLA clock is not currently paused."), frappe.ValidationError)

	open_row = next((row for row in job_doc.sla_pause_log if not row.pause_end), None)
	if not open_row:
		frappe.throw(_("No open pause entry was found."), frappe.ValidationError)
	end = now_datetime()
	duration = max(0, int((get_datetime(end) - get_datetime(open_row.pause_start)).total_seconds() / 60))
	open_row.pause_end = end
	open_row.duration_minutes = duration
	job_doc.total_paused_minutes = cint(job_doc.total_paused_minutes) + duration
	job_doc.sla_paused = 0
	job_doc.job_status = job_doc.get("job_status_before_pause") or "In Progress"
	job_doc.save(ignore_permissions=True)

	create_portal_audit_event(
		client=job_doc.customer,
		user=frappe.session.user,
		matter=job_doc.engagement,
		action="SLA Resumed",
		object_type="LPO Job",
		object_id=job_doc.name,
		new_value={"duration_minutes": duration, "total_paused_minutes": job_doc.total_paused_minutes},
	)
	return {"job": job_doc.name, "job_status": job_doc.job_status, "paused_minutes": duration}


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------

def publish_assignment_sla_warnings():
	"""Hourly: flag Jobs approaching or past their Confirmed Delivery Date."""
	settings = _settings()
	threshold_hours = cint(settings.get("sla_warning_threshold_hours") or 24)
	jobs = frappe.get_all(
		"LPO Job",
		filters={
			"job_status": ["in", ["Work Commenced", "In Progress", "QA Review", "Ready for Delivery"]],
			"confirmed_delivery_date": ["is", "set"],
		},
		fields=["name", "confirmed_delivery_date", "customer", "engagement"],
	)
	now = now_datetime()
	for job in jobs:
		remaining_hours = (get_datetime(job.confirmed_delivery_date) - now).total_seconds() / 3600
		if remaining_hours <= 0:
			_notify_overdue(job)
		elif remaining_hours <= threshold_hours:
			create_portal_audit_event(
				client=job.customer,
				matter=job.engagement,
				action="Assignment Approaching Deadline",
				object_type="LPO Job",
				object_id=job.name,
				new_value={"hours_remaining": round(remaining_hours, 1)},
			)


def _notify_overdue(job):
	create_portal_audit_event(
		client=job.customer,
		matter=job.engagement,
		action="Assignment Overdue",
		object_type="LPO Job",
		object_id=job.name,
	)


def auto_escalate_overdue_assignments():
	"""Hourly: open a Level 1 Service Escalation for any Job past its Confirmed Delivery Date."""
	jobs = frappe.get_all(
		"LPO Job",
		filters={
			"job_status": ["in", ["Work Commenced", "In Progress", "SLA Paused", "QA Review"]],
			"confirmed_delivery_date": ["<", now_datetime()],
		},
		pluck="name",
	)
	from lex.lex.doctype.lpo_service_escalation.lpo_service_escalation import raise_escalation

	for job in jobs:
		if frappe.db.exists("LPO Service Escalation", {"job": job, "status": "Open"}):
			continue
		raise_escalation(
			job=job,
			escalation_level="1",
			escalation_reason=_("Assignment past its Confirmed Delivery Date."),
		)
