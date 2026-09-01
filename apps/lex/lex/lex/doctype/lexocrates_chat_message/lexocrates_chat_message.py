from __future__ import annotations

import json
import re
import uuid
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import format_datetime, get_datetime, now_datetime, sanitize_html, strip_html

from lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel import (
	can_manage_channel,
	can_post_to_channel,
	can_view_channel,
	get_user_chat_identity,
	get_permission_query_conditions as get_channel_permission_query_conditions,
)


MESSAGE_EDIT_WINDOW_MINUTES = 15
MAX_MESSAGE_LENGTH = 10_000
MAX_ATTACHMENTS = 10
CHAT_PROTOCOL_VERSION = 1
CLIENT_MESSAGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,64}$")
ALLOWED_REACTIONS = {
	"👍", "❤️", "✅", "👀", "🎉", "🙏", "🔥", "🚀", "💡", "👏", "💯", "📌", "😂", "🤝", "⚡", "🎯"
}
MENTION_PATTERN = re.compile(
	r"(?<![\w@])@([A-Za-z0-9._+-]+(?:@[A-Za-z0-9.-]+\.[A-Za-z]{2,})?)"
)
JOB_MENTION_PATTERN = re.compile(r"(?<![\w@])@((?:LPOJ)-\d{4}-\d+)", re.IGNORECASE)


class LexocratesChatMessage(Document):
	def before_insert(self):
		is_system = bool(getattr(frappe.flags, "lexocrates_chat_automation", False))
		is_import = bool(getattr(frappe.flags, "lexocrates_chat_import", False))
		if is_import:
			self.sender = self.sender or "Administrator"
			self.sent_at = self.sent_at or now_datetime()
			self._assign_delivery_identity()
			return

		self.sent_at = now_datetime()
		if is_system:
			self.sender = "Administrator"
			self.system_generated = 1
		else:
			self.sender = frappe.session.user
			self.system_generated = 0
			self.source_doctype = None
			self.source_name = None
			self.automation_key = None
		self._assign_delivery_identity()

	def _assign_delivery_identity(self):
		self.client_message_id = normalize_client_message_id(self.client_message_id)
		self.channel_sequence = allocate_channel_sequence(self.channel)

	def validate(self):
		channel = frappe.get_doc("Lexocrates Chat Channel", self.channel)
		is_automation = bool(getattr(frappe.flags, "lexocrates_chat_automation", False))
		is_import = bool(getattr(frappe.flags, "lexocrates_chat_import", False))
		if channel.status != "Active" and self.is_new():
			frappe.throw(_("Messages cannot be added to an archived channel."), frappe.ValidationError)
		if self.is_new() and not (is_automation or is_import) and not can_post_to_channel(channel):
			frappe.throw(_("You cannot post messages in this channel."), frappe.PermissionError)

		self.message_text = sanitize_html(
			self.message_text or "",
			linkify=True,
			always_sanitize=True,
			disallowed_tags=["form", "input", "button", "script", "style", "iframe", "object"],
		)
		plain_text = strip_html(self.message_text).strip()
		if not plain_text:
			frappe.throw(_("Message Text is required."), frappe.MandatoryError)
		if len(plain_text) > MAX_MESSAGE_LENGTH:
			frappe.throw(
				_("Messages cannot exceed {0} characters.").format(MAX_MESSAGE_LENGTH),
				frappe.ValidationError,
			)

		self._validate_thread()
		self.mentions = json.dumps(extract_mentions(plain_text), separators=(",", ":"))
		self.job_mentions = json.dumps(
			extract_job_mentions(plain_text, channel), separators=(",", ":")
		)
		self.attachments = json.dumps(
			_normalize_attachments(self.attachments), separators=(",", ":")
		)
		self._protect_audit_fields()

	def _validate_thread(self):
		if not self.thread_reference:
			return
		parent = frappe.db.get_value(
			"Lexocrates Chat Message",
			self.thread_reference,
			["channel", "thread_reference"],
			as_dict=True,
		)
		if not parent:
			frappe.throw(_("Thread Reference does not exist."), frappe.DoesNotExistError)
		if parent.channel != self.channel:
			frappe.throw(
				_("Replies must remain in the same channel as the parent message."),
				frappe.ValidationError,
			)
		# Keep conversations one level deep and make every reply point at the root.
		if parent.thread_reference:
			self.thread_reference = parent.thread_reference

	def _protect_audit_fields(self):
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		protected = {
			"channel",
			"channel_sequence",
			"client_message_id",
			"sender",
			"sent_at",
			"thread_reference",
			"system_generated",
			"source_doctype",
			"source_name",
			"automation_key",
			"attachments",
		}
		changed = [field for field in protected if self.get(field) != previous.get(field)]
		if changed:
			frappe.throw(
				_("Audited message fields cannot be changed: {0}.").format(", ".join(changed)),
				frappe.PermissionError,
			)

	def before_save(self):
		if self.is_new():
			return
		if self.system_generated:
			frappe.throw(_("System-generated messages are immutable."), frappe.PermissionError)
		if self.sender != frappe.session.user:
			frappe.throw(_("Only the sender can edit this message."), frappe.PermissionError)
		if not is_within_edit_window(self.sent_at):
			frappe.throw(
				_("The {0}-minute message edit window has expired.").format(
					MESSAGE_EDIT_WINDOW_MINUTES
				),
				frappe.PermissionError,
			)
		self.edited_on = now_datetime()

	def after_insert(self):
		frappe.db.set_value(
			"Lexocrates Chat Channel",
			self.channel,
			"last_message_at",
			self.sent_at,
			update_modified=False,
		)
		_bind_uploaded_files(self)
		if getattr(frappe.flags, "lexocrates_chat_import", False):
			return
		payload = serialize_message(self)
		frappe.publish_realtime(
			"new_chat_message",
			payload,
			room=f"doc:Lexocrates Chat Channel/{self.channel}",
			after_commit=True,
		)
		for user in parse_json_list(self.mentions):
			if user != self.sender:
				frappe.publish_realtime(
					"chat_mention",
					payload,
					user=user,
					after_commit=True,
				)
				_send_mention_notification(self, user)
		self._publish_job_mentions(payload)

	def _publish_job_mentions(self, payload):
		for job_mention in parse_json_list(self.job_mentions):
			job = frappe.db.get_value(
				"LPO Job",
				job_mention.get("name"),
				["owner", "assigned_analyst", "engagement"],
				as_dict=True,
			)
			if not job:
				continue
			matter_manager = frappe.db.get_value("LPO Matter", job.engagement, "matter_manager")
			for user in {job.owner, job.assigned_analyst, matter_manager} - {None, self.sender}:
				if can_view_channel(frappe.get_doc("Lexocrates Chat Channel", self.channel), user=user):
					frappe.publish_realtime(
						"chat_job_mention",
						{**payload, "mentioned_job": job_mention},
						user=user,
						after_commit=True,
					)

	def on_update(self):
		if self.edited_on:
			frappe.publish_realtime(
				"chat_message_updated",
				serialize_message(self),
				room=f"doc:Lexocrates Chat Channel/{self.channel}",
				after_commit=True,
			)

	def on_trash(self):
		frappe.throw(
			_("Audited chat messages cannot be physically deleted."),
			frappe.PermissionError,
		)


