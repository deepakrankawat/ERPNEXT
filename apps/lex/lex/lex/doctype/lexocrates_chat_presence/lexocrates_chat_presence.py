from __future__ import annotations

from datetime import timedelta
from typing import Iterable

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_datetime, now_datetime


PRESENCE_STATUSES = {"Online", "Away", "Busy", "Offline"}
PRESENCE_EVENT = "chat_presence_changed"
PRESENCE_TIMEOUT_SECONDS = 90
PRESENCE_STATE_FIELDS = (
	"name",
	"user",
	"status",
	"preferred_status",
	"status_updated_at",
	"last_heartbeat_at",
	"last_activity_at",
	"last_seen_at",
)


class LexocratesChatPresence(Document):
	def validate(self):
		if self.status not in PRESENCE_STATUSES or self.preferred_status not in PRESENCE_STATUSES:
			frappe.throw(_("Invalid chat presence status."), frappe.ValidationError)
		previous = self.get_doc_before_save()
		if previous and previous.user != self.user:
			frappe.throw(_("The User on a presence record cannot be changed."), frappe.PermissionError)

	def on_trash(self):
		if not getattr(frappe.flags, "lexocrates_chat_presence_cleanup", False):
			frappe.throw(_("Chat presence records cannot be deleted manually."), frappe.PermissionError)


def on_doctype_update():
	frappe.db.add_unique(
		"Lexocrates Chat Presence",
		["user"],
		constraint_name="lexocrates_chat_presence_user_unique",
	)
	frappe.db.add_index(
		"Lexocrates Chat Presence",
		["status", "last_heartbeat_at"],
		index_name="lexocrates_chat_presence_status_heartbeat",
	)


def _is_chat_user(user: str) -> bool:
	from lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel import is_chat_user

	return is_chat_user(user)


def _presence_recipients(user: str) -> set[str]:
	recipients = {user}
	channel_names = frappe.get_all(
		"Lexocrates Chat Member",
		filters={"user": user, "parenttype": "Lexocrates Chat Channel"},
		pluck="parent",
		limit_page_length=0,
	)
	if channel_names:
		recipients.update(
			frappe.get_all(
				"Lexocrates Chat Member",
				filters={
					"parent": ["in", channel_names],
					"parenttype": "Lexocrates Chat Channel",
				},
				pluck="user",
				limit_page_length=0,
			)
		)

	# Presence is published only to existing conversation peers. New DM candidates
	# become peers as soon as the private channel is created; loading every Desk
	# user here would make the chat bootstrap grow with the whole User table.
	return {recipient for recipient in recipients if recipient and recipient != "Guest"}


def _effective_status(row, *, at=None) -> str:
	at = at or now_datetime()
	if not row:
		return "Offline"
	last_heartbeat = row.get("last_heartbeat_at")
	if row.get("status") != "Offline" and (
		not last_heartbeat
		or (at - get_datetime(last_heartbeat)).total_seconds() > PRESENCE_TIMEOUT_SECONDS
	):
		return "Offline"
	return row.get("status") or "Offline"


def _user_details(users: Iterable[str]) -> dict[str, dict]:
	users = list(dict.fromkeys(user for user in users if user))
	if not users:
		return {}
	fields = ["name", "full_name", "user_image"]
	if frappe.get_meta("User").has_field("last_active"):
		fields.append("last_active")
	return {
		row.name: row
		for row in frappe.get_all(
			"User",
			filters={"name": ["in", users], "enabled": 1},
			fields=fields,
			limit_page_length=0,
		)
	}


def _serialize_presence(user: str, row=None, details=None, *, at=None) -> dict:
	at = at or now_datetime()
	details = details or {}
	status = _effective_status(row, at=at)
	last_heartbeat = row.get("last_heartbeat_at") if row else None
	last_seen = row.get("last_seen_at") if row else None
	last_activity = row.get("last_activity_at") if row else None
	if status == "Offline":
		last_seen = last_heartbeat or last_seen or details.get("last_active")
	return {
		"user": user,
		"full_name": details.get("full_name") or user,
		"user_image": details.get("user_image"),
		"status": status,
		"preferred_status": row.get("preferred_status") if row else "Online",
		"last_seen_at": str(last_seen) if last_seen else None,
		"last_activity_at": str(last_activity) if last_activity else None,
		"status_updated_at": str(row.get("status_updated_at")) if row and row.get("status_updated_at") else None,
	}


def get_presence_snapshot(users: Iterable[str] | None = None) -> list[dict]:
	current_user = frappe.session.user
	if not _is_chat_user(current_user):
		frappe.throw(_("A chat-enabled role is required to view presence."), frappe.PermissionError)
	visible_users = _presence_recipients(current_user)
	requested = set(users or visible_users)
	allowed_users = sorted(requested.intersection(visible_users))
	user_details = _user_details(allowed_users)
	allowed_users = [user for user in allowed_users if user in user_details]
	rows = frappe.get_all(
		"Lexocrates Chat Presence",
		filters={"user": ["in", allowed_users]},
		fields=[
			"user", "status", "preferred_status", "status_updated_at",
			"last_heartbeat_at", "last_activity_at", "last_seen_at",
		],
		limit_page_length=0,
	) if allowed_users else []
	row_map = {row.user: row for row in rows}
	at = now_datetime()
	return [
		_serialize_presence(user, row_map.get(user), user_details[user], at=at)
		for user in allowed_users
	]


