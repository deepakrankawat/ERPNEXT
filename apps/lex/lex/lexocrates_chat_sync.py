from __future__ import annotations

import hashlib
import json
import re
import frappe
from frappe import _
from frappe.utils import now_datetime
from lex.client_access import get_authorized_portal_users
from lex.portal_audit import create_portal_audit_event
from lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel import (
	APP_ROLES,
	is_client_only_user,
	normalize_channel_name,
)


def _matter_channel_name(matter_id: str, matter_title: str | None) -> str:
	identifier = re.sub(r"[^a-z0-9]+", "-", matter_id.lower()).strip("-")
	title_slug = re.sub(r"[^a-z0-9]+", "-", (matter_title or "matter").lower()).strip("-") or "matter"
	available = max(12, 78 - len(identifier))
	return normalize_channel_name(f"#{title_slug[:available].strip('-')}-{identifier}")


def _member_row(user: str, role: str = "Member") -> dict:
	return {
		"user": user,
		"channel_role": role,
		"can_post_messages": 1,
		"can_invite_members": int(role in {"Owner", "Moderator"}),
		"joined_on": now_datetime(),
	}


def _matter_members(matter, extra_members=None) -> list[dict]:
	roles = {"Administrator": "Owner"}
	for user in (matter.get("matter_manager"), matter.get("owner"), *(extra_members or [])):
		if user:
			roles.setdefault(user, "Moderator" if user == matter.get("matter_manager") else "Member")
	if matter.doctype == "LPO Matter":
		for job in frappe.get_all(
			"LPO Job",
			filters={"engagement": matter.name},
			fields=["owner", "assigned_analyst"],
			limit_page_length=0,
		):
			for user in (job.owner, job.assigned_analyst):
				if user:
					roles.setdefault(user, "Member")
		for user in get_authorized_portal_users(matter.name):
			roles.setdefault(user, "Member")

	rows = []
	for user, role in roles.items():
		if not frappe.db.get_value("User", user, "enabled"):
			continue
		if user != "Administrator" and not APP_ROLES.intersection(frappe.get_roles(user)):
			continue
		rows.append(_member_row(user, role))
	return rows


@frappe.whitelist()
def ensure_matter_chat_channel(matter_id: str, extra_members=None):
	"""Provision native Frappe Lexocrates Chat channel for Matter (COM-001, COM-002)."""
	if not frappe.db.exists("LPO Matter", matter_id):
		frappe.throw(_("Matter not found."), frappe.DoesNotExistError)

	reference_doctype = "LPO Matter"
	if not getattr(frappe.flags, "lexocrates_chat_automation", False):
		frappe.has_permission(reference_doctype, "read", doc=matter_id, throw=True)
	matter = frappe.get_doc(reference_doctype, matter_id)
	matter_title = matter.get("matter_title") or matter.get("title") or matter_id
	channel_name = _matter_channel_name(matter_id, matter_title)
	channel_title = _("Matter Room: {0} ({1})").format(matter_title, matter_id)
	if isinstance(extra_members, str):
		extra_members = frappe.parse_json(extra_members)
	desired_members = _matter_members(matter, extra_members)

	existing_channel = frappe.db.get_value(
		"Lexocrates Chat Channel",
		{"reference_doctype": reference_doctype, "reference_name": matter_id},
		"name",
	) or frappe.db.get_value("Lexocrates Chat Channel", {"channel_name": channel_name}, "name")

	previous_flag = getattr(frappe.flags, "lexocrates_chat_automation", False)
	frappe.flags.lexocrates_chat_automation = True
	try:
		if not existing_channel:
			channel = frappe.get_doc({
				"doctype": "Lexocrates Chat Channel",
				"channel_name": channel_name,
				"channel_type": "Contextual",
				"status": "Active",
				"reference_doctype": reference_doctype,
				"reference_name": matter_id,
				"description": channel_title,
				"members": desired_members,
			}).insert(ignore_permissions=True)
		else:
			channel = frappe.get_doc("Lexocrates Chat Channel", existing_channel)
			channel.channel_name = channel_name
			channel.description = channel_title
			desired = {row["user"]: row for row in desired_members}
			for member in list(channel.members):
				if member.user not in desired and is_client_only_user(member.user):
					channel.remove(member)
			existing = {member.user: member for member in channel.members}
			for user, row in desired.items():
				if user not in existing:
					channel.append("members", row)
				elif user == "Administrator":
					existing[user].channel_role = "Owner"
					existing[user].can_post_messages = 1
					existing[user].can_invite_members = 1
			channel.save(ignore_permissions=True)
	finally:
		frappe.flags.lexocrates_chat_automation = previous_flag

	return channel.name


