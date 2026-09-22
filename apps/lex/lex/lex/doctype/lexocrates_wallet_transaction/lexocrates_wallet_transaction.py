from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

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
SUPPORTED_CAPACITY_CURRENCIES = {"CAD", "USD", "GBP"}
CAPACITY_QUANTUM = Decimal("0.01")


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
	legal_capacity_amount: float,
	currency: str | None = None,
	idempotency_key: str | None = None,
	matter: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	description: str | None = None,
):
	if not _is_internal(frappe.session.user):
		frappe.throw(_("Only authorized Lexocrates staff can post Legal Capacity transactions."), frappe.PermissionError)
	if transaction_type == "Reversal":
		frappe.throw(_("Use the reversal service to reverse a ledger entry."), frappe.ValidationError)
	return _post_transaction(
		client=client,
		transaction_type=transaction_type,
		legal_capacity_amount=legal_capacity_amount,
		currency=currency,
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
		frappe.throw(_("Only authorized Lexocrates staff can reverse Legal Capacity transactions."), frappe.PermissionError)
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
		legal_capacity_amount=original.legal_capacity_amount,
		currency=original.currency,
		idempotency_key=idempotency_key,
		matter=original.matter,
		reference_doctype=original.reference_doctype,
		reference_name=original.reference_name,
		description=(reason or "").strip(),
		reversal_of=original.name,
	).as_dict()


def _post_transaction(**values):
	transaction_type = values["transaction_type"]
	legal_capacity_amount = _capacity_decimal(values.get("legal_capacity_amount"))
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
		frappe.throw(_("Unsupported Legal Capacity transaction type."), frappe.ValidationError)
	if legal_capacity_amount <= 0:
		frappe.throw(_("Legal Capacity must be greater than zero."), frappe.ValidationError)

	wallet_name = frappe.db.get_value("Lexocrates Client Wallet", {"client": client}, "name")
	if not wallet_name:
		wallet = frappe.get_doc({"doctype": "Lexocrates Client Wallet", "client": client, "status": "Active"})
		wallet.insert(ignore_permissions=True)
		wallet_name = wallet.name
	frappe.db.sql("select name from `tabLexocrates Client Wallet` where name=%s for update", wallet_name)
	wallet = frappe.get_doc("Lexocrates Client Wallet", wallet_name)
	if wallet.status != "Active":
		frappe.throw(_("The Client Wallet is frozen."), frappe.ValidationError)
	currency = _capacity_currency(values.get("currency") or wallet.get("capacity_currency") or "CAD")
	wallet_currency = (wallet.get("capacity_currency") or "").strip().upper()
	if wallet_currency and wallet_currency != currency:
		frappe.throw(
			_("Legal Capacity currency must match the Client Wallet currency ({0}).").format(wallet_currency),
			frappe.ValidationError,
		)
	if not wallet_currency:
		# A first credit establishes the wallet currency.  It must match the
		# client's country policy; Desk/API callers cannot seed an arbitrary one.
		from lex.lexpack import _country_currency_for_client

		if currency != _country_currency_for_client(client):
			frappe.throw(
				_("Legal Capacity currency must match the client's country currency."),
				frappe.ValidationError,
			)
		wallet.capacity_currency = currency

	available = _capacity_decimal(wallet.current_balance)
	reserved = _capacity_decimal(wallet.reserved_balance)
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
		available += legal_capacity_amount
	elif transaction_type == "Reservation":
		_require_balance(available, legal_capacity_amount)
		available -= legal_capacity_amount
		reserved += legal_capacity_amount
	elif transaction_type == "Release":
		_require_reserved(reserved, legal_capacity_amount)
		reserved -= legal_capacity_amount
		available += legal_capacity_amount
	elif transaction_type == "Reserved Consumption":
		_require_reserved(reserved, legal_capacity_amount)
		reserved -= legal_capacity_amount
		wallet.total_consumed = _capacity_decimal(wallet.total_consumed) + legal_capacity_amount
	elif transaction_type in {"Direct Consumption", "Adjustment Debit"}:
		_require_balance(available, legal_capacity_amount)
		available -= legal_capacity_amount
		if transaction_type == "Direct Consumption":
			wallet.total_consumed = _capacity_decimal(wallet.total_consumed) + legal_capacity_amount
	elif transaction_type == "Reversal":
		available, reserved = _apply_reversal(wallet, original, available, reserved, legal_capacity_amount)

	if transaction_type == "Purchase":
		wallet.total_purchased = _capacity_decimal(wallet.total_purchased) + legal_capacity_amount
	elif transaction_type == "Top-Up":
		wallet.total_topped_up = _capacity_decimal(wallet.total_topped_up) + legal_capacity_amount

	available = _capacity_decimal(available)
	reserved = _capacity_decimal(reserved)
	wallet.current_balance = flt(available, 2)
	wallet.reserved_balance = flt(reserved, 2)
	wallet.total_purchased = flt(_capacity_decimal(wallet.total_purchased), 2)
	wallet.total_topped_up = flt(_capacity_decimal(wallet.total_topped_up), 2)
	wallet.total_consumed = flt(_capacity_decimal(wallet.total_consumed), 2)
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
				"currency": currency,
				"transaction_type": transaction_type,
				"legal_capacity_amount": flt(legal_capacity_amount, 2),
				"posted_on": wallet.last_transaction_on,
				"posted_by": frappe.session.user,
				"available_balance_after": flt(available, 2),
				"reserved_balance_after": flt(reserved, 2),
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
		action=f"Legal Capacity {transaction_type}",
		object_type="Lexocrates Wallet Transaction",
		object_id=transaction.name,
		new_value={
			"legal_capacity_amount": flt(legal_capacity_amount, 2),
			"currency": currency,
			"available": flt(available, 2),
			"reserved": flt(reserved, 2),
			"reversal_of": values.get("reversal_of"),
		},
	)
	return transaction


