from __future__ import annotations

import frappe
from frappe import _

from lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel import (
	CONTEXT_DOCTYPES,
	can_start_direct_message,
	create_channel as _create_channel,
	ensure_contextual_channel,
	get_channels,
	get_channel_members as _get_channel_members,
	get_or_create_direct_channel as _get_or_create_direct_channel,
	get_user_chat_identity,
	is_chat_user,
	is_management_user,
	serialize_channel,
)
from lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message import (
	MESSAGE_EDIT_WINDOW_MINUTES,
	edit_message as _edit_message,
	get_pinned_messages as _get_pinned_messages,
	get_channel_jobs as _get_channel_jobs,
	get_thread as _get_thread,
	get_messages as _get_messages,
	sync_messages as _sync_messages,
	mark_channel_read as _mark_channel_read,
	publish_typing as _publish_typing,
	search_messages as _search_messages,
	set_channel_preferences as _set_channel_preferences,
	set_message_pinned as _set_message_pinned,
	send_message as _send_message,
	toggle_reaction as _toggle_reaction,
)
from lex.lex.doctype.lexocrates_chat_presence.lexocrates_chat_presence import (
	get_presence_snapshot,
	update_presence as _update_presence,
)


@frappe.whitelist()
def get_chat_bootstrap(selected_channel: str | None = None) -> dict:
	if not is_chat_user():
		frappe.throw(_("An enabled internal user or authorized client role is required to use Lexocrates Chat."), frappe.PermissionError)
	channels = get_channels()
	channel_names = {channel["name"] for channel in channels}
	if selected_channel not in channel_names:
		selected_channel = channels[0]["name"] if channels else None
	return {
		"channels": channels,
		"presence": get_presence_snapshot(),
		"selected_channel": selected_channel,
		"current_user": frappe.session.user,
		"current_user_full_name": frappe.db.get_value(
			"User", frappe.session.user, "full_name"
		)
		or frappe.session.user,
		"current_user_identity": get_user_chat_identity(frappe.session.user),
		"can_create_channel": is_management_user(),
		"can_start_direct_message": can_start_direct_message(),
		"edit_window_minutes": MESSAGE_EDIT_WINDOW_MINUTES,
		"context_doctypes": sorted(
			doctype for doctype in CONTEXT_DOCTYPES if frappe.db.exists("DocType", doctype)
		),
	}


@frappe.whitelist()
def update_presence(status: str | None = None, is_active: int = 1, disconnect: int = 0):
	return _update_presence(status=status, is_active=is_active, disconnect=disconnect)


@frappe.whitelist()
def create_channel(
	channel_name: str,
	channel_type: str = "Public",
	description: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	members=None,
	system_user_only: int = 1,
):
	"""Expose channel creation without forwarding Frappe's internal request keys."""
	return _create_channel(
		channel_name=channel_name,
		channel_type=channel_type,
		description=description,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		members=members,
		system_user_only=system_user_only,
	)


@frappe.whitelist()
def get_channel_members(channel: str):
	return _get_channel_members(channel=channel)


@frappe.whitelist()
def get_messages(
	channel: str,
	before: str | None = None,
	before_sequence: int | None = None,
	limit: int = 100,
):
	return _get_messages(
		channel=channel,
		before=before,
		before_sequence=before_sequence,
		limit=limit,
	)


@frappe.whitelist()
def sync_messages(channel: str, after_sequence: int = 0, limit: int = 200):
	return _sync_messages(channel=channel, after_sequence=after_sequence, limit=limit)


@frappe.whitelist()
def get_channel_jobs(channel: str, search_text: str | None = None, limit: int = 50):
	return _get_channel_jobs(channel=channel, search_text=search_text, limit=limit)


@frappe.whitelist()
def send_message(
	channel: str,
	message_text: str,
	thread_reference: str | None = None,
	attachments=None,
	client_message_id: str | None = None,
):
	return _send_message(
		channel=channel,
		message_text=message_text,
		thread_reference=thread_reference,
		attachments=attachments,
		client_message_id=client_message_id,
	)


@frappe.whitelist()
def edit_message(message_name: str, message_text: str):
	return _edit_message(message_name=message_name, message_text=message_text)


