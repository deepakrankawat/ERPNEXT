from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal, ROUND_HALF_UP

import frappe
import requests
from frappe import _
from frappe.utils import add_months, cint, flt, get_datetime, now_datetime, nowdate

from lex.client_access import get_portal_user
from lex.portal_audit import create_portal_audit_event


RAZORPAY_API_ROOT = "https://api.razorpay.com/v1"
PURCHASE_ROLES = {"System Manager", "Accounts Manager", "Accounts User", "Lexocrates Finance", "LPO_Admin"}
RAZORPAY_SETUP_ROLES = {"System Manager", "Accounts Manager"}
PAID_STATES = {"Paid", "Refund Pending", "Refunded"}


def get_lexpack_portal_data(portal_user=None):
	portal_user = portal_user or get_portal_user()
	if not portal_user or not portal_user.lexpack_view_access:
		return {"plans": [], "purchases": [], "payment_enabled": False}
	plans = frappe.get_all(
		"LexPack Plan",
		filters={"status": "Active"},
		fields=[
			"name", "plan_code", "plan_name", "currency", "price", "lexpoints", "value_advantage",
			"display_order", "self_service", "enterprise_custom", "no_expiry",
			"rolling_qualification_spend", "qualification_bonus_points", "description", "commercial_note",
		],
		order_by="display_order asc",
		limit_page_length=50,
	)
	purchases = frappe.get_all(
		"LexPack Purchase",
		filters={"client": portal_user.client},
		fields=[
			"name", "plan", "plan_name_snapshot", "status", "currency", "amount", "base_lexpoints",
			"bonus_lexpoints", "total_lexpoints", "created_on", "paid_on", "tier_after", "sales_invoice",
		],
		order_by="created_on desc",
		limit_page_length=50,
	)
	settings = _load_settings()
	readiness = get_razorpay_readiness(settings)
	return {
		"plans": plans,
		"purchases": purchases,
		"payment_enabled": readiness["payment_enabled"],
		"purchase_access": bool(portal_user.lexpack_purchase_access),
		"fair_pricing_note": _("Rolling 12-month tier upgrades are automatic. LexPoints never expire."),
		"commercial_note": _("Bundle pricing is illustrative and remains subject to final commercial approval."),
	}


@frappe.whitelist()
def create_razorpay_order(plan: str, work_intake: str | None = None):
	client, portal_user = _require_purchase_authority()
	if not work_intake:
		frappe.throw(
			_("Start a Work Intake, accept the SLA, upload documents and receive a quote before buying a LexPack."),
			frappe.ValidationError,
		)
	from lex.work_intake import prepare_lexpack_purchase

	intake_doc, portal_user = prepare_lexpack_purchase(work_intake, plan, actor=portal_user)
	client = intake_doc.client
	plan_doc = frappe.get_doc("LexPack Plan", plan)
	if plan_doc.status != "Active" or not plan_doc.self_service or plan_doc.enterprise_custom:
		frappe.throw(_("This LexPack is not available for self-service purchase."), frappe.ValidationError)
	settings = _get_settings(require_enabled=True)
	company = _resolve_company(settings)
	exchange_rate = _resolve_exchange_rate(plan_doc.currency, company)
	purchase = _new_purchase(client, portal_user, plan_doc, exchange_rate, work_intake=intake_doc.name)
	from lex.work_intake import link_lexpack_purchase

	link_lexpack_purchase(intake_doc.name, purchase.name)
	payload = {
		"amount": _minor_units(plan_doc.price, plan_doc.currency),
		"currency": plan_doc.currency,
		"receipt": purchase.name,
		"notes": {
			"lexpack_purchase": purchase.name,
			"work_intake": intake_doc.name,
			"client": client,
			"plan": plan_doc.name,
		},
	}
	try:
		order = _razorpay_request("POST", "/orders", settings, payload)
		_validate_order_response(order, payload)
		_set_purchase_values(
			purchase,
			status="Payment Pending",
			razorpay_order_id=order["id"],
			failure_reason=None,
		)
	except Exception as exc:
		_set_purchase_values(purchase, status="Failed", failure_reason=_safe_gateway_error(exc))
		raise

	create_portal_audit_event(
		client=client,
		portal_user=portal_user.name if portal_user else None,
		action="LexPack Razorpay Order Created",
		object_type="LexPack Purchase",
		object_id=purchase.name,
		new_value={"plan": plan_doc.name, "amount": flt(plan_doc.price), "currency": plan_doc.currency},
	)
	return {
		"purchase": purchase.name,
		"work_intake": intake_doc.name,
		"key": settings.key_id,
		"order_id": purchase.razorpay_order_id,
		"amount": payload["amount"],
		"currency": plan_doc.currency,
		"name": settings.checkout_name or "Lexocrates Legal Services Pvt. Ltd.",
		"description": f"{plan_doc.plan_name} LexPack - {cint(plan_doc.lexpoints):,} LexPoints",
		"image": "/assets/lex/images/lexocrates-mark-dark.png",
		"prefill": _checkout_prefill(portal_user),
		"theme": {"color": settings.checkout_theme_color or "#1f2937"},
	}


@frappe.whitelist()
def verify_razorpay_payment(
	purchase: str,
	razorpay_payment_id: str,
	razorpay_order_id: str,
	razorpay_signature: str,
):
	purchase_doc = frappe.get_doc("LexPack Purchase", purchase)
	_assert_purchase_access(purchase_doc)
	settings = _get_settings(require_enabled=True)
	if not purchase_doc.razorpay_order_id or purchase_doc.razorpay_order_id != razorpay_order_id:
		frappe.throw(_("Razorpay order mismatch."), frappe.PermissionError)
	if not _checkout_signature_is_valid(
		purchase_doc.razorpay_order_id,
		razorpay_payment_id,
		razorpay_signature,
		settings.get_password("key_secret"),
	):
		create_portal_audit_event(
			client=purchase_doc.client,
			action="LexPack Payment Signature Rejected",
			object_type="LexPack Purchase",
			object_id=purchase_doc.name,
			result="Failure",
		)
		frappe.throw(_("Payment verification failed. No LexPoints were credited."), frappe.PermissionError)

	payment = _razorpay_request("GET", f"/payments/{razorpay_payment_id}", settings)
	_validate_payment_entity(purchase_doc, payment, require_captured=False)
	_set_purchase_values(
		purchase_doc,
		razorpay_payment_id=razorpay_payment_id,
		signature_verified=1,
		failure_reason=None,
	)
	if payment.get("status") != "captured":
		return {
			"purchase": purchase_doc.name,
			"status": "Payment Pending",
			"message": _("Payment is authorized and will be credited after Razorpay confirms capture."),
		}
	return _complete_purchase(purchase_doc, payment, source="checkout")


