from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class LexocratesPaymentAdjustment(Document):
	def before_insert(self):
		if not getattr(frappe.flags, "lexocrates_payment_adjustment_service", False):
			frappe.throw(_("Payment adjustments must be created by the payment service."), frappe.PermissionError)

	def before_save(self):
		if self.is_new() or getattr(frappe.flags, "lexocrates_payment_adjustment_service", False):
			return
		frappe.throw(_("Payment adjustments are maintained by the payment service."), frappe.PermissionError)

	def on_trash(self):
		frappe.throw(_("Payment adjustment records cannot be deleted."), frappe.PermissionError)


def on_doctype_update():
	frappe.db.add_unique(
		"Lexocrates Payment Adjustment",
		["gateway_key"],
		constraint_name="lexocrates_payment_adjustment_gateway_key_unique",
	)
	frappe.db.add_index(
		"Lexocrates Payment Adjustment",
		["payment_id", "event_type"],
		index_name="lexocrates_payment_adjustment_payment_event",
	)
