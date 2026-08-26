from __future__ import annotations

import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class LPOLexPointServiceRule(Document):
	def validate(self):
		self.service_code = frappe.scrub(self.service_code or self.service_name).upper()
		self.service_name = (self.service_name or "").strip()
		self.internal_pricing_key = f"{self.service_family}|{self.service_name}"
		for fieldname, label in (
			("base_quantity", _("Base Quantity")),
			("standard_hours", _("Estimated Standard Hours")),
			("market_midpoint_per_hour", _("Market Midpoint per Hour")),
			("base_lexpoints", _("Base LexPoints")),
			("default_sla_hours", _("Default SLA Hours")),
		):
			if flt(self.get(fieldname)) <= 0:
				frappe.throw(_("{0} must be greater than zero.").format(label), frappe.ValidationError)
		if not cint(self.base_lexpoints):
			self.base_lexpoints = max(1, math.ceil(flt(self.standard_hours) * flt(self.market_midpoint_per_hour)))


def on_doctype_update():
	frappe.db.add_unique("LPO LexPoint Service Rule", ["service_name"], constraint_name="lexpoint_service_name_unique")
	frappe.db.add_index(
		"LPO LexPoint Service Rule", ["service_family", "active"], index_name="lexpoint_service_family_active"
	)
