from __future__ import annotations

import zlib

import frappe


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
