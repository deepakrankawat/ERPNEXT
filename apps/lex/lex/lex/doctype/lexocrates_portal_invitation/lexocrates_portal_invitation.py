from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from lex.client_access import get_portal_user


MANAGEMENT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager"}


class LexocratesPortalInvitation(Document):
	def before_insert(self):
		if not getattr(frappe.flags, "lexocrates_portal_service", False):
			frappe.throw(_("Portal invitations can only be created by the invitation service."), frappe.PermissionError)

	def before_save(self):
		if not self.is_new() and not getattr(frappe.flags, "lexocrates_portal_service", False):
			frappe.throw(_("Portal invitations can only be changed by the invitation service."), frappe.PermissionError)

	def on_trash(self):
		frappe.throw(_("Portal invitations cannot be deleted."), frappe.PermissionError)


def _is_internal(user: str) -> bool:
	return user == "Administrator" or bool(set(frappe.get_roles(user)).intersection(MANAGEMENT_ROLES))


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if ptype != "read":
		return False
	if _is_internal(user):
		return True
	actor = get_portal_user(user)
	return bool(actor and actor.user_management_authority and actor.client == doc.client)


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _is_internal(user):
		return ""
	actor = get_portal_user(user)
	if not actor or not actor.user_management_authority:
		return "1=0"
	return f"`tabLexocrates Portal Invitation`.client = {frappe.db.escape(actor.client)}"


def on_doctype_update():
	frappe.db.add_index(
		"Lexocrates Portal Invitation", ["client", "status", "expires_on"], index_name="portal_invitation_client_status"
	)
