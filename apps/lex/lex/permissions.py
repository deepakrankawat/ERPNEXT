import frappe


LPO_APP_ROLES = {
	"LPO_Admin",
	"LPO_Manager",
	"LPO_Analyst",
	"System Manager",
	"Junior Legal Associate",
	"Senior Legal Associate",
	"Lexocrates QA Manager",
	"Lexocrates Operations Manager",
	"Lexocrates AI Manager",
	"Lexocrates Compliance Officer",
	"Lexocrates Director",
}
CHAT_APP_ROLES = LPO_APP_ROLES | {
	"Lexocrates Client",
	"Lexocrates Sales & Marketing",
	"Lexocrates HR",
	"Lexocrates Finance",
}


def _has_any_role(roles: set[str]) -> bool:
	if frappe.session.user == "Administrator":
		return True
	# Apps-screen entries are Desk destinations. Website clients use the same
	# features through /client-portal and must never be redirected into /app.
	if frappe.db.get_value("User", frappe.session.user, "user_type") != "System User":
		return False
	return bool(roles.intersection(frappe.get_roles(frappe.session.user)))


def can_access_operations_app() -> bool:
	"""Show operational tools only to legal-production and system roles."""
	return _has_any_role(LPO_APP_ROLES)


def can_access_chat_app() -> bool:
	"""Expose native communication to every approved Lexocrates persona."""
	return _has_any_role(CHAT_APP_ROLES)


def can_access_app() -> bool:
	"""Backward-compatible alias for existing integrations."""
	return can_access_operations_app()
