from __future__ import annotations

import hashlib
from pathlib import Path

import frappe
from frappe.client import get as get_client_document
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime
from frappe.utils.file_manager import save_file
from werkzeug.exceptions import Forbidden

from lex import client_portal, persona_workspaces, portal_management, work_intake
from lex.audit_worm_chain import verify_audit_trail_integrity
from lex.client_access import get_linked_client_ids, has_matter_access, require_client_administrator
from lex.lex.doctype.lexocrates_wallet_transaction.lexocrates_wallet_transaction import (
	_post_transaction,
	reverse_transaction,
)
from lex.portal_audit import create_portal_audit_event
from lex.pdf_watermark import _resolve_downloadable_file
from lex.file_quarantine import release_internally_generated_file


STRONG_TEST_PASSWORD = "Correct-Harbor-Legal-Portal-2026!"


class TestClientPortalArchitecture(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		persona_workspaces.ensure_persona_roles()
		self.previous_in_test = getattr(frappe.flags, "in_test", False)
		frappe.flags.in_test = True

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.in_test = self.previous_in_test

	def test_active_client_schema_and_website_roles_are_installed(self):
		for doctype in (
			"Lexocrates Portal User",
			"Lexocrates Client Department",
			"Lexocrates Matter Authorization",
			"Lexocrates Portal Invitation",
			"Lexocrates Client Registration",
			"Lexocrates Client Wallet",
			"Lexocrates Wallet Transaction",
			"Lexocrates Portal Audit Event",
			"LPO Matter",
			"LPO Job",
		):
			self.assertTrue(frappe.db.exists("DocType", doctype), doctype)
		for role in (
			"Lexocrates Client",
			"Lexocrates Client Administrator",
			"Lexocrates Partner General Counsel",
			"Lexocrates Legal User",
			"Lexocrates Operations User",
			"Lexocrates Finance User",
			"Lexocrates Procurement User",
			"Lexocrates Compliance User",
			"Lexocrates Read Only User",
		):
			self.assertTrue(frappe.db.exists("Role", role), role)
			self.assertFalse(frappe.db.get_value("Role", role, "desk_access"), role)

	def test_client_portal_is_light_only_and_has_mobile_breakpoints(self):
		app_path = Path(frappe.get_app_path("lex"))
		template = (app_path / "www" / "client-portal.html").read_text(encoding="utf-8")
		script = (app_path / "public" / "js" / "client_portal.js").read_text(encoding="utf-8")
		styles = (app_path / "public" / "css" / "client_portal.css").read_text(encoding="utf-8")

		self.assertIn('setAttribute("data-theme", "light")', template)
		self.assertIn('setAttribute("data-theme", "light")', script)
		self.assertIn('localStorage.removeItem("lexocrates-portal-theme")', template)
		self.assertNotIn("data-theme-toggle", script)
		self.assertNotIn("prefers-color-scheme: dark", styles)
		self.assertNotIn('data-theme="dark"', styles)
		self.assertIn("@media (max-width: 640px)", styles)
		self.assertIn("@media (max-width: 480px)", styles)
		self.assertIn("100dvh", styles)

	def test_compliance_approved_registration_creates_company_admin_and_wallet(self):
		country = frappe.db.get_value("Country", {}, "name")
		suffix = frappe.generate_hash(length=8).lower()
		email = f"registration-{suffix}@example.invalid"
		request = portal_management.request_client_registration(
			organization_name=f"Registration Organization {suffix}",
			organization_type="Law Firm",
			country=country,
			primary_user_name="Registration Administrator",
			designation="Managing Partner",
			email=email,
			billing_currency=frappe.db.get_default("currency") or "INR",
		)
		frappe.set_user("Guest")
		verified = portal_management.verify_client_registration(request["test_token"])
		self.assertTrue(verified["pending_compliance_review"])
		self.assertFalse(frappe.db.exists("User", email))
		frappe.set_user("Administrator")
		approved = portal_management.record_registration_compliance(
			verified["registration"], "Passed", "Passed", "Passed", "Approved", "Checks completed"
		)
		frappe.set_user("Guest")
		result = portal_management.activate_approved_registration(
			approved["test_activation_token"], STRONG_TEST_PASSWORD
		)
		client = frappe.get_doc("Customer", result["client"])
		portal_user = frappe.get_doc("Lexocrates Portal User", result["portal_user"])
		user = frappe.get_doc("User", email)
		self.assertEqual(client.customer_type, "Company")
		self.assertEqual(portal_user.client, client.name)
		self.assertEqual(portal_user.portal_role, "Client Administrator")
		self.assertEqual(user.user_type, "Website User")
		self.assertEqual(result["redirect"], "/client-portal")
		self.assertTrue(frappe.db.exists("Lexocrates Client Wallet", {"client": client.name}))
		with self.assertRaises(frappe.PermissionError):
			portal_management.activate_approved_registration(approved["test_activation_token"], STRONG_TEST_PASSWORD)

	def test_client_administrator_invites_user_to_same_client(self):
		client = _make_client()
		admin_user = _make_user()
		_make_portal_user(admin_user.name, client, "Client Administrator")
		frappe.set_user(admin_user.name)
		invitee_email = f"invitee-{frappe.generate_hash(length=8).lower()}@example.invalid"
		invitation = portal_management.invite_portal_user(
			invitee_name="Finance Invitee",
			invitee_email=invitee_email,
			portal_role="Finance User",
			designation="Accounts Manager",
		)
		frappe.set_user("Guest")
		accepted = portal_management.accept_portal_invitation(
			invitation["test_token"], STRONG_TEST_PASSWORD
		)
		invitee = frappe.get_doc("Lexocrates Portal User", accepted["portal_user"])
		self.assertEqual(invitee.client, client)
		self.assertEqual(invitee.portal_role, "Finance User")
		self.assertEqual(invitee.matter_access_scope, "No Matter Access")
		self.assertTrue(invitee.billing_access)
		self.assertTrue(invitee.lexpack_view_access)
		self.assertFalse(invitee.can_upload_documents)

	def test_portal_starts_scoped_intake_before_matter_and_job(self):
		client = _make_client()
		user = _make_user()
		_make_portal_user(user.name, client, "Client Administrator")
		frappe.set_user(user.name)
		result = work_intake.create_work_intake(
			intake_title="Workspace Matter",
			service_type="Legal Research",
			jurisdiction="India",
			priority="Medium",
			expected_outcome="Prepare a cited research note.",
			preliminary_details="Research the requested issue.",
		)
		intake = frappe.get_doc("Lexocrates Work Intake", result["name"])
		self.assertEqual(intake.client, client)
		self.assertEqual(intake.status, "SLA Pending")
		self.assertFalse(intake.matter)
		self.assertFalse(intake.job)

	def test_matter_access_and_cross_client_isolation(self):
		client_a = _make_client()
		client_b = _make_client()
		user_a = _make_user()
		user_b = _make_user()
		portal_a = _make_portal_user(user_a.name, client_a, "Legal User")
		_make_portal_user(user_b.name, client_b, "Legal User")
		matter_a = _make_matter(client_a)
		matter_b = _make_matter(client_b)
		matter_a.append("authorized_portal_users", _authorization(portal_a))
		matter_a.save(ignore_permissions=True)

		self.assertTrue(has_matter_access(matter_a.name, "view", user_a.name))
		self.assertFalse(has_matter_access(matter_b.name, "view", user_a.name))
		frappe.set_user(user_a.name)
		self.assertEqual(get_linked_client_ids(), (client_a,))
		visible = set(frappe.get_list("LPO Matter", pluck="name"))
		self.assertIn(matter_a.name, visible)
		self.assertNotIn(matter_b.name, visible)

	def test_wallet_ledger_is_idempotent_and_immutable(self):
		client = _make_client()
		key = f"purchase-{frappe.generate_hash(length=10)}"
		purchase = _post_transaction(
			client=client, transaction_type="Purchase", points=100, idempotency_key=key
		)
		duplicate = _post_transaction(
			client=client, transaction_type="Purchase", points=100, idempotency_key=key
		)
		_post_transaction(client=client, transaction_type="Reservation", points=40)
		_post_transaction(client=client, transaction_type="Reserved Consumption", points=15)
		_post_transaction(client=client, transaction_type="Release", points=25)
		wallet = frappe.get_doc(
			"Lexocrates Client Wallet",
			frappe.db.get_value("Lexocrates Client Wallet", {"client": client}, "name"),
		)
		self.assertEqual(purchase.name, duplicate.name)
		self.assertEqual(wallet.current_balance, 85)
		self.assertEqual(wallet.reserved_balance, 0)
		self.assertEqual(wallet.total_purchased, 100)
		self.assertEqual(wallet.total_consumed, 15)
		credit = _post_transaction(client=client, transaction_type="Adjustment Credit", points=10)
		reversal = reverse_transaction(credit.name, "Correction reversed", f"reverse-{key}")
		wallet.reload()
		self.assertEqual(reversal["reversal_of"], credit.name)
		self.assertEqual(wallet.total_purchased, 100)
		self.assertEqual(wallet.current_balance, 85)
		with self.assertRaises(frappe.ValidationError):
			reverse_transaction(credit.name, "Second reversal", f"reverse-duplicate-{key}")
		purchase.points = 99
		with self.assertRaises(frappe.PermissionError):
			purchase.save(ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError):
			purchase.delete(ignore_permissions=True)

	def test_deactivation_disables_login_and_preserves_audit(self):
		client = _make_client()
		first_user = _make_user()
		second_user = _make_user()
		_make_portal_user(first_user.name, client, "Client Administrator")
		second = _make_portal_user(second_user.name, client, "Legal User")
		frappe.set_user(first_user.name)
		portal_management.deactivate_portal_user(second.name, "No longer employed")
		self.assertFalse(frappe.db.get_value("User", second_user.name, "enabled"))
		self.assertEqual(
			frappe.db.get_value("Lexocrates Portal User", second.name, "account_status"),
			"Disabled",
		)
		self.assertTrue(
			frappe.db.exists("Lexocrates Portal Audit Event", {"portal_user": second.name})
		)

	def test_timed_lock_and_delegated_administration(self):
		client = _make_client()
		admin_user = _make_user()
		delegate_user = _make_user()
		_make_portal_user(admin_user.name, client, "Client Administrator")
		delegate = _make_portal_user(delegate_user.name, client, "Legal User")
		frappe.set_user(admin_user.name)
		portal_management.grant_temporary_client_administrator(
			delegate.name, add_days(now_datetime(), 1), "Vacation coverage"
		)
		frappe.set_user(delegate_user.name)
		self.assertEqual(require_client_administrator().name, delegate.name)
		frappe.set_user(admin_user.name)
		portal_management.deactivate_portal_user(
			delegate.name, "Repeated failed authentication", "Locked", add_days(now_datetime(), 1)
		)
		self.assertFalse(frappe.db.get_value("User", delegate_user.name, "enabled"))
		self.assertEqual(frappe.db.get_value("Lexocrates Portal User", delegate.name, "account_status"), "Locked")

	def test_audit_hash_chain_detects_tampering(self):
		client = _make_client()
		event = create_portal_audit_event(
			client=client,
			action="Compliance Hash Test",
			object_type="Customer",
			object_id=client,
			new_value={"control": "passed"},
		)
		self.assertTrue(verify_audit_trail_integrity(client)["verified"])
		frappe.db.set_value(
			"Lexocrates Portal Audit Event", event.name, "details", "tampered", update_modified=False
		)
		result = verify_audit_trail_integrity(client)
		self.assertFalse(result["verified"])
		self.assertIn(event.name, result["tampered_events"])

	def test_portal_navigation_is_capability_scoped(self):
		client = _make_client()
		finance_user = _make_user()
		legal_user = _make_user()
		_make_portal_user(finance_user.name, client, "Finance User")
		_make_portal_user(legal_user.name, client, "Legal User")
		frappe.set_user(finance_user.name)
		finance_navigation = {
			item["label"] for item in client_portal.get_portal_dashboard()["navigation"]
		}
		self.assertIn("Billing", finance_navigation)
		self.assertIn("LexPack", finance_navigation)
		self.assertNotIn("My Matters", finance_navigation)
		frappe.set_user(legal_user.name)
		legal_navigation = {
			item["label"] for item in client_portal.get_portal_dashboard()["navigation"]
		}
		self.assertIn("My Matters", legal_navigation)
		self.assertIn("Documents", legal_navigation)
		self.assertNotIn("Billing", legal_navigation)

	def test_final_job_document_unlocks_only_after_completion(self):
		client = _make_client()
		user = _make_user()
		portal_user = _make_portal_user(user.name, client, "Legal User")
		matter = _make_matter(client)
		matter.append("authorized_portal_users", _authorization(portal_user))
		matter.save(ignore_permissions=True)
		job = frappe.get_doc({
			"doctype": "LPO Job",
			"job_title": "Completion-gated delivery",
			"engagement": matter.name,
			"job_type": "Contract Review",
			"job_status": "Activated",
			"priority": "Medium",
			"task_description": "Prepare the final reviewed agreement.",
			"received_at": now_datetime(),
			"due_date": add_days(now_datetime(), 2),
		}).insert(ignore_permissions=True)
		file_doc = save_file(
			fname="completed-deliverable.txt",
			content=b"Final completion-gated legal deliverable.",
			dt="LPO Job",
			dn=job.name,
			is_private=1,
		)
		frappe.db.set_value(
			"LPO Job", job.name,
			{
				"delivery_document": file_doc.file_url,
				"job_status": "Activated",
				"ai_processing_allowed": 1,
				"ai_token_budget": 777,
				"ai_tokens_used": 123,
				"ai_instructions": "INTERNAL AI INSTRUCTION",
				"ai_review_status": "Passed",
				"ai_review_summary": "INTERNAL AI REVIEW SUMMARY",
			},
			update_modified=False,
		)

		frappe.set_user(user.name)
		with self.assertRaises(Forbidden):
			_resolve_downloadable_file(file_id=file_doc.name)
		portal_job = get_client_document("LPO Job", job.name)
		self.assertNotEqual(portal_job.get("ai_token_budget"), 777)
		self.assertNotEqual(portal_job.get("ai_tokens_used"), 123)
		self.assertNotEqual(portal_job.get("ai_instructions"), "INTERNAL AI INSTRUCTION")
		self.assertNotEqual(portal_job.get("ai_review_status"), "Passed")
		self.assertNotEqual(portal_job.get("ai_review_summary"), "INTERNAL AI REVIEW SUMMARY")
		before = next(row for row in client_portal.get_portal_dashboard()["jobs"] if row.name == job.name)
		self.assertFalse(before.delivery_download_url)

		frappe.set_user("Administrator")
		frappe.db.set_value("LPO Job", job.name, "job_status", "Completed", update_modified=False)
		frappe.set_user(user.name)
		self.assertEqual(_resolve_downloadable_file(file_id=file_doc.name).name, file_doc.name)
		after = next(row for row in client_portal.get_portal_dashboard()["jobs"] if row.name == job.name)
		self.assertTrue(after.delivery_download_url)
		deliverable = next(
			row for row in client_portal.get_portal_dashboard()["documents"] if row.name == file_doc.name
		)
		self.assertEqual(deliverable.portal_document_type, "Completed Deliverable")

	def test_authorized_client_previews_then_approves_delivery(self):
		client = _make_client()
		user = _make_user()
		portal_user = _make_portal_user(user.name, client, "Partner / General Counsel")
		matter = _make_matter(client)
		matter.append("authorized_portal_users", _authorization(portal_user))
		matter.save(ignore_permissions=True)
		job = frappe.get_doc({
			"doctype": "LPO Job",
			"job_title": "Client preview approval",
			"engagement": matter.name,
			"job_type": "Contract Review",
			"job_status": "Activated",
			"assigned_analyst": "Administrator",
			"qa_required": 0,
			"priority": "Medium",
			"task_description": "Client reviews the protected final output.",
			"received_at": now_datetime(),
			"due_date": add_days(now_datetime(), 2),
		}).insert(ignore_permissions=True)
		content = b"Protected client-preview legal deliverable."
		file_doc = save_file(
			fname="client-preview-deliverable.txt",
			content=content,
			dt="LPO Job",
			dn=job.name,
			is_private=1,
		)
		release_internally_generated_file(
			file_doc.name,
			expected_checksum=hashlib.sha256(content).hexdigest(),
		)
		frappe.db.set_value(
			"LPO Job",
			job.name,
			{
				"delivery_document": file_doc.file_url,
				"job_status": "Ready for Delivery",
				"client_approval_status": "Pending",
			},
			update_modified=False,
		)

		frappe.set_user(user.name)
		row = next(item for item in client_portal.get_portal_dashboard()["jobs"] if item.name == job.name)
		self.assertTrue(row.delivery_preview_url)
		self.assertFalse(row.delivery_download_url)
		self.assertEqual(_resolve_downloadable_file(file_id=file_doc.name).name, file_doc.name)

		result = client_portal.submit_client_approval(job.name, "Approved", "Approved for delivery.")
		self.assertEqual(result["job_status"], "Completed")
		row = next(item for item in client_portal.get_portal_dashboard()["jobs"] if item.name == job.name)
		self.assertTrue(row.delivery_download_url)


def _make_client() -> str:
	suffix = frappe.generate_hash(length=10).lower()
	return frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": f"Portal Architecture {suffix}",
			"customer_type": "Company",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
		}
	).insert(ignore_permissions=True).name


