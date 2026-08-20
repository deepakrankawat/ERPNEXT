from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from lex.lex.doctype.lexocrates_chat_channel.lexocrates_chat_channel import (
	_channel_matches_search,
	_get_matter_context,
)


class TestLexocratesChatChannel(FrappeTestCase):
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