@frappe.whitelist(allow_guest=True)
def handle_razorpay_webhook():
	settings = _get_settings(require_enabled=True)
	webhook_secret = settings.get_password("webhook_secret")
	raw_body = frappe.request.get_data(cache=True) or b""
	provided = (frappe.get_request_header("X-Razorpay-Signature") or "").strip()
	if not _webhook_signature_is_valid(raw_body, provided, webhook_secret):
		frappe.throw(_("Invalid Razorpay webhook signature."), frappe.PermissionError)
	try:
		payload = json.loads(raw_body.decode("utf-8"))
	except (UnicodeDecodeError, json.JSONDecodeError):
		frappe.throw(_("Invalid Razorpay webhook payload."), frappe.ValidationError)
	if not isinstance(payload, dict):
		frappe.throw(_("Invalid Razorpay webhook payload."), frappe.ValidationError)
	event = payload.get("event")
	event_id = (frappe.get_request_header("X-Razorpay-Event-Id") or "").strip() or None
	if event_id and _event_already_processed(event_id):
		return {"status": "duplicate", "event_id": event_id}
	if event not in {"payment.captured", "payment.failed", "order.paid"}:
		return {"status": "ignored", "event": event}
	payment = ((payload.get("payload") or {}).get("payment") or {}).get("entity") or {}
	order = ((payload.get("payload") or {}).get("order") or {}).get("entity") or {}
	order_id = payment.get("order_id") or order.get("id")
	if not order_id:
		return {"status": "ignored", "reason": "No Razorpay order in event"}
	job_token = event_id or hashlib.sha256(raw_body).hexdigest()
	frappe.enqueue(
		"lex.lexpack.process_razorpay_webhook",
		queue="short",
		timeout=120,
		enqueue_after_commit=True,
		job_id=f"razorpay-webhook-{job_token[:48]}",
		deduplicate=True,
		payload=payload,
		event_id=event_id,
	)
	return {"status": "accepted", "event_id": event_id}


def process_razorpay_webhook(payload: dict, event_id: str | None = None):
	"""Process an authenticated webhook outside the request/response cycle."""
	settings = _get_settings(require_enabled=True)
	if event_id and _event_already_processed(event_id):
		return {"status": "duplicate", "event_id": event_id}
	event = payload.get("event")
	payment = ((payload.get("payload") or {}).get("payment") or {}).get("entity") or {}
	order = ((payload.get("payload") or {}).get("order") or {}).get("entity") or {}
	order_id = payment.get("order_id") or order.get("id")
	if not order_id:
		return {"status": "ignored", "reason": "No Razorpay order in event"}
	purchase_name = frappe.db.get_value("LexPack Purchase", {"razorpay_order_id": order_id}, "name")
	if not purchase_name:
		from lex.work_intake import handle_direct_webhook

		direct_result = handle_direct_webhook(event, event_id, payment, order_id)
		return direct_result or {"status": "ignored", "reason": "Order is not a Lexocrates checkout"}
	purchase_doc = frappe.get_doc("LexPack Purchase", purchase_name)
	if event in {"payment.captured", "order.paid"}:
		if not payment.get("id"):
			payments = _razorpay_request("GET", f"/orders/{order_id}/payments", settings)
			payment = next((row for row in payments.get("items", []) if row.get("status") == "captured"), {})
		_validate_payment_entity(purchase_doc, payment, require_captured=True)
		_set_purchase_values(
			purchase_doc,
			razorpay_payment_id=payment["id"],
			gateway_event_id=event_id,
			failure_reason=None,
		)
		return _complete_purchase(purchase_doc, payment, source="webhook")
	if event == "payment.failed" and purchase_doc.status not in PAID_STATES:
		failure = (payment.get("error_description") or payment.get("error_reason") or _("Razorpay reported a failed payment."))[:500]
		_set_purchase_values(purchase_doc, status="Failed", gateway_event_id=event_id, failure_reason=failure)
		return {"status": "failed", "purchase": purchase_doc.name}
	return {"status": "ignored", "event": event, "purchase": purchase_doc.name}


def _event_already_processed(event_id: str) -> bool:
	if not event_id:
		return False
	return bool(
		frappe.db.exists("LexPack Purchase", {"gateway_event_id": event_id})
		or frappe.db.exists("Lexocrates Work Intake", {"gateway_event_id": event_id})
	)


def _new_purchase(client, portal_user, plan_doc, exchange_rate, work_intake=None):
	previous_flag = getattr(frappe.flags, "lexpack_purchase_service", False)
	frappe.flags.lexpack_purchase_service = True
	try:
		return frappe.get_doc(
			{
				"doctype": "LexPack Purchase",
				"client": client,
				"purchaser": frappe.session.user,
				"plan": plan_doc.name,
				"work_intake": work_intake,
				"plan_name_snapshot": plan_doc.plan_name,
				"status": "Created",
				"gateway": "Razorpay",
				"created_on": now_datetime(),
				"currency": plan_doc.currency,
				"amount": flt(plan_doc.price),
				"exchange_rate": exchange_rate,
				"base_lexpoints": cint(plan_doc.lexpoints),
				"bonus_lexpoints": 0,
				"total_lexpoints": cint(plan_doc.lexpoints),
			}
		).insert(ignore_permissions=True)
	finally:
		frappe.flags.lexpack_purchase_service = previous_flag


