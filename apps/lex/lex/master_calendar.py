"""Permission-aware data source for the internal Matter & Job Master Calendar."""

from __future__ import annotations

from collections import Counter

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate


INTERNAL_ROLES = {
	"System Manager", "LPO_Admin", "LPO_Manager", "LPO_Analyst",
	"Lexocrates Operations Manager", "Junior Legal Associate", "Senior Legal Associate",
	"Lexocrates QA Manager", "Lexocrates Compliance Officer", "Lexocrates Director",
}


def _require_calendar_access():
	if frappe.session.user == "Administrator":
		return
	if not set(frappe.get_roles()).intersection(INTERNAL_ROLES):
		frappe.throw(_("Internal legal-operations access is required for the Master Calendar."), frappe.PermissionError)


def _within(value, start, end):
	if not value:
		return False
	date = getdate(value)
	return getdate(start) <= date <= getdate(end)


def _alert_state(value, control_status=None):
	date = getdate(value)
	today = getdate(nowdate())
	if control_status == "At Risk" or date < today:
		return "overdue"
	if date <= getdate(add_days(today, 7)):
		return "due_soon"
	return "scheduled"


def _event(*, key, date, kind, title, matter=None, matter_title=None, job=None, job_title=None, service=None, status=None, control=None):
	return {
		"key": key, "date": str(getdate(date)), "kind": kind, "title": title,
		"matter": matter, "matter_title": matter_title or matter, "job": job,
		"job_title": job_title or job, "service": service, "status": status,
		"control": control, "alert": _alert_state(date, status),
	}


@frappe.whitelist()
def get_master_calendar(start: str, end: str, service: str | None = None, status: str | None = None):
	"""Return Matter, Job and independently verified SOP-control dates.

	The Job list query applies standard Frappe permission conditions before child
	control rows are read, preventing the calendar from becoming a data leak.
	"""
	_require_calendar_access()
	if not start or not end or getdate(start) > getdate(end):
		frappe.throw(_("Choose a valid calendar start and end date."), frappe.ValidationError)
	job_filters = {"job_status": ["not in", ["Cancelled"]]}
	if service:
		job_filters["job_type"] = service
	jobs = frappe.get_list(
		"LPO Job", filters=job_filters,
		fields=["name", "job_title", "engagement", "job_type", "job_status", "confirmed_delivery_date", "delivery_due_on"],
		limit_page_length=5000,
	)
	job_by_name = {job.name: job for job in jobs}
	matter_names = sorted({job.engagement for job in jobs if job.engagement})
	matters = frappe.get_list(
		"LPO Matter", filters={"name": ["in", matter_names]} if matter_names else {"name": ["in", [""]]},
		fields=["name", "matter_title", "status", "start_date", "end_date"], limit_page_length=5000,
	)
	matter_by_name = {matter.name: matter for matter in matters}
	events = []

	for matter in matters:
		if status and matter.status != status:
			continue
		for field, label in (("start_date", "Matter start"), ("end_date", "Matter milestone")):
			if _within(matter.get(field), start, end):
				events.append(_event(
					key=f"matter:{matter.name}:{field}", date=matter.get(field), kind="Matter",
					title=f"{label}: {matter.matter_title}", matter=matter.name,
					matter_title=matter.matter_title, status=matter.status,
				))

	for job in jobs:
		if status and job.job_status != status:
			continue
		matter = matter_by_name.get(job.engagement) or {}
		for field, label in (("confirmed_delivery_date", "Confirmed delivery"), ("delivery_due_on", "Delivery due")):
			if _within(job.get(field), start, end):
				events.append(_event(
					key=f"job:{job.name}:{field}", date=job.get(field), kind="Job", title=f"{label}: {job.job_title}",
					matter=job.engagement, matter_title=matter.get("matter_title"), job=job.name, job_title=job.job_title,
					service=job.job_type, status=job.job_status,
				))

	if job_by_name:
		controls = frappe.get_all(
			"LPO SOP Control Entry",
			filters={"parenttype": "LPO Job", "parent": ["in", list(job_by_name)], "event_date": ["between", [start, end]]},
			fields=["name", "parent", "control_type", "control_detail", "event_date", "status"],
			order_by="event_date asc",
		)
		for control in controls:
			job = job_by_name[control.parent]
			if status and job.job_status != status:
				continue
			matter = matter_by_name.get(job.engagement) or {}
			events.append(_event(
				key=f"control:{control.name}", date=control.event_date, kind="SOP Control",
				title=f"{control.control_type}: {job.job_title}", matter=job.engagement,
				matter_title=matter.get("matter_title"), job=job.name, job_title=job.job_title,
				service=job.job_type, status=control.status, control=control.control_detail,
			))

	events.sort(key=lambda event: (event["date"], event["title"]))
	alert_counts = Counter(event["alert"] for event in events)
	return {
		"events": events,
		"summary": {
			"overdue": alert_counts["overdue"], "due_soon": alert_counts["due_soon"],
			"scheduled": alert_counts["scheduled"], "matters": len(matter_by_name), "jobs": len(job_by_name),
		},
		"services": sorted({job.job_type for job in jobs if job.job_type}),
	}
