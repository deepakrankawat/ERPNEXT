import frappe


def get_context(context):
	context.no_cache = 1
	context.full_width = 1
	context.body_class = "lex-client-workspace-page"
	context.title = "Client Workspace"
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/client-portal"
		raise frappe.Redirect
	context.portal_access_denied = not frappe.db.exists(
		"Lexocrates Portal User",
		{"user": frappe.session.user, "account_status": "Active"},
	)
	return context
