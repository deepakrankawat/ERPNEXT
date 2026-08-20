from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from lex.client_access import get_portal_user
from lex.portal_audit import create_portal_audit_event


MANAGEMENT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager", "Lexocrates Finance"}
TRANSACTION_TYPES = {
	"Purchase", "Top-Up", "Reservation", "Release", "Reserved Consumption",
	"Direct Consumption", "Adjustment Credit", "Adjustment Debit", "Reversal",
}


class LexocratesWalletTransaction(Document):
	def before_insert(self):
		if not getattr(frappe.flags, "lexocrates_wallet_posting", False):
			frappe.throw(_("Wallet transactions can only be created by the ledger service."), frappe.PermissionError)

	def before_save(self):
		if not self.is_new():
			frappe.throw(_("Wallet transactions are immutable."), frappe.PermissionError)

	def on_trash(self):
		frappe.throw(_("Wallet transactions cannot be deleted."), frappe.PermissionError)


def _is_internal(user: str) -> bool:
	return user == "Administrator" or bool(set(frappe.get_roles(user)).intersection(MANAGEMENT_ROLES))


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if ptype != "read":
		return False
	if _is_internal(user):
		return True
	actor = get_portal_user(user)
	return bool(actor and actor.client == doc.client and actor.lexpack_view_access)


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _is_internal(user):
		return ""
	actor = get_portal_user(user)
	if not actor or not actor.lexpack_view_access:
		return "1=0"
	return f"`tabLexocrates Wallet Transaction`.client = {frappe.db.escape(actor.client)}"


@frappe.whitelist()
def post_transaction(
	client: str,
	transaction_type: str,
	points: float,
	idempotency_key: str | None = None,
	matter: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	description: str | None = None,
):
	if not _is_internal(frappe.session.user):
		frappe.throw(_("Only authorized Lexocrates staff can post LexPoint transactions."), frappe.PermissionError)
	if transaction_type == "Reversal":
		frappe.throw(_("Use the reversal service to reverse a ledger entry."), frappe.ValidationError)
	return _post_transaction(
		client=client,
		transaction_type=transaction_type,
		points=points,
		idempotency_key=idempotency_key,
		matter=matter,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		description=description,
	).as_dict()


@frappe.whitelist()
def reverse_transaction(transaction: str, reason: str, idempotency_key: str):
	"""Post a one-time compensating entry while preserving the original transaction."""
	if not _is_internal(frappe.session.user):
		frappe.throw(_("Only authorized Lexocrates staff can reverse LexPoint transactions."), frappe.PermissionError)
	if not (reason or "").strip():
		frappe.throw(_("A reversal reason is required."), frappe.MandatoryError)
	if not (idempotency_key or "").strip():
		frappe.throw(_("An idempotency key is required for a reversal."), frappe.MandatoryError)
	original = frappe.get_doc("Lexocrates Wallet Transaction", transaction)
	if original.transaction_type == "Reversal":
		frappe.throw(_("A reversal entry cannot itself be reversed."), frappe.ValidationError)
	return _post_transaction(
		client=original.client,
		transaction_type="Reversal",
		points=original.points,
		idempotency_key=idempotency_key,
		matter=original.matter,
		reference_doctype=original.reference_doctype,
		reference_name=original.reference_name,
		description=(reason or "").strip(),
		reversal_of=original.name,
	).as_dict()


