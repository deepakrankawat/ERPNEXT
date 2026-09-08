from __future__ import annotations

import frappe
from frappe import _

from lex.portal_management import verify_email_login_token


no_cache = 1


def get_context(context):
	"""Consume a one-time login token and redirect into the authenticated session."""
	token = frappe.local.request.args.get("token")
	if not token:
		context.error = _("No login token provided.")
		return context

	try:
		result = verify_email_login_token(token)
		frappe.local.flags.redirect_location = result.get("redirect") or "/client-portal"
		raise frappe.Redirect
	except frappe.Redirect:
		raise
	except Exception as exc:
		context.error = str(exc)
		return context
