from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from lex import portal_management, client_portal, sop_execution_engine, workflow_runner, ai_gateway, wallet_statement, work_intake
from lex.lex.doctype.lexocrates_wallet_transaction.lexocrates_wallet_transaction import _post_transaction


class TestSRSAcceptanceScenarios(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.previous_in_test = getattr(frappe.flags, "in_test", False)
		frappe.flags.in_test = True

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.in_test = self.previous_in_test

	def test_scenario_a_new_client_quoted_matter(self):
		"""Scenario A: New Client, Quoted Matter (SRS Section 21.1)."""
		country = frappe.db.get_value("Country", {}, "name")
		suffix = frappe.generate_hash(length=8).lower()
		email = f"scenario-a-{suffix}@example.invalid"

		# Step 1 & 2: Public registration intake snapshot
		req = portal_management.request_client_registration(
			organization_name=f"Scenario A Law Firm {suffix}",
			organization_type="Law Firm",
			country=country,
			primary_user_name="Scenario A Admin",
			designation="Managing Partner",
			email=email,
		)
		self.assertIn("test_token", req)

		# Step 3 & 4: Email verification, compliance approval, then activation
		verified = portal_management.verify_client_registration(req["test_token"])
		self.assertFalse(frappe.db.exists("User", email))
		approved = portal_management.record_registration_compliance(
			verified["registration"], "Passed", "Passed", "Passed", "Approved", "Acceptance scenario"
		)
		frappe.set_user("Guest")
		activated = portal_management.activate_approved_registration(
			approved["test_activation_token"], "Correct-Scenario-A-Password-2026!"
		)
		client_id = activated["client"]
		self.assertTrue(activated["portal_user"])

		# Step 5: Upload-first Work Intake. No Matter is created before SLA,
		# documents, analysis, quote and funding complete.
		frappe.set_user(email)
		result = work_intake.create_work_intake(
			intake_title="Scenario A Acquisition Matter",
			service_type="Due Diligence",
			jurisdiction="India",
			priority="Medium",
			expected_outcome="Acquisition due-diligence report",
			preliminary_details="Review the proposed acquisition.",
		)
		intake = frappe.get_doc("Lexocrates Work Intake", result["name"])
		self.assertEqual(intake.client, client_id)
		self.assertEqual(intake.status, "SLA Pending")
		self.assertFalse(intake.matter)

		# Step 6: SLA acceptance unlocks documents, but still does not create a Matter.
		work_intake.accept_sla(intake.name, 1)
		intake.reload()
		self.assertEqual(intake.status, "Documents Pending")
		self.assertTrue(intake.sla_accepted)
		self.assertFalse(intake.matter)

	def test_scenario_b_existing_client_wallet_matter(self):
		"""Scenario B: Existing Client, Wallet Matter (SRS Section 21.2)."""
		suffix = frappe.generate_hash(length=8).lower()
		client = frappe.get_doc({
			"doctype": "Customer",
			"customer_name": f"Wallet Scenario Corp {suffix}",
			"customer_type": "Company",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
		}).insert(ignore_permissions=True).name

		# Step 1: LexPack purchase & wallet credit
		txn = _post_transaction(client=client, transaction_type="Purchase", points=200, idempotency_key=f"topup-{suffix}")
		self.assertEqual(txn.points, 200)

		# Step 3: Reserve points atomically
		res = _post_transaction(client=client, transaction_type="Reservation", points=50, idempotency_key=f"res-{suffix}")
		self.assertEqual(res.points, 50)

		# Step 4: Approved consumption debit
		debit = _post_transaction(client=client, transaction_type="Reserved Consumption", points=30, idempotency_key=f"cons-{suffix}")
		self.assertEqual(debit.points, 30)

		# Step 5: Statement reconciles balances
		stmt = wallet_statement.generate_wallet_statement_data(client_id=client)
		self.assertEqual(stmt["current_balance"], 170.0)
		self.assertEqual(stmt["total_purchased"], 200.0)
		self.assertEqual(stmt["total_consumed"], 30.0)

	def test_scenario_c_workflow_failure_and_recovery(self):
		"""Scenario C: Workflow Failure & Recovery (SRS Section 21.3)."""
		# Test AI Gateway Kill Switch and fallback
		ai_gateway.set_ai_kill_switch("provider", "FaultyProvider", True)
		with self.assertRaises(frappe.PermissionError):
			ai_gateway.invoke_ai_gateway(
				use_case="Legal Research",
				prompt_text="Test prompt for faulty provider",
				provider="FaultyProvider",
			)
		ai_gateway.set_ai_kill_switch("provider", "FaultyProvider", False)
