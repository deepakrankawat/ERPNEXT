from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_datetime, now_datetime

from lex.client_access import get_portal_user, has_matter_access, has_portal_capability, is_client_user
from lex.portal_audit import create_portal_audit_event


MANAGEMENT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager"}
SCOPE_EXPANSION_FIELDS = (
	"new_facts", "new_documents", "changed_instructions",
	"additional_issues", "additional_research", "additional_deliverables",
)


def _has_management_access(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)).intersection(MANAGEMENT_ROLES))


class LPOCorrectionRequest(Document):
	def validate(self):
		if self.within_original_scope and self.verified_lexocrates_error:
			self.correction_cost = 0
		if any(cint(self.get(field)) for field in SCOPE_EXPANSION_FIELDS):
			self.within_original_scope = 0


@frappe.whitelist()
def create_correction_request(job: str, issue_description: str, **flags):
	job_doc = frappe.get_doc("LPO Job", job)
	if job_doc.job_status not in {"Delivered", "Completed"}:
		frappe.throw(_("A correction can only be requested after delivery."), frappe.ValidationError)

	from lex.sla_engine import add_business_days, _settings

	window = cint(_settings().get("correction_request_window_business_days") or 5)
	deadline = add_business_days(job_doc.completed_on or job_doc.modified, window)
	if now_datetime() > get_datetime(deadline):
		frappe.throw(_("The correction request window for this delivery has closed."), frappe.ValidationError)

	user = frappe.session.user
	if not _has_management_access(user):
		if not is_client_user(user) or not has_portal_capability("can_comment") or not has_matter_access(
			job_doc.engagement, "view", user
		):
			frappe.throw(_("You are not authorized to request a correction on this Assignment."), frappe.PermissionError)

	values = {
		"doctype": "LPO Correction Request",
		"job": job,
		"issue_description": issue_description,
		"status": "Open",
	}
	for field in ("within_original_scope",) + SCOPE_EXPANSION_FIELDS:
		if field in flags:
			values[field] = cint(flags[field])
	request = frappe.get_doc(values).insert(ignore_permissions=True)

	create_portal_audit_event(
		client=job_doc.customer,
		user=user,
		matter=job_doc.engagement,
		action="Correction Request Received",
		object_type=request.doctype,
		object_id=request.name,
	)
	return {"name": request.name, "status": request.status}


@frappe.whitelist()
def verify_error(name: str, verified: int, resolution_notes: str | None = None):
	if not _has_management_access():
		frappe.throw(_("Only Legal Operations may verify a correction request."), frappe.PermissionError)
	request = frappe.get_doc("LPO Correction Request", name)
	request.verified_lexocrates_error = cint(verified)
	if resolution_notes:
		request.resolution_notes = resolution_notes
	request.status = "In Correction" if cint(verified) and request.within_original_scope else request.status
	request.save(ignore_permissions=True)
	return {"name": request.name, "status": request.status, "correction_cost": request.correction_cost}


@frappe.whitelist()
def route_to_scope_change(name: str, requested_change: str, reason: str, additional_price: float = 0):
	if not _has_management_access():
		frappe.throw(_("Only Legal Operations may route a correction to a scope change."), frappe.PermissionError)
	request = frappe.get_doc("LPO Correction Request", name)
	from lex.lex.doctype.lpo_assignment_scope_change.lpo_assignment_scope_change import request_scope_change

	result = request_scope_change(
		job=request.job,
		original_scope=request.issue_description,
		requested_change=requested_change,
		reason=reason,
		additional_price=additional_price,
	)
	request.routed_to_scope_change = result["name"]
	request.status = "Routed to Scope Change"
	request.save(ignore_permissions=True)
	return {"name": request.name, "status": request.status, "scope_change": result["name"]}


@frappe.whitelist()
def resolve(name: str, resolution_notes: str):
	if not _has_management_access():
		frappe.throw(_("Only Legal Operations may resolve a correction request."), frappe.PermissionError)
	request = frappe.get_doc("LPO Correction Request", name)
	request.status = "Resolved"
	request.resolution_notes = resolution_notes
	request.save(ignore_permissions=True)
	create_portal_audit_event(
		client=request.customer,
		user=frappe.session.user,
		matter=request.matter,
		action="Correction Request Resolved",
		object_type=request.doctype,
		object_id=request.name,
	)
	return {"name": request.name, "status": request.status}


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if _has_management_access(user):
		return True
	if is_client_user(user):
		portal_user = get_portal_user(user)
		return bool(portal_user and portal_user.client == doc.customer)
	if "LPO_Analyst" in frappe.get_roles(user):
		return ptype in {"read", "print", "report"}
	return False


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _has_management_access(user):
		return ""
	if is_client_user(user):
		portal_user = get_portal_user(user)
		if not portal_user or not portal_user.client:
			return "1=0"
		return f"`tabLPO Correction Request`.customer = {frappe.db.escape(portal_user.client)}"
	if "LPO_Analyst" in frappe.get_roles(user):
		return ""
	return "1=0"
