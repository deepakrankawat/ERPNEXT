from __future__ import annotations

import frappe


def execute():
	"""Retain the former engagement model on records created before the rename."""
	columns = {row[0] for row in frappe.db.sql("show columns from `tabLPO Matter`")}
	if {"engagement_model", "matter_model"}.issubset(columns):
		frappe.db.sql(
			"""
			update `tabLPO Matter`
			set matter_model = engagement_model
			where name like 'ENG-%'
				and engagement_model is not null
				and engagement_model != ''
			"""
		)