def on_doctype_update():
	frappe.db.add_index(
		"Lexocrates Chat Message",
		["channel", "sent_at"],
		index_name="lexocrates_chat_channel_sent_at",
	)
	frappe.db.add_index(
		"Lexocrates Chat Message",
		["channel", "thread_reference", "sent_at"],
		index_name="lexocrates_chat_thread_sent_at",
	)
	frappe.db.add_index(
		"Lexocrates Chat Message",
		["channel", "channel_sequence"],
		index_name="lexocrates_chat_channel_sequence",
	)


def normalize_client_message_id(value: str | None) -> str:
	value = (value or "").strip()
	if not value:
		return str(uuid.uuid4())
	if not CLIENT_MESSAGE_ID_PATTERN.fullmatch(value):
		frappe.throw(
			_("Client Message ID must be 8-64 URL-safe characters."),
			frappe.ValidationError,
		)
	return value


def allocate_channel_sequence(channel: str) -> int:
	"""Allocate one channel sequence under a row lock.

	The lock serializes concurrent HTTP workers for a channel. The counter update
	and message insert share the request transaction, so a failed insert cannot
	leave a permanent hole and an emitted event can never precede its commit.
	"""
	rows = frappe.db.sql(
		"""
		select coalesce(last_message_sequence, 0) as last_message_sequence
		from `tabLexocrates Chat Channel`
		where name = %s
		for update
		""",
		channel,
		as_dict=True,
	)
	if not rows:
		frappe.throw(_("Chat channel {0} does not exist.").format(channel), frappe.DoesNotExistError)
	sequence = int(rows[0].last_message_sequence or 0) + 1
	frappe.db.set_value(
		"Lexocrates Chat Channel",
		channel,
		"last_message_sequence",
		sequence,
		update_modified=False,
	)
	return sequence


