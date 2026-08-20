from __future__ import annotations

from html import escape

# pyrefly: ignore [missing-import]
import frappe
# pyrefly: ignore [missing-import]
from frappe.utils import get_datetime, now_datetime

from lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel import (
	ensure_contextual_channel,
)
from lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message import (
	create_system_message,
)
from lex.client_access import get_authorized_portal_users
from lex.lexocrates_chat_sync import ensure_matter_chat_channel


LPO_QA_FAILURE_STATUSES = {"Rejected", "Changes Required"}
LPO_OPEN_JOB_STATUSES = {
	"Draft",
	"Assigned",
	"In Progress",
	"On Hold",
	"QA Review",
	"Ready for Delivery",
}


def notify_lpo_job_created(doc, method=None):
	"""Publish the legacy/current LPO Job event used by the installed portal."""
	_run_safely("LPO Job chat notification", _notify_lpo_job_created, doc)


def _notify_lpo_job_created(doc):
	channel = _lpo_matter_channel(doc)
	message = (
		f"<p><strong>New LPO Job created:</strong> "
		f'<a href="/app/lpo-job/{escape(doc.name)}">@{escape(doc.name)}</a> — '
		f"{escape(doc.job_title or doc.name)}.</p>"
		f"<p>Due: <strong>{escape(str(doc.due_date or 'Not set'))}</strong>.</p>"
	)
	create_system_message(
		channel.name,
		message,
		source_doctype="LPO Job",
		source_name=doc.name,
		automation_key=f"lpo-job-created:{channel.name}:{doc.name}",
	)
	if doc.job_type == "Legal Research":
		_publish_to_named_channel(
			"#legal-research",
			message,
			source_doctype="LPO Job",
			source_name=doc.name,
			automation_event=f"lpo-legal-research-job:{doc.name}",
		)


def notify_lpo_job_updated(doc, method=None):
	"""Publish meaningful Job changes into its canonical Matter Room."""
	if doc.is_new() or getattr(doc.flags, "in_insert", False):
		return
	changed_fields = [
		field
		for field in ("job_title", "job_status", "priority", "assigned_analyst", "due_date")
		if doc.has_value_changed(field)
	]
	if not changed_fields:
		return
	_run_safely("LPO Job update chat notification", _notify_lpo_job_updated, doc)


def _notify_lpo_job_updated(doc):
	changed = []
	for field in ("job_title", "job_status", "priority", "assigned_analyst", "due_date"):
		if not doc.has_value_changed(field):
			continue
		label = frappe.get_meta("LPO Job").get_label(field) or field.replace("_", " ").title()
		changed.append(f"<strong>{escape(label)}:</strong> {escape(str(doc.get(field) or 'Not set'))}")
	channel = _lpo_matter_channel(doc)
	message = (
		f'<p><strong>Job updated:</strong> <a href="/app/lpo-job/{escape(doc.name)}">'
		f"@{escape(doc.name)}</a> — {escape(doc.job_title or doc.name)}.</p>"
		f"<p>{' · '.join(changed)}</p>"
	)
	create_system_message(
		channel.name,
		message,
		source_doctype="LPO Job",
		source_name=doc.name,
		automation_key=f"lpo-job-updated:{channel.name}:{doc.name}:{doc.modified}",
	)


def notify_qa_failure(doc, method=None):
	status = doc.get("review_status")
	if status not in LPO_QA_FAILURE_STATUSES:
		return
	if method == "on_update" and not doc.has_value_changed("review_status"):
		return
	_run_safely("QA failure chat notification", _notify_lpo_qa_failure, doc)


def _notify_lpo_qa_failure(doc):
	job = frappe.get_doc("LPO Job", doc.job)
	channel = _lpo_matter_channel(job)
	message = (
		f"<p><strong>QA action required:</strong> "
		f'<a href="/app/lpo-qa-review/{escape(doc.name)}">{escape(doc.name)}</a> '
		f"was marked <strong>{escape(doc.review_status)}</strong> for "
		f'<a href="/app/lpo-job/{escape(job.name)}">@{escape(job.name)}</a>.</p>'
	)
	create_system_message(
		channel.name,
		message,
		source_doctype="LPO QA Review",
		source_name=doc.name,
		automation_key=f"lpo-qa-failure-context:{doc.name}:{doc.review_status}:{channel.name}",
	)
	_publish_to_named_channel(
		"#qa-review",
		message,
		source_doctype="LPO QA Review",
		source_name=doc.name,
		automation_event=f"lpo-qa-failure-global:{doc.name}:{doc.review_status}",
	)
def notify_compliance_action(doc, method=None):
	_run_safely("Compliance chat notification", _notify_compliance_action, doc)


