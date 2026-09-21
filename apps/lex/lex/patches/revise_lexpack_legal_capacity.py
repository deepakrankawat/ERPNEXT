"""Seed the approved LexPack value advantages after the Legal Capacity schema is available."""

import frappe


DISCOUNTS = {
	"STARTER": 7,
	"GROWTH": 14,
	"PROFESSIONAL": 21,
	"BUSINESS": 28,
}


def execute():
	for plan in frappe.get_all("LexPack Plan", fields=["name", "plan_code"]):
		code = (plan.plan_code or plan.name or "").upper()
		if code in DISCOUNTS:
			frappe.db.set_value(
				"LexPack Plan",
				plan.name,
				{"discount_percent": DISCOUNTS[code], "value_advantage": f"{DISCOUNTS[code]}% savings"},
				update_modified=False,
			)
		elif code == "ENTERPRISE":
			frappe.db.set_value(
				"LexPack Plan", plan.name, "value_advantage", "Custom commercial terms", update_modified=False
			)
