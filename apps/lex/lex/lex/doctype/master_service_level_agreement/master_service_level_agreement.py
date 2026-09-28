from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now_datetime

from lex.client_access import get_portal_user, has_customer_access, is_client_user
from lex.portal_audit import create_portal_audit_event


MANAGEMENT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager"}
ACK_FIELDS = (
	"ack_read_and_understood",
	"ack_business_week",
	"ack_no_24x7_production",
	"ack_submission_not_sla_start",
	"ack_lextimator_indicative",
	"ack_fixed_quote_protection",
	"ack_scope_changes_affect_price",
	"ack_confirmed_delivery_date_controls",
	"ack_priority_subject_to_availability",
	"ack_no_automatic_express_service",
	"ack_signatory_authority",
)


class MasterServiceLevelAgreement(Document):
	def validate(self):
		if self.status == "Accepted" and not all(cint(self.get(field)) for field in ACK_FIELDS):
			frappe.throw(
				_("All client acknowledgement checkboxes must be accepted before this SLA can be Accepted."),
				frappe.ValidationError,
			)
		if self.status == "Accepted" and not (self.electronic_acceptance and self.acceptance_datetime):
			frappe.throw(_("Acceptance date/time is required before status can be Accepted."), frappe.ValidationError)


def _has_management_access(user: str) -> bool:
	return user == "Administrator" or bool(set(frappe.get_roles(user)).intersection(MANAGEMENT_ROLES))


@frappe.whitelist()
def send_for_acceptance(name: str):
	if not _has_management_access(frappe.session.user):
		frappe.throw(_("Only Legal Operations may send this SLA for acceptance."), frappe.PermissionError)
	doc = frappe.get_doc("Master Service Level Agreement", name)
	if doc.status != "Draft":
		frappe.throw(_("Only a Draft SLA can be sent for acceptance."), frappe.ValidationError)
	doc.status = "Sent for Acceptance"
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def accept(
	name: str,
	accepted_by_designation: str,
	ack_read_and_understood: int = 0,
	ack_business_week: int = 0,
	ack_no_24x7_production: int = 0,
	ack_submission_not_sla_start: int = 0,
	ack_lextimator_indicative: int = 0,
	ack_fixed_quote_protection: int = 0,
	ack_scope_changes_affect_price: int = 0,
	ack_confirmed_delivery_date_controls: int = 0,
	ack_priority_subject_to_availability: int = 0,
	ack_no_automatic_express_service: int = 0,
	ack_signatory_authority: int = 0,
):
	"""Record a client's formal, checkbox-by-checkbox acceptance of a Master SLA."""
	doc = frappe.get_doc("Master Service Level Agreement", name)
	if doc.status not in {"Draft", "Sent for Acceptance"}:
		frappe.throw(_("This SLA is not awaiting acceptance."), frappe.ValidationError)

	acks = {
		"ack_read_and_understood": ack_read_and_understood,
		"ack_business_week": ack_business_week,
		"ack_no_24x7_production": ack_no_24x7_production,
		"ack_submission_not_sla_start": ack_submission_not_sla_start,
		"ack_lextimator_indicative": ack_lextimator_indicative,
		"ack_fixed_quote_protection": ack_fixed_quote_protection,
		"ack_scope_changes_affect_price": ack_scope_changes_affect_price,
		"ack_confirmed_delivery_date_controls": ack_confirmed_delivery_date_controls,
		"ack_priority_subject_to_availability": ack_priority_subject_to_availability,
		"ack_no_automatic_express_service": ack_no_automatic_express_service,
		"ack_signatory_authority": ack_signatory_authority,
	}
	missing = [field for field in ACK_FIELDS if not cint(acks[field])]
	if missing:
		frappe.throw(_("Every acknowledgement must be checked before the SLA can be accepted."), frappe.ValidationError)
	if not (accepted_by_designation or "").strip():
		frappe.throw(_("Provide the signatory's designation."), frappe.MandatoryError)

	user = frappe.session.user
	if is_client_user(user):
		portal_user = get_portal_user(user)
		if not portal_user or not has_customer_access(doc.client, user):
			frappe.throw(_("You are not authorized to accept this SLA."), frappe.PermissionError)
	elif not _has_management_access(user):
		frappe.throw(_("You are not authorized to accept this SLA."), frappe.PermissionError)

	for field, value in acks.items():
		doc.set(field, cint(value))
	doc.accepted_by = user
	doc.accepted_by_designation = accepted_by_designation.strip()
	doc.accepted_by_email = frappe.db.get_value("User", user, "email") or user
	doc.acceptance_datetime = now_datetime()
	doc.electronic_acceptance = 1
	doc.ip_address = getattr(frappe.local, "request_ip", None)
	doc.status = "Accepted"
	doc.save(ignore_permissions=True)

	audit_event = create_portal_audit_event(
		client=doc.client,
		user=user,
		action="Master SLA Accepted",
		object_type=doc.doctype,
		object_id=doc.name,
		new_value={"version": doc.version, "accepted_by": user, "designation": doc.accepted_by_designation},
	)
	if audit_event:
		frappe.db.set_value(doc.doctype, doc.name, "acceptance_audit_reference", audit_event.name)
		doc.acceptance_audit_reference = audit_event.name

	_supersede_previous(doc)
	return {
		"name": doc.name,
		"status": doc.status,
		"acceptance_datetime": doc.acceptance_datetime,
		"acceptance_audit_reference": doc.acceptance_audit_reference,
	}


def _supersede_previous(doc):
	previous = frappe.db.get_value(
		"Master Service Level Agreement",
		{"client": doc.client, "status": "Accepted", "name": ["!=", doc.name]},
		"name",
		order_by="effective_date desc",
	)
	if not previous:
		return
	frappe.db.set_value("Master Service Level Agreement", previous, "status", "Superseded")
	frappe.db.set_value("Master Service Level Agreement", previous, "superseded_by", doc.name)
	frappe.db.set_value(doc.doctype, doc.name, "supersedes", previous)
	doc.supersedes = previous


def get_latest_accepted(client: str):
	"""Return the current Accepted Master SLA for a client, or None."""
	name = frappe.db.get_value(
		"Master Service Level Agreement",
		{"client": client, "status": "Accepted"},
		"name",
		order_by="effective_date desc",
	)
	return frappe.get_doc("Master Service Level Agreement", name) if name else None


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if _has_management_access(user):
		return True
	if is_client_user(user):
		return ptype in {"read", "print", "report"} and has_customer_access(doc.client, user)
	return False


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _has_management_access(user):
		return ""
	if is_client_user(user):
		from lex.client_access import customer_sql_condition

		return customer_sql_condition("`tabMaster Service Level Agreement`.client", user)
	return "1=0"
