from __future__ import annotations

import hashlib
import hmac
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from lex import install, lexpack
from lex.lex.doctype.lexocrates_wallet_transaction.lexocrates_wallet_transaction import _post_transaction


class TestLexPackCommerce(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		install.ensure_lpo_roles()
		install.ensure_lexpack_catalog()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_pdf_plan_catalog_is_prepaid_and_non_expiring(self):
		plans = frappe.get_all(
			"LexPack Plan",
			fields=["name", "discount_percent", "value_advantage", "no_expiry", "enterprise_custom"],
			order_by="display_order asc",
		)
		self.assertEqual(
			[(row.name, row.discount_percent, row.value_advantage) for row in plans],
			[
				("STARTER", 7.0, "7% savings"),
				("GROWTH", 14.0, "14% savings"),
				("PROFESSIONAL", 21.0, "21% savings"),
				("BUSINESS", 28.0, "28% savings"),
				("ENTERPRISE", 0.0, "Custom commercial terms"),
			],
		)
		self.assertTrue(all(row.no_expiry for row in plans))
		self.assertTrue(plans[-1].enterprise_custom)

	def test_purchase_records_cannot_bypass_payment_service(self):
		client = _make_client()
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "LexPack Purchase",
					"client": client,
					"purchaser": "Administrator",
					"plan": "STARTER",
					"plan_name_snapshot": "Starter",
					"status": "Created",
					"created_on": now_datetime(),
					"currency": "USD",
					"amount": 299,
					"exchange_rate": 1,
					"legal_capacity_amount": 321.51,
				}
			).insert(ignore_permissions=True)

	def test_checkout_signature_and_minor_units(self):
		order_id = "order_test_123"
		payment_id = "pay_test_456"
		secret = "server-only-secret"
		signature = hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
		self.assertTrue(lexpack._checkout_signature_is_valid(order_id, payment_id, signature, secret))
		self.assertFalse(lexpack._checkout_signature_is_valid(order_id, payment_id, "tampered", secret))
		self.assertEqual(lexpack._minor_units(299, "USD"), 29900)
		raw_body = b'{"event":"payment.captured"}'
		webhook_secret = "separate-webhook-secret"
		webhook_signature = hmac.new(webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
		self.assertTrue(lexpack._webhook_signature_is_valid(raw_body, webhook_signature, webhook_secret))
		self.assertFalse(lexpack._webhook_signature_is_valid(raw_body, "tampered", webhook_secret))

	def test_gateway_readiness_requires_explicit_enable_and_matching_key_mode(self):
		settings = _configure_test_gateway(enabled=0)
		readiness = lexpack.get_razorpay_readiness(settings)
		self.assertTrue(readiness["configured"])
		self.assertFalse(readiness["payment_enabled"])
		self.assertEqual(readiness["mode"], "Test")

		settings.enabled = 1
		readiness = lexpack.get_razorpay_readiness(settings)
		self.assertTrue(readiness["payment_enabled"])

		settings.key_id = "rzp_live_wrong_mode"
		readiness = lexpack.get_razorpay_readiness(settings)
		self.assertFalse(readiness["configured"])
		self.assertFalse(readiness["payment_enabled"])
		self.assertTrue(any("rzp_test_" in issue for issue in readiness["issues"]))

	def test_configuration_test_uses_read_only_orders_api_and_hides_secrets(self):
		_configure_test_gateway(enabled=0)
		with patch("lex.lexpack._razorpay_request") as request:
			request.return_value = {"entity": "collection", "count": 0, "items": []}
			result = lexpack.test_razorpay_configuration()
		request.assert_called_once()
		method, path, _settings, payload = request.call_args.args
		self.assertEqual((method, path, payload), ("GET", "/orders", {"count": 1}))
		self.assertTrue(result["ok"])
		self.assertTrue(result["api_authenticated"])
		self.assertNotIn("unit-test-key-secret", str(result))
		self.assertNotIn("unit-test-webhook-secret", str(result))

	def test_razorpay_transport_sends_get_filters_as_query_parameters(self):
		settings = _configure_test_gateway(enabled=0)
		response = Mock()
		response.raise_for_status.return_value = None
		response.json.return_value = {"entity": "collection", "items": []}
		with patch("lex.lexpack.requests.request", return_value=response) as request:
			lexpack._razorpay_request("GET", "/orders", settings, {"count": 1})
		kwargs = request.call_args.kwargs
		self.assertEqual(kwargs["params"], {"count": 1})
		self.assertIsNone(kwargs["json"])

	def test_portal_catalog_uses_client_country_currency(self):
		client = _make_client(default_currency="CAD")
		if frappe.get_meta("Customer").has_field("custom_primary_jurisdiction"):
			frappe.db.set_value("Customer", client, "custom_primary_jurisdiction", "Canada", update_modified=False)
		user = _make_user()
		_make_portal_user(user.name, client, "Client Administrator")
		frappe.set_user(user.name)

		data = lexpack.get_lexpack_portal_data()
		starter = next(row for row in data["plans"] if row.plan_code == "STARTER")

		self.assertEqual(data["selected_currency"], "CAD")
		self.assertEqual(starter.currency, "CAD")
		self.assertEqual(starter.price, 399)
		self.assertEqual(len(data["currency_options"]), 1)
		self.assertEqual(data["currency_options"][0]["code"], "CAD")
		self.assertTrue(data["purchase_access"])

	def test_checkout_currency_cannot_be_overridden_from_client_portal(self):
		_configure_test_gateway(enabled=1)
		client = _make_client(default_currency="CAD")
		user = _make_user()
		_make_portal_user(user.name, client, "Client Administrator")
		frappe.set_user(user.name)

		with self.assertRaises(frappe.ValidationError):
			lexpack.create_razorpay_order("STARTER", currency="USD")

	def test_direct_dashboard_razorpay_order_credits_wallet_after_capture(self):
		_configure_test_gateway(enabled=1)
		client = _make_client(default_currency="USD")
		user = _make_user()
		_make_portal_user(user.name, client, "Client Administrator")
		frappe.set_user(user.name)
		payment_id = "pay_direct_lexpack"

		def fake_gateway(method, path, settings, payload=None):
			if method == "POST" and path == "/orders":
				return {
					"entity": "order",
					"id": "order_direct_lexpack",
					"amount": payload["amount"],
					"currency": payload["currency"],
					"receipt": payload["receipt"],
				}
			if method == "GET" and path == f"/payments/{payment_id}":
				return {
					"entity": "payment",
					"id": payment_id,
					"order_id": "order_direct_lexpack",
					"amount": 29900,
					"currency": "USD",
					"status": "captured",
				}
			raise AssertionError(f"Unexpected Razorpay call: {method} {path}")

		with patch("lex.lexpack._razorpay_request", side_effect=fake_gateway):
			order = lexpack.create_razorpay_order("STARTER", currency="USD")
			signature = hmac.new(
				b"unit-test-key-secret",
				f"{order['order_id']}|{payment_id}".encode(),
				hashlib.sha256,
			).hexdigest()
			result = lexpack.verify_razorpay_payment(
				order["purchase"],
				payment_id,
				order["order_id"],
				signature,
			)

		self.assertIsNone(order["work_intake"])
		self.assertEqual(order["currency"], "USD")
		self.assertEqual(result["status"], "Paid")
		wallet = frappe.db.get_value(
			"Lexocrates Client Wallet", {"client": client}, ["current_balance", "capacity_currency"], as_dict=True
		)
		self.assertEqual(wallet.current_balance, 321.51)
		self.assertEqual(wallet.capacity_currency, "USD")

	def test_failed_webhook_processing_is_auditable_and_idempotent(self):
		_configure_test_gateway(enabled=1)
		client = _make_client()
		purchase = _service_purchase(client, "STARTER", 299, 321.51)
		lexpack._set_purchase_values(purchase, razorpay_order_id="order_failed_webhook")
		payload = {
			"event": "payment.failed",
			"payload": {
				"payment": {
					"entity": {
						"entity": "payment",
						"id": "pay_failed_webhook",
						"order_id": "order_failed_webhook",
						"error_description": "Test payment was declined",
					}
				}
			},
		}
		result = lexpack.process_razorpay_webhook(payload, "event_failed_webhook")
		self.assertEqual(result["status"], "failed")
		purchase.reload()
		self.assertEqual(purchase.status, "Failed")
		self.assertEqual(purchase.gateway_event_id, "event_failed_webhook")
		duplicate = lexpack.process_razorpay_webhook(payload, "event_failed_webhook")
		self.assertEqual(duplicate["status"], "duplicate")

	def test_wallet_is_single_currency_and_keeps_cent_precision(self):
		client = _make_client()
		_post_transaction(
			client=client,
			transaction_type="Purchase",
			legal_capacity_amount=100.10,
			currency="USD",
			idempotency_key=f"legal-capacity-test-base:{client}",
		)
		_post_transaction(
			client=client,
			transaction_type="Reservation",
			legal_capacity_amount=50.05,
			currency="USD",
			idempotency_key=f"legal-capacity-reserve:{client}",
		)
		with self.assertRaises(frappe.ValidationError):
			_post_transaction(
				client=client,
				transaction_type="Top-Up",
				legal_capacity_amount=10,
				currency="CAD",
				idempotency_key=f"legal-capacity-wrong-currency:{client}",
			)
		wallet = frappe.db.get_value(
			"Lexocrates Client Wallet",
			{"client": client},
			["current_balance", "reserved_balance", "capacity_currency"],
			as_dict=True,
		)
		self.assertEqual(wallet.current_balance, 50.05)
		self.assertEqual(wallet.reserved_balance, 50.05)
		self.assertEqual(wallet.capacity_currency, "USD")

	def test_captured_payment_posts_sales_invoice_payment_entry_and_wallet(self):
		company = frappe.db.get_value("Company", {"default_currency": "USD"}, "name")
		clearing = frappe.db.get_value(
			"Account",
			{"company": company, "account_type": ["in", ["Bank", "Cash"]], "is_group": 0},
			"name",
		)
		self.assertTrue(company and clearing)
		frappe.db.set_single_value(
			"LexPack Settings",
			{
				"enabled": 1,
				"test_mode": 1,
				"key_id": "rzp_test_unit",
				"company": company,
				"selling_item": install.LEXPACK_ITEM_CODE,
				"mode_of_payment": install.LEXPACK_MODE_OF_PAYMENT,
				"razorpay_clearing_account": clearing,
			},
		)
		from frappe.utils.password import set_encrypted_password

		set_encrypted_password("LexPack Settings", "LexPack Settings", "unit-test-key-secret", "key_secret")
		set_encrypted_password("LexPack Settings", "LexPack Settings", "unit-test-webhook-secret", "webhook_secret")
		frappe.clear_cache(doctype="LexPack Settings")
		client = _make_client(default_currency="USD")
		purchase = _service_purchase(client, "STARTER", 299, 321.51)
		lexpack._set_purchase_values(purchase, razorpay_order_id="order_unit_lexpack")
		result = lexpack._complete_purchase(
			purchase,
			{
				"entity": "payment",
				"id": "pay_unit_lexpack",
				"order_id": "order_unit_lexpack",
				"amount": 29900,
				"currency": "USD",
				"status": "captured",
			},
			source="unit-test",
		)
		self.assertEqual(result["status"], "Paid")
		self.assertEqual(frappe.db.get_value("Sales Invoice", result["sales_invoice"], "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Payment Entry", result["payment_entry"], "docstatus"), 1)
		self.assertEqual(
			frappe.db.get_value("Lexocrates Client Wallet", {"client": client}, "current_balance"),
			321.51,
		)

	def test_manual_executive_lexpack_approval_generates_invoice_and_credits_wallet(self):
		company = frappe.db.get_value("Company", {"default_currency": "USD"}, "name")
		clearing = frappe.db.get_value(
			"Account",
			{"company": company, "account_type": ["in", ["Bank", "Cash"]], "is_group": 0},
			"name",
		)
		frappe.db.set_single_value(
			"LexPack Settings",
			{
				"enabled": 1,
				"company": company,
				"selling_item": install.LEXPACK_ITEM_CODE,
				"mode_of_payment": install.LEXPACK_MODE_OF_PAYMENT,
				"razorpay_clearing_account": clearing,
			},
		)
		frappe.clear_cache(doctype="LexPack Settings")
		client = _make_client(default_currency="USD")
		result = lexpack.manually_approve_lexpack_plan(
			client=client,
			plan="STARTER",
			approval_reason="Custom Enterprise Manual Approval and Commercial SLA Agreement",
			amount=299,
			create_payment_entry=True,
		)
		self.assertEqual(result["status"], "Paid")
		self.assertTrue(result["sales_invoice"])
		self.assertTrue(result["payment_entry"])
		self.assertEqual(frappe.db.get_value("Sales Invoice", result["sales_invoice"], "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Payment Entry", result["payment_entry"], "docstatus"), 1)

		purchase_doc = frappe.get_doc("LexPack Purchase", result["purchase"])
		self.assertEqual(purchase_doc.is_manual_approval, 1)
		self.assertEqual(purchase_doc.approval_reason, "Custom Enterprise Manual Approval and Commercial SLA Agreement")
		self.assertEqual(
			frappe.db.get_value("Lexocrates Client Wallet", {"client": client}, "current_balance"),
			321.51,
		)

	def test_accounting_workspace_contains_lexpack_controls(self):
		install.ensure_accounting_workspace_actions()
		links = set(
			frappe.get_all(
				"Workspace Shortcut",
				filters={"parent": "Accounting"},
				pluck="label",
			)
		)
		self.assertTrue({"LexPack Plans", "LexPack Purchases", "Legal Capacity Wallets", "Razorpay Settings"}.issubset(links))


def _make_client(default_currency="USD"):
	suffix = frappe.generate_hash(length=8).lower()
	return frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": f"LexPack Test Client {suffix}",
			"customer_type": "Company",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
			"default_currency": default_currency,
		}
	).insert(ignore_permissions=True).name


