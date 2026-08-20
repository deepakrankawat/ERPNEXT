from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from lex import persona_workspaces, portal_management, lexocrates_chat_sync
from lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel import (
	can_start_direct_message,
	can_post_to_channel,
	can_view_channel,
	get_or_create_direct_channel,
)
from lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message import (
	send_message,
)
from lex.lex.page.lexocrates_chat.lexocrates_chat import (
	get_or_create_contextual_channel,
	get_chat_bootstrap,
	search_users,
)


STRONG_TEST_PASSWORD = "Correct-Legal-Portal-Password-2026!"


class TestChatArchitectureScenarios(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		persona_workspaces.ensure_persona_roles()
		self.previous_in_test = getattr(frappe.flags, "in_test", False)
		frappe.flags.in_test = True

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.in_test = self.previous_in_test

	def test_1_idempotent_chat_room_provisioning(self):
		"""1. Test Idempotent Chat Room Provisioning."""
		client = _make_client("Idempotent Provisioning Client")
		matter = _make_matter(client, "Provisioning Test Matter")

		# Assert corresponding Lex Chat Room (Lexocrates Chat Channel) is automatically provisioned
		channels = frappe.get_all(
			"Lexocrates Chat Channel",
			filters={"reference_doctype": "LPO Matter", "reference_name": matter.name},
			pluck="name",
		)
		self.assertEqual(len(channels), 1, "Exactly one Chat Room should be provisioned on creation")
		channel_name = channels[0]

		# Save Matter again without state changes
		matter.matter_title = "Provisioning Test Matter Updated"
		matter.save(ignore_permissions=True)

		# Assert no duplicate Chat Rooms are created
		channels_after = frappe.get_all(
			"Lexocrates Chat Channel",
			filters={"reference_doctype": "LPO Matter", "reference_name": matter.name},
			pluck="name",
		)
		self.assertEqual(len(channels_after), 1, "Saving Matter again must not create duplicate Chat Rooms")
		self.assertEqual(channels_after[0], channel_name)
		self.assertTrue(
			frappe.db.get_value("Lexocrates Chat Channel", channel_name, "channel_name").startswith(
				"#provisioning-test-matter-updated-"
			)
		)

	def test_2_dynamic_permission_and_membership_sync_client_isolation(self):
		"""2. Test Dynamic Permission & Membership Sync (Client Isolation)."""
		# Setup Client A with User A1 and User A2
		client_a = _make_client("Client Organization A")
		user_a1_doc = _make_user("usera1")
		user_a2_doc = _make_user("usera2")
		portal_a1 = _make_portal_membership(user_a1_doc.name, client_a)
		portal_a2 = _make_portal_membership(user_a2_doc.name, client_a)

		# Setup Client B with User B1
		client_b = _make_client("Client Organization B")
		user_b1_doc = _make_user("userb1")
		portal_b1 = _make_portal_membership(user_b1_doc.name, client_b)

		# Create Lex Matter for Client A
		matter_a = _make_matter(client_a, "Client A Secret Matter")

		# Add explicit authorization for User A1 and User A2 on Client A's Matter
		matter_a.append("authorized_portal_users", _authorization(portal_a1))
		matter_a.append("authorized_portal_users", _authorization(portal_a2))
		matter_a.save(ignore_permissions=True)

		channel_name = frappe.db.get_value(
			"Lexocrates Chat Channel",
			{"reference_doctype": "LPO Matter", "reference_name": matter_a.name},
			"name",
		)
		self.assertTrue(channel_name, "Chat Channel must exist for Matter A")
		channel_doc = frappe.get_doc("Lexocrates Chat Channel", channel_name)

		# Test User A1 can view and post in Matter A Chat Room
		frappe.set_user(user_a1_doc.name)
		self.assertTrue(can_view_channel(channel_doc, user=user_a1_doc.name))
		msg_a1 = send_message(channel=channel_name, message_text="User A1 posting in Matter A Chat")
		self.assertEqual(msg_a1["sender"], user_a1_doc.name)

		# Test User A2 can view and post in Matter A Chat Room
		frappe.set_user(user_a2_doc.name)
		self.assertTrue(can_view_channel(channel_doc, user=user_a2_doc.name))

		# Negative Test: User B1 (from Client B) MUST get PermissionError / be completely blocked
		frappe.set_user(user_b1_doc.name)
		self.assertFalse(can_view_channel(channel_doc, user=user_b1_doc.name))
		self.assertFalse(can_post_to_channel(channel_doc, user=user_b1_doc.name))

		with self.assertRaises(frappe.PermissionError):
			send_message(channel=channel_name, message_text="User B1 unauthorized attempt")

		with self.assertRaises(frappe.PermissionError):
			frappe.has_permission("Lexocrates Chat Channel", "read", doc=channel_name, throw=True)

	def test_3_save_to_matter_timeline_invariant(self):
		"""3. Test 'Save to Matter Timeline' Invariant."""
		client = _make_client("Timeline Invariant Client")
		user_doc = _make_user("timelineuser")
		portal_user = _make_portal_membership(user_doc.name, client)

		matter = _make_matter(client, "Timeline Settlement Matter")

		matter.append("authorized_portal_users", _authorization(portal_user))
		matter.save(ignore_permissions=True)

		channel_name = frappe.db.get_value(
			"Lexocrates Chat Channel",
			{"reference_doctype": "LPO Matter", "reference_name": matter.name},
			"name",
		)

		frappe.set_user(user_doc.name)
		msg = send_message(channel=channel_name, message_text="Agreed to settlement terms of $50,000.")

		# Invoke custom whitelisted API endpoint
		res = lexocrates_chat_sync.save_decision_to_timeline(
			message_id=msg["name"],
			matter_id=matter.name,
			decision_notes="Approved by General Counsel",
		)

		self.assertEqual(res["status"], "pinned")
		self.assertEqual(res["audit_tag"], "Material Decision")
		self.assertEqual(res["author"], user_doc.name)
		self.assertEqual(res["message_text"], "Agreed to settlement terms of $50,000.")

		# Assert a new Lex Matter Timeline Event (Comment) is created
		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "LPO Matter", "reference_name": matter.name},
			fields=["content", "comment_by", "creation"],
		)
		self.assertTrue(len(comments) > 0, "Comment should be added to Lex Matter timeline")
		latest_comment = comments[0]["content"]

		# Verify saved event contains immutable metadata: original message text, author, timestamp, Material Decision tag
		self.assertIn("[Material Decision]", latest_comment)
		self.assertIn(user_doc.name, latest_comment)
		self.assertIn("Agreed to settlement terms of $50,000.", latest_comment)
		self.assertIn("Approved by General Counsel", latest_comment)

	def test_4_non_authoritative_chat_boundary(self):
		"""4. Test Non-Authoritative Chat Boundary."""
		client = _make_client("Boundary Test Client")
		user_doc = _make_user("boundaryuser")
		portal_user = _make_portal_membership(user_doc.name, client)

		matter = _make_matter(client, "Non-Authoritative Boundary Matter")

		matter.append("authorized_portal_users", _authorization(portal_user))
		matter.save(ignore_permissions=True)

		channel_name = frappe.db.get_value(
			"Lexocrates Chat Channel",
			{"reference_doctype": "LPO Matter", "reference_name": matter.name},
			"name",
		)

		frappe.set_user(user_doc.name)
		# User posts a message claiming status changed to Completed
		send_message(channel=channel_name, message_text="Status changed to Completed")

		# Assert that posting a chat message DOES NOT change the actual ERP Matter status
		matter.reload()
		self.assertEqual(
			matter.status,
			"Active",
			"Chat message must never manipulate ERP core Matter status directly",
		)

	def test_5_chat_room_archival_on_matter_closure(self):
		"""5. Test Chat Room Archival on Matter Closure."""
		client = _make_client("Closure Archival Client")
		user_doc = _make_user("closureuser")
		portal_user = _make_portal_membership(user_doc.name, client)

		matter = _make_matter(client, "Closure Test Matter")

		matter.append("authorized_portal_users", _authorization(portal_user))
		matter.save(ignore_permissions=True)

		channel_name = frappe.db.get_value(
			"Lexocrates Chat Channel",
			{"reference_doctype": "LPO Matter", "reference_name": matter.name},
			"name",
		)

		# Transition Lex Matter state to 'Completed'
		frappe.set_user("Administrator")
		matter.status = "Completed"
		matter.save(ignore_permissions=True)

		# Assert that corresponding Lex Chat Room status changes to 'Archived' (Read-Only)
		channel_status = frappe.db.get_value("Lexocrates Chat Channel", channel_name, "status")
		self.assertEqual(channel_status, "Archived", "Chat Room must be Archived when Matter is Completed")

		# An archived room is read-only, so posting is denied at the permission boundary.
		frappe.set_user(user_doc.name)
		with self.assertRaises(frappe.PermissionError):
			send_message(channel=channel_name, message_text="Attempting to post after closure")

	def test_6_only_system_users_can_start_direct_messages(self):
		staff = _make_system_user("directstaff")
		frappe.set_user("Administrator")
		channel = get_or_create_direct_channel(staff.name)
		self.assertTrue(channel["is_direct_message"])
		self.assertEqual(channel["channel_type"], "Private")

		frappe.set_user(staff.name)
		self.assertTrue(can_start_direct_message())
		self.assertTrue(get_chat_bootstrap()["can_start_direct_message"])
		self.assertIn("Administrator", {row.name for row in search_users()})

		website_user = _make_user("directclient")
		frappe.set_user(website_user.name)
		self.assertFalse(can_start_direct_message())
		self.assertFalse(get_chat_bootstrap()["can_start_direct_message"])
		with self.assertRaises(frappe.PermissionError):
			search_users()
		with self.assertRaises(frappe.PermissionError):
			get_or_create_direct_channel("Administrator")

	def test_7_jobs_use_matter_room_and_are_mentionable(self):
		client = _make_client("Matter Job Chat Client")
		matter = _make_matter(client, "Contract Review Command Room")
		channel_name = frappe.db.get_value(
			"Lexocrates Chat Channel",
			{"reference_doctype": "LPO Matter", "reference_name": matter.name},
			"name",
		)
		job = _make_lpo_job(matter.name)
		self.assertFalse(
			frappe.db.exists(
				"Lexocrates Chat Channel",
				{"reference_doctype": "LPO Job", "reference_name": job.name},
			),
			"A Job must not create a duplicate standalone room",
		)

		job_context = get_or_create_contextual_channel("LPO Job", job.name)
		self.assertEqual(job_context["name"], channel_name)
		self.assertEqual(job_context["reference_doctype"], "LPO Matter")

		message = send_message(
			channel=channel_name,
			message_text=f"Please prioritize @{job.name} for today's review.",
		)
		self.assertEqual([row["name"] for row in message["job_mentions"]], [job.name])

		job_events = frappe.get_all(
			"Lexocrates Chat Message",
			filters={"channel": channel_name, "source_doctype": "LPO Job", "source_name": job.name},
			fields=["name", "automation_key"],
		)
		self.assertEqual(len(job_events), 1, "Job creation must produce one Matter Room event")
		self.assertTrue(job_events[0].automation_key.startswith("lpo-job-created:"))

		job.priority = "High"
		job.save(ignore_permissions=True)
		job_events = frappe.get_all(
			"Lexocrates Chat Message",
			filters={"channel": channel_name, "source_doctype": "LPO Job", "source_name": job.name},
			pluck="automation_key",
		)
		self.assertEqual(len(job_events), 2)
		self.assertTrue(any(key.startswith("lpo-job-updated:") for key in job_events))


