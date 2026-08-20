from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from lex.client_access import get_portal_user


MANAGEMENT_ROLES = {"System Manager", "LPO_Admin", "LPO_Manager", "Lexocrates Finance", "Accounts Manager"}
LOCKED_AFTER_FUNDING = {
	"client", "portal_user", "submitted_by", "service_type", "jurisdiction", "priority",
	"preliminary_details", "detailed_instructions", "expected_outcome", "sla_terms_snapshot", "sla_snapshot_hash",
	"quoted_amount", "currency", "required_lexpoints", "scope_summary", "delivery_timeline_hours",
	"funding_route", "matter", "job",
}


class LexocratesWorkIntake(Document):
	def before_insert(self):
		if not getattr(frappe.flags, "lexocrates_intake_service", False):
			frappe.throw(_("Work Intakes must be created through the secure client intake service."), frappe.PermissionError)

	def validate(self):
		if self.sla_accepted and not all((self.sla_accepted_by, self.sla_accepted_on, self.sla_snapshot_hash)):
			frappe.throw(_("The accepted SLA must retain its user, timestamp and snapshot hash."), frappe.ValidationError)
		if self.document_count and not self.sla_accepted:
			frappe.throw(_("Document upload remains locked until the SLA is accepted."), frappe.ValidationError)
		if self.quote_status in {"Ready", "Accepted"}:
			if flt(self.quoted_amount) <= 0 or flt(self.required_lexpoints) <= 0 or not self.scope_summary:
				frappe.throw(_("A ready quote requires an amount, LexPoints and confirmed scope."), frappe.ValidationError)
		if self.funding_status == "Funded" and self.funding_route == "Not Selected":
			frappe.throw(_("A funded intake must record its funding route."), frappe.ValidationError)
		previous = self.get_doc_before_save()
		if previous and previous.funding_status == "Funded" and not getattr(frappe.flags, "lexocrates_intake_service", False):
			changed = [self.meta.get_label(field) for field in LOCKED_AFTER_FUNDING if self.has_value_changed(field)]
			if changed:
				frappe.throw(
					_("Funded intake terms are immutable: {0}").format(", ".join(sorted(changed))),
					frappe.PermissionError,
				)

	def before_save(self):
		if self.is_new() or getattr(frappe.flags, "lexocrates_intake_service", False) or _is_internal(frappe.session.user):
			return
		frappe.throw(_("Client changes must use the controlled intake actions."), frappe.PermissionError)

	def on_trash(self):
		if self.document_count or self.quote_version or self.funding_status != "Not Started":
			frappe.throw(_("An auditable Work Intake cannot be deleted after processing starts."), frappe.PermissionError)


def _is_internal(user: str) -> bool:
	return user == "Administrator" or bool(set(frappe.get_roles(user)).intersection(MANAGEMENT_ROLES))


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if _is_internal(user):
		return True
	if ptype != "read":
		return False
	actor = get_portal_user(user)
	if not actor or actor.client != doc.client:
		return False
	return actor.matter_access_scope == "All Client Matters" or doc.portal_user == actor.name


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _is_internal(user):
		return ""
	actor = get_portal_user(user)
	if not actor:
		return "1=0"
	client = frappe.db.escape(actor.client)
	if actor.matter_access_scope == "All Client Matters":
		return f"`tabLexocrates Work Intake`.client = {client}"
	return (
		f"`tabLexocrates Work Intake`.client = {client} and "
		f"`tabLexocrates Work Intake`.portal_user = {frappe.db.escape(actor.name)}"
	)


def on_doctype_update():
	frappe.db.add_unique(
		"Lexocrates Work Intake", ["razorpay_order_id"], constraint_name="work_intake_razorpay_order_unique"
	)
	frappe.db.add_unique(
		"Lexocrates Work Intake", ["razorpay_payment_id"], constraint_name="work_intake_razorpay_payment_unique"
	)
	frappe.db.add_index(
		"Lexocrates Work Intake", ["client", "created_on"], index_name="work_intake_client_created"
	)
	frappe.db.add_index(
		"Lexocrates Work Intake", ["status", "modified"], index_name="work_intake_status_modified"
	)
