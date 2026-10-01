from __future__ import annotations

from email.utils import parseaddr

import frappe
from frappe.utils import now_datetime

DISPATCH_DOCTYPE = "Lexocrates Email Campaign Dispatch"


def link_incoming_reply(doc, method=None):
	"""Thread an inbound IMAP reply back to the campaign send it answers."""
	if doc.sent_or_received != "Received":
		return
	_process_reply(doc)


def backfill_missed_replies():
	"""Catch-up pass for inbound mail that arrived before this hook existed, or
	whose thread headers this hook's normal `in_reply_to` match couldn't
	resolve. Safe to re-run: matching only ever targets dispatches that aren't
	already marked `replied`, so an already-linked reply is never revisited."""
	names = frappe.get_all(
		"Communication",
		filters={"sent_or_received": "Received"},
		pluck="name",
		order_by="creation asc",
		limit_page_length=0,
	)
	linked = 0
	for name in names:
		if _process_reply(frappe.get_doc("Communication", name)):
			linked += 1
	if linked:
		frappe.db.commit()
	return linked


def _process_reply(doc) -> bool:
	if frappe.db.exists(DISPATCH_DOCTYPE, {"reply_communication": doc.name}):
		# Already claimed by another dispatch on a prior pass -- without this,
		# a re-run whose in_reply_to match now fails (its original target
		# dispatch already flipped to replied=1) would fall through to the
		# sender fallback and double-book the same physical reply.
		return False

	dispatch = _match_by_in_reply_to(doc) or _match_by_sender(doc)
	if not dispatch:
		return False

	lead = dispatch.lead or _find_lead_by_email(_clean_email(doc.sender))

	updates = {"replied": 1, "reply_communication": doc.name, "replied_on": now_datetime()}
	if lead and not dispatch.lead:
		updates["lead"] = lead
	frappe.db.set_value(DISPATCH_DOCTYPE, dispatch.name, updates)

	if lead:
		frappe.db.set_value(
			"Communication",
			doc.name,
			{"reference_doctype": "Lead", "reference_name": lead},
		)
	return True


def _match_by_in_reply_to(doc):
	"""Frappe's IMAP pull (frappe/email/receive.py) resolves `in_reply_to` to the
	*name* of the parent Communication before insert, when it can -- match that
	directly against the dispatch it was sent from."""
	if not doc.in_reply_to:
		return None
	return frappe.db.get_value(
		DISPATCH_DOCTYPE,
		{"communication": doc.in_reply_to, "replied": 0},
		["name", "lead"],
		as_dict=True,
	)


def _match_by_sender(doc):
	"""Fallback for when Gmail doesn't preserve In-Reply-To/References across
	the sender's mail client: the most recent un-replied dispatch we sent to
	this reply's sender address is almost certainly what it's answering."""
	sender_email = _clean_email(doc.sender)
	if not sender_email:
		return None
	rows = frappe.db.sql(
		"""
		select d.name, d.lead
		from `tabLexocrates Email Campaign Dispatch` d
		inner join `tabCommunication` c on c.name = d.communication
		where d.replied = 0 and c.recipients like %(pattern)s
		order by d.scheduled_for_utc desc
		limit 1
		""",
		{"pattern": f"%{sender_email}%"},
		as_dict=True,
	)
	return rows[0] if rows else None


def _find_lead_by_email(email: str | None):
	if not email:
		return None
	return frappe.db.get_value("Lead", {"email_id": email}, "name")


def _clean_email(value: str | None) -> str | None:
	if not value:
		return None
	return (parseaddr(value)[1] or "").strip().lower() or None