def _complete_purchase(purchase_doc, payment, source: str):
	frappe.db.sql("select name from `tabLexPack Purchase` where name=%s for update", purchase_doc.name)
	purchase_doc.reload()
	if purchase_doc.status == "Paid" and purchase_doc.wallet_transaction:
		if purchase_doc.work_intake:
			from lex.work_intake import complete_lexpack_funding

			complete_lexpack_funding(purchase_doc)
		return _purchase_result(purchase_doc, duplicate=True)
	if purchase_doc.status in {"Refund Pending", "Refunded", "Cancelled"}:
		frappe.throw(_("This LexPack purchase cannot be fulfilled in its current state."), frappe.ValidationError)
	_validate_payment_entity(purchase_doc, payment, require_captured=True)
	settings = _get_settings(require_enabled=True)
	paid_on = get_datetime(payment.get("created_at")) if isinstance(payment.get("created_at"), str) else now_datetime()

	if not purchase_doc.sales_invoice:
		invoice = _create_sales_invoice(purchase_doc, settings)
		_set_purchase_values(purchase_doc, sales_invoice=invoice.name)
	if not purchase_doc.payment_entry:
		payment_entry = _create_payment_entry(purchase_doc, settings, payment)
		_set_purchase_values(purchase_doc, payment_entry=payment_entry.name)
	if not purchase_doc.wallet_transaction:
		from lex.lex.doctype.lexocrates_wallet_transaction.lexocrates_wallet_transaction import _post_transaction

		wallet_entry = _post_transaction(
			client=purchase_doc.client,
			transaction_type="Purchase",
			points=purchase_doc.base_lexpoints,
			idempotency_key=f"lexpack-purchase:{purchase_doc.name}",
			reference_doctype="LexPack Purchase",
			reference_name=purchase_doc.name,
			description=f"{purchase_doc.plan_name_snapshot} LexPack paid through Razorpay",
		)
		_set_purchase_values(purchase_doc, wallet_transaction=wallet_entry.name)

	pricing = recalculate_client_pricing(purchase_doc.client, purchase_doc.name)
	_set_purchase_values(
		purchase_doc,
		status="Paid",
		paid_on=paid_on,
		razorpay_payment_id=payment["id"],
		rolling_spend_before=pricing["rolling_spend_before"],
		rolling_spend_after=pricing["rolling_spend_after"],
		tier_before=pricing["tier_before"],
		tier_after=pricing["tier_after"],
		bonus_lexpoints=pricing["bonus_points"],
		total_lexpoints=cint(purchase_doc.base_lexpoints) + cint(pricing["bonus_points"]),
		bonus_wallet_transactions=json.dumps(pricing["bonus_transactions"]),
		failure_reason=None,
	)
	create_portal_audit_event(
		client=purchase_doc.client,
		action="LexPack Purchase Paid",
		object_type="LexPack Purchase",
		object_id=purchase_doc.name,
		new_value={
			"source": source,
			"plan": purchase_doc.plan,
			"amount": purchase_doc.amount,
			"currency": purchase_doc.currency,
			"base_lexpoints": purchase_doc.base_lexpoints,
			"bonus_lexpoints": pricing["bonus_points"],
		},
	)
	if purchase_doc.work_intake:
		from lex.work_intake import complete_lexpack_funding

		complete_lexpack_funding(purchase_doc)
	return _purchase_result(purchase_doc)


def recalculate_client_pricing(client: str, triggering_purchase: str | None = None):
	"""Update rolling spend/current tier and post each configured tier bonus once."""
	wallet_name = frappe.db.get_value("Lexocrates Client Wallet", {"client": client}, "name")
	if not wallet_name:
		frappe.get_doc({"doctype": "Lexocrates Client Wallet", "client": client, "status": "Active"}).insert(ignore_permissions=True)
		wallet_name = frappe.db.get_value("Lexocrates Client Wallet", {"client": client}, "name")
	frappe.db.sql("select name from `tabLexocrates Client Wallet` where name=%s for update", wallet_name)
	wallet = frappe.get_doc("Lexocrates Client Wallet", wallet_name)
	cutoff = add_months(nowdate(), -12)
	rolling_after = flt(
		frappe.db.sql(
			"""select coalesce(sum(amount), 0) from `tabLexPack Purchase`
			where client=%s and status='Paid' and date(paid_on) >= %s""",
			(client, cutoff),
		)[0][0]
	)
	if triggering_purchase:
		trigger = frappe.get_doc("LexPack Purchase", triggering_purchase)
		# The triggering row is marked Paid only after the atomic fulfilment succeeds.
		if trigger.status != "Paid":
			rolling_after += flt(trigger.amount)
	rolling_before = max(0, rolling_after - (flt(trigger.amount) if triggering_purchase else 0))
	plans = frappe.get_all(
		"LexPack Plan",
		filters={"status": "Active", "enterprise_custom": 0},
		fields=["name", "display_order", "rolling_qualification_spend", "qualification_bonus_points"],
		order_by="display_order asc",
		limit_page_length=50,
	)
	eligible = None
	for plan in plans:
		if flt(plan.rolling_qualification_spend) <= rolling_after:
			eligible = plan
	tier_before = wallet.get("current_pricing_tier") or None
	previous_order = next((cint(row.display_order) for row in plans if row.name == tier_before), 0)
	eligible_order = cint(eligible.display_order) if eligible else 0
	bonus_points = 0
	bonus_transactions = []
	if eligible_order > previous_order:
		from lex.lex.doctype.lexocrates_wallet_transaction.lexocrates_wallet_transaction import _post_transaction

		for plan in plans:
			if not (previous_order < cint(plan.display_order) <= eligible_order) or cint(plan.qualification_bonus_points) <= 0:
				continue
			idempotency_key = f"lexpack-fair-pricing:{client}:{plan.name}"
			already_posted = frappe.db.exists(
				"Lexocrates Wallet Transaction", {"idempotency_key": idempotency_key}
			)
			entry = _post_transaction(
				client=client,
				transaction_type="Adjustment Credit",
				points=cint(plan.qualification_bonus_points),
				idempotency_key=idempotency_key,
				reference_doctype="LexPack Purchase" if triggering_purchase else None,
				reference_name=triggering_purchase,
				description=f"LexPack Fair Pricing Promise qualification bonus: {plan.name}",
			)
			if not already_posted:
				bonus_points += cint(entry.points)
				bonus_transactions.append(entry.name)
	current_tier = eligible.name if eligible else None
	total_bonus = flt(
		frappe.db.sql(
			"""select coalesce(sum(points), 0) from `tabLexocrates Wallet Transaction`
			where client=%s and transaction_type='Adjustment Credit'
			and idempotency_key like 'lexpack-fair-pricing:%%'""",
			client,
		)[0][0]
	)
	frappe.db.set_value(
		"Lexocrates Client Wallet",
		wallet_name,
		{
			"rolling_12_month_spend": rolling_after,
			"current_pricing_tier": current_tier,
			"bonus_points_earned": total_bonus,
			"pricing_calculated_on": now_datetime(),
		},
		update_modified=False,
	)
	return {
		"rolling_spend_before": rolling_before,
		"rolling_spend_after": rolling_after,
		"tier_before": tier_before,
		"tier_after": current_tier,
		"bonus_points": bonus_points,
		"bonus_transactions": bonus_transactions,
	}


