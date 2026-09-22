from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


SUPPORTED_LEXPACK_CURRENCIES = {"CAD", "USD", "GBP"}


class LexPackPlan(Document):
	def validate(self):
		self.plan_code = (self.plan_code or "").strip().upper()
		self.plan_name = (self.plan_name or "").strip()
		self.currency = (self.currency or "USD").strip().upper()
		if not self.plan_code or not self.plan_name:
			frappe.throw(_("Plan Code and Plan Name are required."), frappe.MandatoryError)
		if self.currency not in SUPPORTED_LEXPACK_CURRENCIES:
			frappe.throw(
				_("LexPack Legal Capacity is currently available only in CAD, USD, or GBP."),
				frappe.ValidationError,
			)
		if not self.enterprise_custom:
			if flt(self.price) <= 0:
				frappe.throw(_("A self-service LexPack needs a positive price."), frappe.ValidationError)
			if not 0 < flt(self.discount_percent) < 100:
				frappe.throw(_("A self-service LexPack needs a Legal Capacity discount between 0% and 100%."), frappe.ValidationError)
			if flt(self.rolling_qualification_spend) <= 0:
				frappe.throw(_("Rolling qualification spend must be greater than zero."), frappe.ValidationError)
			self.value_advantage = _("{0}% savings").format(_display_percent(self.discount_percent))
		if self.enterprise_custom:
			self.self_service = 0
			self.discount_percent = 0
			self.value_advantage = _("Custom commercial terms")
		self.no_expiry = 1


def _display_percent(value) -> str:
	return ("{0:.2f}".format(flt(value))).rstrip("0").rstrip(".")


def on_doctype_update():
	frappe.db.add_unique("LexPack Plan", ["plan_code"], constraint_name="lexpack_plan_code_unique")
	frappe.db.add_index("LexPack Plan", ["status", "display_order"], index_name="lexpack_plan_catalog")