def is_within_edit_window(sent_at) -> bool:
	if not sent_at:
		return False
	elapsed = (now_datetime() - get_datetime(sent_at)).total_seconds()
	return 0 <= elapsed <= MESSAGE_EDIT_WINDOW_MINUTES * 60


def extract_mentions(plain_text: str) -> list[str]:
	tokens = {match.group(1).lower() for match in MENTION_PATTERN.finditer(plain_text or "")}
	if not tokens:
		return []
	users = frappe.get_all(
		"User",
		filters={"enabled": 1},
		fields=["name", "username"],
		limit_page_length=0,
	)
	lookup = {}
	for user in users:
		lookup[user.name.lower()] = user.name
		if user.username:
			lookup[user.username.lower()] = user.name
	return sorted({lookup[token] for token in tokens if token in lookup})


def extract_job_mentions(plain_text: str, channel) -> list[dict]:
	names = sorted({match.group(1).upper() for match in JOB_MENTION_PATTERN.finditer(plain_text or "")})
	if not names or not frappe.db.exists("DocType", "LPO Job"):
		return []
	jobs = frappe.get_all(
		"LPO Job",
		filters={"name": ["in", names]},
		fields=["name", "job_title", "engagement", "job_status", "assigned_analyst"],
		limit_page_length=0,
	)
	mentions = []
	for job in jobs:
		is_context_job = channel.reference_doctype == "LPO Job" and channel.reference_name == job.name
		is_context_matter = channel.reference_doctype == "LPO Matter" and channel.reference_name == job.engagement
		if not (is_context_job or is_context_matter) and not frappe.has_permission(
			"LPO Job", "read", doc=job.name
		):
			continue
		mentions.append(
			{
				"doctype": "LPO Job",
				"name": job.name,
				"title": job.job_title or job.name,
				"matter": job.engagement,
				"status": job.job_status,
			}
		)
	return mentions


def parse_json_list(value) -> list:
	if not value:
		return []
	if isinstance(value, list):
		return value
	try:
		parsed = json.loads(value)
	except (TypeError, ValueError):
		frappe.throw(_("Expected a JSON list."), frappe.ValidationError)
	if not isinstance(parsed, list):
		frappe.throw(_("Expected a JSON list."), frappe.ValidationError)
	return parsed


def _normalize_attachments(value) -> list[str]:
	urls = parse_json_list(value)
	if len(urls) > MAX_ATTACHMENTS:
		frappe.throw(
			_("A message can contain at most {0} attachments.").format(MAX_ATTACHMENTS),
			frappe.ValidationError,
		)
	normalized = []
	for url in dict.fromkeys(urls):
		if not isinstance(url, str) or not url.startswith(("/files/", "/private/files/")):
			frappe.throw(_("Invalid attachment URL."), frappe.ValidationError)
		file_row = frappe.db.get_value(
			"File", {"file_url": url}, ["name", "owner"], as_dict=True
		)
		if not file_row:
			frappe.throw(_("Attachment {0} does not exist.").format(frappe.bold(url)))
		if not getattr(frappe.flags, "lexocrates_chat_automation", False):
			if file_row.owner != frappe.session.user and not frappe.has_permission(
				"File", "read", doc=file_row.name
			):
				frappe.throw(_("You cannot attach file {0}.").format(frappe.bold(url)))
		normalized.append(url)
	return normalized


def _bind_uploaded_files(message):
	for url in parse_json_list(message.attachments):
		file_name = frappe.db.get_value("File", {"file_url": url}, "name")
		if file_name:
			frappe.db.set_value(
				"File",
				file_name,
				{
					"attached_to_doctype": "Lexocrates Chat Message",
					"attached_to_name": message.name,
					"attached_to_field": "attachments",
				},
				update_modified=False,
			)


