import frappe

MATTERMOST_LOGIN_URL = "https://msg.lexocrates.com/oauth/gitlab/login"


def execute():
	frappe.reload_doc("core", "doctype", "navbar_settings")
	frappe.reload_doc("core", "doctype", "navbar_item")

	navbar_settings = frappe.get_single("Navbar Settings")

	if frappe.db.exists("Navbar Item", {"item_label": "Mattermost", "parent": navbar_settings.name}):
		return

	theme_item = next(
		(d for d in navbar_settings.settings_dropdown if d.item_label == "Toggle Theme"), None
	)
	insert_at = theme_item.idx if theme_item else len(navbar_settings.settings_dropdown)

	for navbar_item in navbar_settings.settings_dropdown:
		if navbar_item.idx > insert_at:
			navbar_item.idx = navbar_item.idx + 1

	navbar_settings.append(
		"settings_dropdown",
		{
			"item_label": "Mattermost",
			"item_type": "Action",
			"action": f"window.open('{MATTERMOST_LOGIN_URL}', '_blank')",
			"idx": insert_at + 1,
		},
	)

	navbar_settings.save()