@frappe.whitelist()
def search_messages(search_text: str, channel: str | None = None, limit: int = 50):
	return _search_messages(search_text=search_text, channel=channel, limit=limit)


@frappe.whitelist()
def get_thread(message_name: str):
	return _get_thread(message_name=message_name)


@frappe.whitelist()
def mark_channel_read(channel: str, message_name: str | None = None):
	return _mark_channel_read(channel=channel, message_name=message_name)


@frappe.whitelist()
def set_channel_preferences(channel: str, notification_level: str = "All Messages"):
	return _set_channel_preferences(
		channel=channel, notification_level=notification_level
	)


@frappe.whitelist()
def toggle_reaction(message_name: str, emoji: str):
	return _toggle_reaction(message_name=message_name, emoji=emoji)


@frappe.whitelist()
def set_message_pinned(message_name: str, pinned: int = 1):
	return _set_message_pinned(message_name=message_name, pinned=pinned)


@frappe.whitelist()
def get_pinned_messages(channel: str):
	return _get_pinned_messages(channel=channel)


@frappe.whitelist()
def publish_typing(channel: str, is_typing: int = 1):
	return _publish_typing(channel=channel, is_typing=is_typing)


@frappe.whitelist()
def get_or_create_direct_channel(other_user: str):
	return _get_or_create_direct_channel(other_user=other_user)


@frappe.whitelist()
def get_or_create_contextual_channel(reference_doctype: str, reference_name: str) -> dict:
	if reference_doctype not in CONTEXT_DOCTYPES:
		frappe.throw(_("This DocType is not enabled as a chat context."), frappe.ValidationError)
	frappe.has_permission(reference_doctype, "read", doc=reference_name, throw=True)
	members = [frappe.session.user]
	if reference_doctype == "LPO Job":
		job = frappe.db.get_value(
			"LPO Job", reference_name, ["owner", "assigned_analyst", "engagement"], as_dict=True
		)
		if job:
			members.extend([job.owner, job.assigned_analyst])
			members.append(
				frappe.db.get_value("LPO Matter", job.engagement, "matter_manager")
			)
			from lex.lexocrates_chat_sync import ensure_matter_chat_channel

			channel_name = ensure_matter_chat_channel(job.engagement, members)
			channel = frappe.get_doc("Lexocrates Chat Channel", channel_name)
			frappe.has_permission("Lexocrates Chat Channel", "read", doc=channel.name, throw=True)
			return serialize_channel(channel)
	elif reference_doctype == "LPO Matter":
		from lex.lexocrates_chat_sync import ensure_matter_chat_channel

		channel_name = ensure_matter_chat_channel(reference_name, members)
		channel = frappe.get_doc("Lexocrates Chat Channel", channel_name)
		frappe.has_permission("Lexocrates Chat Channel", "read", doc=channel.name, throw=True)
		return serialize_channel(channel)
	channel = ensure_contextual_channel(reference_doctype, reference_name, members)
	frappe.has_permission("Lexocrates Chat Channel", "read", doc=channel.name, throw=True)
	return serialize_channel(channel)


@frappe.whitelist()
def search_users(search_text: str | None = None) -> list[dict]:
	if not can_start_direct_message():
		frappe.throw(
			_("Only enabled System Users can search for direct-message recipients."),
			frappe.PermissionError,
		)
	search_text = (search_text or "").strip()
	filters = {"enabled": 1, "user_type": "System User"}
	or_filters = None
	if search_text:
		like = f"%{search_text}%"
		or_filters = {"name": ["like", like], "full_name": ["like", like], "username": ["like", like]}
	users = frappe.get_all(
		"User",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "full_name", "user_image", "username"],
		order_by="full_name asc",
		limit_page_length=25,
	)
	return [
		get_user_chat_identity(user.name)
		for user in users
		if user.name != frappe.session.user and can_start_direct_message(user.name)
	]


@frappe.whitelist()
def get_unread_summary() -> dict:
	if not is_chat_user():
		return {"total_unread": 0, "channels": []}
	channels = get_channels()
	total_unread = sum(int(c.get("unread_count") or 0) for c in channels)
	unread_channels = [c for c in channels if int(c.get("unread_count") or 0) > 0]
	return {
		"total_unread": total_unread,
		"channels": unread_channels,
		"all_channels": channels[:15],
	}
