from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now_datetime

from lex.client_access import get_portal_user
from lex.portal_audit import create_portal_audit_event


PORTAL_ROLE_TO_FRAPPE_ROLE = {
	"Client Administrator": "Lexocrates Client Administrator",
	"Partner / General Counsel": "Lexocrates Partner General Counsel",
	"Legal User": "Lexocrates Legal User",
	"Operations User": "Lexocrates Operations User",
	"Finance User": "Lexocrates Finance User",
	"Procurement User": "Lexocrates Procurement User",
	"Compliance User": "Lexocrates Compliance User",
	"Read-Only User": "Lexocrates Read Only User",
}
PORTAL_FRAPPE_ROLES = set(PORTAL_ROLE_TO_FRAPPE_ROLE.values())
MANAGEMENT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager"}
CAPABILITY_FIELDS = (
	"can_create_matters",
	"can_upload_documents",
	"can_comment",
	"billing_access",
	"lexpack_view_access",
	"lexpack_purchase_access",
	"user_management_authority",
)
ROLE_DEFAULTS = {
	"Client Administrator": {
		"can_create_matters": 1,
		"can_upload_documents": 1,
		"can_comment": 1,
		"billing_access": 1,
		"lexpack_view_access": 1,
		"lexpack_purchase_access": 1,
		"approval_authority": "All Client Approvals",
		"user_management_authority": 1,
		"report_access": "All Client Reports",
	},
	"Partner / General Counsel": {
		"can_create_matters": 1,
		"can_upload_documents": 1,
		"can_comment": 1,
		"lexpack_view_access": 1,
		"approval_authority": "Deliverable Approval",
		"report_access": "Matter Reports",
	},
	"Legal User": {
		"can_create_matters": 1,
		"can_upload_documents": 1,
		"can_comment": 1,
		"report_access": "Matter Reports",
	},
	"Operations User": {
		"can_comment": 1,
		"report_access": "Matter Reports",
	},
	"Finance User": {
		"billing_access": 1,
		"lexpack_view_access": 1,
		"report_access": "Financial Reports",
	},
	"Procurement User": {
		"billing_access": 1,
		"lexpack_view_access": 1,
		"lexpack_purchase_access": 1,
		"approval_authority": "Commercial Approval",
	},
	"Compliance User": {"report_access": "Compliance Reports"},
	"Read-Only User": {},
}


