from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from lex.client_access import get_portal_user
from lex.portal_audit import create_portal_audit_event


MANAGEMENT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager"}


class LexocratesClientDepartment(Document):
	def validate(self):
		self.department_name = (self.department_name or "").strip()
		if self.parent_department:
			parent = frappe.db.get_value(
				"Lexocrates Client Department", self.parent_department, ["client", "parent_department"], as_dict=True
			)
			if not parent or parent.client != self.client:
				frappe.throw(_("Parent Department must belong to the same Client."), frappe.ValidationError)
			if self.parent_department == self.name or parent.parent_department == self.name:
				frappe.throw(_("Department hierarchy cannot contain a cycle."), frappe.ValidationError)
		existing = frappe.db.get_value(
			"Lexocrates Client Department",
			{"client": self.client, "department_name": self.department_name},
			"name",
		)
		if existing and existing != self.name:
			frappe.throw(_("This Client already has a Department with that name."), frappe.DuplicateEntryError)

	def after_insert(self):
		create_portal_audit_event(
			client=self.client,
			action="Client Department Created",
			object_type=self.doctype,
			object_id=self.name,
			new_value={"department_name": self.department_name, "status": self.status},
		)

	def on_update(self):
		previous = self.get_doc_before_save()
		if previous and (previous.department_name != self.department_name or previous.status != self.status):
			create_portal_audit_event(
				client=self.client,
				action="Client Department Changed",
				object_type=self.doctype,
				object_id=self.name,
				previous_value={"department_name": previous.department_name, "status": previous.status},
				new_value={"department_name": self.department_name, "status": self.status},
			)

	def on_trash(self):
		if frappe.db.exists("Lexocrates Portal User", {"department": self.name}):
			frappe.throw(_("Disable this Department after moving its Portal Users."), frappe.PermissionError)


def _is_internal(user: str) -> bool:
	return user == "Administrator" or bool(set(frappe.get_roles(user)).intersection(MANAGEMENT_ROLES))


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if ptype == "delete":
		return False
	if _is_internal(user):
		return True
	actor = get_portal_user(user)
	if not actor or actor.client != doc.client:
		return False
	return ptype == "read" or bool(actor.user_management_authority and ptype in {"create", "write"})


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _is_internal(user):
		return ""
	actor = get_portal_user(user)
	if not actor:
		return "1=0"
	return f"`tabLexocrates Client Department`.client = {frappe.db.escape(actor.client)}"


def on_doctype_update():
	frappe.db.add_unique(
		"Lexocrates Client Department",
		["client", "department_name"],
		constraint_name="client_department_unique",
	)
