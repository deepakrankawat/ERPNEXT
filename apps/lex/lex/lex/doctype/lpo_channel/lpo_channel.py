from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


ALLOWED_REFERENCE_DOCTYPES = {"LPO Matter", "LPO Job"}
LPO_ACCESS_ROLES = {"LPO_Admin", "LPO_Manager", "LPO_Analyst", "System Manager"}


class LPOChannel(Document):
	def validate(self):
		_validate_reference(self.reference_doctype, self.reference_name)
		self._validate_unique_reference()
		self._validate_members()

	def _validate_unique_reference(self):
		filters = {
			"reference_doctype": self.reference_doctype,
			"reference_name": self.reference_name,
		}
		existing = frappe.db.get_value("LPO Channel", filters, "name")
		if existing and existing != self.name:
			frappe.throw(
				_("Channel {0} already exists for this operational record.").format(
					frappe.bold(existing)
				),
				frappe.DuplicateEntryError,
			)

	def _validate_members(self):
		if not self.members:
			role = "Admin" if _is_lpo_manager(frappe.session.user) else "Participant"
			self.append("members", {"user": frappe.session.user, "role": role})

		seen = set()
		for member in self.members:
			if member.user in seen:
				frappe.throw(_("User {0} is listed more than once.").format(frappe.bold(member.user)))
			seen.add(member.user)


def on_doctype_update():
	# One contextual record owns one channel. The database constraint also closes
	# the race between two simultaneous first-page loads.
	frappe.db.add_unique("LPO Channel", ("reference_doctype", "reference_name"))


def _validate_reference(reference_doctype: str, reference_name: str, user: str | None = None):
	user = user or frappe.session.user
	if reference_doctype not in ALLOWED_REFERENCE_DOCTYPES:
		frappe.throw(
			_("Channels may only reference LPO Matter or LPO Job records."),
			frappe.ValidationError,
		)

	if not frappe.db.exists("DocType", reference_doctype):
		frappe.throw(
			_("DocType {0} is not installed yet.").format(frappe.bold(reference_doctype)),
			frappe.DoesNotExistError,
		)

	if not frappe.db.exists(reference_doctype, reference_name):
		frappe.throw(
			_("{0} {1} does not exist.").format(reference_doctype, frappe.bold(reference_name)),
			frappe.DoesNotExistError,
		)

	# Membership never substitutes for access to the underlying legal record.
	# This makes a revoked Job/Engagement permission take effect immediately.
	frappe.has_permission(reference_doctype, "read", doc=reference_name, user=user, throw=True)


def _is_lpo_manager(user: str) -> bool:
	roles = set(frappe.get_roles(user))
	return user == "Administrator" or bool(
		roles.intersection({"LPO_Admin", "LPO_Manager", "System Manager"})
	)


def _assert_lpo_user(user: str):
	if user == "Administrator":
		return
	if not set(frappe.get_roles(user)).intersection(LPO_ACCESS_ROLES):
		frappe.throw(_("An LPO role is required to use contextual messaging."), frappe.PermissionError)


@frappe.whitelist()
def get_or_create_channel(reference_doctype: str, reference_name: str) -> dict:
	"""Return the contextual channel, creating it only on the first access."""
	user = frappe.session.user
	_assert_lpo_user(user)
	_validate_reference(reference_doctype, reference_name, user=user)

	filters = {"reference_doctype": reference_doctype, "reference_name": reference_name}
	channel_name = frappe.db.get_value("LPO Channel", filters, "name")
	if channel_name:
		frappe.has_permission("LPO Channel", "read", doc=channel_name, user=user, throw=True)
		return _channel_summary(channel_name)

	member_role = "Admin" if _is_lpo_manager(user) else "Participant"
	channel = frappe.get_doc(
		{
			"doctype": "LPO Channel",
			"channel_name": f"{reference_doctype}: {reference_name}"[:140],
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"status": "Active",
			"members": [{"user": user, "role": member_role}],
		}
	)

	# Analysts cannot manually create arbitrary channels, but this narrow endpoint
	# can create the one channel for a record they are already allowed to read.
	try:
		channel.insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		# A concurrent browser tab may have won the unique-reference race.
		channel_name = frappe.db.get_value("LPO Channel", filters, "name")
		if not channel_name:
			raise
		frappe.has_permission("LPO Channel", "read", doc=channel_name, user=user, throw=True)
		return _channel_summary(channel_name)

	return _channel_summary(channel.name)


@frappe.whitelist()
def get_channel_history(channel_name: str) -> list[dict]:
	"""Return the newest 200 records in chronological display order."""
	frappe.has_permission("LPO Channel", "read", doc=channel_name, throw=True)

	rows = frappe.db.get_all(
		"LPO Message",
		filters={"channel": channel_name},
		fields=["name", "channel", "sender", "content", "timestamp"],
		order_by="timestamp desc, creation desc",
		limit_page_length=200,
	)
	rows.reverse()

	senders = {row.sender for row in rows if row.sender}
	full_names = {
		row.name: row.full_name
		for row in frappe.db.get_all(
			"User",
			filters={"name": ("in", tuple(senders))},
			fields=["name", "full_name"],
		)
	} if senders else {}

	from lex.lex.doctype.lpo_message.lpo_message import serialize_message

	return [serialize_message(row, full_names.get(row.sender)) for row in rows]


def _channel_summary(channel_name: str) -> dict:
	return frappe.db.get_value(
		"LPO Channel",
		channel_name,
		["name", "channel_name", "reference_doctype", "reference_name", "status"],
		as_dict=True,
	)


def has_permission(doc, ptype="read", user=None, debug=False):
	"""Restrict document and Socket.IO room access to explicit members."""
	user = user or frappe.session.user
	if ptype == "delete":
		return False
	if user == "Administrator" or set(frappe.get_roles(user)).intersection({"LPO_Admin", "System Manager"}):
		return True

	member_role = next((row.role for row in doc.members if row.user == user), None)
	if not member_role:
		return False

	if ptype in {"write", "share"} and member_role != "Admin":
		return False

	if doc.reference_doctype and doc.reference_name:
		return frappe.has_permission(
			doc.reference_doctype,
			"read",
			doc=doc.reference_name,
			user=user,
			debug=debug,
		)
	return False


def get_permission_query_conditions(user=None):
	"""Apply membership filtering to list/report queries as well as document reads."""
	user = user or frappe.session.user
	if user == "Administrator" or set(frappe.get_roles(user)).intersection({"LPO_Admin", "System Manager"}):
		return ""

	user = frappe.db.escape(user)
	return f"""
		exists (
			select 1
			from `tabLPO Channel Member` member
			where member.parent = `tabLPO Channel`.name
				and member.parenttype = 'LPO Channel'
				and member.user = {user}
		)
	"""
