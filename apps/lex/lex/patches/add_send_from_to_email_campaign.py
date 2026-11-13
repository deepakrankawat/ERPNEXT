import frappe


def execute():
	"""Add an Email Account picker to Email Campaign so a campaign can be sent
	as sales/info/hr/support instead of only the legacy `sender` User field,
	which can't represent info@/support@ at all since no User record exists
	for either address."""
	if frappe.db.exists("Custom Field", "Email Campaign-send_from"):
		return
	frappe.get_doc({
		"doctype": "Custom Field",
		"dt": "Email Campaign",
		"fieldname": "send_from",
		"label": "Send From",
		"fieldtype": "Link",
		"options": "Email Account",
		"insert_after": "sender",
		"description": "Only accounts you have permission to send from are selectable.",
	}).insert(ignore_permissions=True)