def serialize_message(
	message: Any,
	sender_full_name: str | None = None,
	sender_identity: dict | None = None,
) -> dict:
	if isinstance(message, str):
		message = frappe.get_doc("Lexocrates Chat Message", message)
	get = message.get
	if sender_identity is None:
		sender_identity = get_user_chat_identity(get("sender"))
	if sender_full_name is None:
		sender_full_name = sender_identity.get("full_name")
	timestamp = get("sent_at")
	return {
		"protocol_version": CHAT_PROTOCOL_VERSION,
		"event_id": f"chat-message:{get('name')}:{get('edited_on') or 'created'}",
		"event_type": "message.updated" if get("edited_on") else "message.created",
		"name": get("name"),
		"channel": get("channel"),
		"channel_sequence": int(get("channel_sequence") or 0),
		"client_message_id": get("client_message_id"),
		"sender": get("sender"),
		"sender_full_name": sender_full_name or get("sender"),
		"sender_role": sender_identity.get("primary_role"),
		"sender_roles": sender_identity.get("roles") or [],
		"sender_user_type": sender_identity.get("user_type"),
		"sender_image": sender_identity.get("user_image"),
		"message_text": get("message_text"),
		"sent_at": str(timestamp),
		"formatted_timestamp": format_datetime(timestamp),
		"server_time": str(now_datetime()),
		"thread_reference": get("thread_reference"),
		"mentions": parse_json_list(get("mentions")),
		"job_mentions": parse_json_list(get("job_mentions")),
		"attachments": parse_json_list(get("attachments")),
		"system_generated": bool(get("system_generated")),
		"source_doctype": get("source_doctype"),
		"source_name": get("source_name"),
		"edited_on": str(get("edited_on")) if get("edited_on") else None,
		"is_pinned": bool(get("is_pinned")),
		"pinned_by": get("pinned_by"),
		"pinned_at": str(get("pinned_at")) if get("pinned_at") else None,
		"reactions": [],
		"reply_count": 0,
		"read_by": [],
		"can_edit": bool(
			not get("system_generated")
			and get("sender") == frappe.session.user
			and is_within_edit_window(timestamp)
		),
	}


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if ptype == "delete":
		return False
	if not doc.channel:
		return False
	channel = frappe.get_doc("Lexocrates Chat Channel", doc.channel)
	if ptype == "create":
		return can_post_to_channel(channel, user=user)
	if ptype in {"write", "share"}:
		return bool(
			ptype == "write"
			and doc.sender == user
			and not doc.system_generated
			and is_within_edit_window(doc.sent_at)
		)
	return can_view_channel(channel, user=user, debug=debug)


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	channel_condition = get_channel_permission_query_conditions(user)
	if not channel_condition:
		return ""
	if channel_condition == "1=0":
		return "1=0"
	return f"""
		exists (
			select 1 from `tabLexocrates Chat Channel`
			where `tabLexocrates Chat Channel`.name = `tabLexocrates Chat Message`.channel
				and ({channel_condition})
		)
	"""


@frappe.whitelist()
def send_message(
	channel: str,
	message_text: str,
	thread_reference: str | None = None,
	attachments=None,
	client_message_id: str | None = None,
) -> dict:
	client_message_id = normalize_client_message_id(client_message_id)
	existing = frappe.db.get_value(
		"Lexocrates Chat Message",
		{"client_message_id": client_message_id},
		["name", "channel", "sender"],
		as_dict=True,
	)
	if existing:
		if existing.channel != channel or existing.sender != frappe.session.user:
			frappe.throw(_("This message delivery key is already in use."), frappe.PermissionError)
		return serialize_message(existing.name)
	savepoint = "lexocrates_chat_idempotent_send"
	frappe.db.savepoint(savepoint)
	try:
		doc = frappe.get_doc(
			{
				"doctype": "Lexocrates Chat Message",
				"channel": channel,
				"message_text": message_text,
				"thread_reference": thread_reference,
				"attachments": json.dumps(parse_json_list(attachments)),
				"client_message_id": client_message_id,
			}
		).insert()
		frappe.db.release_savepoint(savepoint)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		# Two retries can race before either transaction sees the idempotency row.
		# Roll back the losing sequence allocation, then return the winner.
		frappe.db.rollback(save_point=savepoint)
		existing = frappe.db.get_value(
			"Lexocrates Chat Message",
			{"client_message_id": client_message_id},
			["name", "channel", "sender"],
			as_dict=True,
		)
		if not existing or existing.channel != channel or existing.sender != frappe.session.user:
			raise
		return serialize_message(existing.name)
	return serialize_message(doc)


@frappe.whitelist()
def get_channel_jobs(channel: str, search_text: str | None = None, limit: int = 50) -> list[dict]:
	"""Return Jobs that can be mentioned in the selected Matter conversation."""
	channel_doc = frappe.get_doc("Lexocrates Chat Channel", channel)
	if not can_view_channel(channel_doc):
		frappe.throw(_("You cannot view this channel."), frappe.PermissionError)
	matter = None
	if channel_doc.reference_doctype == "LPO Matter":
		matter = channel_doc.reference_name
	elif channel_doc.reference_doctype == "LPO Job":
		matter = frappe.db.get_value("LPO Job", channel_doc.reference_name, "engagement")
	if not matter:
		return []
	# Matter Room membership is the authorization boundary. A client or executive
	# may legitimately use the room without a Desk-level LPO Job role.
	rows = frappe.get_all(
		"LPO Job",
		filters={"engagement": matter},
		fields=["name", "job_title", "job_status", "priority", "assigned_analyst", "due_date"],
		order_by="modified desc",
		limit_page_length=min(max(int(limit or 50), 1), 100),
	)
	query = (search_text or "").strip().lower()
	if query:
		rows = [
			row
			for row in rows
			if query in row.name.lower() or query in (row.job_title or "").lower()
		]
	return rows


