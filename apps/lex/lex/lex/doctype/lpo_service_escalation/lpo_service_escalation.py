from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from lex.portal_audit import create_portal_audit_event


MANAGEMENT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager"}


def _has_management_access(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)).intersection(MANAGEMENT_ROLES))


class LPOServiceEscalation(Document):
	pass


@frappe.whitelist()
def raise_escalation(job: str, escalation_level: str, escalation_reason: str, assigned_to: str | None = None):
	user = frappe.session.user
	job_doc = frappe.get_doc("LPO Job", job)
	if not _has_management_access(user) and job_doc.assigned_analyst != user:
		frappe.throw(_("Only the assigned analyst or Legal Operations may raise an escalation."), frappe.PermissionError)

	if not assigned_to:
		settings = frappe.get_single("Lexocrates SLA Settings")
		default = next(
			(row for row in (settings.get("default_escalation_users") or []) if row.escalation_level == escalation_level),
			None,
		)
		assigned_to = (default.assigned_user if default else None) or job_doc.assigned_analyst

	escalation = frappe.get_doc({
		"doctype": "LPO Service Escalation",
		"job": job,
		"escalation_level": escalation_level,
		"escalation_reason": escalation_reason,
		"assigned_to": assigned_to,
		"status": "Open",
	}).insert(ignore_permissions=True)

	create_portal_audit_event(
		client=job_doc.customer,
		user=user,
		matter=job_doc.engagement,
		action="Escalation Created",
		object_type=escalation.doctype,
		object_id=escalation.name,
		new_value={"level": escalation_level, "reason": escalation_reason},
	)
	return {"name": escalation.name, "status": escalation.status}


@frappe.whitelist()
def resolve_escalation(name: str, resolution: str):
	if not _has_management_access():
		frappe.throw(_("Only Legal Operations may resolve an escalation."), frappe.PermissionError)
	escalation = frappe.get_doc("LPO Service Escalation", name)
	if escalation.status == "Resolved":
		frappe.throw(_("This escalation is already resolved."), frappe.ValidationError)
	escalation.status = "Resolved"
	escalation.resolution = resolution
	escalation.resolved_on = now_datetime()
	escalation.resolved_by = frappe.session.user
	escalation.save(ignore_permissions=True)
	return {"name": escalation.name, "status": escalation.status}


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if _has_management_access(user):
		return True
	if "LPO_Analyst" in frappe.get_roles(user):
		return bool(frappe.db.get_value("LPO Job", doc.job, "assigned_analyst") == user)
	return False


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _has_management_access(user):
		return ""
	if "LPO_Analyst" in frappe.get_roles(user):
		escaped_user = frappe.db.escape(user)
		return f"""
			exists (
				select 1 from `tabLPO Job` job
				where job.name = `tabLPO Service Escalation`.job
					and job.assigned_analyst = {escaped_user}
			)
		"""
	return "1=0"