def _notify_compliance_action(doc):
	job_reference = (
		f' for <a href="/app/lpo-job/{escape(doc.job)}">@{escape(doc.job)}</a>'
		if doc.job
		else ""
	)
	message = (
		f"<p><strong>Compliance action logged:</strong> "
		f'<a href="/app/lpo-compliance-log/{escape(doc.name)}">{escape(doc.name)}</a> — '
		f"{escape(doc.compliance_type or doc.name)} ({escape(doc.severity or 'Medium')})"
		f"{job_reference}.</p>"
	)
	if doc.engagement:
		channel_name = ensure_matter_chat_channel(
			doc.engagement,
			[doc.owner, getattr(doc, "compliance_owner", None)],
		)
		create_system_message(
			channel_name,
			message,
			source_doctype="LPO Compliance Log",
			source_name=doc.name,
			automation_key=f"lpo-compliance-matter:{channel_name}:{doc.name}",
		)
	_publish_to_named_channel(
		"#compliance-alerts",
		message,
		source_doctype="LPO Compliance Log",
		source_name=doc.name,
		automation_event=f"lpo-compliance-action:{doc.name}",
	)


def notify_ai_job_request_created(doc, method=None):
	_run_safely("AI job request chat notification", _notify_ai_job_request_created, doc)


def _notify_ai_job_request_created(doc):
	members = filter(None, [doc.owner, getattr(doc, "reviewer", None)])
	channel = ensure_contextual_channel(doc.doctype, doc.name, list(members))
	message = (
		f"<p><strong>AI Execution created:</strong> "
		f'<a href="/app/{frappe.scrub(doc.doctype).replace("_", "-")}/{escape(doc.name)}">'
		f"{escape(doc.name)}</a>.</p>"
	)
	create_system_message(
		channel.name,
		message,
		source_doctype=doc.doctype,
		source_name=doc.name,
		automation_key=f"ai-job-created:{channel.name}:{doc.name}",
	)


def publish_sla_breaches():
	jobs = frappe.get_all(
		"LPO Job",
		filters={
			"job_status": ["in", sorted(LPO_OPEN_JOB_STATUSES)],
			"due_date": ["<", now_datetime()],
		},
		fields=["name", "job_title", "job_type", "engagement", "assigned_analyst", "due_date", "owner"],
		limit_page_length=500,
	)
	for job in jobs:
		_run_safely("LPO SLA breach chat notification", _publish_lpo_sla_breach, job)


def _publish_lpo_sla_breach(job):
	channel = _lpo_matter_channel(job)
	message = (
		f"<p><strong>SLA breach:</strong> "
		f'<a href="/app/lpo-job/{escape(job.name)}">@{escape(job.name)}</a> — '
		f"{escape(job.job_title or job.name)} passed its due time "
		f"({escape(str(get_datetime(job.due_date)))}) and remains open.</p>"
	)
	create_system_message(
		channel.name,
		message,
		source_doctype="LPO Job",
		source_name=job.name,
		automation_key=f"lpo-sla-breach:{channel.name}:{job.name}",
	)
	_publish_to_named_channel(
		"#compliance-alerts",
		message,
		source_doctype="LPO Job",
		source_name=job.name,
		automation_event=f"lpo-sla-breach-global:{job.name}",
	)


def _publish_to_named_channel(
	channel_name,
	message,
	*,
	source_doctype,
	source_name,
	automation_event,
):
	channel = frappe.db.get_value(
		"Lexocrates Chat Channel", {"channel_name": channel_name, "status": "Active"}, "name"
	)
	if not channel:
		return
	create_system_message(
		channel,
		message,
		source_doctype=source_doctype,
		source_name=source_name,
		automation_key=f"{automation_event}:{channel}",
	)


def _lpo_job_members(job) -> list[str]:
	matter_manager = None
	if job.engagement:
		matter_manager = frappe.db.get_value("LPO Matter", job.engagement, "matter_manager")
	portal_users = get_authorized_portal_users(job.engagement) if job.engagement else []
	return [
		user
		for user in dict.fromkeys(
			[job.owner, getattr(job, "assigned_analyst", None), matter_manager, *portal_users]
		)
		if user
	]


def _lpo_matter_channel(job):
	if not job.engagement:
		frappe.throw(f"LPO Job {job.name} is not linked to a Matter.")
	channel_name = ensure_matter_chat_channel(job.engagement, _lpo_job_members(job))
	return frappe.get_doc("Lexocrates Chat Channel", channel_name)


def _run_safely(title, handler, doc):
	try:
		handler(doc)
	except Exception:
		frappe.log_error(title=title, message=frappe.get_traceback())
