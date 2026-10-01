from __future__ import annotations

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now_datetime

from lex.client_access import get_portal_user, has_customer_access, is_client_user
from lex.portal_audit import _safe_user_agent, create_portal_audit_event


MANAGEMENT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager"}
SALES_SENDER = "Lexocrates <sales@lexocrates.com>"
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

# Once a Master SLA has been Accepted it becomes a legal record: none of these
# fields may change again, on any save, by any role. The only legitimate
# post-acceptance mutations are status moving to Superseded/Terminated and the
# operational bookkeeping fields below (set via direct frappe.db.set_value
# calls, which never re-run validate() anyway). Accepting a *new* version is
# done by creating a brand-new Master Service Level Agreement document, never
# by editing an already-Accepted one.
LOCKED_AFTER_ACCEPTANCE_FIELDS = ACK_FIELDS + (
	"version",
	"effective_date",
	"client",
	"client_legal_name",
	"client_address",
	"terms_html",
	"lexocrates_representative_name",
	"lexocrates_representative_designation",
	"lexocrates_signed_on",
	"accepted_by_name",
	"accepted_by",
	"accepted_by_designation",
	"accepted_by_email",
	"acceptance_datetime",
	"electronic_acceptance",
	"ip_address",
	"user_agent",
	"accepted_terms_hash",
)


def hash_terms_html(terms_html: str | None) -> str:
	"""SHA-256 of the exact Terms text as shown to the Client at acceptance time,
	so a later edit to this record (or a dispute over what was agreed) can be
	checked against the hash permanently recorded on the acceptance audit event."""
	return hashlib.sha256((terms_html or "").encode("utf-8")).hexdigest()


class MasterServiceLevelAgreement(Document):
	def validate(self):
		if self.status == "Accepted" and not all(cint(self.get(field)) for field in ACK_FIELDS):
			frappe.throw(
				_("All client acknowledgement checkboxes must be accepted before this SLA can be Accepted."),
				frappe.ValidationError,
			)
		if self.status == "Accepted" and not (self.electronic_acceptance and self.acceptance_datetime):
			frappe.throw(_("Acceptance date/time is required before status can be Accepted."), frappe.ValidationError)
		self._enforce_post_acceptance_lock()

	def _enforce_post_acceptance_lock(self):
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if not before or before.status != "Accepted":
			return
		for fieldname in LOCKED_AFTER_ACCEPTANCE_FIELDS:
			if frappe.utils.cstr(self.get(fieldname)) != frappe.utils.cstr(before.get(fieldname)):
				frappe.throw(
					_(
						"This Master SLA was Accepted on {0} and is now a locked legal record — "
						"it cannot be edited. Create a new Master Service Level Agreement to "
						"supersede it instead."
					).format(frappe.utils.format_datetime(before.acceptance_datetime) if before.acceptance_datetime else before.name),
					frappe.ValidationError,
				)

	def on_trash(self):
		if self.status == "Accepted":
			frappe.throw(
				_("An Accepted Master SLA is a legal record and cannot be deleted."),
				frappe.PermissionError,
			)


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


SLA_PRINT_FORMAT = "Master Service Level Agreement"


