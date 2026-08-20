from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


ALLOWED_REACTIONS = {"👍", "❤️", "✅", "👀", "🎉", "🙏"}


class LexocratesChatReaction(Document):
	def before_insert(self):
		self.user = frappe.session.user
		self.reacted_at = now_datetime()

	def validate(self):
		if self.emoji not in ALLOWED_REACTIONS:
			frappe.throw(_("This reaction is not supported."), frappe.ValidationError)
		message_channel = frappe.db.get_value("Lexocrates Chat Message", self.message, "channel")
		if not message_channel:
			frappe.throw(_("The message no longer exists."), frappe.DoesNotExistError)
		self.channel = message_channel

	def on_trash(self):
		if self.user != frappe.session.user and frappe.session.user != "Administrator":
			frappe.throw(_("You can only remove your own reaction."), frappe.PermissionError)


def on_doctype_update():
	frappe.db.add_unique(
		"Lexocrates Chat Reaction",
		("message", "user", "emoji"),
		constraint_name="lexocrates_chat_reaction_unique",
	)
	frappe.db.add_index(
		"Lexocrates Chat Reaction",
		["channel", "reacted_at"],
		index_name="lexocrates_chat_reaction_channel",
	)
