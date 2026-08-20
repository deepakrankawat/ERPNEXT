from __future__ import annotations

import csv
import hashlib
import hmac
import io
import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime
from lex.client_access import get_portal_user
from lex.portal_audit import create_portal_audit_event


@frappe.whitelist()
def generate_wallet_statement_data(client_id: str | None = None, from_date: str | None = None, to_date: str | None = None):
	"""Generate reconciled ledger statement for Client Portal (WAL-007)."""
	portal_user = get_portal_user()
	if portal_user:
		client_id = portal_user.client
		if not portal_user.get("lexpack_view_access"):
			frappe.throw(_("Access denied to wallet statements."), frappe.PermissionError)
	elif not client_id:
		frappe.throw(_("Client ID is required."), frappe.MandatoryError)

	wallet = frappe.db.get_value(
		"Lexocrates Client Wallet",
		{"client": client_id},
		[
			"name", "current_balance", "reserved_balance", "total_purchased", "total_consumed",
			"current_pricing_tier", "rolling_12_month_spend", "bonus_points_earned",
		],
		as_dict=True,
	)
	if not wallet:
		frappe.throw(_("Wallet not found for this Client."), frappe.DoesNotExistError)

	filters = [["wallet", "=", wallet.name]]
	if from_date:
		filters.append(["posted_on", ">=", from_date])
	if to_date:
		filters.append(["posted_on", "<=", to_date])

	transactions = frappe.get_all(
		"Lexocrates Wallet Transaction",
		filters=filters,
		fields=[
			"name",
			"transaction_type",
			"points",
			"posted_on",
			"matter",
			"reference_doctype",
			"reference_name",
			"idempotency_key",
			"reversal_of",
			"available_balance_after",
			"posted_by",
		],
		order_by="posted_on asc",
		limit_page_length=5000,
	)
	for transaction in transactions:
		transaction["job"] = (
			transaction.reference_name
			if transaction.reference_doctype == "LPO Job"
			else None
		)

	return {
		"client": client_id,
		"wallet": wallet.name,
		# The current balance is the total unconsumed balance.  Reservations move
		# points between the available and reserved buckets; they do not consume
		# them.
		"current_balance": flt(wallet.current_balance) + flt(wallet.reserved_balance),
		"reserved_balance": flt(wallet.reserved_balance),
		"available_balance": flt(wallet.current_balance),
		"total_purchased": flt(wallet.total_purchased),
		"total_consumed": flt(wallet.total_consumed),
		"current_pricing_tier": wallet.current_pricing_tier,
		"rolling_12_month_spend": flt(wallet.rolling_12_month_spend),
		"bonus_points_earned": flt(wallet.bonus_points_earned),
		"transactions": transactions,
	}


@frappe.whitelist()
def download_wallet_statement_csv(client_id: str | None = None, from_date: str | None = None, to_date: str | None = None):
	"""Export downloadable CSV statement (WAL-007)."""
	data = generate_wallet_statement_data(client_id, from_date, to_date)
	output = io.StringIO()
	writer = csv.writer(output)

	writer.writerow(["Statement Date", str(now_datetime())])
	writer.writerow(["Client", data["client"]])
	writer.writerow(["Current LexPoint Balance", data["current_balance"]])
	writer.writerow(["Reserved LexPoints", data["reserved_balance"]])
	writer.writerow(["Available Balance", data["available_balance"]])
	writer.writerow([])
	writer.writerow(["Transaction ID", "Posted On", "Type", "Points", "Matter", "Job", "Balance After"])

	for txn in data["transactions"]:
		writer.writerow([
			txn.name,
			str(txn.posted_on),
			txn.transaction_type,
			txn.points,
			txn.matter or "",
			txn.job or "",
			txn.available_balance_after,
		])

	frappe.response["filename"] = f"LexPoint_Statement_{data['client']}.csv"
	frappe.response["filecontent"] = output.getvalue().encode("utf-8")
	frappe.response["type"] = "binary"


@frappe.whitelist(allow_guest=True)
def handle_payment_topup_webhook():
	"""Signed, replay-bounded, idempotent payment webhook receiver (WAL-008)."""
	secret = (frappe.conf.get("lexocrates_wallet_webhook_secret") or "").strip()
	if not secret:
		frappe.throw(_("Payment webhook is disabled until a signing secret is configured."), frappe.PermissionError)
	raw_body = frappe.request.get_data(cache=True) or b""
	provided = (frappe.get_request_header("X-Lexocrates-Signature") or "").strip()
	expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
	provided_digest = provided.removeprefix("sha256=")
	if not provided_digest or not hmac.compare_digest(provided_digest, expected):
		frappe.throw(_("Invalid payment webhook signature."), frappe.PermissionError)
	data = frappe.request.get_json() or {}
	idempotency_key = data.get("idempotency_key") or data.get("payment_id")
	client_id = data.get("client_id")
	lexpoints = flt(data.get("points") or 0)
	event_timestamp = data.get("timestamp")

	if not idempotency_key or not client_id or lexpoints <= 0 or not event_timestamp:
		frappe.throw(_("Invalid webhook payload."), frappe.ValidationError)
	try:
		age_seconds = abs((now_datetime() - get_datetime(event_timestamp)).total_seconds())
	except (TypeError, ValueError):
		frappe.throw(_("Invalid webhook timestamp."), frappe.ValidationError)
	if age_seconds > 300:
		frappe.throw(_("Payment webhook timestamp is outside the five-minute replay window."), frappe.PermissionError)

	# Check for idempotency
	existing = frappe.db.exists("Lexocrates Wallet Transaction", {"idempotency_key": idempotency_key})
	if existing:
		return {"status": "success", "duplicate": True, "transaction": existing}

	from lex.lex.doctype.lexocrates_wallet_transaction.lexocrates_wallet_transaction import _post_transaction

	txn = _post_transaction(
		client=client_id,
		transaction_type="Purchase",
		points=lexpoints,
		idempotency_key=idempotency_key,
	)

	create_portal_audit_event(
		client=client_id,
		action="LexPack Webhook Top-Up Posted",
		object_type="Lexocrates Wallet Transaction",
		object_id=txn.name,
		new_value={"points": lexpoints, "idempotency_key": idempotency_key},
	)

	return {"status": "success", "transaction": txn.name, "points": lexpoints}
