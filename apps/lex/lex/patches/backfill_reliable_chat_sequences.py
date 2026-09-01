from __future__ import annotations

import frappe


def execute():
	"""Backfill the durable ordering/idempotency fields for existing chat history."""
	if not frappe.db.exists("DocType", "Lexocrates Chat Message"):
		return

	channels = frappe.get_all("Lexocrates Chat Channel", pluck="name", limit_page_length=0)
	for channel in channels:
		messages = frappe.get_all(
			"Lexocrates Chat Message",
			filters={"channel": channel},
			fields=["name", "channel_sequence", "client_message_id"],
			order_by="sent_at asc, creation asc, name asc",
			limit_page_length=0,
		)
		for sequence, message in enumerate(messages, start=1):
			values = {}
			if int(message.channel_sequence or 0) != sequence:
				values["channel_sequence"] = sequence
			if not message.client_message_id:
				values["client_message_id"] = f"legacy:{message.name}"
			if values:
				frappe.db.set_value(
					"Lexocrates Chat Message", message.name, values, update_modified=False
				)
		frappe.db.set_value(
			"Lexocrates Chat Channel",
			channel,
			"last_message_sequence",
			len(messages),
			update_modified=False,
		)

	states = frappe.get_all(
		"Lexocrates Chat User State",
		filters={"last_read_message": ["is", "set"]},
		fields=["name", "last_read_message"],
		limit_page_length=0,
	)
	for state in states:
		sequence = frappe.db.get_value(
			"Lexocrates Chat Message", state.last_read_message, "channel_sequence"
		)
		frappe.db.set_value(
			"Lexocrates Chat User State",
			state.name,
			"last_read_sequence",
			int(sequence or 0),
			update_modified=False,
		)

	frappe.db.add_unique(
		"Lexocrates Chat Message",
		("channel", "channel_sequence"),
		constraint_name="lexocrates_chat_message_channel_sequence_unique",
	)