def _get_or_create_presence(user: str):
	name = frappe.db.get_value("Lexocrates Chat Presence", {"user": user}, "name")
	if name:
		return frappe.get_doc("Lexocrates Chat Presence", name)
	try:
		return frappe.get_doc(
			{
				"doctype": "Lexocrates Chat Presence",
				"user": user,
				"status": "Offline",
				"preferred_status": "Online",
			}
		).insert(ignore_permissions=True)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		# Another tab may have created the one-row-per-user presence record.
		name = frappe.db.get_value("Lexocrates Chat Presence", {"user": user}, "name")
		if not name:
			raise
		return frappe.get_doc("Lexocrates Chat Presence", name)


def _get_locked_presence(user: str):
	"""Serialize concurrent heartbeats for a user's ephemeral presence row."""
	presence = _get_or_create_presence(user)
	fields = ", ".join(f"`{field}`" for field in PRESENCE_STATE_FIELDS)
	rows = frappe.db.sql(
		f"""
			select {fields}
			from `tabLexocrates Chat Presence`
			where `name` = %s
			for update
		""",
		presence.name,
		as_dict=True,
	)
	return rows[0] if rows else presence.as_dict()


def _publish_presence(payload: dict):
	for recipient in _presence_recipients(payload["user"]):
		frappe.publish_realtime(
			PRESENCE_EVENT,
			payload,
			user=recipient,
			after_commit=True,
		)


def touch_presence(
	user: str,
	*,
	preferred_status: str | None = None,
	is_active: bool = True,
	disconnect: bool = False,
	publish: bool = True,
) -> dict:
	if not user or user == "Guest" or not frappe.db.get_value("User", user, "enabled"):
		return {}
	presence = _get_locked_presence(user)
	now = now_datetime()
	previous_status = _effective_status(presence, at=now)
	values = {"last_heartbeat_at": now}
	if preferred_status is not None:
		if preferred_status not in PRESENCE_STATUSES:
			frappe.throw(_("Invalid chat presence status."), frappe.ValidationError)
		values["preferred_status"] = preferred_status
	else:
		preferred_status = presence.preferred_status or "Online"

	if is_active and not disconnect:
		values["last_activity_at"] = now
	if disconnect:
		status = "Offline"
	else:
		status = preferred_status
		if status == "Online" and not is_active:
			status = "Away"
	if status == "Offline":
		values["last_seen_at"] = now
	elif previous_status == "Offline":
		# Preserve the previous session's last-seen timestamp while online.
		values["last_seen_at"] = presence.last_seen_at or now
	if presence.status != status:
		values["status_updated_at"] = now
	values["status"] = status
	# Heartbeats are operational state, not user edits. Avoid Document.save's
	# optimistic timestamp check and do not churn `modified` every 30 seconds.
	frappe.db.set_value(
		"Lexocrates Chat Presence",
		presence.name,
		values,
		update_modified=False,
	)
	presence.update(values)
	details = _user_details([user]).get(user, {})
	payload = _serialize_presence(user, presence, details, at=now)
	if publish and (previous_status != status or preferred_status is not None or disconnect):
		_publish_presence(payload)
	return payload


@frappe.whitelist()
def update_presence(
	status: str | None = None,
	is_active: int = 1,
	disconnect: int = 0,
) -> dict:
	if not _is_chat_user(frappe.session.user):
		frappe.throw(_("A chat-enabled role is required to update presence."), frappe.PermissionError)
	return touch_presence(
		frappe.session.user,
		preferred_status=status or None,
		is_active=bool(cint(is_active)),
		disconnect=bool(cint(disconnect)),
	)


@frappe.whitelist()
def get_presence(users=None) -> list[dict]:
	if isinstance(users, str):
		users = frappe.parse_json(users)
	if users is not None and not isinstance(users, list):
		frappe.throw(_("Users must be a JSON list."), frappe.ValidationError)
	return get_presence_snapshot(users)


def mark_user_offline(user: str, *, publish: bool = True) -> dict:
	if not frappe.db.exists("DocType", "Lexocrates Chat Presence"):
		return {}
	return touch_presence(user, is_active=False, disconnect=True, publish=publish)


def mark_stale_presences_offline():
	if not frappe.db.exists("DocType", "Lexocrates Chat Presence"):
		return
	cutoff = now_datetime() - timedelta(seconds=PRESENCE_TIMEOUT_SECONDS)
	rows = frappe.get_all(
		"Lexocrates Chat Presence",
		filters={"status": ["!=", "Offline"], "last_heartbeat_at": ["<", cutoff]},
		fields=["name", "user", "last_heartbeat_at"],
		limit_page_length=500,
	)
	for row in rows:
		frappe.db.set_value(
			"Lexocrates Chat Presence",
			row.name,
			{
				"status": "Offline",
				"status_updated_at": now_datetime(),
				"last_seen_at": row.last_heartbeat_at or now_datetime(),
			},
			update_modified=False,
		)
		details = _user_details([row.user]).get(row.user, {})
		updated = frappe.db.get_value(
			"Lexocrates Chat Presence",
			row.name,
			[
				"user", "status", "preferred_status", "status_updated_at",
				"last_heartbeat_at", "last_activity_at", "last_seen_at",
			],
			as_dict=True,
		)
		_publish_presence(_serialize_presence(row.user, updated, details))
