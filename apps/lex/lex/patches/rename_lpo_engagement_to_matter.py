from __future__ import annotations

import frappe


def execute():
	"""Preserve existing records while adopting the client-facing Matter name."""
	old_name = "LPO Engagement"
	new_name = "LPO Matter"

	if not frappe.db.exists("DocType", old_name):
		return
	if frappe.db.exists("DocType", new_name):
		frappe.throw(
			"Cannot rename LPO Engagement because LPO Matter already exists. "
			"Resolve the duplicate DocTypes before continuing the migration."
		)

	frappe.rename_doc("DocType", old_name, new_name, force=True)