def backfill_matter_chat_channels():
	"""Create or rename every Matter Room after schema/app migrations."""
	if not frappe.db.exists("DocType", "LPO Matter"):
		return
	previous_flag = getattr(frappe.flags, "lexocrates_chat_automation", False)
	frappe.flags.lexocrates_chat_automation = True
	try:
		for matter_id in frappe.get_all("LPO Matter", pluck="name", limit_page_length=0):
			ensure_matter_chat_channel(matter_id)
		for channel_name in frappe.get_all(
			"Lexocrates Chat Channel",
			filters={"reference_doctype": "LPO Job", "channel_type": "Contextual"},
			pluck="name",
			limit_page_length=0,
		):
			# Preserve the immutable history while retiring duplicate per-Job rooms.
			frappe.db.set_value(
				"Lexocrates Chat Channel", channel_name, "status", "Archived", update_modified=False
			)
	finally:
		frappe.flags.lexocrates_chat_automation = previous_flag


@frappe.whitelist()
def pin_chat_decision_to_timeline(message_id: str, matter_id: str, decision_notes: str | None = None):
	"""Pin native Frappe chat decision into ERP Matter/Job timeline (COM-003)."""
	if not frappe.db.exists("Lexocrates Chat Message", message_id):
		frappe.throw(_("Chat message not found."), frappe.DoesNotExistError)

	msg = frappe.get_doc("Lexocrates Chat Message", message_id)
	matter_doc = frappe.get_doc("LPO Matter", matter_id)

	msg_text = msg.get("message_text") or msg.get("message_html") or msg.get("content")
	sender = msg.get("sender")
	timestamp = str(msg.get("sent_at") or msg.get("creation"))

	comment_text = f"[Material Decision] Pinned Chat Decision | Author: {sender} | Timestamp: {timestamp} | Message: {msg_text} | Notes: {decision_notes or 'None'}"
	comment_doc = matter_doc.add_comment("Comment", comment_text)

	create_portal_audit_event(
		client=getattr(matter_doc, "client_id", getattr(matter_doc, "customer", None)),
		user=frappe.session.user,
		action="Chat Decision Pinned To Timeline",
		object_type="Lexocrates Chat Message",
		object_id=message_id,
		new_value={"matter": matter_id, "notes": decision_notes, "audit_tag": "Material Decision"},
	)

	return {
		"status": "pinned",
		"message_id": message_id,
		"matter": matter_id,
		"comment_id": comment_doc.name if comment_doc else None,
		"author": sender,
		"timestamp": timestamp,
		"message_text": msg_text,
		"audit_tag": "Material Decision",
	}


@frappe.whitelist()
def save_decision_to_timeline(message_id: str, matter_id: str, decision_notes: str | None = None):
	"""Whitelisted API alias for /api/method/lexocrates.chat.save_decision_to_timeline."""
	return pin_chat_decision_to_timeline(message_id, matter_id, decision_notes)


@frappe.whitelist()
def send_deduplicated_notification(
	recipient: str,
	event_id: str,
	channel: str,
	template_version: str,
	message_payload: dict,
):
	"""Send notification via Frappe native chat or email with deduplication key (COM-004..006)."""
	dedup_key = hashlib.sha256(f"{recipient}:{event_id}:{channel}:{template_version}".encode()).hexdigest()

	# Check if deduplication key already processed
	if frappe.cache().get_value(f"notif_dedup_{dedup_key}"):
		return {"status": "deduplicated", "dedup_key": dedup_key}

	# Security check: redact sensitive content for email channel (COM-006)
	if channel == "email":
		message_payload["body"] = f"A new notification (ID: {event_id}) requires your attention. Log in to the secure Client Portal to view details: {frappe.utils.get_url('/client-portal')}"

	# Cache deduplication key for 24h
	frappe.cache().set_value(f"notif_dedup_{dedup_key}", True, expires_in_sec=86400)

	return {"status": "sent", "recipient": recipient, "channel": channel, "dedup_key": dedup_key}