def _make_user():
	email = f"lexpack-{frappe.generate_hash(length=12).lower()}@example.invalid"
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": "LexPack",
			"last_name": "Buyer",
			"enabled": 1,
			"user_type": "Website User",
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True)
	user.add_roles("Lexocrates Client")
	return user


def _make_portal_user(user: str, client: str, portal_role: str):
	return frappe.get_doc(
		{
			"doctype": "Lexocrates Portal User",
			"user": user,
			"client": client,
			"portal_role": portal_role,
			"account_status": "Active",
			"matter_access_scope": "All Client Matters",
		}
	).insert(ignore_permissions=True)


def _service_purchase(client, plan, amount, legal_capacity_amount, currency="USD"):
	previous = getattr(frappe.flags, "lexpack_purchase_service", False)
	frappe.flags.lexpack_purchase_service = True
	try:
		return frappe.get_doc(
			{
				"doctype": "LexPack Purchase",
				"client": client,
				"purchaser": "Administrator",
				"plan": plan,
				"plan_name_snapshot": frappe.db.get_value("LexPack Plan", plan, "plan_name"),
				"status": "Payment Pending",
				"gateway": "Razorpay",
				"created_on": now_datetime(),
				"currency": currency,
				"amount": amount,
				"exchange_rate": 1,
				"legal_capacity_amount": legal_capacity_amount,
			}
		).insert(ignore_permissions=True)
	finally:
		frappe.flags.lexpack_purchase_service = previous