def _make_client(name_prefix: str) -> str:
	suffix = frappe.generate_hash(length=8).lower()
	return frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": f"{name_prefix} {suffix}",
			"customer_type": "Company",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
		}
	).insert(ignore_permissions=True).name


def _make_matter(client: str, title: str):
	return frappe.get_doc(
		{
			"doctype": "LPO Matter",
			"matter_title": title,
			"customer": client,
			"status": "Active",
			"matter_model": "Project",
			"matter_manager": "Administrator",
			"billing_method": "Quoted Price",
			"quoted_amount": 1000,
			"quote_status": "Approved",
			"practice_area": "Corporate & Commercial",
			"jurisdictions": "India",
			"start_date": frappe.utils.nowdate(),
			"end_date": add_days(frappe.utils.nowdate(), 30),
			"standard_turnaround_hours": 24,
			"sla_warning_hours": 4,
			"confidentiality_level": "Confidential",
		}
	).insert(ignore_permissions=True)


def _make_lpo_job(matter: str):
	return frappe.get_doc(
		{
			"doctype": "LPO Job",
			"job_title": "Contract risk review",
			"engagement": matter,
			"job_type": "Contract Review",
			"job_status": "Draft",
			"priority": "Medium",
			"task_description": "Review the agreement and identify material risks.",
			"received_at": now_datetime(),
			"due_date": add_days(now_datetime(), 1),
		}
	).insert(ignore_permissions=True)