def recalculate_all_lexpack_tiers():
	for client in frappe.get_all("Lexocrates Client Wallet", filters={"status": "Active"}, pluck="client", limit_page_length=0):
		recalculate_client_pricing(client)


def _resolve_company(settings=None) -> str:
	if settings:
		company = getattr(settings, "company", None) or (settings.get("company") if isinstance(settings, dict) else None)
		if company:
			return company
	company = frappe.db.get_single_value("LexPack Settings", "company")
	if company:
		return company
	default_company = frappe.defaults.get_user_default("Company")
	if default_company:
		return default_company
	companies = frappe.get_all("Company", limit=1, pluck="name")
	if companies:
		return companies[0]
	frappe.throw(_("Please configure a Company in ERPNext or LexPack Settings."), frappe.ValidationError)


def _create_sales_invoice(purchase_doc, settings):
	company = _resolve_company(settings)
	company_currency = frappe.get_cached_value("Company", company, "default_currency") or "INR"

	from erpnext.accounts.party import get_party_account

	debit_to = get_party_account("Customer", purchase_doc.client, company)
	party_account_currency = (
		frappe.db.get_value("Account", debit_to, "account_currency") if debit_to else None
	) or company_currency

	doc_currency = purchase_doc.currency or "USD"
	exchange_rate = flt(purchase_doc.exchange_rate) or 1.0

	# If party receivable account (Debtors) currency is INR, convert foreign currency (USD/CAD) invoice to INR
	if party_account_currency == company_currency and doc_currency != company_currency:
		invoice_currency = company_currency
		conversion_rate = 1.0
		item_rate = flt(purchase_doc.amount * exchange_rate)
	else:
		invoice_currency = doc_currency
		conversion_rate = exchange_rate
		item_rate = flt(purchase_doc.amount)

	selling_item = (
		(settings.get("selling_item") if isinstance(settings, dict) else getattr(settings, "selling_item", None))
		or frappe.db.get_single_value("LexPack Settings", "selling_item")
		or frappe.db.get_value("Item", {"item_code": "LEXPACK-LEGAL-CAPACITY"}, "name")
		or frappe.db.get_value("Item", {"is_sales_item": 1}, "name")
	)
	if not selling_item:
		frappe.throw(_("No selling item configured for LexPack Sales Invoice."), frappe.ValidationError)

	invoice = frappe.new_doc("Sales Invoice")
	invoice.customer = purchase_doc.client
	invoice.company = company
	if debit_to:
		invoice.debit_to = debit_to
	invoice.posting_date = nowdate()
	invoice.due_date = nowdate()
	invoice.currency = invoice_currency
	invoice.conversion_rate = conversion_rate
	invoice.remarks = f"LexPack Purchase {purchase_doc.name}; Order {purchase_doc.get('razorpay_order_id') or ''}"
	item = {
		"item_code": selling_item,
		"qty": 1,
		"rate": item_rate,
		"description": f"{purchase_doc.plan_name_snapshot} LexPack - {cint(purchase_doc.base_lexpoints):,} non-expiring LexPoints ({doc_currency} {flt(purchase_doc.amount):,.2f})",
	}
	income_account = settings.get("income_account") if isinstance(settings, dict) else getattr(settings, "income_account", None)
	cost_center = settings.get("cost_center") if isinstance(settings, dict) else getattr(settings, "cost_center", None)
	if income_account:
		item["income_account"] = income_account
	if cost_center:
		item["cost_center"] = cost_center
	invoice.append("items", item)
	invoice.insert(ignore_permissions=True)
	invoice.flags.ignore_permissions = True
	invoice.submit()
	return invoice


