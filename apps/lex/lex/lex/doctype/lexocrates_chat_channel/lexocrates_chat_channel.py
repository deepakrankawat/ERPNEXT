from __future__ import annotations

import json
import hashlib
import re
from typing import Iterable

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now_datetime, strip_html

from lex.client_access import get_portal_user


CLIENT_ROLE = "Lexocrates Client"
INTERNAL_CHAT_ROLES = {
	"CEO",
	"LPO_Admin",
	"LPO_Manager",
	"LPO_Analyst",
	"System Manager",
	"Junior Legal Associate",
	"Senior Legal Associate",
	"Lexocrates QA Manager",
	"Lexocrates Operations Manager",
	"Lexocrates AI Manager",
	"Lexocrates Sales & Marketing",
	"Lexocrates HR",
	"Lexocrates Compliance Officer",
	"Lexocrates Finance",
	"Lexocrates Director",
}
APP_ROLES = INTERNAL_CHAT_ROLES | {CLIENT_ROLE}
MATTER_CONTEXT_DOCTYPES = {"LPO Matter"}
MANAGEMENT_ROLES = {
	"LPO_Admin",
	"LPO_Manager",
	"System Manager",
	"Senior Legal Associate",
	"Lexocrates QA Manager",
	"Lexocrates Operations Manager",
	"Lexocrates Compliance Officer",
	"Lexocrates Director",
}
CONTEXT_DOCTYPES = {
	"LPO Matter",
	"LPO Job",
	"LPO QA Review",
	"AI Job Request",
	"LPO AI Job Request",
}
CHANNEL_NAME_PATTERN = re.compile(r"^#[a-z0-9][a-z0-9._-]{1,79}$")
CHAT_ROLE_PRIORITY = (
	"CEO",
	"Lexocrates Director",
	"LPO_Admin",
	"LPO_Manager",
	"Lexocrates Operations Manager",
	"Senior Legal Associate",
	"Junior Legal Associate",
	"Lexocrates QA Manager",
	"Lexocrates Compliance Officer",
	"Lexocrates AI Manager",
	"Lexocrates Finance",
	"Lexocrates Sales & Marketing",
	"Lexocrates HR",
	"LPO_Analyst",
	"System Manager",
	"Sales Manager",
	"Accounts Manager",
	"HR Manager",
	"Projects Manager",
	"Support Manager",
	"Quality Manager",
	"Sales User",
	"Accounts User",
	"Employee",
	"Lexocrates Client Administrator",
	"Lexocrates Partner General Counsel",
	"Lexocrates Operations User",
	"Lexocrates Legal User",
	"Lexocrates Compliance User",
	"Lexocrates Finance User",
	"Lexocrates Procurement User",
	"Lexocrates Read Only User",
	"Lexocrates Client",
)
GENERIC_ROLES = {
	"All",
	"Desk User",
	"Guest",
	"Website Manager",
	"Report Manager",
	"Translator",
	"Prepared Report User",
}


