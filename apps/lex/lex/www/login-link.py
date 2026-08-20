from __future__ import annotations

import frappe
from frappe import _
from lex.portal_management import verify_email_login_token

no_cache = 1


def get_context(context):
	token = frappe.local.request.args.get("token")
	if not token:
		context.error = _("No login token provided.")
		return context

	try:
		res = verify_email_login_token(token)
		frappe.local.flags.redirect_location = res.get("redirect") or "/client-portal"
		raise frappe.Redirect
	except frappe.Redirect:
		raise
	except Exception as e:
		context.error = str(e)
		return context