def _make_user():
	email = f"portal-{frappe.generate_hash(length=12).lower()}@example.invalid"
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": "Portal",
			"last_name": "User",
			"enabled": 1,
			"user_type": "Website User",
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True)


def _make_portal_user(user: str, client: str, portal_role: str, scope="Assigned Matters"):
	return frappe.get_doc(
		{
			"doctype": "Lexocrates Portal User",
			"user": user,
			"client": client,
			"portal_role": portal_role,
			"account_status": "Active",
			"matter_access_scope": scope,
		}
	).insert(ignore_permissions=True)


def _make_matter(client: str):
	return frappe.get_doc(
		{
			"doctype": "LPO Matter",
			"matter_title": f"Matter {frappe.generate_hash(length=8)}",
			"customer": client,
			"status": "Active",
			"matter_model": "Project",
			"matter_manager": "Administrator",
			"billing_method": "Quoted Price",
			"quoted_amount": 1000,
			"quote_status": "Approved",
			"practice_area": "Legal Research",
			"jurisdictions": "India",
			"start_date": frappe.utils.nowdate(),
			"end_date": add_days(frappe.utils.nowdate(), 30),
			"standard_turnaround_hours": 24,
			"sla_warning_hours": 4,
			"confidentiality_level": "Confidential",
		}
	).insert(ignore_permissions=True)


def _authorization(portal_user):
	return {
		"portal_user": portal_user.name,
		"can_view": 1,
		"can_upload": int(bool(portal_user.can_upload_documents)),
		"can_comment": int(bool(portal_user.can_comment)),
		"can_approve": int(portal_user.approval_authority not in {None, "", "None"}),
		"can_view_billing": int(bool(portal_user.billing_access)),
	}
