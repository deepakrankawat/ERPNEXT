from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class LexPackSettings(Document):
	def validate(self):
		self.api_timeout_seconds = max(5, min(cint(self.api_timeout_seconds or 15), 60))
		if not self.enabled:
			return
		required = {
			"key_id": _("Razorpay Key ID"),
			"company": _("Company"),
			"selling_item": _("LexPack Selling Item"),
			"razorpay_clearing_account": _("Razorpay Clearing Account"),
			"mode_of_payment": _("Mode of Payment"),
		}
		missing = [label for fieldname, label in required.items() if not self.get(fieldname)]
		for fieldname, label in (("key_secret", _("Razorpay Key Secret")), ("webhook_secret", _("Razorpay Webhook Secret"))):
			if not self.get(fieldname) and not self.get_password(fieldname, raise_exception=False):
				missing.append(label)
		if missing:
			frappe.throw(_("Configure these fields before enabling LexPack payments: {0}").format(", ".join(missing)), frappe.MandatoryError)
		account_company, is_group, account_type = frappe.db.get_value(
			"Account", self.razorpay_clearing_account, ["company", "is_group", "account_type"]
		) or (None, None, None)
		if account_company != self.company or is_group or account_type not in {"Bank", "Cash"}:
			frappe.throw(_("Razorpay Clearing Account must be a leaf Bank or Cash account for the selected Company."), frappe.ValidationError)
