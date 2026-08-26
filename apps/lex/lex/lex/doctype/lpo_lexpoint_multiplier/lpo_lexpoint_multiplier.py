from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class LPOLexPointMultiplier(Document):
	def validate(self):
		self.factor_key = (self.factor_key or "").strip()
		self.rule_key = f"{frappe.scrub(self.factor_type)}__{frappe.scrub(self.factor_key)}".upper()
		if flt(self.multiplier) <= 0:
			frappe.throw(_("Multiplier must be greater than zero."), frappe.ValidationError)
		if self.factor_type == "Complexity":
			if self.minimum_score is None or self.maximum_score is None:
				frappe.throw(_("Complexity rules require minimum and maximum scores."), frappe.ValidationError)
			if not (1 <= int(self.minimum_score) <= int(self.maximum_score) <= 100):
				frappe.throw(_("Complexity score range must be between 1 and 100."), frappe.ValidationError)
		else:
			self.minimum_score = None
			self.maximum_score = None


def on_doctype_update():
	frappe.db.add_unique(
		"LPO LexPoint Multiplier", ["factor_type", "factor_key"], constraint_name="lexpoint_multiplier_factor_unique"
	)
	frappe.db.add_index(
		"LPO LexPoint Multiplier", ["factor_type", "active"], index_name="lexpoint_multiplier_type_active"
	)