@frappe.whitelist()
def edit_message(message_name: str, message_text: str) -> dict:
	doc = frappe.get_doc("Lexocrates Chat Message", message_name)
	if not has_permission(doc, "write"):
		frappe.throw(_("This message is outside your edit window."), frappe.PermissionError)
	doc.message_text = message_text
	doc.save(ignore_permissions=True)
	return serialize_message(doc)


@frappe.whitelist()
def get_messages(
	channel: str,
	before: str | None = None,
	before_sequence: int | None = None,
	limit: int = 100,
) -> list[dict]:
	frappe.has_permission("Lexocrates Chat Channel", "read", doc=channel, throw=True)
	limit = min(max(int(limit or 100), 1), 200)
	filters: dict[str, Any] = {"channel": channel}
	if before_sequence is not None:
		filters["channel_sequence"] = ["<", max(int(before_sequence or 0), 0)]
	elif before:
		filters["sent_at"] = ["<", get_datetime(before)]
	rows = frappe.get_all(
		"Lexocrates Chat Message",
		filters=filters,
		fields=[
			"name",
			"channel",
			"channel_sequence",
			"client_message_id",
			"sender",
			"message_text",
			"sent_at",
			"thread_reference",
			"mentions",
			"job_mentions",
			"attachments",
			"system_generated",
			"source_doctype",
			"source_name",
			"edited_on",
			"is_pinned",
			"pinned_by",
			"pinned_at",
		],
		order_by="channel_sequence desc",
		limit_page_length=limit,
	)
	rows.reverse()
	identities = _sender_identities(rows)
	return _enrich_messages(
		[serialize_message(row, sender_identity=identities.get(row.sender)) for row in rows]
	)


@frappe.whitelist()
def sync_messages(channel: str, after_sequence: int = 0, limit: int = 200) -> dict:
	"""Return committed messages after a client high-water mark.

	This HTTP recovery path complements Socket.IO. It is intentionally safe to
	call on every reconnect and periodically while online.
	"""
	frappe.has_permission("Lexocrates Chat Channel", "read", doc=channel, throw=True)
	after_sequence = max(int(after_sequence or 0), 0)
	limit = min(max(int(limit or 200), 1), 500)
	rows = frappe.get_all(
		"Lexocrates Chat Message",
		filters={"channel": channel, "channel_sequence": [">", after_sequence]},
		fields=[
			"name", "channel", "channel_sequence", "client_message_id", "sender",
			"message_text", "sent_at", "thread_reference", "mentions", "job_mentions",
			"attachments", "system_generated", "source_doctype", "source_name", "edited_on",
			"is_pinned", "pinned_by", "pinned_at",
		],
		order_by="channel_sequence asc",
		limit_page_length=limit + 1,
	)
	has_more = len(rows) > limit
	rows = rows[:limit]
	identities = _sender_identities(rows)
	messages = _enrich_messages(
		[serialize_message(row, sender_identity=identities.get(row.sender)) for row in rows]
	)
	high_watermark = int(
		frappe.db.get_value("Lexocrates Chat Channel", channel, "last_message_sequence") or 0
	)
	return {
		"protocol_version": CHAT_PROTOCOL_VERSION,
		"channel": channel,
		"after_sequence": after_sequence,
		"next_sequence": int(messages[-1]["channel_sequence"] if messages else after_sequence),
		"high_watermark": high_watermark,
		"has_more": has_more,
		"messages": messages,
		"server_time": str(now_datetime()),
	}


@frappe.whitelist()
def search_messages(search_text: str, channel: str | None = None, limit: int = 50) -> list[dict]:
	search_text = strip_html(search_text or "").strip()
	if len(search_text) < 2:
		return []
	filters: dict[str, Any] = {"message_text": ["like", f"%{search_text}%"]}
	if channel:
		frappe.has_permission("Lexocrates Chat Channel", "read", doc=channel, throw=True)
		filters["channel"] = channel
	rows = frappe.get_all(
		"Lexocrates Chat Message",
		filters=filters,
		fields=[
			"name",
			"channel",
			"channel_sequence",
			"client_message_id",
			"sender",
			"message_text",
			"sent_at",
			"thread_reference",
			"mentions",
			"job_mentions",
			"attachments",
			"system_generated",
			"source_doctype",
			"source_name",
			"edited_on",
			"is_pinned",
			"pinned_by",
			"pinned_at",
		],
		order_by="sent_at desc",
		limit_page_length=min(max(int(limit or 50), 1), 100),
	)
	identities = _sender_identities(rows)
	return _enrich_messages(
		[serialize_message(row, sender_identity=identities.get(row.sender)) for row in rows]
	)