@frappe.whitelist()
def accept(
	name: str,
	accepted_by_name: str,
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
	if not (accepted_by_name or "").strip():
		frappe.throw(_("Provide the authorized representative's name."), frappe.MandatoryError)

	user = frappe.session.user
	if is_client_user(user):
		portal_user = get_portal_user(user)
		if not portal_user or not has_customer_access(doc.client, user):
			frappe.throw(_("You are not authorized to accept this SLA."), frappe.PermissionError)
	elif not _has_management_access(user):
		frappe.throw(_("You are not authorized to accept this SLA."), frappe.PermissionError)

	# Hash the Terms text exactly as it stands right now — i.e. exactly as shown
	# to the Client on the acceptance screen — before anything else on this
	# document changes, so the hash can never reflect a later edit.
	terms_hash = hash_terms_html(doc.terms_html)

	for field, value in acks.items():
		doc.set(field, cint(value))
	doc.accepted_by = user
	doc.accepted_by_name = accepted_by_name.strip()
	doc.accepted_by_designation = accepted_by_designation.strip()
	doc.accepted_by_email = frappe.db.get_value("User", user, "email") or user
	doc.acceptance_datetime = now_datetime()
	doc.electronic_acceptance = 1
	doc.ip_address = getattr(frappe.local, "request_ip", None)
	doc.user_agent = _safe_user_agent()
	doc.accepted_terms_hash = terms_hash
	doc.status = "Accepted"
	doc.save(ignore_permissions=True)

	audit_event = create_portal_audit_event(
		client=doc.client,
		user=user,
		action="Master SLA Accepted",
		object_type=doc.doctype,
		object_id=doc.name,
		new_value={
			"version": doc.version,
			"accepted_by": user,
			"designation": doc.accepted_by_designation,
			"accepted_terms_hash": terms_hash,
		},
	)
	if audit_event:
		frappe.db.set_value(doc.doctype, doc.name, "acceptance_audit_reference", audit_event.name)
		doc.acceptance_audit_reference = audit_event.name

	_supersede_previous(doc)
	_email_signed_copy(doc)
	return {
		"name": doc.name,
		"status": doc.status,
		"acceptance_datetime": doc.acceptance_datetime,
		"acceptance_audit_reference": doc.acceptance_audit_reference,
		"pdf_emailed_to": doc.pdf_emailed_to,
	}


def _email_signed_copy(doc):
	"""Best-effort: email the signed SLA as a PDF to the client's own address.

	Never blocks acceptance itself — a failed email is logged, not raised, since
	the acceptance record (and its audit event) is already durably saved.
	"""
	if not doc.accepted_by_email:
		return
	from lex.work_intake import _outgoing_email_is_ready

	if not _outgoing_email_is_ready() or getattr(frappe.flags, "in_test", False):
		return
	try:
		pdf = frappe.attach_print(
			doc.doctype,
			doc.name,
			print_format=SLA_PRINT_FORMAT,
			doc=doc,
		)
		message = _(
			"<p>Attached is your signed copy of the Master Service Level Agreement "
			"between {0} and Lexocrates Legal Services Private Limited, accepted on "
			"{1} by {2} ({3}).</p><p>Please retain this copy for your records.</p>"
		).format(
			frappe.utils.escape_html(doc.client_legal_name or doc.client),
			frappe.utils.format_datetime(doc.acceptance_datetime),
			frappe.utils.escape_html(doc.accepted_by_name),
			frappe.utils.escape_html(doc.accepted_by_designation),
		)
		frappe.sendmail(
			recipients=[doc.accepted_by_email],
			subject=_("Your signed Lexocrates Master Service Level Agreement ({0})").format(doc.version),
			sender=SALES_SENDER,
			message=message,
			attachments=[pdf],
			reference_doctype=doc.doctype,
			reference_name=doc.name,
			delayed=False,
			send_priority=1,
			x_priority=1,
			add_unsubscribe_link=0,
		)
		doc.pdf_emailed_on = now_datetime()
		doc.pdf_emailed_to = doc.accepted_by_email
		frappe.db.set_value(
			doc.doctype, doc.name,
			{"pdf_emailed_on": doc.pdf_emailed_on, "pdf_emailed_to": doc.pdf_emailed_to},
		)
		create_portal_audit_event(
			client=doc.client,
			user=doc.accepted_by,
			action="Master SLA Signed Copy Emailed",
			object_type=doc.doctype,
			object_id=doc.name,
			new_value={"recipient": doc.accepted_by_email},
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"Master SLA signed-copy email failed for {doc.name}")


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


def get_or_create_pending_master_sla(client: str):
	"""Return the client's Draft/Sent-for-Acceptance Master SLA, auto-provisioning
	the standard company-wide one on first use. Never creates a second pending
	record if one already exists, and never touches an Accepted one — this is
	strictly the "no formal SLA yet" onboarding path."""
	pending_name = frappe.db.get_value(
		"Master Service Level Agreement",
		{"client": client, "status": ["in", ["Draft", "Sent for Acceptance"]]},
		"name",
		order_by="creation desc",
	)
	if pending_name:
		doc = frappe.get_doc("Master Service Level Agreement", pending_name)
		if doc.status == "Draft":
			doc.status = "Sent for Acceptance"
			doc.save(ignore_permissions=True)
		return doc

	from lex.work_intake import DEFAULT_SLA_TERMS

	doc = frappe.get_doc({
		"doctype": "Master Service Level Agreement",
		"version": "1.0",
		"effective_date": frappe.utils.nowdate(),
		"client": client,
		"terms_html": DEFAULT_SLA_TERMS.replace("\n", "<br>"),
		"status": "Sent for Acceptance",
		"lexocrates_representative_name": "Lexocrates Legal Operations",
		"lexocrates_representative_designation": "Legal Operations",
		"lexocrates_signed_on": frappe.utils.nowdate(),
	}).insert(ignore_permissions=True)
	return doc


@frappe.whitelist()
def get_my_master_sla_status():
	"""Portal-facing: does the current client have an Accepted Master SLA yet?
	If not, auto-provision (or fetch) the pending one and return everything the
	client-portal onboarding gate needs to render the acceptance form."""
	from lex.work_intake import _require_portal_user

	actor = _require_portal_user()
	accepted = get_latest_accepted(actor.client)
	if accepted:
		return {"status": "Accepted", "name": accepted.name}

	doc = get_or_create_pending_master_sla(actor.client)
	return {
		"status": doc.status,
		"name": doc.name,
		"version": doc.version,
		"terms_html": doc.terms_html,
		"client_legal_name": doc.client_legal_name or actor.client,
		"prefill_email": frappe.db.get_value("User", frappe.session.user, "email") or frappe.session.user,
	}


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if _has_management_access(user):
		return True
	if is_client_user(user):
		return ptype in {"read", "print", "report"} and has_customer_access(doc.client, user)
	return False


SLA_PRINT_FORMAT_HTML = """
<div class="sla-print" style="font-family:'Helvetica Neue',Arial,sans-serif;color:#1a1a1a;line-height:1.5;font-size:13px;">
	<h2 style="text-align:center;margin-bottom:4px;">MASTER SERVICE LEVEL AGREEMENT</h2>
	<p style="text-align:center;margin-top:0;color:#555;">Legal Process Outsourcing &amp; Legal Support Services &middot; Version {{ doc.version }}</p>

	<table style="width:100%;margin:16px 0;">
		<tr><td style="width:50%;"><strong>Company:</strong> {{ doc.company }}</td><td><strong>Effective Date:</strong> {{ frappe.utils.formatdate(doc.effective_date) if doc.effective_date else "" }}</td></tr>
		<tr><td><strong>Client:</strong> {{ doc.client_legal_name or doc.client }}</td><td><strong>Status:</strong> {{ doc.status }}</td></tr>
	</table>
	{% if doc.client_address %}<p><strong>Address:</strong> {{ doc.client_address }}</p>{% endif %}

	<div style="margin:16px 0;">{{ doc.terms_html or "" }}</div>

	<p>This SLA may be accepted electronically during Client onboarding.<br>By accepting this SLA, the Client confirms that:</p>
	{% set acks = [
		(doc.ack_read_and_understood, "it has read and understood the SLA;"),
		(doc.ack_business_week, "it understands that Lexocrates operates a Monday-to-Friday Business Week;"),
		(doc.ack_no_24x7_production, "it understands that the Client Portal may accept submissions outside Business Days but that this does not constitute 24/7 production service;"),
		(doc.ack_submission_not_sla_start, "it understands that submission of an Assignment does not itself commence the delivery period;"),
		(doc.ack_lextimator_indicative, "it understands that Lextimator&trade; may provide an Indicative Turnaround which is subject to scope and capacity review;"),
		(doc.ack_fixed_quote_protection, "it understands that a Fixed Quote will not be increased merely because Lexocrates underestimated the internal time or resources required for the unchanged agreed scope;"),
		(doc.ack_scope_changes_affect_price, "it understands that material Client-initiated changes to scope may result in a revised price and delivery date;"),
		(doc.ack_confirmed_delivery_date_controls, "it understands that the Confirmed Delivery Date contained in the approved Assignment Confirmation is the applicable delivery commitment;"),
		(doc.ack_priority_subject_to_availability, "it understands that Priority Service is subject to operational availability;"),
		(doc.ack_no_automatic_express_service, "it understands that Lexocrates does not presently provide a general entitlement to Express, same-day, weekend or emergency delivery; and"),
		(doc.ack_signatory_authority, "the individual accepting this SLA is authorized to accept it on behalf of the Client."),
	] %}
	<ul style="list-style:none;padding-left:0;">
		{% for checked, text in acks %}
		<li style="margin-bottom:6px;">{{ "&#9745;" if checked else "&#9744;" }}&nbsp; {{ text }}</li>
		{% endfor %}
	</ul>

	<table style="width:100%;margin-top:28px;border-collapse:collapse;">
		<tr>
			<td style="width:50%;vertical-align:top;padding-right:16px;">
				<h4>ACCEPTED FOR THE CLIENT</h4>
				<p>
					Organization: {{ doc.client_legal_name or doc.client or "" }}<br>
					Authorized Representative: {{ doc.accepted_by_name or "" }}<br>
					Designation: {{ doc.accepted_by_designation or "" }}<br>
					Email: {{ doc.accepted_by_email or "" }}<br>
					Date &amp; Time: {{ frappe.utils.format_datetime(doc.acceptance_datetime) if doc.acceptance_datetime else "" }}<br>
					Electronic Signature / Acceptance: {{ "Accepted electronically" if doc.electronic_acceptance else "" }}<br>
					{% if doc.accepted_terms_hash %}<small>Terms Checksum (SHA-256): {{ doc.accepted_terms_hash }}</small>{% endif %}
				</p>
			</td>
			<td style="width:50%;vertical-align:top;padding-left:16px;border-left:1px solid #ccc;">
				<h4>LEXOCRATES LEGAL SERVICES PRIVATE LIMITED</h4>
				<p>
					Authorized Representative: {{ doc.lexocrates_representative_name or "" }}<br>
					Designation: {{ doc.lexocrates_representative_designation or "" }}<br>
					Date: {{ frappe.utils.formatdate(doc.lexocrates_signed_on) if doc.lexocrates_signed_on else "" }}
				</p>
			</td>
		</tr>
	</table>
</div>
"""


def ensure_print_format():
	"""Idempotently install/refresh the Master SLA Print Format used for the
	client's signed-copy PDF. Registered in hooks.py's after_migrate so it stays
	in sync with SLA_PRINT_FORMAT_HTML across deploys."""
	if frappe.db.exists("Print Format", SLA_PRINT_FORMAT):
		doc = frappe.get_doc("Print Format", SLA_PRINT_FORMAT)
	else:
		doc = frappe.new_doc("Print Format")
		doc.name = SLA_PRINT_FORMAT
		doc.doc_type = "Master Service Level Agreement"
	doc.module = "Lex"
	doc.print_format_type = "Jinja"
	doc.standard = "No"
	doc.disabled = 0
	doc.html = SLA_PRINT_FORMAT_HTML
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _has_management_access(user):
		return ""
	if is_client_user(user):
		from lex.client_access import customer_sql_condition

		return customer_sql_condition("`tabMaster Service Level Agreement`.client", user)
	return "1=0"
