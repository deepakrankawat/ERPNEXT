"""Internal chat notifications for the Master SLA / Assignment SLA feature.

Mirrors the existing convention in chat_automation.py: post a short, link-only
message into the Job's Matter Room — never the underlying matter content —
whenever an SLA-governed event happens.
"""

from __future__ import annotations

from html import escape

import frappe

from lex.chat_automation import _lpo_matter_channel, _run_safely
from lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message import create_system_message


def notify_confirmation_ready(doc, method=None):
	_run_safely("Assignment Confirmation ready notification", _notify_confirmation_ready, doc)


def _notify_confirmation_ready(doc):
	job = frappe.get_doc("LPO Job", doc.job)
	channel = _lpo_matter_channel(job)
	message = (
		f"<p><strong>Assignment Confirmation ready for approval:</strong> "
		f'<a href="/app/lpo-assignment-confirmation/{escape(doc.name)}">{escape(doc.name)}</a> '
		f'for <a href="/app/lpo-job/{escape(job.name)}">@{escape(job.name)}</a>. '
		f"Confirmed Delivery Date: <strong>{escape(str(doc.confirmed_delivery_date))}</strong>.</p>"
	)
	create_system_message(
		channel.name, message,
		source_doctype=doc.doctype, source_name=doc.name,
		automation_key=f"assignment-confirmation-ready:{doc.name}",
	)


def notify_confirmation_decision(doc, method=None):
	if doc.is_new() or not doc.has_value_changed("client_decision") or doc.client_decision == "Pending":
		return
	_run_safely("Assignment Confirmation decision notification", _notify_confirmation_decision, doc)


def _notify_confirmation_decision(doc):
	job = frappe.get_doc("LPO Job", doc.job)
	channel = _lpo_matter_channel(job)
	message = (
		f"<p><strong>Assignment Confirmation {escape(doc.client_decision)}:</strong> "
		f'<a href="/app/lpo-assignment-confirmation/{escape(doc.name)}">{escape(doc.name)}</a> '
		f'for <a href="/app/lpo-job/{escape(job.name)}">@{escape(job.name)}</a>.</p>'
	)
	create_system_message(
		channel.name, message,
		source_doctype=doc.doctype, source_name=doc.name,
		automation_key=f"assignment-confirmation-decision:{doc.name}:{doc.client_decision}",
	)


def notify_scope_change_proposed(doc, method=None):
	_run_safely("Scope Change proposed notification", _notify_scope_change_proposed, doc)


def _notify_scope_change_proposed(doc):
	job = frappe.get_doc("LPO Job", doc.job)
	channel = _lpo_matter_channel(job)
	message = (
		f"<p><strong>Scope Change proposed:</strong> "
		f'<a href="/app/lpo-assignment-scope-change/{escape(doc.name)}">{escape(doc.name)}</a> '
		f'for <a href="/app/lpo-job/{escape(job.name)}">@{escape(job.name)}</a>.</p>'
	)
	create_system_message(
		channel.name, message,
		source_doctype=doc.doctype, source_name=doc.name,
		automation_key=f"scope-change-proposed:{doc.name}",
	)


def notify_scope_change_decision(doc, method=None):
	if doc.is_new() or not doc.has_value_changed("status") or doc.status not in {"Approved", "Rejected"}:
		return
	_run_safely("Scope Change decision notification", _notify_scope_change_decision, doc)


def _notify_scope_change_decision(doc):
	job = frappe.get_doc("LPO Job", doc.job)
	channel = _lpo_matter_channel(job)
	message = (
		f"<p><strong>Scope Change {escape(doc.status)}:</strong> "
		f'<a href="/app/lpo-assignment-scope-change/{escape(doc.name)}">{escape(doc.name)}</a> '
		f'for <a href="/app/lpo-job/{escape(job.name)}">@{escape(job.name)}</a>.</p>'
	)
	create_system_message(
		channel.name, message,
		source_doctype=doc.doctype, source_name=doc.name,
		automation_key=f"scope-change-decision:{doc.name}:{doc.status}",
	)


def notify_correction_received(doc, method=None):
	_run_safely("Correction Request notification", _notify_correction_received, doc)


def _notify_correction_received(doc):
	job = frappe.get_doc("LPO Job", doc.job)
	channel = _lpo_matter_channel(job)
	message = (
		f"<p><strong>Correction Request received:</strong> "
		f'<a href="/app/lpo-correction-request/{escape(doc.name)}">{escape(doc.name)}</a> '
		f'for <a href="/app/lpo-job/{escape(job.name)}">@{escape(job.name)}</a>.</p>'
	)
	create_system_message(
		channel.name, message,
		source_doctype=doc.doctype, source_name=doc.name,
		automation_key=f"correction-request-received:{doc.name}",
	)


def notify_escalation_created(doc, method=None):
	_run_safely("Service Escalation notification", _notify_escalation_created, doc)


def _notify_escalation_created(doc):
	job = frappe.get_doc("LPO Job", doc.job)
	channel = _lpo_matter_channel(job)
	message = (
		f"<p><strong>Level {escape(str(doc.escalation_level))} Escalation raised:</strong> "
		f'<a href="/app/lpo-service-escalation/{escape(doc.name)}">{escape(doc.name)}</a> '
		f'for <a href="/app/lpo-job/{escape(job.name)}">@{escape(job.name)}</a> — '
		f"{escape(doc.escalation_reason or '')}</p>"
	)
	create_system_message(
		channel.name, message,
		source_doctype=doc.doctype, source_name=doc.name,
		automation_key=f"escalation-created:{doc.name}",
	)
