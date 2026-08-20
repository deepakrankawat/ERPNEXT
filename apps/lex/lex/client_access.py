from __future__ import annotations

from typing import Literal

import frappe
from frappe import _


CLIENT_ROLE = "Lexocrates Client"
PORTAL_USER_DOCTYPE = "Lexocrates Portal User"
MATTER_AUTHORIZATION_DOCTYPE = "Lexocrates Matter Authorization"

MatterAction = Literal["view", "upload", "comment", "approve", "billing"]


def is_client_user(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user in {"Guest", "Administrator"}:
		return False
	if CLIENT_ROLE in frappe.get_roles(user):
		return True
	return bool(
		frappe.db.exists("DocType", PORTAL_USER_DOCTYPE)
		and frappe.db.exists(PORTAL_USER_DOCTYPE, {"user": user})
	)


def get_portal_user(user: str | None = None, *, require_active: bool = True):
	"""Return the direct Client -> Portal User record for a Frappe User.

	The 2026 client architecture deliberately removes Contact from the authorization
	chain. A caller never receives access merely because a Contact happens to share
	an email address or Dynamic Link.
	"""
	user = user or frappe.session.user
	if not frappe.db.exists("DocType", PORTAL_USER_DOCTYPE):
		return None
	filters = {"user": user}
	if require_active:
		filters["account_status"] = "Active"
	return frappe.db.get_value(
		PORTAL_USER_DOCTYPE,
		filters,
		[
			"name",
			"user",
			"client",
			"portal_role",
			"account_status",
			"department",
			"mfa_required",
			"mfa_enabled",
			"matter_access_scope",
			"can_create_matters",
			"can_upload_documents",
			"can_comment",
			"billing_access",
			"lexpack_view_access",
			"lexpack_purchase_access",
			"approval_authority",
			"user_management_authority",
			"report_access",
			"delegated_admin_until",
			"delegated_by",
		],
		as_dict=True,
	)


def get_linked_customers(user: str | None = None) -> tuple[str, ...]:
	"""Return the single Client organization directly assigned to the Portal User."""
	portal_user = get_portal_user(user)
	return (portal_user.client,) if portal_user and portal_user.client else ()


def get_linked_client_ids(user: str | None = None) -> tuple[str, ...]:
	"""Backward-compatible name for callers that treat Customer as the Client ID."""
	return get_linked_customers(user)


def has_customer_access(customer: str | None, user: str | None = None) -> bool:
	portal_user = get_portal_user(user)
	return bool(customer and portal_user and portal_user.client == customer)


def customer_sql_condition(field: str, user: str | None = None) -> str:
	portal_user = get_portal_user(user)
	if not portal_user or not portal_user.client:
		return "1=0"
	return f"{field} = {frappe.db.escape(portal_user.client)}"


def has_portal_capability(capability: str, user: str | None = None) -> bool:
	portal_user = get_portal_user(user)
	if not portal_user or capability not in portal_user:
		return False
	value = portal_user.get(capability)
	if capability == "approval_authority":
		return value not in {None, "", "None"}
	if capability == "report_access":
		return value not in {None, "", "None"}
	return bool(value)


def has_matter_access(
	matter: str | None,
	action: MatterAction = "view",
	user: str | None = None,
) -> bool:
	if not matter:
		return False
	portal_user = get_portal_user(user)
	if not portal_user:
		return False
	matter_customer = frappe.db.get_value("LPO Matter", matter, "customer")
	if not matter_customer or matter_customer != portal_user.client:
		return False

	if action == "view" and portal_user.matter_access_scope == "All Client Matters":
		return True
	if portal_user.matter_access_scope == "No Matter Access" and action != "billing":
		return False
	if action == "billing" and not portal_user.billing_access:
		return False
	if action == "upload" and not portal_user.can_upload_documents:
		return False
	if action == "comment" and not portal_user.can_comment:
		return False
	if action == "approve" and portal_user.approval_authority in {None, "", "None"}:
		return False

	fieldname = {
		"view": "can_view",
		"upload": "can_upload",
		"comment": "can_comment",
		"approve": "can_approve",
		"billing": "can_view_billing",
	}[action]
	return bool(
		frappe.db.get_value(
			MATTER_AUTHORIZATION_DOCTYPE,
			{
				"parent": matter,
				"parenttype": "LPO Matter",
				"parentfield": "authorized_portal_users",
				"portal_user": portal_user.name,
			},
			fieldname,
		)
	)


def matter_sql_condition(
	matter_table: str = "`tabLPO Matter`",
	user: str | None = None,
) -> str:
	portal_user = get_portal_user(user)
	if not portal_user:
		return "1=0"
	client = frappe.db.escape(portal_user.client)
	portal_user_name = frappe.db.escape(portal_user.name)
	if portal_user.matter_access_scope == "All Client Matters":
		return f"{matter_table}.customer = {client}"
	if portal_user.matter_access_scope == "No Matter Access":
		return "1=0"
	return f"""
		{matter_table}.customer = {client}
		and exists (
			select 1 from `tabLexocrates Matter Authorization` authorization
			where authorization.parent = {matter_table}.name
				and authorization.parenttype = 'LPO Matter'
				and authorization.parentfield = 'authorized_portal_users'
				and authorization.portal_user = {portal_user_name}
				and authorization.can_view = 1
		)
	"""


def job_sql_condition(job_table: str = "`tabLPO Job`", user: str | None = None) -> str:
	portal_user = get_portal_user(user)
	if not portal_user:
		return "1=0"
	client = frappe.db.escape(portal_user.client)
	portal_user_name = frappe.db.escape(portal_user.name)
	if portal_user.matter_access_scope == "All Client Matters":
		return f"{job_table}.customer = {client}"
	if portal_user.matter_access_scope == "No Matter Access":
		return "1=0"
	return f"""
		{job_table}.customer = {client}
		and exists (
			select 1 from `tabLexocrates Matter Authorization` authorization
			where authorization.parent = {job_table}.engagement
				and authorization.parenttype = 'LPO Matter'
				and authorization.parentfield = 'authorized_portal_users'
				and authorization.portal_user = {portal_user_name}
				and authorization.can_view = 1
		)
	"""


def get_authorized_portal_users(matter: str) -> list[str]:
	"""Return active users who are authorized to view a Matter."""
	customer = frappe.db.get_value("LPO Matter", matter, "customer")
	if not customer:
		return []
	users = frappe.get_all(
		PORTAL_USER_DOCTYPE,
		filters={
			"client": customer,
			"account_status": "Active",
			"matter_access_scope": "All Client Matters",
		},
		pluck="user",
		limit_page_length=0,
	)
	authorized_profiles = frappe.get_all(
		MATTER_AUTHORIZATION_DOCTYPE,
		filters={
			"parent": matter,
			"parenttype": "LPO Matter",
			"parentfield": "authorized_portal_users",
			"can_view": 1,
		},
		pluck="portal_user",
		limit_page_length=0,
	)
	if authorized_profiles:
		users.extend(
			frappe.get_all(
				PORTAL_USER_DOCTYPE,
				filters={
					"name": ["in", authorized_profiles],
					"client": customer,
					"account_status": "Active",
				},
				pluck="user",
				limit_page_length=0,
			)
		)
	return list(dict.fromkeys(user for user in users if user))


def require_client_administrator(user: str | None = None):
	portal_user = get_portal_user(user)
	delegation_active = bool(
		portal_user
		and portal_user.delegated_admin_until
		and frappe.utils.get_datetime(portal_user.delegated_admin_until) >= frappe.utils.now_datetime()
	)
	if not portal_user or not (portal_user.user_management_authority or delegation_active):
		frappe.throw(
			_("Client Administrator authority is required for this action."),
			frappe.PermissionError,
		)
	return portal_user
