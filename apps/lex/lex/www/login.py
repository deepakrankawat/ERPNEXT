from __future__ import annotations

import frappe
from frappe import _

no_cache = 1


def get_context(context):
	if frappe.session.user != "Guest":
		redirect_to = frappe.local.request.args.get("redirect-to") or frappe.local.request.args.get("redirect_to")
		if not redirect_to:
			user_type = frappe.db.get_value("User", frappe.session.user, "user_type")
			if user_type == "System User":
				redirect_to = "/app"
			elif user_type == "Website User":
				redirect_to = "/client-portal"
			else:
				roles = set(frappe.get_roles())
				portal_roles = {
					"Lexocrates Client",
					"Lexocrates Client Administrator",
					"Lexocrates Partner General Counsel",
					"Lexocrates Legal User",
					"Lexocrates Operations User",
					"Lexocrates Finance User",
					"Lexocrates Procurement User",
					"Lexocrates Compliance User",
					"Lexocrates Read Only User",
					"Customer",
				}
				if roles.intersection(portal_roles):
					redirect_to = "/client-portal"
				else:
					redirect_to = "/app"
		frappe.local.flags.redirect_location = redirect_to
		raise frappe.Redirect

	context.title = _("Lexocrates Platform Access")
	context.redirect_to = frappe.local.request.args.get("redirect-to") or frappe.local.request.args.get("redirect_to") or ""
	return context
