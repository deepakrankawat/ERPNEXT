from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class LexocratesChatUserState(Document):
	def validate(self):
		if self.last_read_message:
			message_channel = frappe.db.get_value(
				"Lexocrates Chat Message", self.last_read_message, "channel"
			)
			if message_channel != self.channel:
				frappe.throw(_("The last-read message must belong to the selected channel."))
		if self.notification_level == "Muted":
			self.muted = 1
		elif self.muted:
			self.notification_level = "Muted"

	def on_trash(self):
		if not getattr(frappe.flags, "lexocrates_chat_state_cleanup", False):
			frappe.throw(_("Chat read-state records cannot be deleted manually."), frappe.PermissionError)


def on_doctype_update():
	frappe.db.add_unique(
		"Lexocrates Chat User State",
		("channel", "user"),
		constraint_name="lexocrates_chat_state_channel_user_unique",
	)
	frappe.db.add_index(
		"Lexocrates Chat User State",
		["user", "last_read_at"],
		index_name="lexocrates_chat_state_user_read",
	)
