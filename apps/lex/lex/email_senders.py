"""Shared outgoing-sender policy for Lexocrates-branded transactional email.

Routing: auth/account emails (login links, registration, invitations) go out
as Support; matter and payment client emails (quotes, pilot approval,
deliverable-ready, signed SLA copies) go out as Sales. If the category
account can't actually hand the message to SMTP (expired app password,
Gmail block, etc.) it is retried once through Info, which also doubles as
Frappe's own default-outgoing account for anything else in the system that
sends without naming a sender at all.
"""

from __future__ import annotations

import frappe

SUPPORT_SENDER = "Lexocrates <support@lexocrates.com>"
SALES_SENDER = "Lexocrates <sales@lexocrates.com>"
INFO_SENDER = "Lexocrates <info@lexocrates.com>"


def outgoing_email_is_ready() -> bool:
	return bool(
		frappe.db.exists(
			"Email Account",
			{"enable_outgoing": 1, "default_outgoing": 1},
		)
	)


def send_with_fallback(sender: str, **kwargs) -> None:
	"""frappe.sendmail(), retried once via INFO_SENDER if the requested
	category account can't actually send. Callers keep their own try/except
	for the case where even the Info retry fails."""
	try:
		frappe.sendmail(sender=sender, **kwargs)
	except Exception:
		if sender == INFO_SENDER:
			raise
		frappe.log_error(
			title="Outgoing email failed, retrying via info@",
			message=f"sender={sender}\n{frappe.get_traceback()}",
		)
		frappe.sendmail(sender=INFO_SENDER, **kwargs)
