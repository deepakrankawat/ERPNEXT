from __future__ import annotations

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import escape_html, get_url_to_form, now_datetime, strip_html_tags, validate_email_address


SALES_NOTIFICATION_TEMPLATE = "Lexocrates Website Contact - Sales Notification"
SALES_FALLBACK_EMAIL = "sales@lexocrates.com"


def _plain_text(value: str | None, limit: int) -> str:
	return " ".join(strip_html_tags(value or "").split())[:limit]


def _sales_manager_recipients() -> list[str]:
	users = frappe.get_all(
		"Has Role",
		filters={"role": "Sales Manager", "parenttype": "User"},
		pluck="parent",
	)
	recipients = []
	for user in users:
		values = frappe.db.get_value("User", user, ["enabled", "email"], as_dict=True)
		if values and values.enabled and values.email:
			recipients.append(values.email.strip().lower())
	return sorted(set(recipients)) or [SALES_FALLBACK_EMAIL]


def _notify_sales_managers(*, lead, name: str, email: str, subject: str, message: str):
	template = frappe.get_doc("Email Template", SALES_NOTIFICATION_TEMPLATE)
	context = {
		"lead_name": escape_html(lead.name),
		"lead_url": get_url_to_form("Lead", lead.name),
		"request_name": escape_html(name),
		"request_email": escape_html(email),
		"request_subject": escape_html(subject),
		"request_message": escape_html(message),
		"submitted_on": escape_html(str(now_datetime())),
	}
	frappe.sendmail(
		recipients=_sales_manager_recipients(),
		reply_to=email,
		subject=frappe.render_template(template.subject, context),
		message=frappe.render_template(template.response_html, context),
		now=False,
		reference_doctype="Lead",
		reference_name=lead.name,
	)


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=5, seconds=60 * 60, methods="POST")
def submit_contact_request(
	name: str,
	email: str,
	subject: str,
	message: str,
	website: str | None = None,
):
	"""Create a CRM lead from the public compliance contact page."""
	if frappe.request and frappe.request.method != "POST":
		frappe.throw(_("Only POST requests are accepted."), frappe.PermissionError)

	# Bots commonly populate this visually hidden field. Return the normal success
	# response so the endpoint does not reveal the anti-spam rule.
	if (website or "").strip():
		return {"ok": True, "message": _("Thank you. We will respond within 24 business hours.")}

	name = _plain_text(name, 140)
	subject = _plain_text(subject, 180)
	message = strip_html_tags(message or "").strip()[:4000]
	email = validate_email_address((email or "").strip().lower(), throw=True)

	if not name or not subject or not message or not email:
		frappe.throw(_("Name, business email, subject and message are required."), frappe.MandatoryError)
	if len(message) < 10:
		frappe.throw(_("Please provide a little more detail so our team can assist."), frappe.ValidationError)

	lead = frappe.new_doc("Lead")
	lead.first_name = name
	lead.email_id = email
	lead.status = "Lead"
	lead.notes = f"Public website contact\n\nSubject: {subject}\n\n{message}"
	lead.flags.ignore_permissions = True
	lead.insert()
	try:
		_notify_sales_managers(
			lead=lead,
			name=name,
			email=email,
			subject=subject,
			message=message,
		)
	except Exception:
		# The enquiry remains safely recorded even when SMTP or the queue is
		# temporarily unavailable. Operations can retry from the Lead timeline.
		frappe.log_error(frappe.get_traceback(), f"Website enquiry notification failed for {lead.name}")

	return {
		"ok": True,
		"message": _("Thank you. We will respond within 24 business hours."),
	}