def _post_transaction(**values):
	transaction_type = values["transaction_type"]
	points = flt(values["points"])
	client = values["client"]
	idempotency_key = (values.get("idempotency_key") or "").strip() or None
	if idempotency_key:
		existing = frappe.db.get_value(
			"Lexocrates Wallet Transaction",
			{"idempotency_key": idempotency_key},
			"name",
		)
		if existing:
			return frappe.get_doc("Lexocrates Wallet Transaction", existing)
	if transaction_type not in TRANSACTION_TYPES:
		frappe.throw(_("Unsupported LexPoint transaction type."), frappe.ValidationError)
	if points <= 0:
		frappe.throw(_("LexPoints must be greater than zero."), frappe.ValidationError)

	wallet_name = frappe.db.get_value("Lexocrates Client Wallet", {"client": client}, "name")
	if not wallet_name:
		wallet = frappe.get_doc({"doctype": "Lexocrates Client Wallet", "client": client, "status": "Active"})
		wallet.insert(ignore_permissions=True)
		wallet_name = wallet.name
	frappe.db.sql("select name from `tabLexocrates Client Wallet` where name=%s for update", wallet_name)
	wallet = frappe.get_doc("Lexocrates Client Wallet", wallet_name)
	if wallet.status != "Active":
		frappe.throw(_("The Client Wallet is frozen."), frappe.ValidationError)

	available = flt(wallet.current_balance)
	reserved = flt(wallet.reserved_balance)
	original = None
	if transaction_type == "Reversal":
		reversal_of = values.get("reversal_of")
		if not reversal_of:
			frappe.throw(_("Reversal Of is required."), frappe.MandatoryError)
		frappe.db.sql(
			"select name from `tabLexocrates Wallet Transaction` where name=%s for update",
			reversal_of,
		)
		original = frappe.get_doc("Lexocrates Wallet Transaction", reversal_of)
		if original.client != client or original.wallet != wallet.name:
			frappe.throw(_("The reversed entry must belong to the same Client Wallet."), frappe.ValidationError)
		if original.transaction_type == "Reversal":
			frappe.throw(_("A reversal entry cannot itself be reversed."), frappe.ValidationError)
		existing_reversal = frappe.db.get_value(
			"Lexocrates Wallet Transaction", {"reversal_of": original.name}, "name"
		)
		if existing_reversal:
			frappe.throw(
				_("Transaction {0} was already reversed by {1}.").format(original.name, existing_reversal),
				frappe.ValidationError,
			)
	if transaction_type in {"Purchase", "Top-Up", "Adjustment Credit"}:
		available += points
	elif transaction_type == "Reservation":
		_require_balance(available, points)
		available -= points
		reserved += points
	elif transaction_type == "Release":
		_require_reserved(reserved, points)
		reserved -= points
		available += points
	elif transaction_type == "Reserved Consumption":
		_require_reserved(reserved, points)
		reserved -= points
		wallet.total_consumed = flt(wallet.total_consumed) + points
	elif transaction_type in {"Direct Consumption", "Adjustment Debit"}:
		_require_balance(available, points)
		available -= points
		if transaction_type == "Direct Consumption":
			wallet.total_consumed = flt(wallet.total_consumed) + points
	elif transaction_type == "Reversal":
		available, reserved = _apply_reversal(wallet, original, available, reserved, points)

	if transaction_type == "Purchase":
		wallet.total_purchased = flt(wallet.total_purchased) + points
	elif transaction_type == "Top-Up":
		wallet.total_topped_up = flt(wallet.total_topped_up) + points

	wallet.current_balance = available
	wallet.reserved_balance = reserved
	wallet.last_transaction_on = now_datetime()
	previous_flag = getattr(frappe.flags, "lexocrates_wallet_posting", False)
	frappe.flags.lexocrates_wallet_posting = True
	try:
		wallet.save(ignore_permissions=True)
		transaction = frappe.get_doc(
			{
				"doctype": "Lexocrates Wallet Transaction",
				"wallet": wallet.name,
				"client": client,
				"transaction_type": transaction_type,
				"points": points,
				"posted_on": wallet.last_transaction_on,
				"posted_by": frappe.session.user,
				"available_balance_after": available,
				"reserved_balance_after": reserved,
				"idempotency_key": idempotency_key,
				"matter": values.get("matter"),
				"reference_doctype": values.get("reference_doctype"),
				"reference_name": values.get("reference_name"),
				"reversal_of": values.get("reversal_of"),
				"description": values.get("description"),
			}
		).insert(ignore_permissions=True)
	finally:
		frappe.flags.lexocrates_wallet_posting = previous_flag
	create_portal_audit_event(
		client=client,
		matter=values.get("matter"),
		action=f"LexPoint {transaction_type}",
		object_type="Lexocrates Wallet Transaction",
		object_id=transaction.name,
		new_value={
			"points": points,
			"available": available,
			"reserved": reserved,
			"reversal_of": values.get("reversal_of"),
		},
	)
	return transaction


def _require_balance(balance, points):
	if points > balance:
		frappe.throw(_("Insufficient available LexPoints."), frappe.ValidationError)


def _require_reserved(balance, points):
	if points > balance:
		frappe.throw(_("Insufficient reserved LexPoints."), frappe.ValidationError)


def _apply_reversal(wallet, original, available, reserved, points):
	"""Undo the accounting effect of exactly one immutable original entry."""
	type_ = original.transaction_type
	if type_ == "Purchase":
		_require_balance(available, points)
		available -= points
		wallet.total_purchased = max(0, flt(wallet.total_purchased) - points)
	elif type_ == "Top-Up":
		_require_balance(available, points)
		available -= points
		wallet.total_topped_up = max(0, flt(wallet.total_topped_up) - points)
	elif type_ == "Reservation":
		_require_reserved(reserved, points)
		reserved -= points
		available += points
	elif type_ == "Release":
		_require_balance(available, points)
		available -= points
		reserved += points
	elif type_ == "Reserved Consumption":
		reserved += points
		wallet.total_consumed = max(0, flt(wallet.total_consumed) - points)
	elif type_ == "Direct Consumption":
		available += points
		wallet.total_consumed = max(0, flt(wallet.total_consumed) - points)
	elif type_ == "Adjustment Credit":
		_require_balance(available, points)
		available -= points
	elif type_ == "Adjustment Debit":
		available += points
	else:
		frappe.throw(_("Unsupported original transaction type for reversal."), frappe.ValidationError)
	return available, reserved


def on_doctype_update():
	frappe.db.add_unique(
		"Lexocrates Wallet Transaction",
		["idempotency_key"],
		constraint_name="wallet_transaction_idempotency_unique",
	)
	frappe.db.add_unique(
		"Lexocrates Wallet Transaction",
		["reversal_of"],
		constraint_name="wallet_transaction_reversal_unique",
	)
	frappe.db.add_index(
		"Lexocrates Wallet Transaction", ["client", "posted_on"], index_name="wallet_transaction_client_posted"
	)