def _require_balance(balance, legal_capacity_amount):
	if legal_capacity_amount > balance:
		frappe.throw(_("Insufficient available Legal Capacity."), frappe.ValidationError)


def _require_reserved(balance, legal_capacity_amount):
	if legal_capacity_amount > balance:
		frappe.throw(_("Insufficient reserved Legal Capacity."), frappe.ValidationError)


def _apply_reversal(wallet, original, available, reserved, legal_capacity_amount):
	"""Undo the accounting effect of exactly one immutable original entry."""
	type_ = original.transaction_type
	if type_ == "Purchase":
		_require_balance(available, legal_capacity_amount)
		available -= legal_capacity_amount
		wallet.total_purchased = max(Decimal("0"), _capacity_decimal(wallet.total_purchased) - legal_capacity_amount)
	elif type_ == "Top-Up":
		_require_balance(available, legal_capacity_amount)
		available -= legal_capacity_amount
		wallet.total_topped_up = max(Decimal("0"), _capacity_decimal(wallet.total_topped_up) - legal_capacity_amount)
	elif type_ == "Reservation":
		_require_reserved(reserved, legal_capacity_amount)
		reserved -= legal_capacity_amount
		available += legal_capacity_amount
	elif type_ == "Release":
		_require_balance(available, legal_capacity_amount)
		available -= legal_capacity_amount
		reserved += legal_capacity_amount
	elif type_ == "Reserved Consumption":
		reserved += legal_capacity_amount
		wallet.total_consumed = max(Decimal("0"), _capacity_decimal(wallet.total_consumed) - legal_capacity_amount)
	elif type_ == "Direct Consumption":
		available += legal_capacity_amount
		wallet.total_consumed = max(Decimal("0"), _capacity_decimal(wallet.total_consumed) - legal_capacity_amount)
	elif type_ == "Adjustment Credit":
		_require_balance(available, legal_capacity_amount)
		available -= legal_capacity_amount
	elif type_ == "Adjustment Debit":
		available += legal_capacity_amount
	else:
		frappe.throw(_("Unsupported original transaction type for reversal."), frappe.ValidationError)
	return available, reserved


def _capacity_decimal(value) -> Decimal:
	"""Normalize money-like Legal Capacity values before a ledger calculation."""
	try:
		amount = Decimal(str(value if value not in (None, "") else 0))
	except (InvalidOperation, ValueError, TypeError):
		frappe.throw(_("Legal Capacity must be a valid currency amount."), frappe.ValidationError)
	if not amount.is_finite():
		frappe.throw(_("Legal Capacity must be a valid currency amount."), frappe.ValidationError)
	return amount.quantize(CAPACITY_QUANTUM, rounding=ROUND_HALF_UP)


def _capacity_currency(value) -> str:
	currency = str(value or "").strip().upper()
	if currency not in SUPPORTED_CAPACITY_CURRENCIES:
		frappe.throw(
			_("Legal Capacity is currently available only in CAD, USD, or GBP."),
			frappe.ValidationError,
		)
	return currency


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