def _format_payment_entry_currencies(entry, purchase_doc, company: str):
	"""Harmonize multi-currency payment entries (USD/CAD vs INR) so Party Account Debtors currency matches payment entry currency."""
	company_currency = frappe.get_cached_value("Company", company, "default_currency") or "INR"
	party_account = entry.paid_from
	party_account_currency = (
		frappe.db.get_value("Account", party_account, "account_currency") if party_account else None
	) or company_currency

	bank_account = entry.paid_to
	bank_account_currency = (
		(frappe.db.get_value("Account", bank_account, "account_currency") if bank_account else None)
		or company_currency
	)

	doc_currency = purchase_doc.currency or "USD"
	exchange_rate = flt(purchase_doc.exchange_rate) or 1.0

	# If party receivable account (Debtors) is in company currency (INR), convert foreign currency payment (USD/CAD) to base currency (INR)
	if party_account_currency == company_currency and doc_currency != company_currency:
		base_amount = flt(purchase_doc.amount * exchange_rate)
		entry.paid_from_account_currency = company_currency
		entry.paid_to_account_currency = bank_account_currency
		entry.paid_amount = base_amount
		entry.received_amount = base_amount
		entry.source_exchange_rate = 1.0
		entry.target_exchange_rate = 1.0
		for ref in entry.get("references", []):
			if ref.reference_doctype == "Sales Invoice" and ref.reference_name == purchase_doc.sales_invoice:
				ref.allocated_amount = flt(ref.outstanding_amount)
	elif party_account_currency == doc_currency:
		entry.paid_from_account_currency = doc_currency
		entry.paid_to_account_currency = bank_account_currency
		entry.paid_amount = flt(purchase_doc.amount)
		if bank_account_currency == company_currency:
			entry.received_amount = flt(purchase_doc.amount * exchange_rate)
			entry.target_exchange_rate = exchange_rate
			entry.source_exchange_rate = 1.0
		else:
			entry.received_amount = flt(purchase_doc.amount)
			entry.target_exchange_rate = 1.0
			entry.source_exchange_rate = 1.0


def _create_payment_entry(purchase_doc, settings, payment):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	company = _resolve_company(settings)
	clearing_acc = settings.get("razorpay_clearing_account") if isinstance(settings, dict) else getattr(settings, "razorpay_clearing_account", None)
	payment_account = clearing_acc or frappe.db.get_value(
		"Account", {"account_type": "Bank", "is_group": 0, "company": company}, "name"
	) or frappe.db.get_value("Account", {"is_group": 0, "company": company}, "name")

	entry = get_payment_entry(
		"Sales Invoice",
		purchase_doc.sales_invoice,
		bank_account=payment_account,
		reference_date=nowdate(),
		ignore_permissions=True,
	)
	mop = settings.get("mode_of_payment") if isinstance(settings, dict) else getattr(settings, "mode_of_payment", None)
	entry.mode_of_payment = mop or "Cash"
	payment_id = (payment.get("id") if isinstance(payment, dict) else str(payment)) if payment else f"MANUAL-{nowdate()}"
	entry.reference_no = payment_id
	entry.reference_date = nowdate()
	entry.remarks = f"Settlement for LexPack Purchase {purchase_doc.name}"

	_format_payment_entry_currencies(entry, purchase_doc, company)

	entry.insert(ignore_permissions=True)
	entry.flags.ignore_permissions = True
	entry.submit()
	return entry


def _resolve_exchange_rate(plan_currency: str, company: str) -> float:
	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	if not company_currency:
		frappe.throw(_("The selected Company has no default currency."), frappe.ValidationError)
	if plan_currency == company_currency:
		return 1
	from erpnext.setup.utils import get_exchange_rate

	rate = flt(get_exchange_rate(plan_currency, company_currency, nowdate(), "for_selling"))
	if rate <= 0:
		frappe.throw(
			_("Create a current Currency Exchange rate from {0} to {1} before accepting this purchase.").format(plan_currency, company_currency),
			frappe.ValidationError,
		)
	return rate


def _get_settings(require_enabled=False):
	settings = _load_settings()
	if require_enabled:
		readiness = get_razorpay_readiness(settings)
		if not readiness["enabled"]:
			frappe.throw(_("LexPack online purchase is not enabled yet."), frappe.ValidationError)
		if not readiness["configured"]:
			frappe.throw(
				_("Razorpay configuration is incomplete: {0}").format("; ".join(readiness["issues"])),
				frappe.ValidationError,
			)
	return settings


def _load_settings():
	try:
		return frappe.get_single("LexPack Settings")
	except frappe.DoesNotExistError:
		# A fresh test transaction may not yet have written values to tabSingles.
		return frappe.new_doc("LexPack Settings")


def get_razorpay_readiness(settings=None):
	"""Return a secret-free local readiness report for checkout activation."""
	settings = settings or _load_settings()
	issues = []
	key_id = str(settings.get("key_id") or "").strip()
	key_secret = _settings_password(settings, "key_secret")
	webhook_secret = _settings_password(settings, "webhook_secret")
	test_mode = bool(cint(settings.get("test_mode")))
	expected_prefix = "rzp_test_" if test_mode else "rzp_live_"

	if not key_id:
		issues.append(_("Razorpay Key ID is missing"))
	elif not key_id.startswith(expected_prefix):
		issues.append(
			_("Razorpay Key ID must start with {0} while {1} Mode is selected").format(
				expected_prefix, _("Test") if test_mode else _("Live")
			)
		)
	if not key_secret:
		issues.append(_("Razorpay Key Secret is missing"))
	if not webhook_secret:
		issues.append(_("Razorpay Webhook Secret is missing"))
	elif key_secret and hmac.compare_digest(key_secret, webhook_secret):
		issues.append(_("Webhook Secret must be different from the API Key Secret"))
	non_accounting_issue_count = len(issues)

	company = settings.get("company")
	if not company or not frappe.db.exists("Company", company):
		issues.append(_("A valid Company is required"))

	selling_item = settings.get("selling_item")
	if not _valid_sales_item(selling_item):
		issues.append(_("LexPack Selling Item must be an enabled sales item"))
	direct_quote_item = settings.get("direct_quote_item") or selling_item
	if not _valid_sales_item(direct_quote_item):
		issues.append(_("Fixed Quote Selling Item must be an enabled sales item"))

	mode_of_payment = settings.get("mode_of_payment")
	if not mode_of_payment or not frappe.db.exists("Mode of Payment", mode_of_payment):
		issues.append(_("A valid Mode of Payment is required"))

	clearing_account = settings.get("razorpay_clearing_account")
	account_values = (
		frappe.db.get_value("Account", clearing_account, ["company", "is_group", "account_type"])
		if clearing_account
		else None
	)
	if not account_values or account_values[0] != company or cint(account_values[1]) or account_values[2] not in {"Bank", "Cash"}:
		issues.append(_("Razorpay Clearing Account must be a leaf Bank or Cash account for the selected Company"))

	income_account = settings.get("income_account")
	if income_account:
		account = frappe.db.get_value("Account", income_account, ["company", "is_group", "root_type"])
		if not account or account[0] != company or cint(account[1]) or account[2] != "Income":
			issues.append(_("LexPack Income Account must be a leaf Income account for the selected Company"))
	cost_center = settings.get("cost_center")
	if cost_center:
		center = frappe.db.get_value("Cost Center", cost_center, ["company", "is_group"])
		if not center or center[0] != company or cint(center[1]):
			issues.append(_("Cost Center must be a leaf cost center for the selected Company"))

	credentials_ready = bool(key_id and key_secret and key_id.startswith(expected_prefix))
	webhook_ready = bool(webhook_secret and (not key_secret or webhook_secret != key_secret))
	accounting_ready = len(issues) == non_accounting_issue_count
	configured = not issues
	enabled = bool(cint(settings.get("enabled")))
	return {
		"enabled": enabled,
		"configured": configured,
		"payment_enabled": bool(enabled and configured),
		"mode": "Test" if test_mode else "Live",
		"credentials_ready": credentials_ready,
		"webhook_ready": webhook_ready,
		"accounting_ready": accounting_ready,
		"api_test_status": settings.get("last_connection_test_status") or "Not Tested",
		"api_tested_on": settings.get("last_connection_test_on"),
		"api_test_message": settings.get("last_connection_test_message") or "",
		"issues": [str(issue) for issue in issues],
	}


