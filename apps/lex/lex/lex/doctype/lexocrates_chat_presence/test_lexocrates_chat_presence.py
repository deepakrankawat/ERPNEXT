from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from lex.lex.doctype.lexocrates_chat_presence.lexocrates_chat_presence import (
	LexocratesChatPresence,
	get_presence_snapshot,
	mark_stale_presences_offline,
	update_presence,
)


class TestLexocratesChatPresence(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.delete("Lexocrates Chat Presence", {"user": "Administrator"})

	def tearDown(self):
		frappe.db.delete("Lexocrates Chat Presence", {"user": "Administrator"})
		frappe.set_user("Administrator")

	def test_manual_and_automatic_presence_transitions(self):
		with patch("frappe.publish_realtime") as publish:
			online = update_presence("Online", is_active=1)
			away = update_presence(is_active=0)
			busy = update_presence("Busy", is_active=1)
			offline = update_presence(is_active=0, disconnect=1)
			busy_again = update_presence(is_active=1)

		self.assertEqual(online["status"], "Online")
		self.assertEqual(away["status"], "Away")
		self.assertEqual(away["preferred_status"], "Online")
		self.assertEqual(busy["status"], "Busy")
		self.assertEqual(offline["status"], "Offline")
		self.assertIsNotNone(offline["last_seen_at"])
		self.assertEqual(busy_again["status"], "Busy")
		self.assertTrue(
			any(call.args[0] == "chat_presence_changed" for call in publish.call_args_list)
		)

	def test_stale_heartbeat_becomes_offline_and_snapshot_has_last_seen(self):
		update_presence("Online", is_active=1)
		old_heartbeat = now_datetime() - timedelta(minutes=5)
		frappe.db.set_value(
			"Lexocrates Chat Presence",
			"Administrator",
			"last_heartbeat_at",
			old_heartbeat,
			update_modified=False,
		)
		with patch("frappe.publish_realtime"):
			mark_stale_presences_offline()

		row = frappe.db.get_value(
			"Lexocrates Chat Presence",
			"Administrator",
			["status", "last_seen_at"],
			as_dict=True,
		)
		self.assertEqual(row.status, "Offline")
		self.assertEqual(row.last_seen_at, old_heartbeat)
		snapshot = {item["user"]: item for item in get_presence_snapshot()}
		self.assertEqual(snapshot["Administrator"]["status"], "Offline")
		self.assertIsNotNone(snapshot["Administrator"]["last_seen_at"])

	def test_repeated_heartbeats_do_not_use_document_save_or_churn_modified(self):
		update_presence("Online", is_active=1)
		modified_before = frappe.db.get_value(
			"Lexocrates Chat Presence", "Administrator", "modified"
		)

		with patch.object(LexocratesChatPresence, "save") as document_save:
			first = update_presence(is_active=1)
			second = update_presence(is_active=1)

		document_save.assert_not_called()
		modified_after = frappe.db.get_value(
			"Lexocrates Chat Presence", "Administrator", "modified"
		)
		self.assertEqual(first["status"], "Online")
		self.assertEqual(second["status"], "Online")
		self.assertEqual(modified_before, modified_after)