def _enrich_messages(messages: list[dict]) -> list[dict]:
	if not messages:
		return messages
	message_names = [message["name"] for message in messages]
	reactions = frappe.get_all(
		"Lexocrates Chat Reaction",
		filters={"message": ["in", message_names]},
		fields=["message", "user", "emoji"],
		order_by="reacted_at asc",
		limit_page_length=0,
	)
	reaction_map: dict[str, dict[str, list[str]]] = {}
	for reaction in reactions:
		reaction_map.setdefault(reaction.message, {}).setdefault(reaction.emoji, []).append(
			reaction.user
		)

	replies = frappe.get_all(
		"Lexocrates Chat Message",
		filters={"thread_reference": ["in", message_names]},
		fields=["thread_reference", "count(name) as reply_count"],
		group_by="thread_reference",
		limit_page_length=0,
	)
	reply_counts = {row.thread_reference: int(row.reply_count or 0) for row in replies}

	channel_names = list({message["channel"] for message in messages})
	states = frappe.get_all(
		"Lexocrates Chat User State",
		filters={"channel": ["in", channel_names], "last_read_at": ["is", "set"]},
		fields=["channel", "user", "last_read_at", "last_read_sequence"],
		limit_page_length=0,
	)
	read_state: dict[str, list] = {}
	for state in states:
		read_state.setdefault(state.channel, []).append(state)

	for message in messages:
		message["reactions"] = [
			{
				"emoji": emoji,
				"count": len(users),
				"users": users,
				"reacted_by_me": frappe.session.user in users,
			}
			for emoji, users in reaction_map.get(message["name"], {}).items()
		]
		message["reply_count"] = reply_counts.get(message["name"], 0)
		message["read_by"] = [
			state.user
			for state in read_state.get(message["channel"], [])
			if state.user != message["sender"]
			and int(state.last_read_sequence or 0) >= int(message["channel_sequence"] or 0)
		]
	return messages


@frappe.whitelist()
def get_thread(message_name: str) -> dict:
	message = frappe.get_doc("Lexocrates Chat Message", message_name)
	frappe.has_permission("Lexocrates Chat Channel", "read", doc=message.channel, throw=True)
	root_name = message.thread_reference or message.name
	root = frappe.get_doc("Lexocrates Chat Message", root_name)
	rows = frappe.get_all(
		"Lexocrates Chat Message",
		filters={"thread_reference": root_name},
		fields=[
			"name", "channel", "channel_sequence", "client_message_id", "sender", "message_text", "sent_at", "thread_reference",
			"mentions", "job_mentions", "attachments", "system_generated", "source_doctype", "source_name",
			"edited_on", "is_pinned", "pinned_by", "pinned_at",
		],
		order_by="channel_sequence asc",
		limit_page_length=200,
	)
	all_rows = [root.as_dict()] + rows
	identities = _sender_identities(all_rows)
	return {
		"root": root_name,
		"messages": _enrich_messages(
			[serialize_message(row, sender_identity=identities.get(row.sender)) for row in all_rows]
		),
	}


