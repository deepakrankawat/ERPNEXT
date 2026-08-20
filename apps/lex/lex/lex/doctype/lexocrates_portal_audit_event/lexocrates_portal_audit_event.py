from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from lex.client_access import get_portal_user


INTERNAL_AUDIT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager", "Lexocrates Compliance Officer"}


class LexocratesPortalAuditEvent(Document):
	def before_insert(self):
		if not getattr(frappe.flags, "lexocrates_portal_audit", False):
			frappe.throw(_("Portal audit events can only be created by the audit service."), frappe.PermissionError)
		from lex.audit_worm_chain import GENESIS_HASH, compute_audit_event_hash

		self.chain_scope = self.client or "__GLOBAL__"
		previous = frappe.db.get_value(
			"Lexocrates Portal Audit Event",
			{"chain_scope": self.chain_scope},
			["name", "event_hash"],
			order_by="event_timestamp desc, creation desc, name desc",
			as_dict=True,
		)
		self.previous_hash = previous.event_hash if previous and previous.event_hash else GENESIS_HASH
		self.hash_version = 1
		self.event_hash = compute_audit_event_hash(self.as_dict(), self.previous_hash)

	def before_save(self):
		if not self.is_new():
			frappe.throw(_("Portal audit events are immutable."), frappe.PermissionError)

	def on_trash(self):
		frappe.throw(_("Portal audit events cannot be deleted."), frappe.PermissionError)


def _is_internal(user: str) -> bool:
	return user == "Administrator" or bool(set(frappe.get_roles(user)).intersection(INTERNAL_AUDIT_ROLES))


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if ptype != "read":
		return False
	if _is_internal(user):
		return True
	portal_user = get_portal_user(user)
	if not portal_user or portal_user.client != doc.client:
		return False
	return bool(
		portal_user.user_management_authority
		or portal_user.report_access in {"Compliance Reports", "All Client Reports"}
		or doc.user == user
		or doc.portal_user == portal_user.name
	)


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _is_internal(user):
		return ""
	portal_user = get_portal_user(user)
	if not portal_user:
		return "1=0"
	client = frappe.db.escape(portal_user.client)
	if portal_user.user_management_authority or portal_user.report_access in {"Compliance Reports", "All Client Reports"}:
		return f"`tabLexocrates Portal Audit Event`.client = {client}"
	return (
		f"`tabLexocrates Portal Audit Event`.client = {client} and ("
		f"`tabLexocrates Portal Audit Event`.user = {frappe.db.escape(user)} or "
		f"`tabLexocrates Portal Audit Event`.portal_user = {frappe.db.escape(portal_user.name)})"
	)


def on_doctype_update():
	frappe.db.add_index(
		"Lexocrates Portal Audit Event",
		["client", "event_timestamp"],
		index_name="portal_audit_client_timestamp",
	)
	frappe.db.add_index(
		"Lexocrates Portal Audit Event",
		["chain_scope", "event_timestamp"],
		index_name="portal_audit_chain_timestamp",
	)