@frappe.whitelist()
def get_razorpay_status():
	_require_razorpay_setup_access()
	status = get_razorpay_readiness()
	status["webhook_url"] = frappe.utils.get_url(
		"/api/method/lex.lexpack.handle_razorpay_webhook"
	)
	status["required_webhook_events"] = ["payment.captured", "payment.failed", "order.paid"]
	return status


@frappe.whitelist()
def test_razorpay_configuration():
	"""Authenticate with Razorpay using a read-only Orders request; never creates a charge."""
	_require_razorpay_setup_access()
	settings = _load_settings()
	readiness = get_razorpay_readiness(settings)
	if not readiness["credentials_ready"]:
		message = _("API test was not run because the Key ID/Secret or Test/Live mode is invalid.")
		_record_razorpay_connection_test("Failed", message)
		return {
			"ok": False,
			"api_authenticated": False,
			"message": message,
			"readiness": get_razorpay_readiness(_load_settings()),
		}
	try:
		response = _razorpay_request("GET", "/orders", settings, {"count": 1})
		if not isinstance(response, dict) or response.get("entity") != "collection" or not isinstance(response.get("items"), list):
			frappe.throw(_("Razorpay returned an unexpected API response."), frappe.ValidationError)
		message = _("Razorpay API authentication succeeded in {0} Mode. No order or charge was created.").format(
			readiness["mode"]
		)
		_record_razorpay_connection_test("Passed", message)
		readiness = get_razorpay_readiness(_load_settings())
		return {"ok": True, "api_authenticated": True, "message": message, "readiness": readiness}
	except Exception as exc:
		message = _safe_gateway_error(exc)
		_record_razorpay_connection_test("Failed", message)
		return {
			"ok": False,
			"api_authenticated": False,
			"message": message,
			"readiness": get_razorpay_readiness(_load_settings()),
		}


def _record_razorpay_connection_test(status: str, message: str):
	values = {
		"last_connection_test_on": now_datetime(),
		"last_connection_test_status": status,
		"last_connection_test_message": str(message)[:500],
	}
	for fieldname, value in values.items():
		if frappe.get_meta("LexPack Settings").has_field(fieldname):
			frappe.db.set_single_value("LexPack Settings", fieldname, value)
	frappe.clear_cache(doctype="LexPack Settings")


def _require_razorpay_setup_access():
	if frappe.session.user == "Administrator" or set(frappe.get_roles()).intersection(RAZORPAY_SETUP_ROLES):
		return
	frappe.throw(_("System Manager or Accounts Manager access is required."), frappe.PermissionError)


def _settings_password(settings, fieldname: str) -> str:
	raw_value = settings.get(fieldname)
	if raw_value and raw_value != "*****":
		return str(raw_value)
	try:
		return str(settings.get_password(fieldname, raise_exception=False) or "")
	except (frappe.AuthenticationError, frappe.DoesNotExistError):
		return ""


def _valid_sales_item(item_code: str | None) -> bool:
	if not item_code:
		return False
	values = frappe.db.get_value("Item", item_code, ["disabled", "is_sales_item"])
	return bool(values and not cint(values[0]) and cint(values[1]))


def _razorpay_request(method: str, path: str, settings, payload=None):
	method = method.upper()
	try:
		response = requests.request(
			method,
			f"{RAZORPAY_API_ROOT}{path}",
			auth=(settings.key_id, settings.get_password("key_secret")),
			params=payload if method == "GET" else None,
			json=payload if method != "GET" else None,
			timeout=cint(settings.api_timeout_seconds or 15),
		)
		response.raise_for_status()
		try:
			return response.json()
		except ValueError:
			frappe.throw(_("Razorpay returned an unreadable API response."), frappe.ValidationError)
	except requests.RequestException as exc:
		message = _("Razorpay could not process this request.")
		if getattr(exc, "response", None) is not None:
			try:
				message = (((exc.response.json() or {}).get("error") or {}).get("description") or message)[:500]
			except (ValueError, AttributeError):
				pass
		frappe.throw(message, frappe.ValidationError)


def _validate_order_response(order, requested):
	if (
		order.get("entity") != "order"
		or not order.get("id")
		or cint(order.get("amount")) != cint(requested["amount"])
		or order.get("currency") != requested["currency"]
		or order.get("receipt") != requested["receipt"]
	):
		frappe.throw(_("Razorpay returned an invalid order response."), frappe.ValidationError)


