from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from lex.lex.doctype.lpo_channel.lpo_channel import get_channel_history


class TestLPOMessage(FrappeTestCase):
	def setUp(self):
		self.channel_name = "_Test LPO Channel"
		frappe.db.delete("LPO Message", {"channel": self.channel_name})
		frappe.db.delete("LPO Channel", {"name": self.channel_name})

		# The communication app intentionally does not fabricate the operational
		# LPO Job schema. db_insert provides an isolated channel fixture here.
		frappe.get_doc(
			{
				"doctype": "LPO Channel",
				"name": self.channel_name,
				"channel_name": "Test channel",
				"reference_doctype": "LPO Job",
				"reference_name": "_Test LPO Job",
				"status": "Active",
			}
		).db_insert()

	def tearDown(self):
		frappe.db.delete("LPO Message", {"channel": self.channel_name})
		frappe.db.delete("LPO Channel", {"name": self.channel_name})

	def test_sender_content_and_timestamp_are_server_controlled(self):
		message = frappe.get_doc(
			{
				"doctype": "LPO Message",
				"channel": self.channel_name,
				"sender": "Guest",
				"timestamp": "2000-01-01 00:00:00",
				"content": '<script>alert(1)</script><p onclick="bad()">Verified</p>',
			}
		).insert()

		self.assertEqual(message.sender, "Administrator")
		self.assertNotIn("<script", message.content)
		self.assertNotIn("onclick", message.content)
		self.assertIn("Verified", message.content)
		self.assertNotEqual(str(message.timestamp), "2000-01-01 00:00:00")

	def test_messages_cannot_be_edited_or_deleted(self):
		message = frappe.get_doc(
			{
				"doctype": "LPO Message",
				"channel": self.channel_name,
				"content": "Original instruction",
			}
		).insert()

		message.content = "Altered instruction"
		with self.assertRaises(frappe.PermissionError):
			message.save(ignore_permissions=True)

		with self.assertRaises(frappe.PermissionError):
			message.delete(ignore_permissions=True)

	def test_history_is_chronological_and_contextual(self):
		first = frappe.get_doc(
			{"doctype": "LPO Message", "channel": self.channel_name, "content": "First"}
		).insert()
		second = frappe.get_doc(
			{"doctype": "LPO Message", "channel": self.channel_name, "content": "Second"}
		).insert()

		history = get_channel_history(self.channel_name)
		self.assertEqual([row["name"] for row in history], [first.name, second.name])
		self.assertTrue(all(row["channel"] == self.channel_name for row in history))

	def test_realtime_delivery_is_scoped_and_deferred_until_commit(self):
		with patch("frappe.publish_realtime") as publish:
			message = frappe.get_doc(
				{"doctype": "LPO Message", "channel": self.channel_name, "content": "Committed only"}
			).insert()

		message_events = [call for call in publish.call_args_list if call.args[0] == "new_lpo_message"]
		self.assertEqual(len(message_events), 1)
		args, kwargs = message_events[0]
		self.assertEqual(args[0], "new_lpo_message")
		self.assertEqual(args[1]["channel"], self.channel_name)
		self.assertEqual(args[1]["name"], message.name)
		self.assertEqual(kwargs["room"], f"doc:LPO Channel/{self.channel_name}")
		self.assertTrue(kwargs["after_commit"])
