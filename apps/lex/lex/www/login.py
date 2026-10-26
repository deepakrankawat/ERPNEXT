from __future__ import annotations
from urllib.parse import urlparse

import frappe
from frappe import _

from lex.mattermost_oauth import get_mattermost_login_url, user_is_mattermost_only
from lex.portal_management import _safe_local_redirect

no_cache = 1

# OAuth2 clients (e.g. the Mattermost mobile app's GitLab-SSO login) redirect guests
# here to authenticate, then need to resume at this exact endpoint afterwards.
OAUTH_AUTHORIZE_PATH = "/api/method/frappe.integrations.oauth2.authorize"


def _relative_redirect(value: str | None) -> str:
	"""Collapse an absolute same-site URL (as sent by frappe.integrations.oauth2.authorize)
	down to a bare path+query so `_safe_local_redirect` can validate it."""
	value = str(value or "").strip()
	if not value:
		return ""
	parsed = urlparse(value)
	if parsed.netloc and parsed.netloc != urlparse(frappe.local.request.url).netloc:
		return ""
	path = parsed.path or ""
	if parsed.query:
		path = f"{path}?{parsed.query}"
	return path


def get_context(context):
	requested_redirect = _safe_local_redirect(
		_relative_redirect(
			frappe.local.request.args.get("redirect-to") or frappe.local.request.args.get("redirect_to")
		),
		"",
	)
	if frappe.session.user != "Guest":
		redirect_to = requested_redirect
		if not redirect_to and user_is_mattermost_only():
			redirect_to = get_mattermost_login_url()
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
	if requested_redirect.startswith("/client-portal"):
		frappe.local.flags.redirect_location = "/client-login?redirect-to=/client-portal"
		raise frappe.Redirect

	context.title = _("Lexocrates Legal Desk Access")
	# Left blank (not defaulted to "/app") when there's no explicit redirect request,
	# so the login page's JS can tell "nothing requested" apart from "/app was
	# requested" and still apply the Mattermost-only override in the former case.
	context.redirect_to = (
		requested_redirect
		if requested_redirect.startswith(("/app", OAUTH_AUTHORIZE_PATH))
		else ""
	)
	return context
