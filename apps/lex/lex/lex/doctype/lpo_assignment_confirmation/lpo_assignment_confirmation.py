from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now_datetime

from lex.client_access import get_portal_user, has_matter_access, is_client_user
from lex.portal_audit import create_portal_audit_event
from lex.work_intake import _portal_service_writes


MANAGEMENT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager"}


def _has_management_access(user: str) -> bool:
	return user == "Administrator" or bool(set(frappe.get_roles(user)).intersection(MANAGEMENT_ROLES))


class LPOAssignmentConfirmation(Document):
	def validate(self):
		if self.is_new():
			previous_max = frappe.db.get_value(
				"LPO Assignment Confirmation",
				{"job": self.job},
				"max(confirmation_version)",
			)
			self.confirmation_version = cint(previous_max or 0) + 1
			self.issued_by = frappe.session.user
			self.issued_date = now_datetime()
		if not _has_management_access(frappe.session.user) and self.has_value_changed("confirmed_delivery_date"):
			frappe.throw(
				_("Only Legal Operations may set or revise the Confirmed Delivery Date."),
				frappe.PermissionError,
			)


@frappe.whitelist()
def issue(job: str, **fields):
	"""Issue a new (versioned) Assignment Confirmation for a Job and route it to the client."""
	if not _has_management_access(frappe.session.user):
		frappe.throw(_("Only Legal Operations may issue an Assignment Confirmation."), frappe.PermissionError)
	job_doc = frappe.get_doc("LPO Job", job)
	if job_doc.job_status not in {"Awaiting Internal Scope Review", "Awaiting Client Approval", "Confirmed"}:
		frappe.throw(
			_("An Assignment Confirmation can only be issued once internal scope review has been reached."),
			frappe.ValidationError,
		)
	required = ("scope_summary", "confirmed_delivery_date", "service_level")
	missing = [f for f in required if not fields.get(f)]
	if missing:
		frappe.throw(_("Missing required confirmation fields: {0}").format(", ".join(missing)), frappe.MandatoryError)

	previous_name = frappe.db.get_value(
		"LPO Assignment Confirmation",
		{"job": job, "client_decision": "Pending"},
		"name",
	)
	confirmation = frappe.get_doc({
		"doctype": "LPO Assignment Confirmation",
		"job": job,
		"client_requested_date": job_doc.due_date,
		"indicative_turnaround_snapshot": job_doc.get("indicative_turnaround_snapshot"),
		**{k: v for k, v in fields.items() if k in {
			"scope_summary", "document_volume", "deliverables_summary", "assumptions",
			"exclusions", "confirmed_delivery_date", "service_level", "fixed_quote",
			"currency", "lexpack_capacity_deduction",
		}},
	}).insert(ignore_permissions=True)
	if previous_name:
		frappe.db.set_value("LPO Assignment Confirmation", previous_name, "superseded_by", confirmation.name)

	job_doc.reload()
	job_doc.assignment_confirmation = confirmation.name
	job_doc.service_level = confirmation.service_level
	job_doc.job_status = "Awaiting Client Approval"
	job_doc.save(ignore_permissions=True)

	create_portal_audit_event(
		client=job_doc.customer,
		user=frappe.session.user,
		matter=job_doc.engagement,
		action="Assignment Confirmation Issued",
		object_type="LPO Assignment Confirmation",
		object_id=confirmation.name,
		new_value={"job": job, "confirmed_delivery_date": str(confirmation.confirmed_delivery_date)},
	)
	return {"name": confirmation.name, "job": job, "status": job_doc.job_status}


@frappe.whitelist()
def approve(name: str):
	confirmation = frappe.get_doc("LPO Assignment Confirmation", name)
	_require_client_authority(confirmation, action="approve")
	if confirmation.client_decision != "Pending":
		frappe.throw(_("This confirmation has already been decided."), frappe.ValidationError)

	confirmation.client_decision = "Approved"
	confirmation.approved_by = frappe.session.user
	confirmation.approved_on = now_datetime()
	confirmation.save(ignore_permissions=True)

	job = frappe.get_doc("LPO Job", confirmation.job)
	with _portal_service_writes():
		job.confirmed_delivery_date = confirmation.confirmed_delivery_date
		job.indicative_turnaround_snapshot = job.get("indicative_turnaround_snapshot") or ""
		job.service_level = confirmation.service_level
		job.job_status = "Confirmed"
		job.save(ignore_permissions=True)

	create_portal_audit_event(
		client=job.customer,
		user=frappe.session.user,
		matter=job.engagement,
		action="Assignment Confirmation Approved",
		object_type="LPO Assignment Confirmation",
		object_id=confirmation.name,
	)

	from lex.sla_engine import try_start_sla

	started = try_start_sla(job)
	return {"name": confirmation.name, "job": job.name, "job_status": job.job_status, "sla_started": started}


@frappe.whitelist()
def request_change(name: str, notes: str):
	confirmation = frappe.get_doc("LPO Assignment Confirmation", name)
	_require_client_authority(confirmation, action="approve")
	if confirmation.client_decision != "Pending":
		frappe.throw(_("This confirmation has already been decided."), frappe.ValidationError)
	if not (notes or "").strip():
		frappe.throw(_("Describe the requested change."), frappe.MandatoryError)

	confirmation.client_decision = "Change Requested"
	confirmation.change_request_notes = notes.strip()
	confirmation.save(ignore_permissions=True)

	job = frappe.get_doc("LPO Job", confirmation.job)
	with _portal_service_writes():
		job.job_status = "Awaiting Internal Scope Review"
		job.save(ignore_permissions=True)

	create_portal_audit_event(
		client=job.customer,
		user=frappe.session.user,
		matter=job.engagement,
		action="Assignment Confirmation Change Requested",
		object_type="LPO Assignment Confirmation",
		object_id=confirmation.name,
		new_value={"notes": notes.strip()},
	)
	return {"name": confirmation.name, "job": job.name, "job_status": job.job_status}


def _require_client_authority(confirmation, *, action: str):
	user = frappe.session.user
	if _has_management_access(user):
		return
	if not is_client_user(user):
		frappe.throw(_("Not authorized."), frappe.PermissionError)
	job = frappe.db.get_value("LPO Job", confirmation.job, ["engagement", "customer"], as_dict=True)
	portal_user = get_portal_user(user)
	if (
		not portal_user
		or portal_user.client != job.customer
		or not has_matter_access(job.engagement, action, user)
	):
		frappe.throw(_("You are not authorized to decide this Assignment Confirmation."), frappe.PermissionError)


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if _has_management_access(user):
		return True
	if "LPO_Analyst" in frappe.get_roles(user):
		return ptype in {"read", "print", "report"}
	if is_client_user(user):
		portal_user = get_portal_user(user)
		job_customer = frappe.db.get_value("LPO Job", doc.job, "customer")
		return ptype in {"read", "print", "report"} and bool(portal_user and portal_user.client == job_customer)
	return False


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _has_management_access(user):
		return ""
	if "LPO_Analyst" in frappe.get_roles(user):
		return ""
	if is_client_user(user):
		portal_user = get_portal_user(user)
		if not portal_user or not portal_user.client:
			return "1=0"
		client = frappe.db.escape(portal_user.client)
		return f"""
			exists (
				select 1 from `tabLPO Job` job
				where job.name = `tabLPO Assignment Confirmation`.job
					and job.customer = {client}
			)
		"""
	return "1=0"