class LexocratesChatChannel(Document):
	def validate(self):
		self.channel_name = normalize_channel_name(self.channel_name)
		self.description = frappe.utils.sanitize_html(
			self.description or "",
			linkify=True,
			always_sanitize=True,
			disallowed_tags=["form", "input", "button", "script", "style", "iframe"],
		)
		self._validate_reference()
		self._validate_members()
		self._validate_direct_message()

	def _validate_direct_message(self):
		if not self.is_direct_message:
			self.direct_message_key = None
			return
		if self.channel_type != "Private" or len(self.members) != 2:
			frappe.throw(
				_("A direct-message channel must be private and contain exactly two members."),
				frappe.ValidationError,
			)
		users = sorted(member.user for member in self.members)
		if not all(is_enabled_system_user(user) for user in users):
			frappe.throw(
				_("Direct messages are available only between enabled System Users."),
				frappe.PermissionError,
			)
		self.system_user_only = 1
		self.direct_message_key = hashlib.sha256("|".join(users).encode()).hexdigest()

	def _validate_reference(self):
		if self.channel_type != "Contextual":
			self.reference_doctype = None
			self.reference_name = None
			return

		if not self.reference_doctype or not self.reference_name:
			frappe.throw(
				_("Reference DocType and Reference Name are mandatory for a contextual channel."),
				frappe.MandatoryError,
			)
		if self.reference_doctype not in CONTEXT_DOCTYPES:
			frappe.throw(
				_("{0} is not an approved chat context.").format(frappe.bold(self.reference_doctype)),
				frappe.ValidationError,
			)
		if not frappe.db.exists("DocType", self.reference_doctype):
			frappe.throw(
				_("DocType {0} is not installed.").format(frappe.bold(self.reference_doctype)),
				frappe.DoesNotExistError,
			)
		if not frappe.db.exists(self.reference_doctype, self.reference_name):
			frappe.throw(
				_("{0} {1} does not exist.").format(
					self.reference_doctype, frappe.bold(self.reference_name)
				),
				frappe.DoesNotExistError,
			)
		if not getattr(frappe.flags, "lexocrates_chat_automation", False):
			frappe.has_permission(
				self.reference_doctype,
				"read",
				doc=self.reference_name,
				user=frappe.session.user,
				throw=True,
			)

		filters = {
			"channel_type": "Contextual",
			"reference_doctype": self.reference_doctype,
			"reference_name": self.reference_name,
		}
		existing = frappe.db.get_value("Lexocrates Chat Channel", filters, "name")
		if existing and existing != self.name:
			frappe.throw(
				_("Contextual channel {0} already exists for this record.").format(
					frappe.bold(existing)
				),
				frappe.DuplicateEntryError,
			)

	def _validate_members(self):
		if not self.members and frappe.session.user != "Guest":
			self.append(
				"members",
				{
					"user": frappe.session.user,
					"channel_role": "Owner",
					"can_post_messages": 1,
					"can_invite_members": 1,
					"joined_on": now_datetime(),
				},
			)

		seen = set()
		has_owner = False
		for member in self.members:
			if member.user in seen:
				frappe.throw(
					_("User {0} is listed more than once.").format(frappe.bold(member.user)),
					frappe.ValidationError,
				)
			seen.add(member.user)
			if not frappe.db.get_value("User", member.user, "enabled"):
				frappe.throw(
					_("Channel member {0} must be an enabled user.").format(
						frappe.bold(member.user)
					),
					frappe.ValidationError,
				)
			if self.get("system_user_only") and not is_enabled_system_user(member.user):
				frappe.throw(
					_("Internal team channels can contain enabled System Users only: {0}.").format(
						frappe.bold(member.user)
					),
					frappe.PermissionError,
				)
			if (
				member.user != "Administrator"
				and not is_enabled_system_user(member.user)
				and not APP_ROLES.intersection(frappe.get_roles(member.user))
			):
				frappe.throw(
					_("Channel member {0} must have an approved Lexocrates role.").format(
						frappe.bold(member.user)
					),
					frappe.ValidationError,
				)
			if member.channel_role == "Owner":
				has_owner = True
				member.can_post_messages = 1
				member.can_invite_members = 1
			elif member.channel_role == "Read Only":
				member.can_post_messages = 0
				member.can_invite_members = 0
			elif member.channel_role == "Moderator":
				member.can_post_messages = 1
				member.can_invite_members = 1
			if not member.joined_on:
				member.joined_on = now_datetime()

		if self.channel_type in {"Private", "Contextual"} and not has_owner:
			frappe.throw(
				_("Private and contextual channels require at least one Owner."),
				frappe.ValidationError,
			)

	def on_trash(self):
		if frappe.db.exists("Lexocrates Chat Message", {"channel": self.name}):
			frappe.throw(
				_("Channels containing audited messages cannot be deleted. Archive the channel instead."),
				frappe.PermissionError,
			)


def on_doctype_update():
	frappe.db.add_unique(
		"Lexocrates Chat Channel",
		("reference_doctype", "reference_name"),
		constraint_name="lexocrates_chat_context_unique",
	)
	frappe.db.add_index(
		"Lexocrates Chat Channel",
		["status", "last_message_at"],
		index_name="lexocrates_chat_channel_activity",
	)


