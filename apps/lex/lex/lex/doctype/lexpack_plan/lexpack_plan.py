from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class LexPackPlan(Document):
	def validate(self):
		self.plan_code = (self.plan_code or "").strip().upper()
		self.plan_name = (self.plan_name or "").strip()
		self.currency = (self.currency or "USD").strip().upper()
		if not self.plan_code or not self.plan_name:
			frappe.throw(_("Plan Code and Plan Name are required."), frappe.MandatoryError)
		if not self.enterprise_custom:
			if flt(self.price) <= 0 or cint(self.lexpoints) <= 0:
				frappe.throw(_("A self-service LexPack needs a positive price and LexPoint value."), frappe.ValidationError)
			if flt(self.rolling_qualification_spend) <= 0:
				frappe.throw(_("Rolling qualification spend must be greater than zero."), frappe.ValidationError)
		if self.enterprise_custom:
			self.self_service = 0
		self.no_expiry = 1


def on_doctype_update():
	frappe.db.add_unique("LexPack Plan", ["plan_code"], constraint_name="lexpack_plan_code_unique")
	frappe.db.add_index("LexPack Plan", ["status", "display_order"], index_name="lexpack_plan_catalog")
