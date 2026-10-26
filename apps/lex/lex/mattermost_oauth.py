from __future__ import annotations

import zlib

import frappe

# Users holding only this role have no Desk access (see lex.install.ensure_lpo_roles);
# logging in should bounce them straight into Mattermost instead of /app.
MATTERMOST_ONLY_ROLE = "LPO_Mattermost_Only"


def get_mattermost_login_url() -> str | None:
	mm_settings = frappe.get_cached_doc("Mattermost Settings")
	if not mm_settings.enabled or not mm_settings.mattermost_url:
		return None
	return f"{mm_settings.mattermost_url.rstrip('/')}/oauth/gitlab/login"


def user_is_mattermost_only(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False
	return MATTERMOST_ONLY_ROLE in frappe.get_roles(user)


@frappe.whitelist()
def get_mattermost_only_redirect() -> str | None:
	"""Called by the staff login page right after a successful login; returns the
	Mattermost SSO URL when this user's only purpose is messaging, else None."""
	if not user_is_mattermost_only():
		return None
	return get_mattermost_login_url()


@frappe.whitelist()
def gitlab_user_profile():
	"""GitLab-compatible userinfo endpoint consumed by Mattermost's GitLab SSO client.

	Mattermost's GitLab OAuth provider expects: id, username, login, email, name,
	preferred_username. Frappe's OAuth2 bearer-token auth already resolves
	frappe.session.user before this whitelisted method runs.
	"""
	user_email = frappe.session.user
	if not user_email or user_email == "Guest":
		frappe.throw("Not authenticated", frappe.AuthenticationError)

	user = frappe.get_doc("User", user_email)
	handle = user.username or user_email.split("@")[0]
	# Stable positive int derived from email; Mattermost persists this as AuthData.
	uid = zlib.crc32(user_email.encode("utf-8")) & 0x7FFFFFFF

	# Mattermost expects a flat JSON object, not Frappe's default {"message": ...} envelope.
	frappe.local.response = frappe._dict({
		"id": uid,
		"username": handle,
		"login": handle,
		"email": user_email,
		"name": user.full_name or user_email,
		"preferred_username": handle,
	})