def normalize_channel_name(value: str) -> str:
	value = strip_html(value or "").strip().lower().replace(" ", "-")
	if not value.startswith("#"):
		value = f"#{value}"
	value = re.sub(r"-+", "-", value)
	if not CHANNEL_NAME_PATTERN.fullmatch(value):
		frappe.throw(
			_("Channel names must use # followed by 2-80 lowercase letters, numbers, dots, dashes, or underscores."),
			frappe.ValidationError,
		)
	return value


def _roles(user: str) -> set[str]:
	return set(frappe.get_roles(user))


def is_management_user(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(_roles(user).intersection(MANAGEMENT_ROLES))


def is_chat_user(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return bool(is_enabled_system_user(user) or _roles(user).intersection(APP_ROLES))


def is_enabled_system_user(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False
	account = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
	return bool(account and account.enabled and account.user_type == "System User")


def can_start_direct_message(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return bool(is_enabled_system_user(user) and is_chat_user(user))


def is_client_only_user(user: str | None = None) -> bool:
	user = user or frappe.session.user
	roles = _roles(user)
	return CLIENT_ROLE in roles and not roles.intersection(INTERNAL_CHAT_ROLES)


@frappe.request_cache
def get_user_chat_identity(user: str) -> dict:
	"""Return the canonical name and business-role label used throughout chat."""
	account = frappe.db.get_value(
		"User", user, ["name", "full_name", "user_image", "user_type"], as_dict=True
	)
	if not account:
		return frappe._dict({
			"name": user,
			"full_name": user,
			"user_image": None,
			"user_type": None,
			"primary_role": _("Unknown user"),
			"roles": [],
		})

	roles = [role for role in frappe.get_roles(user) if role not in GENERIC_ROLES]
	if user == "Administrator":
		primary_role = _("Administrator")
		ordered_roles = [primary_role]
	else:
		primary_role = next((role for role in CHAT_ROLE_PRIORITY if role in roles), None)
		if not primary_role:
			primary_role = sorted(roles)[0] if roles else account.user_type or _("User")
		ordered_roles = [role for role in CHAT_ROLE_PRIORITY if role in roles]
		if not ordered_roles:
			ordered_roles = [primary_role]
	return frappe._dict({
		"name": account.name,
		"full_name": account.full_name or account.name,
		"user_image": account.user_image,
		"user_type": account.user_type,
		"primary_role": primary_role,
		"roles": ordered_roles,
	})


def _member_row(doc, user: str):
	return next((member for member in doc.members if member.user == user), None)


def can_view_channel(doc, user: str | None = None, debug: bool = False) -> bool:
	user = user or frappe.session.user
	if not is_chat_user(user):
		return False

	member = _member_row(doc, user)
	if doc.get("is_direct_message"):
		return bool(
			member
			and can_start_direct_message(user)
			and all(can_start_direct_message(row.user) for row in doc.members)
		)
	# Clients are isolated from all internal/global channels. They only enter a
	# deliberately provisioned private or client-owned contextual channel.
	if is_client_only_user(user):
		if not member:
			return False
		if doc.channel_type == "Private":
			return True
		return bool(
			doc.channel_type == "Contextual"
			and doc.reference_doctype in {"LPO Matter", "LPO Job"}
			and doc.reference_name
			and frappe.has_permission(
				doc.reference_doctype,
				"read",
				doc=doc.reference_name,
				user=user,
				debug=debug,
			)
		)
	if is_management_user(user):
		return True
	if doc.channel_type != "Public" and not member:
		return False
	if doc.channel_type == "Contextual":
		if not doc.reference_doctype or not doc.reference_name:
			return False
		return bool(
			frappe.has_permission(
				doc.reference_doctype,
				"read",
				doc=doc.reference_name,
				user=user,
				debug=debug,
			)
		)
	return True


def can_post_to_channel(doc, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if doc.status != "Active" or not can_view_channel(doc, user=user):
		return False
	if is_management_user(user):
		return True
	member = _member_row(doc, user)
	if doc.channel_type == "Public" and not member:
		return True
	return bool(
		member
		and member.channel_role != "Read Only"
		and member.can_post_messages
	)


def can_manage_channel(doc, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if is_management_user(user):
		return True
	member = _member_row(doc, user)
	return bool(
		member
		and member.channel_role in {"Owner", "Moderator"}
		and member.can_invite_members
	)


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if ptype == "create":
		return is_management_user(user)
	if ptype == "delete":
		return False
	if ptype in {"write", "share"}:
		return can_manage_channel(doc, user=user)
	return can_view_channel(doc, user=user, debug=debug)


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if is_management_user(user):
		return ""
	if not is_chat_user(user):
		return "1=0"

	escaped_user = frappe.db.escape(user)
	if is_client_only_user(user):
		portal_user = get_portal_user(user)
		if not portal_user:
			return "1=0"
		client = frappe.db.escape(portal_user.client)
		portal_user_name = frappe.db.escape(portal_user.name)
		if portal_user.matter_access_scope == "All Client Matters":
			matter_access = "1=1"
		elif portal_user.matter_access_scope == "No Matter Access":
			matter_access = "1=0"
		else:
			matter_access = f"""
				exists (
					select 1 from `tabLexocrates Matter Authorization` authorization
					where authorization.parent = engagement.name
						and authorization.parenttype = 'LPO Matter'
						and authorization.parentfield = 'authorized_portal_users'
						and authorization.portal_user = {portal_user_name}
						and authorization.can_view = 1
				)
			"""
		return f"""
			exists (
				select 1 from `tabLexocrates Chat Member` member
				where member.parent = `tabLexocrates Chat Channel`.name
					and member.parenttype = 'Lexocrates Chat Channel'
					and member.user = {escaped_user}
			)
			and (
				`tabLexocrates Chat Channel`.channel_type = 'Private'
				or (
					`tabLexocrates Chat Channel`.channel_type = 'Contextual'
					and (
						(`tabLexocrates Chat Channel`.reference_doctype = 'LPO Matter'
							and exists (
								select 1 from `tabLPO Matter` engagement
								where engagement.name = `tabLexocrates Chat Channel`.reference_name
									and engagement.customer = {client}
									and ({matter_access})
							))
						or (`tabLexocrates Chat Channel`.reference_doctype = 'LPO Job'
							and exists (
								select 1 from `tabLPO Job` job
								inner join `tabLPO Matter` engagement on engagement.name = job.engagement
								where job.name = `tabLexocrates Chat Channel`.reference_name
									and job.customer = {client}
									and ({matter_access})
							))
					)
				)
			)
		"""
	return f"""
		(
			`tabLexocrates Chat Channel`.channel_type = 'Public'
			or (
			exists (
				select 1 from `tabLexocrates Chat Member` member
				where member.parent = `tabLexocrates Chat Channel`.name
					and member.parenttype = 'Lexocrates Chat Channel'
					and member.user = {escaped_user}
			)
			and (
				`tabLexocrates Chat Channel`.channel_type = 'Private'
				or (
					`tabLexocrates Chat Channel`.channel_type = 'Contextual'
					and (
						(`tabLexocrates Chat Channel`.reference_doctype = 'LPO Job'
							and exists (
								select 1 from `tabLPO Job` job
								where job.name = `tabLexocrates Chat Channel`.reference_name
									and job.assigned_analyst = {escaped_user}
							))
						or (`tabLexocrates Chat Channel`.reference_doctype = 'LPO QA Review'
							and exists (
								select 1 from `tabLPO QA Review` review
								left join `tabLPO Job` job on job.name = review.job
								where review.name = `tabLexocrates Chat Channel`.reference_name
									and (review.reviewer = {escaped_user} or job.assigned_analyst = {escaped_user})
							))
					)
				)
			)
			)
		)
	"""


def _parse_members(members) -> list[dict]:
	if not members:
		return []
	if isinstance(members, str):
		members = json.loads(members)
	if not isinstance(members, list):
		frappe.throw(_("Members must be supplied as a list."), frappe.ValidationError)

	parsed = []
	for item in members:
		if isinstance(item, str):
			item = {"user": item}
		parsed.append(
			{
				"user": item.get("user"),
				"channel_role": item.get("channel_role") or "Member",
				"can_post_messages": item.get("can_post_messages", 1),
				"can_invite_members": item.get("can_invite_members", 0),
				"joined_on": now_datetime(),
			}
		)
	return parsed


@frappe.whitelist()
def create_channel(
	channel_name: str,
	channel_type: str = "Public",
	description: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	members=None,
	system_user_only: int = 0,
) -> dict:
	if not is_management_user():
		frappe.throw(_("Only LPO managers can create channels."), frappe.PermissionError)

	member_rows = _parse_members(members)
	if frappe.session.user not in {row.get("user") for row in member_rows}:
		member_rows.insert(
			0,
			{
				"user": frappe.session.user,
				"channel_role": "Owner",
				"can_post_messages": 1,
				"can_invite_members": 1,
				"joined_on": now_datetime(),
			},
		)

	doc = frappe.get_doc(
		{
			"doctype": "Lexocrates Chat Channel",
			"channel_name": channel_name,
			"channel_type": channel_type,
			"status": "Active",
			"description": description,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"system_user_only": cint(system_user_only),
			"members": member_rows,
		}
	).insert()
	return serialize_channel(doc)


def ensure_contextual_channel(
	reference_doctype: str,
	reference_name: str,
	members: Iterable[str] | None = None,
) -> "LexocratesChatChannel":
	filters = {
		"channel_type": "Contextual",
		"reference_doctype": reference_doctype,
		"reference_name": reference_name,
	}
	channel_name = frappe.db.get_value("Lexocrates Chat Channel", filters, "name")
	if channel_name:
		channel = frappe.get_doc("Lexocrates Chat Channel", channel_name)
	else:
		member_users = [user for user in dict.fromkeys(members or []) if user]
		if "Administrator" not in member_users:
			member_users.insert(0, "Administrator")
		rows = []
		for index, user in enumerate(member_users):
			rows.append(
				{
					"user": user,
					"channel_role": "Owner" if index == 0 else "Member",
					"can_post_messages": 1,
					"can_invite_members": 1 if index == 0 else 0,
					"joined_on": now_datetime(),
				}
			)
		channel_label = normalize_channel_name(f"{reference_doctype}-{reference_name}")
		previous_flag = getattr(frappe.flags, "lexocrates_chat_automation", False)
		frappe.flags.lexocrates_chat_automation = True
		try:
			channel = frappe.get_doc(
				{
					"doctype": "Lexocrates Chat Channel",
					"channel_name": channel_label,
					"channel_type": "Contextual",
					"status": "Active",
					"description": _("Secure discussion linked to {0} {1}.").format(
						reference_doctype, reference_name
					),
					"reference_doctype": reference_doctype,
					"reference_name": reference_name,
					"members": rows,
				}
			).insert(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			channel_name = frappe.db.get_value("Lexocrates Chat Channel", filters, "name")
			if not channel_name:
				raise
			channel = frappe.get_doc("Lexocrates Chat Channel", channel_name)
		finally:
			frappe.flags.lexocrates_chat_automation = previous_flag

	_add_missing_members(channel, members or [])
	return channel


def _add_missing_members(channel, users: Iterable[str]):
	existing = {member.user for member in channel.members}
	changed = False
	for user in dict.fromkeys(users):
		if not user or user in existing or not frappe.db.get_value("User", user, "enabled"):
			continue
		if user != "Administrator" and not APP_ROLES.intersection(frappe.get_roles(user)):
			continue
		channel.append(
			"members",
			{
				"user": user,
				"channel_role": "Member",
				"can_post_messages": 1,
				"can_invite_members": 0,
				"joined_on": now_datetime(),
			},
		)
		existing.add(user)
		changed = True
	if changed:
		previous_flag = getattr(frappe.flags, "lexocrates_chat_automation", False)
		frappe.flags.lexocrates_chat_automation = True
		try:
			channel.save(ignore_permissions=True)
		finally:
			frappe.flags.lexocrates_chat_automation = previous_flag


@frappe.whitelist()
def get_channels(search_text: str | None = None) -> list[dict]:
	if not is_chat_user():
		frappe.throw(_("An LPO role is required to use Lexocrates Chat."), frappe.PermissionError)

	rows = frappe.get_all(
		"Lexocrates Chat Channel",
		fields=[
			"name",
			"channel_name",
			"channel_type",
			"status",
			"description",
			"reference_doctype",
			"reference_name",
			"last_message_at",
		],
		order_by="coalesce(last_message_at, creation) desc, channel_name asc",
		limit_page_length=200,
	)
	result = []
	for row in rows:
		if row.reference_doctype == "LPO Job" and row.status == "Archived":
			continue
		doc = frappe.get_doc("Lexocrates Chat Channel", row.name)
		if can_view_channel(doc):
			result.append(serialize_channel(doc))
	if search_text and search_text.strip():
		needle = search_text.strip().casefold()
		result = [channel for channel in result if _channel_matches_search(channel, needle)]
	return _decorate_channel_states(result)


def _channel_matches_search(channel: dict, needle: str) -> bool:
	haystack = " ".join(
		str(channel.get(field) or "")
		for field in (
			"channel_name",
			"display_name",
			"reference_name",
			"matter_id",
			"matter_title",
			"organization_id",
			"organization_name",
		)
	).casefold()
	return needle in haystack


def _decorate_channel_states(channels: list[dict], user: str | None = None) -> list[dict]:
	if not channels:
		return channels
	user = user or frappe.session.user
	channel_names = [channel["name"] for channel in channels]
	states = frappe.get_all(
		"Lexocrates Chat User State",
		filters={"user": user, "channel": ["in", channel_names]},
		fields=["channel", "last_read_at", "last_read_sequence", "muted", "notification_level"],
		limit_page_length=0,
	)
	state_map = {state.channel: state for state in states}
	placeholders = ", ".join(["%s"] * len(channel_names))
	unread_rows = frappe.db.sql(
		f"""
		select message.channel, count(message.name) as unread_count
		from `tabLexocrates Chat Message` message
		left join `tabLexocrates Chat User State` state
			on state.channel = message.channel and state.user = %s
		where message.channel in ({placeholders})
			and message.sender != %s
			and message.channel_sequence > coalesce(state.last_read_sequence, 0)
		group by message.channel
		""",
		[user, *channel_names, user],
		as_dict=True,
	)
	unread_map = {row.channel: int(row.unread_count or 0) for row in unread_rows}
	for channel in channels:
		state = state_map.get(channel["name"])
		channel["unread_count"] = unread_map.get(channel["name"], 0)
		channel["last_read_at"] = str(state.last_read_at) if state and state.last_read_at else None
		channel["last_read_sequence"] = int(state.last_read_sequence or 0) if state else 0
		channel["notification_level"] = (
			state.notification_level if state else "All Messages"
		)
		channel["muted"] = bool(state.muted) if state else False
	return channels


def serialize_channel(doc) -> dict:
	if isinstance(doc, str):
		doc = frappe.get_doc("Lexocrates Chat Channel", doc)
	display_name = doc.channel_name
	direct_user = None
	direct_user_image = None
	direct_user_role = None
	if doc.get("is_direct_message"):
		other = next((member.user for member in doc.members if member.user != frappe.session.user), None)
		if other:
			direct_user = other
			identity = get_user_chat_identity(other)
			display_name = identity["full_name"]
			direct_user_image = identity["user_image"]
			direct_user_role = identity["primary_role"]
	channel = {
		"name": doc.name,
		"channel_name": doc.channel_name,
		"channel_type": doc.channel_type,
		"status": doc.status,
		"description": doc.description,
		"reference_doctype": doc.reference_doctype,
		"reference_name": doc.reference_name,
		"last_message_at": str(doc.last_message_at) if doc.last_message_at else None,
		"is_direct_message": bool(doc.get("is_direct_message")),
		"system_user_only": bool(doc.get("system_user_only") or doc.get("is_direct_message")),
		"display_name": display_name,
		"direct_user": direct_user,
		"direct_user_image": direct_user_image,
		"direct_user_role": direct_user_role,
		"member_count": len(doc.members),
		"can_post": can_post_to_channel(doc),
		"can_manage": can_manage_channel(doc),
		"unread_count": 0,
		"notification_level": "All Messages",
		"muted": False,
	}
	channel.update(_get_matter_context(doc.reference_doctype, doc.reference_name))
	return channel


@frappe.whitelist()
def get_channel_members(channel: str) -> list[dict]:
	"""Return role-labelled members only to users who can view the channel."""
	doc = frappe.get_doc("Lexocrates Chat Channel", channel)
	if not can_view_channel(doc):
		frappe.throw(_("You cannot view this channel."), frappe.PermissionError)
	rows = []
	for member in doc.members:
		identity = get_user_chat_identity(member.user)
		rows.append(
			{
				**identity,
				"channel_role": member.channel_role,
				"can_post_messages": bool(member.can_post_messages),
				"can_invite_members": bool(member.can_invite_members),
			}
		)
	return sorted(
		rows,
		key=lambda row: (
			{"Owner": 0, "Moderator": 1, "Member": 2, "Read Only": 3}.get(
				row["channel_role"], 9
			),
			(row["full_name"] or row["name"]).casefold(),
		),
	)


@frappe.request_cache
def _get_matter_context(reference_doctype: str | None, reference_name: str | None) -> dict:
	context = {
		"is_matter_channel": False,
		"matter_id": None,
		"matter_title": None,
		"organization_id": None,
		"organization_name": None,
	}
	if reference_doctype not in MATTER_CONTEXT_DOCTYPES or not reference_name:
		return context

	matter = frappe.db.get_value(
		"LPO Matter",
		reference_name,
		["name", "matter_title", "customer", "customer_name"],
		as_dict=True,
	)
	if not matter:
		return context
	organization_name = matter.customer_name
	if not organization_name and matter.customer:
		organization_name = frappe.db.get_value("Customer", matter.customer, "customer_name")
	context.update(
		{
			"is_matter_channel": True,
			"matter_id": matter.name,
			"matter_title": matter.matter_title or matter.name,
			"organization_id": matter.customer,
			"organization_name": organization_name or matter.customer,
		}
	)
	return context


@frappe.whitelist()
def get_or_create_direct_channel(other_user: str) -> dict:
	current_user = frappe.session.user
	if not can_start_direct_message(current_user):
		frappe.throw(
			_("Direct messages are available only to enabled System Users with chat access."),
			frappe.PermissionError,
		)
	if not other_user or other_user == current_user:
		frappe.throw(_("Choose another chat user."), frappe.ValidationError)
	if not can_start_direct_message(other_user):
		frappe.throw(
			_("The selected user must be an enabled System User with chat access."),
			frappe.PermissionError,
		)
	users = sorted([current_user, other_user])
	direct_key = hashlib.sha256("|".join(users).encode()).hexdigest()
	existing = frappe.db.get_value(
		"Lexocrates Chat Channel", {"direct_message_key": direct_key}, "name"
	)
	if existing:
		return serialize_channel(frappe.get_doc("Lexocrates Chat Channel", existing))
	label_parts = [re.sub(r"[^a-z0-9]+", "-", user.lower()).strip("-")[:24] for user in users]
	channel = frappe.get_doc(
		{
			"doctype": "Lexocrates Chat Channel",
			"channel_name": f"#dm-{'-'.join(label_parts)}-{direct_key[:6]}",
			"channel_type": "Private",
			"status": "Active",
			"is_direct_message": 1,
			"system_user_only": 1,
			"direct_message_key": direct_key,
			"description": _("Private direct conversation."),
			"members": [
				{
					"user": user,
					"channel_role": "Owner" if user == current_user else "Member",
					"can_post_messages": 1,
					"can_invite_members": 0,
					"joined_on": now_datetime(),
				}
				for user in users
			],
		}
	).insert(ignore_permissions=True)
	return serialize_channel(channel)


def _users_share_channel(first_user: str, second_user: str) -> bool:
	return bool(
		frappe.db.sql(
			"""
			select channel.name
			from `tabLexocrates Chat Channel` channel
			inner join `tabLexocrates Chat Member` first_member
				on first_member.parent = channel.name
				and first_member.parenttype = 'Lexocrates Chat Channel'
			inner join `tabLexocrates Chat Member` second_member
				on second_member.parent = channel.name
				and second_member.parenttype = 'Lexocrates Chat Channel'
			where channel.status = 'Active'
				and first_member.user = %s
				and second_member.user = %s
			limit 1
			""",
			(first_user, second_user),
		)
	)
