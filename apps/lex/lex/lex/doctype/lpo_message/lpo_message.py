from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import format_datetime, now_datetime, sanitize_html


class LPOMessage(Document):
	def before_insert(self):
		# Sender and time are authoritative server values; accepting either from the
		# browser would permit identity spoofing or back-dated legal instructions.
		self.sender = frappe.session.user
		self.timestamp = now_datetime()

	def validate(self):
		frappe.has_permission("LPO Channel", "read", doc=self.channel, throw=True)
		if frappe.db.get_value("LPO Channel", self.channel, "status") != "Active":
			frappe.throw(_("Messages cannot be added to an archived channel."))

		# Text Editor values are HTML. Persist only Frappe-sanitized markup so both
		# historical REST responses and realtime rendering remain XSS-safe.
		self.content = sanitize_html(
			self.content,
			linkify=True,
			always_sanitize=True,
			disallowed_tags=["form", "input", "button", "script", "style", "iframe"],
		)

	def before_save(self):
		if not self.is_new():
			raise frappe.PermissionError(
				"Legal operational messages represent an audit trail and cannot be edited or modified."
			)

	def after_insert(self):
		payload = serialize_message(self)
		# after_commit is essential: clients must not receive a message identifier
		# while the MariaDB transaction that created it can still roll back.
		frappe.publish_realtime(
			"new_lpo_message",
			payload,
			room=f"doc:LPO Channel/{self.channel}",
			after_commit=True,
		)

	def on_trash(self):
		raise frappe.PermissionError(
			"Legal operational messages represent an audit trail and cannot be deleted."
		)


def on_doctype_update():
	# History reads filter by channel and order by timestamp, so one composite
	# index covers the hot path as message volume grows.
	frappe.db.add_index(
		"LPO Message",
		["channel", "timestamp"],
		index_name="lpo_message_channel_timestamp",
	)


def serialize_message(message: Any, sender_full_name: str | None = None) -> dict:
	timestamp = message.get("timestamp")
	if sender_full_name is None:
		sender_full_name = frappe.db.get_value("User", message.get("sender"), "full_name")

	return {
		"name": message.get("name"),
		"channel": message.get("channel"),
		"sender": message.get("sender"),
		"sender_full_name": sender_full_name or message.get("sender"),
		"content": message.get("content"),
		"timestamp": str(timestamp),
		"formatted_timestamp": format_datetime(timestamp),
	}


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if ptype in {"write", "delete", "submit", "cancel", "share"}:
		return False
	if not doc.channel:
		return False
	return frappe.has_permission(
		"LPO Channel",
		"read",
		doc=doc.channel,
		user=user,
		debug=debug,
	)


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if user == "Administrator" or set(frappe.get_roles(user)).intersection({"LPO_Admin", "System Manager"}):
		return ""

	user = frappe.db.escape(user)
	return f"""
		exists (
			select 1
			from `tabLPO Channel Member` member
			where member.parent = `tabLPO Message`.channel
				and member.parenttype = 'LPO Channel'
				and member.user = {user}
		)
	"""
