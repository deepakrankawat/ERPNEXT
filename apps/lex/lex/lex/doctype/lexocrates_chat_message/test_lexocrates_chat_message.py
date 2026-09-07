from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message import (
	_normalize_attachments,
	_send_mention_notification,
	create_system_message,
	edit_message,
	extract_mentions,
	get_pinned_messages,
	get_thread,
	get_messages,
	get_message_states,
	mark_channel_read,
	publish_typing,
	set_channel_preferences,
	set_message_pinned,
	send_message,
	search_messages,
	sync_messages,
	toggle_reaction,
)
from lex.patches.privatize_chat_attachments import _privatize_attachment


class TestLexocratesChatMessage(FrappeTestCase):
	def setUp(self):
		self._remove_test_channel()
		self.channel = frappe.get_doc(
			{
				"doctype": "Lexocrates Chat Channel",
				"channel_name": "#test-native-chat",
				"channel_type": "Public",
				"status": "Active",
				"description": "Automated test channel",
				"members": [
					{
						"user": "Administrator",
						"channel_role": "Owner",
						"can_post_messages": 1,
						"can_invite_members": 1,
					}
				],
			}
		).insert()

	def tearDown(self):
		self._remove_test_channel()

	def _remove_test_channel(self):
		channel = frappe.db.get_value(
			"Lexocrates Chat Channel", {"channel_name": "#test-native-chat"}, "name"
		)
		if not channel:
			return
		message_names = frappe.get_all(
			"Lexocrates Chat Message", filters={"channel": channel}, pluck="name"
		)
		if message_names:
			frappe.db.delete("Lexocrates Chat Reaction", {"message": ["in", message_names]})
		frappe.db.delete("Lexocrates Chat User State", {"channel": channel})
		frappe.db.delete("Lexocrates Chat Message", {"channel": channel})
		frappe.db.delete(
			"Lexocrates Chat Member",
			{"parent": channel, "parenttype": "Lexocrates Chat Channel"},
		)
		frappe.db.delete("Lexocrates Chat Channel", {"name": channel})

	def test_server_controls_sender_sanitizes_content_and_extracts_mentions(self):
		message = frappe.get_doc(
			{
				"doctype": "Lexocrates Chat Message",
				"channel": self.channel.name,
				"sender": "Guest",
				"system_generated": 1,
				"message_text": '<script>alert(1)</script><p onclick="bad()">Hello @Administrator</p>',
			}
		).insert()

		self.assertEqual(message.sender, "Administrator")
		self.assertFalse(message.system_generated)
		self.assertNotIn("<script", message.message_text)
		self.assertNotIn("onclick", message.message_text)
		self.assertEqual(frappe.parse_json(message.mentions), ["Administrator"])

	def test_global_message_search_requires_an_authorized_channel(self):
		with self.assertRaises(frappe.MandatoryError):
			search_messages("%%")

	def test_mentions_exclude_users_without_channel_access(self):
		channel = frappe._dict({"name": "LCC-PRIVATE"})
		users = [
			frappe._dict({"name": "allowed@example.invalid", "username": "allowed"}),
			frappe._dict({"name": "blocked@example.invalid", "username": "blocked"}),
		]
		with (
			patch("frappe.get_all", return_value=users),
			patch(
				"lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message.can_view_channel",
				side_effect=lambda _channel, user=None: user == "allowed@example.invalid",
			),
		):
			mentions = extract_mentions(
				"@allowed@example.invalid @blocked@example.invalid", channel
			)

		self.assertEqual(mentions, ["allowed@example.invalid"])

	def test_chat_attachments_must_be_private(self):
		with self.assertRaises(frappe.ValidationError):
			_normalize_attachments(["/files/public-evidence.pdf"])

		file_row = frappe._dict({"name": "FILE-PRIVATE", "owner": "Administrator"})
		with patch("frappe.db.get_value", return_value=file_row):
			self.assertEqual(
				_normalize_attachments(["/private/files/private-evidence.pdf"]),
				["/private/files/private-evidence.pdf"],
			)

	def test_legacy_public_attachment_migration_preserves_the_json_field(self):
		file_doc = frappe._dict(
			{
				"name": "FILE-PUBLIC",
				"file_url": "/files/evidence.pdf",
				"attached_to_field": "attachments",
			}
		)

		def save_file(**_kwargs):
			self.assertIsNone(file_doc.attached_to_field)
			file_doc.file_url = "/private/files/evidence.pdf"

		file_doc.save = MagicMock(side_effect=save_file)
		with (
			patch("frappe.db.get_value", return_value="FILE-PUBLIC"),
			patch("frappe.get_doc", return_value=file_doc),
			patch("frappe.db.set_value") as set_value,
		):
			private_url = _privatize_attachment(
				"LCM-LEGACY", "/files/evidence.pdf", {}
			)

		self.assertEqual(private_url, "/private/files/evidence.pdf")
		file_doc.save.assert_called_once_with(ignore_permissions=True)
		set_value.assert_called_once_with(
			"File",
			"FILE-PUBLIC",
			"attached_to_field",
			"attachments",
			update_modified=False,
		)

	def test_mention_notification_uses_the_channel_name(self):
		notification = MagicMock()
		notification.flags = frappe._dict()
		message = frappe._dict(
			{
				"channel": "LCC-PRIVATE",
				"sender": "sender@example.invalid",
				"name": "LCM-PRIVATE",
				"message_text": "Privileged update",
			}
		)
		with (
			patch("frappe.db.exists", return_value=True),
			patch(
				"frappe.get_cached_doc",
				return_value=frappe._dict({"channel_name": "#private-case"}),
			),
			patch("frappe.db.get_value", return_value="Sender Name"),
			patch("frappe.get_doc", return_value=notification) as get_doc,
		):
			_send_mention_notification(message, "recipient@example.invalid")

		payload = get_doc.call_args.args[0]
		self.assertEqual(payload["subject"], "Sender Name mentioned you in #private-case")
		notification.insert.assert_called_once_with(ignore_permissions=True)

	def test_threaded_replies_and_history(self):
		root = send_message(self.channel.name, "Root instruction")
		reply = send_message(
			self.channel.name,
			"Reply with evidence",
			thread_reference=root["name"],
		)
		history = get_messages(self.channel.name)

		self.assertEqual(reply["thread_reference"], root["name"])
		self.assertEqual([row["name"] for row in history], [root["name"], reply["name"]])
		self.assertEqual(root["sender_full_name"], "Administrator")
		self.assertEqual(root["sender_role"], "Administrator")
		self.assertIn("sender_roles", root)

	def test_realtime_event_is_channel_scoped_and_after_commit(self):
		with patch("frappe.publish_realtime") as publish:
			message = send_message(self.channel.name, "Committed message")

		calls = [call for call in publish.call_args_list if call.args[0] == "new_chat_message"]
		self.assertEqual(len(calls), 1)
		args, kwargs = calls[0]
		self.assertEqual(args[1]["name"], message["name"])
		self.assertEqual(
			kwargs["room"], f"doc:Lexocrates Chat Channel/{self.channel.name}"
		)
		self.assertTrue(kwargs["after_commit"])
		self.assertEqual(args[1]["protocol_version"], 1)
		self.assertGreater(args[1]["channel_sequence"], 0)
		self.assertTrue(args[1]["event_id"].startswith("chat-message:"))

	def test_idempotent_retry_returns_one_committed_message(self):
		client_message_id = "test:retry:00000001"
		first = send_message(
			self.channel.name,
			"Network retry test",
			client_message_id=client_message_id,
		)
		second = send_message(
			self.channel.name,
			"Network retry test",
			client_message_id=client_message_id,
		)
		self.assertEqual(first["name"], second["name"])
		self.assertEqual(first["channel_sequence"], second["channel_sequence"])
		self.assertEqual(
			frappe.db.count(
				"Lexocrates Chat Message", {"client_message_id": client_message_id}
			),
			1,
		)

	def test_sequence_gap_recovery_is_ordered_and_paginated(self):
		first = send_message(self.channel.name, "Sequence one", client_message_id="test:sequence:0001")
		second = send_message(self.channel.name, "Sequence two", client_message_id="test:sequence:0002")
		third = send_message(self.channel.name, "Sequence three", client_message_id="test:sequence:0003")

		page = sync_messages(self.channel.name, after_sequence=first["channel_sequence"], limit=1)
		self.assertEqual([row["name"] for row in page["messages"]], [second["name"]])
		self.assertTrue(page["has_more"])
		self.assertEqual(page["next_sequence"], second["channel_sequence"])
		remaining = sync_messages(
			self.channel.name, after_sequence=page["next_sequence"], limit=10
		)
		self.assertEqual([row["name"] for row in remaining["messages"]], [third["name"]])
		self.assertEqual(remaining["high_watermark"], third["channel_sequence"])
		older = get_messages(
			self.channel.name, before_sequence=third["channel_sequence"], limit=10
		)
		self.assertEqual([row["name"] for row in older], [first["name"], second["name"]])

	def test_loaded_message_states_can_be_reconciled_after_reconnect(self):
		first = send_message(self.channel.name, "Original state")
		second = send_message(self.channel.name, "Unchanged state")
		edit_message(first["name"], "Updated while disconnected")

		states = get_message_states(
			self.channel.name,
			[first["name"], second["name"], "LCM-NOT-IN-CHANNEL"],
		)
		self.assertEqual([row["name"] for row in states], [first["name"], second["name"]])
		self.assertIn("Updated while disconnected", states[0]["message_text"])
		self.assertTrue(states[0]["edited_on"])

	def test_stale_read_marker_is_ignored_without_advancing_the_channel(self):
		with (
			patch("frappe.has_permission", return_value=True),
			patch(
				"frappe.db.get_value",
				return_value=frappe._dict(
					{"channel": "LCC-OTHER", "sent_at": "2026-09-06", "channel_sequence": 99}
				),
			),
		):
			result = mark_channel_read(self.channel.name, "LCM-FROM-OTHER-CHANNEL")

		self.assertTrue(result["ignored"])
		self.assertEqual(result["channel"], self.channel.name)
		self.assertEqual(result["reason"], "stale_message_marker")

	def test_edit_window_and_physical_delete_protection(self):
		message = send_message(self.channel.name, "Original")
		edited = edit_message(message["name"], "Corrected")
		self.assertIn("Corrected", edited["message_text"])

		frappe.db.set_value(
			"Lexocrates Chat Message",
			message["name"],
			"sent_at",
			"2000-01-01 00:00:00",
			update_modified=False,
		)
		with self.assertRaises(frappe.PermissionError):
			edit_message(message["name"], "Too late")
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc(
				"Lexocrates Chat Message", message["name"], ignore_permissions=True
			)

	def test_system_messages_cannot_be_spoofed_or_edited(self):
		message = create_system_message(
			self.channel.name,
			"Automated QA alert",
			automation_key=f"test-system:{self.channel.name}",
		)
		self.assertTrue(message["system_generated"])
		with self.assertRaises(frappe.PermissionError):
			edit_message(message["name"], "Altered alert")

	def test_reactions_are_toggleable_and_realtime(self):
		message = send_message(self.channel.name, "Review this point")
		with patch("frappe.publish_realtime") as publish:
			result = toggle_reaction(message["name"], "✅")
		self.assertTrue(result["active"])
		self.assertEqual(result["reactions"][0]["count"], 1)
		calls = [call for call in publish.call_args_list if call.args[0] == "chat_reaction_changed"]
		self.assertEqual(len(calls), 1)
		self.assertTrue(calls[0].kwargs["after_commit"])
		result = toggle_reaction(message["name"], "✅")
		self.assertFalse(result["active"])
		self.assertEqual(result["reactions"], [])

	def test_read_state_preferences_and_receipts(self):
		message = send_message(self.channel.name, "Read-state test")
		with patch("frappe.publish_realtime") as publish:
			state = mark_channel_read(self.channel.name, message["name"])
		self.assertEqual(state["last_read_message"], message["name"])
		self.assertTrue(
			frappe.db.exists(
				"Lexocrates Chat User State",
				{"channel": self.channel.name, "user": "Administrator"},
			)
		)
		self.assertTrue(any(call.args[0] == "chat_read_receipt" for call in publish.call_args_list))
		preference = set_channel_preferences(self.channel.name, "Mentions Only")
		self.assertEqual(preference["notification_level"], "Mentions Only")
		muted = set_channel_preferences(self.channel.name, "Muted")
		self.assertEqual(muted["notification_level"], "Muted")
		self.assertTrue(muted["muted"])
		self.assertEqual(
			frappe.db.get_value(
				"Lexocrates Chat User State",
				{"channel": self.channel.name, "user": "Administrator"},
				["notification_level", "muted"],
				as_dict=True,
			),
			{"notification_level": "Muted", "muted": 1},
		)

	def test_read_sequence_cannot_move_backwards(self):
		first = send_message(self.channel.name, "Read first", client_message_id="test:read:00000001")
		second = send_message(self.channel.name, "Read second", client_message_id="test:read:00000002")
		latest = mark_channel_read(self.channel.name, second["name"])
		stale = mark_channel_read(self.channel.name, first["name"])
		self.assertEqual(stale["last_read_message"], second["name"])
		self.assertEqual(stale["last_read_sequence"], latest["last_read_sequence"])

	def test_pins_and_thread_details(self):
		root = send_message(self.channel.name, "Pinned root")
		send_message(self.channel.name, "Thread reply", thread_reference=root["name"])
		thread = get_thread(root["name"])
		self.assertEqual(thread["root"], root["name"])
		self.assertEqual(len(thread["messages"]), 2)
		pinned = set_message_pinned(root["name"], 1)
		self.assertTrue(pinned["is_pinned"])
		self.assertEqual(get_pinned_messages(self.channel.name)[0]["name"], root["name"])
		self.assertFalse(set_message_pinned(root["name"], 0)["is_pinned"])

	def test_thread_replies_are_paginated_from_the_latest(self):
		root = send_message(self.channel.name, "Thread root")
		replies = [
			send_message(self.channel.name, f"Reply {index}", thread_reference=root["name"])
			for index in range(1, 4)
		]

		latest = get_thread(root["name"], limit=2)
		self.assertEqual(
			[row["name"] for row in latest["messages"]],
			[root["name"], replies[1]["name"], replies[2]["name"]],
		)
		self.assertTrue(latest["has_more"])
		self.assertEqual(latest["oldest_sequence"], replies[1]["channel_sequence"])

		older = get_thread(
			root["name"],
			before_sequence=latest["oldest_sequence"],
			limit=2,
		)
		self.assertEqual([row["name"] for row in older["messages"]], [replies[0]["name"]])
		self.assertFalse(older["has_more"])

	def test_typing_event_is_permission_scoped(self):
		with patch("frappe.publish_realtime") as publish:
			payload = publish_typing(self.channel.name, 1)
		self.assertTrue(payload["is_typing"])
		calls = [call for call in publish.call_args_list if call.args[0] == "chat_typing"]
		self.assertEqual(len(calls), 1)
		self.assertEqual(
			calls[0].kwargs["room"],
			f"doc:Lexocrates Chat Channel/{self.channel.name}",
		)
