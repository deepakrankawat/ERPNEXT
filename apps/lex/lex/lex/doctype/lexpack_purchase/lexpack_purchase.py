from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from lex.client_access import get_portal_user


MANAGEMENT_ROLES = {"System Manager", "Accounts Manager", "Accounts User", "Lexocrates Finance", "LPO_Admin"}


class LexPackPurchase(Document):
	def before_insert(self):
		if not getattr(frappe.flags, "lexpack_purchase_service", False):
			frappe.throw(_("LexPack purchases must be created through the payment service."), frappe.PermissionError)

	def before_save(self):
		if self.is_new() or getattr(frappe.flags, "lexpack_purchase_service", False):
			return
		if self.has_value_changed("status") or any(
			self.has_value_changed(fieldname)
			for fieldname in (
				"amount", "currency", "base_lexpoints", "bonus_lexpoints", "total_lexpoints",
				"razorpay_order_id", "razorpay_payment_id", "sales_invoice", "payment_entry",
				"wallet_transaction", "bonus_wallet_transactions", "work_intake",
			)
		):
			frappe.throw(_("Commercial and payment fields are maintained by the LexPack payment service."), frappe.PermissionError)

	def on_trash(self):
		if self.status in {"Paid", "Refund Pending", "Refunded"}:
			frappe.throw(_("Paid LexPack purchases cannot be deleted."), frappe.PermissionError)


def _is_internal(user: str) -> bool:
	return user == "Administrator" or bool(set(frappe.get_roles(user)).intersection(MANAGEMENT_ROLES))


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if _is_internal(user):
		return True
	if ptype != "read":
		return False
	actor = get_portal_user(user)
	return bool(actor and actor.client == doc.client and actor.lexpack_view_access)


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _is_internal(user):
		return ""
	actor = get_portal_user(user)
	if not actor or not actor.lexpack_view_access:
		return "1=0"
	return f"`tabLexPack Purchase`.client = {frappe.db.escape(actor.client)}"


def on_doctype_update():
	frappe.db.add_unique("LexPack Purchase", ["razorpay_order_id"], constraint_name="lexpack_razorpay_order_unique")
	frappe.db.add_unique("LexPack Purchase", ["razorpay_payment_id"], constraint_name="lexpack_razorpay_payment_unique")
	frappe.db.add_index("LexPack Purchase", ["client", "paid_on"], index_name="lexpack_purchase_client_paid")
	frappe.db.add_index("LexPack Purchase", ["status", "modified"], index_name="lexpack_purchase_status")
