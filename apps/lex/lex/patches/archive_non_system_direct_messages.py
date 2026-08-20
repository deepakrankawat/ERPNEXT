from __future__ import annotations

import frappe


def execute():
	"""Retire legacy direct-message rooms involving Website Users."""
	if not frappe.db.exists("DocType", "Lexocrates Chat Channel"):
		return
	channels = frappe.get_all(
		"Lexocrates Chat Channel",
		filters={"is_direct_message": 1, "status": ["!=", "Archived"]},
		pluck="name",
		limit_page_length=0,
	)
	for channel in channels:
		users = frappe.get_all(
			"Lexocrates Chat Member",
			filters={"parent": channel, "parenttype": "Lexocrates Chat Channel"},
			pluck="user",
			limit_page_length=0,
		)
		if len(users) != 2 or any(
			frappe.db.get_value("User", user, "user_type") != "System User" for user in users
		):
			frappe.db.set_value(
				"Lexocrates Chat Channel",
				channel,
				"status",
				"Archived",
				update_modified=False,
			)
