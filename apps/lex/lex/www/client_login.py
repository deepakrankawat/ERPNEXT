from __future__ import annotations

import frappe
from frappe import _

from lex.portal_management import _safe_client_redirect


no_cache = 1


def get_context(context):
	if frappe.session.user != "Guest":
		user_type = frappe.db.get_value("User", frappe.session.user, "user_type")
		frappe.local.flags.redirect_location = (
			_safe_client_redirect(
				frappe.local.request.args.get("redirect-to")
				or frappe.local.request.args.get("redirect_to")
			)
			if user_type == "Website User"
			else "/app"
		)
		raise frappe.Redirect

	context.no_cache = 1
	context.full_width = 1
	context.body_class = "lex-client-login-page"
	context.title = _("Lexocrates Client Portal Login")
	context.redirect_to = _safe_client_redirect(
		frappe.local.request.args.get("redirect-to")
		or frappe.local.request.args.get("redirect_to")
	)
	return context
