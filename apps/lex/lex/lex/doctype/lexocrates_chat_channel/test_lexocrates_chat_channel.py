from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel import (
	_channel_matches_search,
	_get_matter_context,
	get_or_create_direct_channel,
	get_user_chat_identity,
)


class TestLexocratesChatChannel(FrappeTestCase):
	def test_chat_identity_exposes_full_name_and_primary_role(self):
		identity = get_user_chat_identity("Administrator")
		self.assertEqual(identity["full_name"], "Administrator")
		self.assertEqual(identity["primary_role"], "Administrator")
		self.assertEqual(identity["user_type"], "System User")

	def test_matter_channel_searches_id_name_and_organization(self):
		channel = {
			"channel_name": "#vendor-contract-review-matter-2026-00001",
			"matter_id": "MATTER-2026-00001",
			"matter_title": "Vendor Contract Review",
			"organization_id": "CUST-0001",
			"organization_name": "Demo Client Private Limited",
		}

		self.assertTrue(_channel_matches_search(channel, "matter-2026-00001"))
		self.assertTrue(_channel_matches_search(channel, "vendor contract"))
		self.assertTrue(_channel_matches_search(channel, "demo client"))
		self.assertFalse(_channel_matches_search(channel, "unrelated organization"))

	def test_lpo_matter_context_exposes_search_metadata(self):
		matter = frappe._dict(
			{
				"name": "MATTER-2026-00001",
				"matter_title": "Vendor Contract Review",
				"customer": "CUST-0001",
				"customer_name": "Demo Client Private Limited",
			}
		)
		with patch("frappe.db.get_value", return_value=matter):
			context = _get_matter_context("LPO Matter", "MATTER-2026-00001")

		self.assertTrue(context["is_matter_channel"])
		self.assertEqual(context["matter_id"], "MATTER-2026-00001")
		self.assertEqual(context["matter_title"], "Vendor Contract Review")
		self.assertEqual(context["organization_name"], "Demo Client Private Limited")

	def test_direct_message_creation_recovers_from_a_unique_key_race(self):
		candidate = MagicMock()
		candidate.insert.side_effect = frappe.DuplicateEntryError
		existing_doc = MagicMock()
		with (
			patch(
				"lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel.can_start_direct_message",
				return_value=True,
			),
			patch("frappe.db.get_value", side_effect=[None, "LCC-EXISTING"]) as get_value,
			patch("frappe.db.savepoint"),
			patch("frappe.db.rollback") as rollback,
			patch(
				"lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel.now_datetime",
				return_value="2026-09-06 12:00:00",
			),
			patch("frappe.get_doc", side_effect=[candidate, existing_doc]),
			patch(
				"lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel.serialize_channel",
				return_value={"name": "LCC-EXISTING"},
			),
		):
			result = get_or_create_direct_channel("other@example.invalid")

		self.assertEqual(result, {"name": "LCC-EXISTING"})
		rollback.assert_called_once_with(save_point="lexocrates_chat_direct_channel")
		self.assertTrue(get_value.call_args_list[1].kwargs["for_update"])
