from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from lex.client_access import get_portal_user, has_matter_access, has_portal_capability, is_client_user
from lex.portal_audit import create_portal_audit_event
from lex.work_intake import _portal_service_writes


MANAGEMENT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager"}


def _has_management_access(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)).intersection(MANAGEMENT_ROLES))


class LPOAssignmentScopeChange(Document):
	def validate(self):
		if self.status == "Approved" and not (self.internal_approval and self.client_approval):
			frappe.throw(
				_("A Scope Change can only be Approved once both internal and client approval are recorded."),
				frappe.ValidationError,
			)


@frappe.whitelist()
def request_scope_change(
	job: str,
	original_scope: str,
	requested_change: str,
	reason: str,
	additional_price: float = 0,
	additional_lexpack_deduction: float = 0,
	revised_delivery_date: str | None = None,
):
	job_doc = frappe.get_doc("LPO Job", job)
	user = frappe.session.user
	if _has_management_access(user) or "LPO_Analyst" in frappe.get_roles(user):
		pass
	elif is_client_user(user):
		if not has_portal_capability("can_create_matters") or not has_matter_access(job_doc.engagement, "view", user):
			frappe.throw(_("You are not authorized to request a scope change on this Assignment."), frappe.PermissionError)
	else:
		frappe.throw(_("Not authorized."), frappe.PermissionError)

	change = frappe.get_doc({
		"doctype": "LPO Assignment Scope Change",
		"job": job,
		"original_scope": original_scope,
		"requested_change": requested_change,
		"reason": reason,
		"additional_price": flt(additional_price),
		"additional_lexpack_deduction": flt(additional_lexpack_deduction),
		"revised_delivery_date": revised_delivery_date or None,
		"status": "Pending Internal Review",
	}).insert(ignore_permissions=True)

	create_portal_audit_event(
		client=job_doc.customer,
		user=user,
		matter=job_doc.engagement,
		action="Scope Change Requested",
		object_type="LPO Assignment Scope Change",
		object_id=change.name,
		new_value={"additional_price": flt(additional_price), "reason": reason},
	)
	return {"name": change.name, "status": change.status}


@frappe.whitelist()
def approve_internal(name: str):
	if not _has_management_access():
		frappe.throw(_("Only Legal Operations may internally approve a scope change."), frappe.PermissionError)
	change = frappe.get_doc("LPO Assignment Scope Change", name)
	if change.status != "Pending Internal Review":
		frappe.throw(_("This scope change is not awaiting internal review."), frappe.ValidationError)
	change.internal_approval = 1
	change.internal_approved_by = frappe.session.user
	change.internal_approved_on = now_datetime()
	change.status = "Pending Client Approval"
	change.save(ignore_permissions=True)
	create_portal_audit_event(
		client=change.customer,
		user=frappe.session.user,
		matter=change.matter,
		action="Scope Change Internally Approved",
		object_type=change.doctype,
		object_id=change.name,
	)
	return {"name": change.name, "status": change.status}


@frappe.whitelist()
def approve_client(name: str):
	change = frappe.get_doc("LPO Assignment Scope Change", name)
	user = frappe.session.user
	if not _has_management_access(user):
		if not is_client_user(user):
			frappe.throw(_("Not authorized."), frappe.PermissionError)
		portal_user = get_portal_user(user)
		if (
			not portal_user
			or portal_user.client != change.customer
			or not has_matter_access(change.matter, "scope_change", user)
		):
			frappe.throw(_("You are not authorized to approve scope changes for this Matter."), frappe.PermissionError)
	if change.status != "Pending Client Approval":
		frappe.throw(_("This scope change is not awaiting client approval."), frappe.ValidationError)

	change.client_approval = 1
	change.client_approved_by = user
	change.client_approved_on = now_datetime()
	change.status = "Approved"
	change.save(ignore_permissions=True)

	job = frappe.get_doc("LPO Job", change.job)
	with _portal_service_writes():
		if flt(change.additional_price):
			job.quoted_amount = flt(job.quoted_amount) + flt(change.additional_price)
			job.required_legal_capacity = flt(job.required_legal_capacity) + flt(change.additional_price)
		if change.revised_delivery_date:
			job.delivery_date_revision_reason = _("Approved Scope Change {0}: {1}").format(change.name, change.reason)
			job.confirmed_delivery_date = change.revised_delivery_date
		job.save(ignore_permissions=True)

	create_portal_audit_event(
		client=change.customer,
		user=user,
		matter=change.matter,
		action="Scope Change Approved",
		object_type=change.doctype,
		object_id=change.name,
		new_value={
			"additional_price": flt(change.additional_price),
			"revised_delivery_date": str(change.revised_delivery_date) if change.revised_delivery_date else None,
		},
	)
	return {"name": change.name, "status": change.status, "job": job.name}


@frappe.whitelist()
def reject(name: str, rejection_reason: str):
	change = frappe.get_doc("LPO Assignment Scope Change", name)
	user = frappe.session.user
	if not _has_management_access(user):
		if not is_client_user(user):
			frappe.throw(_("Not authorized."), frappe.PermissionError)
		portal_user = get_portal_user(user)
		if (
			not portal_user
			or portal_user.client != change.customer
			or not has_matter_access(change.matter, "scope_change", user)
		):
			frappe.throw(_("You are not authorized to reject scope changes for this Matter."), frappe.PermissionError)
	if change.status not in {"Pending Internal Review", "Pending Client Approval"}:
		frappe.throw(_("This scope change has already been decided."), frappe.ValidationError)
	if not (rejection_reason or "").strip():
		frappe.throw(_("Provide a rejection reason."), frappe.MandatoryError)

	change.status = "Rejected"
	change.rejection_reason = rejection_reason.strip()
	change.save(ignore_permissions=True)
	create_portal_audit_event(
		client=change.customer,
		user=user,
		matter=change.matter,
		action="Scope Change Rejected",
		object_type=change.doctype,
		object_id=change.name,
		new_value={"rejection_reason": change.rejection_reason},
	)
	return {"name": change.name, "status": change.status}


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if _has_management_access(user):
		return True
	if is_client_user(user):
		return ptype in {"read", "print", "report"} and has_matter_access(doc.matter, "view", user)
	if "LPO_Analyst" in frappe.get_roles(user):
		return ptype in {"read", "print", "report", "create"}
	return False


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _has_management_access(user):
		return ""
	if is_client_user(user):
		from lex.client_access import get_portal_user as _get_portal_user

		portal_user = _get_portal_user(user)
		if not portal_user or not portal_user.client:
			return "1=0"
		return f"`tabLPO Assignment Scope Change`.customer = {frappe.db.escape(portal_user.client)}"
	if "LPO_Analyst" in frappe.get_roles(user):
		return ""
	return "1=0"
