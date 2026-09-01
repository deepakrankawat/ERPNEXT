from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime


class LPOStandaloneEstimate(Document):
	"""Immutable audit record for the internal, non-client estimation sandbox."""

	def before_insert(self):
		if not getattr(frappe.flags, "lexocrates_standalone_estimate_service", False):
			frappe.throw(
				_("Standalone estimates must be created from the controlled LexPoint Estimator."),
				frappe.PermissionError,
			)
		self.requested_by = self.requested_by or frappe.session.user
		self.requested_on = self.requested_on or now_datetime()

	def validate(self):
		if self.status == "Complete":
			if cint(self.estimated_lexpoints) <= 0:
				frappe.throw(_("Estimated LexPoints must be greater than zero."), frappe.ValidationError)
			if flt(self.estimated_price) <= 0:
				frappe.throw(_("Estimated price must be greater than zero."), frappe.ValidationError)
			if cint(self.delivery_hours) <= 0:
				frappe.throw(_("Estimated delivery hours must be greater than zero."), frappe.ValidationError)

		if self.is_new() or getattr(frappe.flags, "lexocrates_standalone_estimate_service", False):
			return
		frappe.throw(
			_("Standalone estimate evidence is immutable. Run a new estimate instead."),
			frappe.PermissionError,
		)

	def on_trash(self):
		frappe.throw(_("Standalone estimate history cannot be deleted."), frappe.PermissionError)


def on_doctype_update():
	frappe.db.add_index(
		"LPO Standalone Estimate",
		["requested_by", "requested_on"],
		index_name="standalone_estimate_user_created",
	)
	frappe.db.add_index(
		"LPO Standalone Estimate", ["status", "modified"], index_name="standalone_estimate_status_modified"
	)
