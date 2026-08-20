from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe
from frappe.utils import now_datetime


def create_portal_audit_event(
	*,
	client: str,
	action: str,
	portal_user: str | None = None,
	user: str | None = None,
	matter: str | None = None,
	object_type: str | None = None,
	object_id: str | None = None,
	previous_value: Any = None,
	new_value: Any = None,
	result: str = "Success",
	details: str | None = None,
):
	"""Append one protected portal audit event without exposing insert permission."""
	if not frappe.db.exists("DocType", "Lexocrates Portal Audit Event"):
		return None
	session_id = getattr(frappe.session, "sid", None) if getattr(frappe, "session", None) else None
	previous_flag = getattr(frappe.flags, "lexocrates_portal_audit", False)
	frappe.flags.lexocrates_portal_audit = True
	try:
		return frappe.get_doc(
			{
				"doctype": "Lexocrates Portal Audit Event",
				"event_timestamp": now_datetime(),
				"client": client,
				"portal_user": portal_user,
				"user": user or (frappe.session.user if frappe.session else None),
				"matter": matter,
				"action": action,
				"object_type": object_type,
				"object_id": object_id,
				"previous_value": _json(previous_value),
				"new_value": _json(new_value),
				"ip_address": getattr(frappe.local, "request_ip", None),
				"session_id": hashlib.sha256(session_id.encode()).hexdigest()[:24] if session_id else None,
				"result": result,
				"details": details,
			}
		).insert(ignore_permissions=True)
	finally:
		frappe.flags.lexocrates_portal_audit = previous_flag


def _json(value):
	if value in (None, ""):
		return None
	return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def audit_login(login_manager=None):
	user = getattr(login_manager, "user", None) or frappe.session.user
	portal_user = _portal_user_for(user)
	if not portal_user:
		return
	create_portal_audit_event(
		client=portal_user.client,
		portal_user=portal_user.name,
		user=user,
		action="Login",
		object_type="User",
		object_id=user,
	)


def audit_logout(login_manager=None):
	user = getattr(login_manager, "user", None) or frappe.session.user
	try:
		from lex.lex.doctype.lexocrates_chat_presence.lexocrates_chat_presence import (
			mark_user_offline,
		)

		mark_user_offline(user)
	except Exception:
		# Presence must never prevent a user from signing out. The stale-presence
		# scheduler is the fallback if this best-effort transition cannot run.
		pass
	portal_user = _portal_user_for(user)
	if not portal_user:
		return
	create_portal_audit_event(
		client=portal_user.client,
		portal_user=portal_user.name,
		user=user,
		action="Logout",
		object_type="User",
		object_id=user,
	)


def sync_portal_user_security(doc, method=None):
	if not frappe.db.exists("DocType", "Lexocrates Portal User"):
		return
	portal_user = frappe.db.get_value("Lexocrates Portal User", {"user": doc.name}, "name")
	if not portal_user:
		return
	mfa_enabled = int(bool(frappe.db.get_single_value("System Settings", "enable_two_factor_auth")))
	frappe.db.set_value(
		"Lexocrates Portal User",
		portal_user,
		{"last_login": doc.last_login or None, "mfa_enabled": mfa_enabled},
		update_modified=False,
	)
	from lex.client_schema import schedule_portal_contact_cleanup

	schedule_portal_contact_cleanup(doc.name)


def _portal_user_for(user):
	if not user or user in {"Guest", "Administrator"} or not frappe.db.exists("DocType", "Lexocrates Portal User"):
		return None
	return frappe.db.get_value(
		"Lexocrates Portal User",
		{"user": user},
		["name", "client"],
		as_dict=True,
	)