def _validate_payment_entity(purchase_doc, payment, require_captured=True):
	if not payment or payment.get("entity") != "payment" or not payment.get("id"):
		frappe.throw(_("Razorpay payment details are missing."), frappe.ValidationError)
	if payment.get("order_id") != purchase_doc.razorpay_order_id:
		frappe.throw(_("Razorpay payment is linked to a different order."), frappe.PermissionError)
	if cint(payment.get("amount")) != _minor_units(purchase_doc.amount, purchase_doc.currency):
		frappe.throw(_("Razorpay payment amount does not match the LexPack purchase."), frappe.PermissionError)
	if payment.get("currency") != purchase_doc.currency:
		frappe.throw(_("Razorpay payment currency does not match the LexPack purchase."), frappe.PermissionError)
	if require_captured and payment.get("status") != "captured":
		frappe.throw(_("LexPoints are credited only after Razorpay marks the payment as captured."), frappe.ValidationError)


def _minor_units(amount, currency: str) -> int:
	# Razorpay expects currency minor units. The configured LexPack/quote currencies
	# currently use either a zero-decimal or standard two-decimal exponent.
	zero_decimal = {"BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"}
	factor = Decimal("1") if currency in zero_decimal else Decimal("100")
	return int((Decimal(str(amount)) * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _checkout_signature_is_valid(order_id: str, payment_id: str, signature: str, key_secret: str) -> bool:
	if not all((order_id, payment_id, signature, key_secret)):
		return False
	expected = hmac.new(
		key_secret.encode("utf-8"),
		f"{order_id}|{payment_id}".encode("utf-8"),
		hashlib.sha256,
	).hexdigest()
	return hmac.compare_digest(expected, signature)


def _webhook_signature_is_valid(raw_body: bytes, signature: str, webhook_secret: str) -> bool:
	if not raw_body or not signature or not webhook_secret:
		return False
	expected = hmac.new(webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
	return hmac.compare_digest(expected, signature)


def _set_purchase_values(purchase_doc, **values):
	previous_flag = getattr(frappe.flags, "lexpack_purchase_service", False)
	frappe.flags.lexpack_purchase_service = True
	try:
		purchase_doc.update(values)
		purchase_doc.save(ignore_permissions=True)
	finally:
		frappe.flags.lexpack_purchase_service = previous_flag


def _require_purchase_authority():
	portal_user = get_portal_user()
	if portal_user:
		if not portal_user.lexpack_purchase_access:
			frappe.throw(_("Your client role cannot purchase LexPacks."), frappe.PermissionError)
		return portal_user.client, portal_user
	if frappe.session.user == "Administrator" or set(frappe.get_roles()).intersection(PURCHASE_ROLES):
		frappe.throw(_("Internal users must choose a Client from the LexPack Purchase workflow."), frappe.ValidationError)
	frappe.throw(_("An active Lexocrates Portal User is required."), frappe.PermissionError)


def _assert_purchase_access(purchase_doc):
	portal_user = get_portal_user()
	if portal_user and portal_user.client == purchase_doc.client and portal_user.lexpack_purchase_access:
		return
	if frappe.session.user == "Administrator" or set(frappe.get_roles()).intersection(PURCHASE_ROLES):
		return
	frappe.throw(_("You cannot access this LexPack purchase."), frappe.PermissionError)


def _checkout_prefill(portal_user):
	if not portal_user:
		return {}
	return {
		"name": portal_user.full_name or frappe.db.get_value("User", portal_user.user, "full_name") or "",
		"email": portal_user.user,
		"contact": portal_user.get("mobile_no") or "",
	}


def _purchase_result(purchase_doc, duplicate=False):
	return {
		"purchase": purchase_doc.name,
		"work_intake": purchase_doc.work_intake,
		"status": purchase_doc.status,
		"sales_invoice": purchase_doc.sales_invoice,
		"payment_entry": purchase_doc.payment_entry,
		"wallet_transaction": purchase_doc.wallet_transaction,
		"base_lexpoints": cint(purchase_doc.base_lexpoints),
		"bonus_lexpoints": cint(purchase_doc.bonus_lexpoints),
		"total_lexpoints": cint(purchase_doc.total_lexpoints),
		"duplicate": duplicate,
	}


def _safe_gateway_error(exc) -> str:
	message = getattr(exc, "message", None) or str(exc) or _("Razorpay request failed.")
	return str(message).replace("Traceback", "").strip()[:500]


@frappe.whitelist()
def manually_approve_lexpack_plan(
	client: str,
	plan: str,
	approval_reason: str,
	work_intake: str | None = None,
	amount: float | None = None,
	lexpoints: int | None = None,
	create_payment_entry: bool = True,
):
	"""Manually approve and grant a LexPack Plan to a Customer with a mandatory approval reason and automatic ERPNext Sales Invoice generation."""
	allowed_roles = {"CEO", "Lexocrates Director", "LPO_Admin", "System Manager", "Accounts Manager", "Lexocrates Finance"}
	if frappe.session.user != "Administrator" and not set(frappe.get_roles()).intersection(allowed_roles):
		frappe.throw(_("Only Executive/Finance managers can manually approve LexPack plans."), frappe.PermissionError)

	if not approval_reason or not str(approval_reason).strip():
		frappe.throw(_("Approval Reason is required for manual LexPack plan approval."), frappe.ValidationError)

	if not frappe.db.exists("Customer", client):
		frappe.throw(_("Customer {0} does not exist.").format(client), frappe.NotFoundError)
	if work_intake:
		if not frappe.db.exists("Lexocrates Work Intake", work_intake):
			frappe.throw(_("Work Intake {0} does not exist.").format(work_intake), frappe.DoesNotExistError)
		intake_doc = frappe.get_doc("Lexocrates Work Intake", work_intake)
		if intake_doc.client != client:
			frappe.throw(_("Work Intake belongs to another Client."), frappe.PermissionError)
		from lex.work_intake import _validate_ready_quote

		_validate_ready_quote(intake_doc)

	plan_doc = frappe.get_doc("LexPack Plan", plan)
	settings = _get_settings(require_enabled=False)
	company = _resolve_company(settings)
	exchange_rate = _resolve_exchange_rate(plan_doc.currency, company)

	paid_amount = flt(amount) if amount is not None and flt(amount) > 0 else flt(plan_doc.price)
	granted_points = cint(lexpoints) if lexpoints is not None and cint(lexpoints) > 0 else cint(plan_doc.lexpoints)

	prev_ignore_perm = getattr(frappe.flags, "ignore_permissions", False)
	prev_service_flag = getattr(frappe.flags, "lexpack_purchase_service", False)
	frappe.flags.ignore_permissions = True
	frappe.flags.lexpack_purchase_service = True
	try:
		purchase_doc = frappe.get_doc(
			{
				"doctype": "LexPack Purchase",
				"client": client,
				"purchaser": frappe.session.user,
				"plan": plan_doc.name,
				"work_intake": work_intake,
				"plan_name_snapshot": plan_doc.plan_name,
				"status": "Paid",
				"gateway": "Manual Executive Approval",
				"created_on": now_datetime(),
				"paid_on": now_datetime(),
				"currency": plan_doc.currency,
				"amount": paid_amount,
				"exchange_rate": exchange_rate,
				"base_lexpoints": granted_points,
				"bonus_lexpoints": 0,
				"total_lexpoints": granted_points,
				"is_manual_approval": 1,
				"approval_reason": str(approval_reason).strip(),
			}
		).insert(ignore_permissions=True)

		invoice = _create_sales_invoice(purchase_doc, settings)
		_set_purchase_values(purchase_doc, sales_invoice=invoice.name)

		if create_payment_entry:
			payment_payload = {
				"id": f"MANUAL-{purchase_doc.name}",
				"amount": paid_amount,
			}
			payment_entry = _create_manual_payment_entry(purchase_doc, settings, payment_payload, str(approval_reason).strip())
			_set_purchase_values(purchase_doc, payment_entry=payment_entry.name)

		from lex.lex.doctype.lexocrates_wallet_transaction.lexocrates_wallet_transaction import _post_transaction

		wallet_entry = _post_transaction(
			client=client,
			transaction_type="Purchase",
			points=granted_points,
			idempotency_key=f"lexpack-purchase:{purchase_doc.name}",
			reference_doctype="LexPack Purchase",
			reference_name=purchase_doc.name,
			description=f"Manual approval of {plan_doc.plan_name} LexPack by {frappe.session.user}: {str(approval_reason).strip()}",
		)
		_set_purchase_values(purchase_doc, wallet_transaction=wallet_entry.name)

		pricing = recalculate_client_pricing(client, purchase_doc.name)
		_set_purchase_values(
			purchase_doc,
			rolling_spend_before=pricing["rolling_spend_before"],
			rolling_spend_after=pricing["rolling_spend_after"],
			tier_before=pricing["tier_before"],
			tier_after=pricing["tier_after"],
			bonus_lexpoints=pricing["bonus_points"],
			total_lexpoints=granted_points + cint(pricing["bonus_points"]),
			bonus_wallet_transactions=json.dumps(pricing["bonus_transactions"]),
		)

		if work_intake and frappe.db.exists("Lexocrates Work Intake", work_intake):
			from lex.work_intake import complete_lexpack_funding

			complete_lexpack_funding(purchase_doc)

		actor_portal_user = get_portal_user(frappe.session.user)
		create_portal_audit_event(
			client=client,
			portal_user=actor_portal_user.name if actor_portal_user else None,
			user=frappe.session.user,
			action="LexPack Manual Executive Approval",
			object_type="LexPack Purchase",
			object_id=purchase_doc.name,
			new_value={
				"plan": plan_doc.name,
				"amount": paid_amount,
				"lexpoints": granted_points,
				"approval_reason": str(approval_reason).strip(),
				"sales_invoice": invoice.name,
				"payment_entry": purchase_doc.payment_entry,
			},
		)

		return {
			"purchase": purchase_doc.name,
			"sales_invoice": invoice.name,
			"payment_entry": purchase_doc.payment_entry,
			"total_lexpoints": purchase_doc.total_lexpoints,
			"status": "Paid",
			"message": _("LexPack Plan manually approved successfully. Invoice {0} generated.").format(invoice.name),
		}
	finally:
		frappe.flags.ignore_permissions = prev_ignore_perm
		frappe.flags.lexpack_purchase_service = prev_service_flag


def _create_manual_payment_entry(purchase_doc, settings, payment, reason: str):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	company = _resolve_company(settings)
	clearing_acc = settings.get("razorpay_clearing_account") if isinstance(settings, dict) else getattr(settings, "razorpay_clearing_account", None)
	payment_account = clearing_acc or frappe.db.get_value(
		"Account", {"account_type": "Bank", "is_group": 0, "company": company}, "name"
	) or frappe.db.get_value("Account", {"is_group": 0, "company": company}, "name")

	entry = get_payment_entry(
		"Sales Invoice",
		purchase_doc.sales_invoice,
		bank_account=payment_account,
		reference_date=nowdate(),
		ignore_permissions=True,
	)
	mop = settings.get("mode_of_payment") if isinstance(settings, dict) else getattr(settings, "mode_of_payment", None)
	entry.mode_of_payment = mop or "Cash"
	payment_id = (payment.get("id") if isinstance(payment, dict) else str(payment)) if payment else f"MANUAL-{nowdate()}"
	entry.reference_no = payment_id
	entry.reference_date = nowdate()
	entry.remarks = f"Manual LexPack approval settlement. Reason: {reason}"

	_format_payment_entry_currencies(entry, purchase_doc, company)

	entry.insert(ignore_permissions=True)
	entry.flags.ignore_permissions = True
	entry.submit()
	return entry
