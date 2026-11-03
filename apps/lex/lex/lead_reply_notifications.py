"""Alert sales when a Lead replies to an email.

Hooked after lex.email_reply_handler.link_incoming_reply on Communication
after_insert, so campaign-dispatch replies are already threaded to their
Lead by the time this runs. Reads the Communication back from the database
rather than trusting the in-memory `doc`, since that threading is written
with frappe.db.set_value and never touches the in-memory object.
"""

from __future__ import annotations

import frappe
from frappe import _

from lex.mattermost_notifications import notify

SALES_ROLES = ("Sales Manager", "Sales User")


def notify_sales_of_lead_reply(doc, method=None):
	if doc.sent_or_received != "Received":
		return
	row = frappe.db.get_value(
		"Communication",
		doc.name,
		["reference_doctype", "reference_name"],
		as_dict=True,
	)
	if not row or row.reference_doctype != "Lead" or not row.reference_name:
		return

	lead_label = frappe.db.get_value("Lead", row.reference_name, "lead_name") or row.reference_name
	subject = _("{0} replied to your email").format(lead_label)
	for user in _sales_recipients():
		notify(
			for_user=user,
			subject=subject,
			document_type="Lead",
			document_name=row.reference_name,
		)


def _sales_recipients() -> list[str]:
	users = frappe.get_all(
		"Has Role",
		filters={"role": ["in", SALES_ROLES], "parenttype": "User"},
		pluck="parent",
	)
	recipients = []
	for user in set(users):
		values = frappe.db.get_value("User", user, ["enabled", "email", "user_type"], as_dict=True)
		if values and values.enabled and values.email and values.user_type == "System User":
			recipients.append(values.email)
	return sorted(set(recipients))
