import re

import frappe
from frappe import _
from frappe.utils import cstr, strip_html

MAX_MESSAGES = 200
SNIPPET_LENGTH = 4000

FIELDS = [
	"name",
	"subject",
	"sender",
	"sender_full_name",
	"recipients",
	"cc",
	"communication_date",
	"creation",
	"sent_or_received",
	"reference_doctype",
	"reference_name",
	"has_attachment",
	"text_content",
	"content",
]


def _extract_addresses(value):
	addresses = []
	for part in cstr(value).split(","):
		part = part.strip()
		if not part:
			continue
		match = re.search(r"<([^>]+)>", part)
		email = (match.group(1) if match else part).strip().strip('"').lower()
		if email:
			addresses.append(email)
	return addresses


QUOTE_LINE_RE = re.compile(r"^>")
QUOTE_HEADER_RE = re.compile(r"^on .{3,80} wrote:\s*$", re.IGNORECASE)
ORIGINAL_MESSAGE_RE = re.compile(r"^-{2,}\s*original message\s*-{2,}$", re.IGNORECASE)


def _strip_quoted_chain(text):
	"""Cut a message body off at the start of its quoted-reply chain.

	Every earlier message in the chain already appears as its own bubble in
	the merged history (see get_conversation_history), so re-including the
	quoted copy inside each later message's snippet just repeats the same
	text over and over -- and for a long thread, dumps the entire history as
	one unstyled wall of ">" lines into what's meant to be a short preview.
	"""
	lines = text.splitlines()
	cut = len(lines)
	for i, line in enumerate(lines):
		stripped = line.strip()
		if QUOTE_LINE_RE.match(stripped) or QUOTE_HEADER_RE.match(stripped) or ORIGINAL_MESSAGE_RE.match(stripped):
			cut = i
			break
	trimmed = "\n".join(lines[:cut]).strip()
	# A message that's nothing but a forwarded/quoted body (no new text above
	# the quote) would otherwise end up as an empty bubble -- show the
	# untrimmed text in that case rather than losing the message entirely.
	return trimmed or text.strip()


def _snippet(row):
	text = row.get("text_content") or strip_html(row.get("content") or "")
	text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
	text = _strip_quoted_chain(text)
	return text[:SNIPPET_LENGTH]


@frappe.whitelist()
def get_conversation_history(communication):
	"""Return every email exchanged either on the same linked record or with
	the same counterpart address as `communication`, merged into one
	chronological conversation -- the "combined" view, since a single email
	can be both part of a linked record's thread and part of a longer
	back-and-forth with that address that predates/outlives the record link.
	"""
	doc = frappe.get_doc("Communication", communication)
	try:
		allowed = frappe.has_permission("Communication", ptype="read", doc=doc)
	except frappe.DoesNotExistError:
		# Communication.has_permission (see communication.py) re-checks permission
		# against the *linked* record (doc.reference_doctype/doc.reference_name)
		# by loading it via frappe.get_doc -- which raises DoesNotExistError for
		# an email whose linked Lead/Opportunity/etc. has since been deleted,
		# even though the email itself still exists and the user can see it.
		# Treat that as "no extra link to check", not as a hard failure.
		frappe.clear_last_message()
		allowed = True
	if not allowed:
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if doc.communication_type != "Communication" or doc.communication_medium != "Email":
		return {"messages": [], "counterpart": None}

	if doc.sent_or_received == "Sent":
		counterpart_candidates = _extract_addresses(doc.recipients) + _extract_addresses(doc.cc)
	else:
		counterpart_candidates = _extract_addresses(doc.sender)
	counterpart = counterpart_candidates[0] if counterpart_candidates else None

	base_filters = {"communication_type": "Communication", "communication_medium": "Email"}
	by_name = {}

	if doc.reference_doctype and doc.reference_name:
		for row in frappe.get_all(
			"Communication",
			filters={
				**base_filters,
				"reference_doctype": doc.reference_doctype,
				"reference_name": doc.reference_name,
			},
			fields=FIELDS,
			order_by="communication_date asc",
			limit_page_length=MAX_MESSAGES,
		):
			by_name[row.name] = row

	if counterpart:
		for row in frappe.get_all(
			"Communication",
			filters=base_filters,
			or_filters=[
				["sender", "=", counterpart],
				["recipients", "like", f"%{counterpart}%"],
				["cc", "like", f"%{counterpart}%"],
			],
			fields=FIELDS,
			order_by="communication_date asc",
			limit_page_length=MAX_MESSAGES,
		):
			by_name[row.name] = row

	by_name[doc.name] = doc.as_dict()

	messages = sorted(by_name.values(), key=lambda row: row.get("communication_date") or row.get("creation") or "")
	messages = messages[-MAX_MESSAGES:]

	result = []
	for row in messages:
		result.append(
			{
				"name": row.get("name"),
				"subject": row.get("subject"),
				"sender": row.get("sender"),
				"sender_full_name": row.get("sender_full_name"),
				"recipients": row.get("recipients"),
				"cc": row.get("cc"),
				"communication_date": row.get("communication_date") or row.get("creation"),
				"sent_or_received": row.get("sent_or_received"),
				"reference_doctype": row.get("reference_doctype"),
				"reference_name": row.get("reference_name"),
				"has_attachment": row.get("has_attachment"),
				"snippet": _snippet(row),
				"is_current": row.get("name") == doc.name,
			}
		)

	return {"messages": result, "counterpart": counterpart}