def _make_user(prefix: str):
	suffix = frappe.generate_hash(length=8).lower()
	email = f"{prefix}-{suffix}@example.invalid"
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": prefix.capitalize(),
			"last_name": "User",
			"enabled": 1,
			"user_type": "Website User",
			"send_welcome_email": 0,
			"roles": [{"role": "Lexocrates Client"}],
		}
	).insert(ignore_permissions=True)


def _make_system_user(prefix: str):
	suffix = frappe.generate_hash(length=8).lower()
	email = f"{prefix}-{suffix}@example.invalid"
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": prefix.capitalize(),
			"last_name": "Staff",
			"enabled": 1,
			"user_type": "System User",
			"send_welcome_email": 0,
			"roles": [{"role": "LPO_Analyst"}],
		}
	).insert(ignore_permissions=True)


def _make_portal_membership(user: str, client: str, roles="Legal User", scope="Assigned Matters"):
	return frappe.get_doc(
		{
			"doctype": "Lexocrates Portal User",
			"user": user,
			"client": client,
			"portal_role": roles,
			"account_status": "Active",
			"matter_access_scope": scope,
			"can_upload_documents": 1,
			"can_comment": 1,
		}
	).insert(ignore_permissions=True)


def _authorization(portal_membership):
	return {
		"portal_user": portal_membership.name,
		"can_view": 1,
		"can_upload": 1,
		"can_comment": 1,
		"can_approve": 0,
		"can_view_billing": 0,
	}
