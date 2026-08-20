from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from lex.client_access import get_portal_user


MANAGEMENT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager", "Lexocrates Finance"}
BALANCE_FIELDS = {"current_balance", "reserved_balance", "total_purchased", "total_topped_up", "total_consumed", "last_transaction_on"}


class LexocratesClientWallet(Document):
	def validate(self):
		existing = frappe.db.get_value("Lexocrates Client Wallet", {"client": self.client}, "name")
		if existing and existing != self.name:
			frappe.throw(_("Each Client can have only one LexPack Wallet."), frappe.DuplicateEntryError)
		if not self.is_new() and not getattr(frappe.flags, "lexocrates_wallet_posting", False):
			previous = self.get_doc_before_save()
			changed = [fieldname for fieldname in BALANCE_FIELDS if previous and self.get(fieldname) != previous.get(fieldname)]
			if changed:
				frappe.throw(_("Wallet balances can only change through the transaction ledger."), frappe.PermissionError)

	def on_trash(self):
		frappe.throw(_("Client Wallets cannot be deleted."), frappe.PermissionError)


def _is_internal(user: str) -> bool:
	return user == "Administrator" or bool(set(frappe.get_roles(user)).intersection(MANAGEMENT_ROLES))


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if ptype == "delete":
		return False
	if _is_internal(user):
		return True
	actor = get_portal_user(user)
	return bool(ptype == "read" and actor and actor.client == doc.client and actor.lexpack_view_access)


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _is_internal(user):
		return ""
	actor = get_portal_user(user)
	if not actor or not actor.lexpack_view_access:
		return "1=0"
	return f"`tabLexocrates Client Wallet`.client = {frappe.db.escape(actor.client)}"


def on_doctype_update():
	frappe.db.add_unique("Lexocrates Client Wallet", ["client"], constraint_name="client_wallet_unique")
