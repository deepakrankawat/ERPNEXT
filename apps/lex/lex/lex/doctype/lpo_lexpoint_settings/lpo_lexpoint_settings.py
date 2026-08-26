from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class LPOLexPointSettings(Document):
	def validate(self):
		for fieldname, label in (
			("minimum_charge", _("Minimum Charge")),
			("rounding_increment", _("Rounding Increment")),
			("contingency_buffer", _("Contingency Buffer")),
			("words_per_page", _("Fallback Words per Page")),
		):
			if flt(self.get(fieldname)) <= 0:
				frappe.throw(_("{0} must be greater than zero.").format(label), frappe.ValidationError)
		self.require_human_approval = 1
