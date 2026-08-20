from __future__ import annotations

import frappe


def execute():
	"""Copy renamed field values and provision chat for migrated Matters."""
	if not frappe.db.exists("DocType", "LPO Matter"):
		return

	column_map = {
		"engagement_title": "matter_title",
		"engagement_model": "matter_model",
		"engagement_manager": "matter_manager",
	}
	columns = {row[0] for row in frappe.db.sql("show columns from `tabLPO Matter`")}
	for old_field, new_field in column_map.items():
		if old_field not in columns or new_field not in columns:
			continue
		frappe.db.sql(
			f"""
			update `tabLPO Matter`
			set `{new_field}` = `{old_field}`
			where (`{new_field}` is null or `{new_field}` = '')
				and `{old_field}` is not null
				and `{old_field}` != ''
			"""
		)

	from lex.lexocrates_chat_sync import ensure_matter_chat_channel

	for matter_name in frappe.get_all("LPO Matter", pluck="name"):
		ensure_matter_chat_channel(matter_name)
