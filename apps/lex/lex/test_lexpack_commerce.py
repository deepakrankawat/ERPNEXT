from __future__ import annotations

import hashlib
import hmac

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from lex import install, lexpack
from lex.lex.doctype.lexocrates_wallet_transaction.lexocrates_wallet_transaction import _post_transaction


class TestLexPackCommerce(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		install.ensure_lexpack_catalog()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_pdf_plan_catalog_is_prepaid_and_non_expiring(self):
		plans = frappe.get_all(
			"LexPack Plan",
			fields=["name", "price", "lexpoints", "value_advantage", "no_expiry", "enterprise_custom"],
			order_by="display_order asc",
		)
		self.assertEqual(
			[(row.name, row.price, row.lexpoints, row.value_advantage) for row in plans],
			[
				("STARTER", 299.0, 100, "Standard"),
				("GROWTH", 899.0, 350, "Save 14%"),
				("PROFESSIONAL", 1999.0, 900, "Save 26%"),
				("BUSINESS", 3999.0, 2000, "Save 33%"),
				("ENTERPRISE", 0.0, 0, "Custom Commercial Terms"),
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
					"base_lexpoints": 100,
					"total_lexpoints": 100,
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

	def test_fair_pricing_bonus_is_atomic_and_idempotent(self):
		client = _make_client()
		_post_transaction(
			client=client,
			transaction_type="Purchase",
			points=350,
			idempotency_key=f"lexpack-test-base:{client}",
		)
		purchase = _service_purchase(client, "GROWTH", 899, 350)
		result = lexpack.recalculate_client_pricing(client, purchase.name)
		self.assertEqual(result["tier_after"], "GROWTH")
		self.assertEqual(result["bonus_points"], 30)
		wallet = frappe.db.get_value(
			"Lexocrates Client Wallet",
			{"client": client},
			["current_balance", "current_pricing_tier", "rolling_12_month_spend", "bonus_points_earned"],
			as_dict=True,
		)
		self.assertEqual(wallet.current_balance, 380)
		self.assertEqual(wallet.current_pricing_tier, "GROWTH")
		self.assertEqual(wallet.rolling_12_month_spend, 899)
		self.assertEqual(wallet.bonus_points_earned, 30)
		duplicate = lexpack.recalculate_client_pricing(client, purchase.name)
		self.assertEqual(duplicate["bonus_points"], 0)
		self.assertEqual(
			frappe.db.count(
				"Lexocrates Wallet Transaction",
				{"idempotency_key": f"lexpack-fair-pricing:{client}:GROWTH"},
			),
			1,
		)

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
		client = _make_client()
		purchase = _service_purchase(client, "STARTER", 299, 100)
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
			100,
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
		client = _make_client()
		result = lexpack.manually_approve_lexpack_plan(
			client=client,
			plan="STARTER",
			approval_reason="Custom Enterprise Manual Approval and Commercial SLA Agreement",
			amount=299,
			lexpoints=100,
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
			100,
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
		self.assertTrue({"LexPack Plans", "LexPack Purchases", "LexPoint Wallets", "Razorpay Settings"}.issubset(links))


def _make_client():
	suffix = frappe.generate_hash(length=8).lower()
	return frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": f"LexPack Test Client {suffix}",
			"customer_type": "Company",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
		}
	).insert(ignore_permissions=True).name


def _service_purchase(client, plan, amount, points):
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
				"currency": "USD",
				"amount": amount,
				"exchange_rate": 1,
				"base_lexpoints": points,
				"total_lexpoints": points,
			}
		).insert(ignore_permissions=True)
	finally:
		frappe.flags.lexpack_purchase_service = previous
