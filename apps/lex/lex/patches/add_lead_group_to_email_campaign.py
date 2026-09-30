import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	"""Let Email Campaign target a Lead Group, the same way it already targets an Email Group."""
	options = frappe.db.get_value("DocField", {"parent": "Email Campaign", "fieldname": "email_campaign_for"}, "options") or ""
	if "Lead Group" in options.split("\n"):
		return
	make_property_setter(
		"Email Campaign",
		"email_campaign_for",
		"options",
		"\nLead\nContact\nEmail Group\nLead Group",
		"Select",
	)