class LexocratesPortalUser(Document):
	def before_insert(self):
		self._load_user_identity()
		if not any(self.get(fieldname) for fieldname in CAPABILITY_FIELDS):
			self.apply_role_defaults()
		if self.account_status == "Active" and not self.activated_on:
			self.activated_on = now_datetime()

	def validate(self):
		self._load_user_identity()
		self._validate_client()
		self._validate_unique_user()
		self._validate_department()
		self._validate_lifecycle()
		self._protect_client_administration()
		self._validate_notification_preferences()

	def after_insert(self):
		self._synchronize_user()
		create_portal_audit_event(
			client=self.client,
			portal_user=self.name,
			user=frappe.session.user,
			action="Portal User Created",
			object_type=self.doctype,
			object_id=self.name,
			new_value=self._audit_values(),
		)

	def on_update(self):
		self._synchronize_user()
		previous = self.get_doc_before_save()
		if previous:
			old = self._audit_values(previous)
			new = self._audit_values()
			if old != new:
				create_portal_audit_event(
					client=self.client,
					portal_user=self.name,
					user=frappe.session.user,
					action="Portal User Permissions Changed",
					object_type=self.doctype,
					object_id=self.name,
					previous_value=old,
					new_value=new,
				)

	def on_trash(self):
		frappe.throw(
			_("Portal Users must be disabled, not deleted, so historical audit records remain intact."),
			frappe.PermissionError,
		)

	def apply_role_defaults(self):
		defaults = ROLE_DEFAULTS.get(self.portal_role, {})
		for fieldname in CAPABILITY_FIELDS:
			self.set(fieldname, int(bool(defaults.get(fieldname, 0))))
		self.approval_authority = defaults.get("approval_authority", "None")
		self.report_access = defaults.get("report_access", "None")
		if self.portal_role in {"Finance User", "Procurement User", "Compliance User", "Read-Only User"}:
			self.matter_access_scope = "No Matter Access"

	def _load_user_identity(self):
		user = frappe.db.get_value(
			"User", self.user, ["name", "full_name", "email", "enabled", "last_login"], as_dict=True
		)
		if not user or user.name in {"Guest", "Administrator"}:
			frappe.throw(_("Select a valid individual User account."), frappe.ValidationError)
		self.full_name = user.full_name or user.email
		self.email = user.email
		self.last_login = user.last_login

	def _validate_client(self):
		if frappe.db.get_value("Customer", self.client, "customer_type") != "Company":
			frappe.throw(_("A Client must be an organization-type Customer."), frappe.ValidationError)

	def _validate_unique_user(self):
		existing = frappe.db.get_value("Lexocrates Portal User", {"user": self.user}, "name")
		if existing and existing != self.name:
			frappe.throw(
				_("User {0} is already Portal User {1}.").format(frappe.bold(self.user), frappe.bold(existing)),
				frappe.DuplicateEntryError,
			)

	def _validate_department(self):
		if self.department and frappe.db.get_value("Lexocrates Client Department", self.department, "client") != self.client:
			frappe.throw(_("Department must belong to the same Client."), frappe.ValidationError)

	def _validate_lifecycle(self):
		previous = self.get_doc_before_save()
		if self.account_status in {"Locked", "Suspended", "Disabled", "Revoked"}:
			if not self.deactivation_reason:
				frappe.throw(_("A reason is required for a non-active Portal User."), frappe.MandatoryError)
			if not self.deactivated_on:
				self.deactivated_on = now_datetime()
			if self.account_status != "Locked":
				self.lock_until = None
		elif self.account_status == "Active":
			self.deactivated_on = None
			self.deactivation_reason = None
			self.lock_until = None
			if not self.activated_on or (previous and previous.account_status != "Active"):
				self.activated_on = now_datetime()

	def _protect_client_administration(self):
		if _is_internal(frappe.session.user) or getattr(frappe.flags, "lexocrates_portal_service", False):
			return
		actor = get_portal_user(frappe.session.user)
		if not actor or not actor.user_management_authority or actor.client != self.client:
			frappe.throw(_("You cannot administer Portal Users for this Client."), frappe.PermissionError)
		if self.user == frappe.session.user and self.account_status != "Active":
			frappe.throw(_("Client Administrators cannot disable their own account."), frappe.PermissionError)

	def _validate_notification_preferences(self):
		if not self.notification_preferences:
			self.notification_preferences = "{}"
			return
		try:
			value = json.loads(self.notification_preferences)
		except (TypeError, ValueError):
			frappe.throw(_("Notification Preferences must contain valid JSON."), frappe.ValidationError)
		if not isinstance(value, dict):
			frappe.throw(_("Notification Preferences must be a JSON object."), frappe.ValidationError)

	def _synchronize_user(self):
		from lex.client_workspace import ensure_client_customer_permission

		desired_specific_role = PORTAL_ROLE_TO_FRAPPE_ROLE[self.portal_role]
		user = None
		# User may also be touched by login/security hooks. Always reload and retry a
		# clean snapshot so background migration never surfaces TimestampMismatchError
		# to clients or aborts after_migrate.
		for attempt in range(3):
			user = frappe.get_doc("User", self.user)
			kept_roles = [row.role for row in user.roles if row.role not in PORTAL_FRAPPE_ROLES]
			for role in ("Lexocrates Client", "Customer", desired_specific_role):
				if role not in kept_roles and frappe.db.exists("Role", role):
					kept_roles.append(role)
			desired_enabled = 1 if self.account_status == "Active" else 0
			current_roles = [row.role for row in user.roles]
			changed = (
				current_roles != kept_roles
				or user.user_type != "Website User"
				or bool(user.default_workspace)
				or bool(user.module_profile)
				or cint(user.enabled) != desired_enabled
			)
			if not changed:
				break
			user.set("roles", [{"role": role} for role in kept_roles])
			# Client identities deliberately remain Website Users. They receive the
			# native Website workspace and never enter Desk.
			user.user_type = "Website User"
			user.default_workspace = ""
			user.module_profile = ""
			user.enabled = desired_enabled
			try:
				user.save(ignore_permissions=True)
				break
			except frappe.TimestampMismatchError:
				frappe.clear_messages()
				if attempt == 2:
					raise
		ensure_client_customer_permission(user.name, self.client)
		if not user.enabled:
			frappe.sessions.clear_sessions(user=user.name, force=True)

	def _audit_values(self, source=None):
		source = source or self
		fields = (
			"client", "user", "portal_role", "account_status", "department",
			"matter_access_scope", *CAPABILITY_FIELDS, "approval_authority", "report_access", "mfa_required",
			"lock_until", "delegated_admin_until", "delegated_by", "delegation_reason",
		)
		return {fieldname: source.get(fieldname) for fieldname in fields}


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
	if ptype == "read":
		return True
	return bool(actor.user_management_authority and ptype in {"create", "write"})


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _is_internal(user):
		return ""
	actor = get_portal_user(user)
	if not actor:
		return "1=0"
	return f"`tabLexocrates Portal User`.client = {frappe.db.escape(actor.client)}"


def on_doctype_update():
	frappe.db.add_unique("Lexocrates Portal User", ["user"], constraint_name="portal_user_user_unique")
	frappe.db.add_index(
		"Lexocrates Portal User", ["client", "account_status"], index_name="portal_user_client_status"
	)


@frappe.whitelist()
def apply_role_defaults(portal_user: str):
	doc = frappe.get_doc("Lexocrates Portal User", portal_user)
	frappe.has_permission(doc.doctype, "write", doc=doc, throw=True)
	doc.apply_role_defaults()
	doc.save()
	return doc.as_dict()
