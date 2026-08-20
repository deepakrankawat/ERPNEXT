from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from lex.lex.page.lexocrates_chat.lexocrates_chat import create_channel


class TestLexocratesChatPage(FrappeTestCase):
	def test_create_channel_rpc_does_not_forward_framework_command(self):
		created_channel = {"name": "test-private-channel"}
		with patch(
			"lex.lex.page.lexocrates_chat.lexocrates_chat._create_channel",
			return_value=created_channel,
		) as channel_creator:
			result = frappe.call(
				create_channel,
				cmd="lex.lex.page.lexocrates_chat.lexocrates_chat.create_channel",
				channel_name="deede",
				channel_type="Private",
			)

		self.assertEqual(result, created_channel)
		channel_creator.assert_called_once_with(
			channel_name="deede",
			channel_type="Private",
			description=None,
			reference_doctype=None,
			reference_name=None,
			members=None,
		)