@frappe.whitelist()
def mark_channel_read(channel: str, message_name: str | None = None) -> dict:
	frappe.has_permission("Lexocrates Chat Channel", "read", doc=channel, throw=True)
	if message_name:
		message = frappe.db.get_value(
			"Lexocrates Chat Message", message_name, ["channel", "sent_at", "channel_sequence"], as_dict=True
		)
		if not message or message.channel != channel:
			frappe.throw(_("The read marker must belong to this channel."), frappe.ValidationError)
	else:
		message = frappe.db.get_value(
			"Lexocrates Chat Message",
			{"channel": channel},
			["name", "channel", "sent_at", "channel_sequence"],
			order_by="channel_sequence desc",
			as_dict=True,
		)
		message_name = message.name if message else None
	read_at = now_datetime()
	state_rows = frappe.db.sql(
		"""
		select name, last_read_message, last_read_sequence, last_read_at
		from `tabLexocrates Chat User State`
		where channel = %s and user = %s
		for update
		""",
		(channel, frappe.session.user),
		as_dict=True,
	)
	state_row = state_rows[0] if state_rows else None
	state_name = state_row.name if state_row else None
	read_sequence = int(message.channel_sequence or 0) if message else 0
	current_sequence = int(state_row.last_read_sequence or 0) if state_row else 0
	if state_row and current_sequence >= read_sequence:
		return {
			"name": state_name,
			"channel": channel,
			"user": frappe.session.user,
			"last_read_message": state_row.last_read_message,
			"last_read_sequence": current_sequence,
			"last_read_at": str(state_row.last_read_at),
		}
	values = {
		"last_read_message": message_name,
		"last_read_sequence": read_sequence,
		"last_read_at": read_at,
	}
	if state_name:
		frappe.db.set_value("Lexocrates Chat User State", state_name, values, update_modified=True)
	else:
		savepoint = "lexocrates_chat_read_state"
		frappe.db.savepoint(savepoint)
		try:
			state = frappe.get_doc(
				{
					"doctype": "Lexocrates Chat User State",
					"channel": channel,
					"user": frappe.session.user,
					"notification_level": "All Messages",
					**values,
				}
			).insert(ignore_permissions=True)
			state_name = state.name
			frappe.db.release_savepoint(savepoint)
		except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
			frappe.db.rollback(save_point=savepoint)
			# Another tab created the one-row-per-user state while this request waited.
			return mark_channel_read(channel, message_name)
	payload = {
		"channel": channel,
		"user": frappe.session.user,
		"last_read_message": message_name,
		"last_read_sequence": read_sequence,
		"last_read_at": str(read_at),
	}
	frappe.publish_realtime(
		"chat_read_receipt",
		payload,
		room=f"doc:Lexocrates Chat Channel/{channel}",
		after_commit=True,
	)
	return {"name": state_name, **payload}


@frappe.whitelist()
def set_channel_preferences(
	channel: str,
	notification_level: str = "All Messages",
) -> dict:
	frappe.has_permission("Lexocrates Chat Channel", "read", doc=channel, throw=True)
	allowed = {"All Messages", "Mentions Only", "Muted"}
	if notification_level not in allowed:
		frappe.throw(_("Invalid notification preference."), frappe.ValidationError)
	state_name = frappe.db.get_value(
		"Lexocrates Chat User State", {"channel": channel, "user": frappe.session.user}, "name"
	)
	values = {
		"notification_level": notification_level,
		"muted": notification_level == "Muted",
	}
	if state_name:
		frappe.db.set_value("Lexocrates Chat User State", state_name, values)
	else:
		state = frappe.get_doc(
			{
				"doctype": "Lexocrates Chat User State",
				"channel": channel,
				"user": frappe.session.user,
				**values,
			}
		).insert(ignore_permissions=True)
		state_name = state.name
	return {"name": state_name, **values}


@frappe.whitelist()
def toggle_reaction(message_name: str, emoji: str) -> dict:
	if emoji not in ALLOWED_REACTIONS:
		frappe.throw(_("This reaction is not supported."), frappe.ValidationError)
	message = frappe.get_doc("Lexocrates Chat Message", message_name)
	frappe.has_permission("Lexocrates Chat Channel", "read", doc=message.channel, throw=True)
	existing = frappe.db.get_value(
		"Lexocrates Chat Reaction",
		{"message": message_name, "user": frappe.session.user, "emoji": emoji},
		"name",
	)
	if existing:
		frappe.delete_doc("Lexocrates Chat Reaction", existing, ignore_permissions=True)
		active = False
	else:
		frappe.get_doc(
			{
				"doctype": "Lexocrates Chat Reaction",
				"message": message_name,
				"channel": message.channel,
				"emoji": emoji,
			}
		).insert(ignore_permissions=True)
		active = True
	payload = _reaction_payload(message_name, message.channel)
	payload.update({"actor": frappe.session.user, "emoji": emoji, "active": active})
	frappe.publish_realtime(
		"chat_reaction_changed",
		payload,
		room=f"doc:Lexocrates Chat Channel/{message.channel}",
		after_commit=True,
	)
	return payload


def _reaction_payload(message_name: str, channel: str) -> dict:
	rows = frappe.get_all(
		"Lexocrates Chat Reaction",
		filters={"message": message_name},
		fields=["user", "emoji"],
		order_by="reacted_at asc",
		limit_page_length=0,
	)
	grouped: dict[str, list[str]] = {}
	for row in rows:
		grouped.setdefault(row.emoji, []).append(row.user)
	return {
		"message": message_name,
		"channel": channel,
		"reactions": [
			{
				"emoji": emoji,
				"count": len(users),
				"users": users,
				"reacted_by_me": frappe.session.user in users,
			}
			for emoji, users in grouped.items()
		],
	}


