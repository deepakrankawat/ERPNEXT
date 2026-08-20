from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message import (
	create_system_message,
	edit_message,
	get_pinned_messages,
	get_thread,
	get_messages,
	mark_channel_read,
	publish_typing,
	set_channel_preferences,
	set_message_pinned,
	send_message,
	toggle_reaction,
)


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