def _configure_test_gateway(enabled=1):
	install.ensure_lexpack_master_data()
	company = frappe.db.get_value("Company", {"default_currency": "USD"}, "name") or frappe.db.get_value("Company", {}, "name")
	clearing = frappe.db.get_value(
		"Account",
		{"company": company, "account_type": ["in", ["Bank", "Cash"]], "is_group": 0},
		"name",
	)
	if not company or not clearing:
		raise AssertionError("A test Company with a leaf Bank/Cash account is required")
	frappe.db.set_single_value(
		"LexPack Settings",
		{
			"enabled": enabled,
			"test_mode": 1,
			"key_id": "rzp_test_unit",
			"company": company,
			"selling_item": install.LEXPACK_ITEM_CODE,
			"direct_quote_item": install.FIXED_QUOTE_ITEM_CODE,
			"mode_of_payment": install.LEXPACK_MODE_OF_PAYMENT,
			"razorpay_clearing_account": clearing,
		},
	)
	from frappe.utils.password import set_encrypted_password

	set_encrypted_password("LexPack Settings", "LexPack Settings", "unit-test-key-secret", "key_secret")
	set_encrypted_password("LexPack Settings", "LexPack Settings", "unit-test-webhook-secret", "webhook_secret")
	frappe.clear_cache(doctype="LexPack Settings")
	return frappe.get_single("LexPack Settings")