@frappe.whitelist()
def set_message_pinned(message_name: str, pinned: int = 1) -> dict:
	message = frappe.get_doc("Lexocrates Chat Message", message_name)
	channel = frappe.get_doc("Lexocrates Chat Channel", message.channel)
	if not can_manage_channel(channel):
		frappe.throw(_("Only channel owners and moderators can pin messages."), frappe.PermissionError)
	pinned = bool(int(pinned or 0))
	values = {
		"is_pinned": pinned,
		"pinned_by": frappe.session.user if pinned else None,
		"pinned_at": now_datetime() if pinned else None,
	}
	frappe.db.set_value("Lexocrates Chat Message", message_name, values, update_modified=False)
	message.reload()
	payload = serialize_message(message)
	frappe.publish_realtime(
		"chat_message_pinned",
		payload,
		room=f"doc:Lexocrates Chat Channel/{message.channel}",
		after_commit=True,
	)
	return payload


@frappe.whitelist()
def get_pinned_messages(channel: str) -> list[dict]:
	frappe.has_permission("Lexocrates Chat Channel", "read", doc=channel, throw=True)
	rows = frappe.get_all(
		"Lexocrates Chat Message",
		filters={"channel": channel, "is_pinned": 1},
		fields=[
			"name", "channel", "channel_sequence", "client_message_id", "sender", "message_text", "sent_at", "thread_reference",
			"mentions", "job_mentions", "attachments", "system_generated", "source_doctype", "source_name",
			"edited_on", "is_pinned", "pinned_by", "pinned_at",
		],
		order_by="pinned_at desc",
		limit_page_length=100,
	)
	identities = _sender_identities(rows)
	return _enrich_messages(
		[serialize_message(row, sender_identity=identities.get(row.sender)) for row in rows]
	)


@frappe.whitelist()
def publish_typing(channel: str, is_typing: int = 1) -> dict:
	channel_doc = frappe.get_doc("Lexocrates Chat Channel", channel)
	if not can_view_channel(channel_doc):
		frappe.throw(_("You cannot access this channel."), frappe.PermissionError)
	payload = {
		"channel": channel,
		"user": frappe.session.user,
		"full_name": frappe.db.get_value("User", frappe.session.user, "full_name")
		or frappe.session.user,
		"is_typing": bool(int(is_typing or 0)),
	}
	frappe.publish_realtime(
		"chat_typing",
		payload,
		room=f"doc:Lexocrates Chat Channel/{channel}",
	)
	return payload


def _sender_identities(rows) -> dict[str, dict]:
	senders = {row.sender for row in rows if row.sender}
	return {sender: get_user_chat_identity(sender) for sender in senders}


def create_system_message(
	channel: str,
	message_text: str,
	*,
	source_doctype: str | None = None,
	source_name: str | None = None,
	automation_key: str | None = None,
	thread_reference: str | None = None,
	attachments=None,
) -> dict | None:
	if automation_key and frappe.db.exists(
		"Lexocrates Chat Message", {"automation_key": automation_key}
	):
		return None
	previous_flag = getattr(frappe.flags, "lexocrates_chat_automation", False)
	frappe.flags.lexocrates_chat_automation = True
	try:
		doc = frappe.get_doc(
			{
				"doctype": "Lexocrates Chat Message",
				"channel": channel,
				"message_text": message_text,
				"thread_reference": thread_reference,
				"attachments": json.dumps(parse_json_list(attachments)),
				"system_generated": 1,
				"source_doctype": source_doctype,
				"source_name": source_name,
				"automation_key": automation_key,
			}
		).insert(ignore_permissions=True)
	finally:
		frappe.flags.lexocrates_chat_automation = previous_flag
	return serialize_message(doc)


def _send_mention_notification(message_doc, user: str):
	"""Create a system Notification Log and trigger realtime alert for mentioned user."""
	try:
		if not user or not frappe.db.exists("User", user):
			return

		channel_doc = frappe.get_cached_doc("Lexocrates Chat Channel", message_doc.channel)
		sender_name = frappe.db.get_value("User", message_doc.sender, "full_name") or message_doc.sender
		channel_title = channel_doc.display_name or channel_doc.channel_name
		subject = _("{0} mentioned you in #{1}").format(sender_name, channel_title)

		# Create standard Frappe Notification Log
		notification = frappe.get_doc({
			"doctype": "Notification Log",
			"subject": subject,
			"for_user": user,
			"from_user": message_doc.sender,
			"type": "Mention",
			"document_type": "Lexocrates Chat Message",
			"document_name": message_doc.name,
			"email_content": message_doc.message_text,
		})
		notification.flags.ignore_permissions = True
		notification.insert(ignore_permissions=True)
	except Exception as e:
		frappe.log_error(f"Failed to create Notification Log for mention: {e}", "Lexocrates Chat Mention")
