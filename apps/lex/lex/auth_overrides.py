"""Lexocrates-branded overrides for a handful of Frappe core auth emails.

Frappe's core magic-link login flow (frappe.www.login.send_login_link) renders
a hardcoded framework template (frappe/templates/emails/login_with_email_link.html)
wrapped in Frappe's generic default email frame — not the "Email Template"
DocType records this app manages, and not something to edit in frappe core
directly (it would be silently lost on the next framework upgrade). Registered
in hooks.py's override_whitelisted_methods instead, so the guest-facing,
rate-limited whitelisted endpoint keeps its exact original signature and
security behaviour, only the email body changes.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.www.login import _generate_temporary_login_link, get_login_with_email_link_ratelimit


SUPPORT_SENDER = "Lexocrates <support@lexocrates.com>"


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=get_login_with_email_link_ratelimit, seconds=60 * 60)
def send_login_link(email: str):
	from lex.install import _branded_email

	if not frappe.get_system_settings("login_with_email_link"):
		return

	try:
		expiry = frappe.get_system_settings("login_with_email_link_expiry") or 10
		link = _generate_temporary_login_link(email, expiry)

		app_name = (
			frappe.get_website_settings("app_name") or frappe.get_system_settings("app_name") or _("Lexocrates")
		)
		subject = _("Log In to {0}").format(app_name)

		body = f"""	<p style="margin:0 0 16px; color:#111111;">Click the button below to log in to your {frappe.utils.escape_html(app_name)} account.</p>
	<p style="margin:0 0 24px;">
		<a href="{link}" style="display:inline-block; background-color:#0B2545; color:#ffffff; padding:12px 28px; border-radius:6px; font-weight:600; text-decoration:none;">Log In &rarr;</a>
	</p>
	<p style="margin:0; color:#4B5563; font-size:13px;">This link expires in {expiry} minutes. If you did not request it, you can safely ignore this email.</p>
"""
		frappe.sendmail(
			subject=subject,
			recipients=email,
			sender=SUPPORT_SENDER,
			message=_branded_email("Log in to your account", body),
			now=True,
		)
	except frappe.DoesNotExistError:
		frappe.clear_messages()
	except frappe.OutgoingEmailError:
		frappe.clear_messages()
		frappe.log_error(title="Login link email could not be sent", message=frappe.get_traceback())
	except Exception:
		frappe.clear_messages()
		frappe.log_error(title="Login link generation failed unexpectedly", message=frappe.get_traceback())
