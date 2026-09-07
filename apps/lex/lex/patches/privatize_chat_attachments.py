from __future__ import annotations

import json

import frappe


CHAT_MESSAGE_DOCTYPE = "Lexocrates Chat Message"


def execute():
	"""Move legacy public chat uploads into Frappe's private file storage."""
	if not frappe.db.exists("DocType", CHAT_MESSAGE_DOCTYPE):
		return

	messages = frappe.get_all(
		CHAT_MESSAGE_DOCTYPE,
		filters={"attachments": ["like", "%/files/%"]},
		fields=["name", "attachments"],
		limit_page_length=0,
	)
	converted_urls: dict[str, str] = {}
	for message in messages:
		attachments = _parse_attachments(message.name, message.attachments)
		updated_attachments = [
			_privatize_attachment(message.name, url, converted_urls)
			if isinstance(url, str) and url.startswith("/files/")
			else url
			for url in attachments
		]
		if updated_attachments != attachments:
			frappe.db.set_value(
				CHAT_MESSAGE_DOCTYPE,
				message.name,
				"attachments",
				json.dumps(updated_attachments, separators=(",", ":")),
				update_modified=False,
			)


def _parse_attachments(message_name: str, value) -> list:
	try:
		attachments = json.loads(value or "[]")
	except (TypeError, ValueError) as exc:
		raise frappe.ValidationError(
			f"Chat message {message_name} has malformed attachment metadata."
		) from exc
	if not isinstance(attachments, list):
		raise frappe.ValidationError(
			f"Chat message {message_name} has malformed attachment metadata."
		)
	return attachments


def _privatize_attachment(
	message_name: str, public_url: str, converted_urls: dict[str, str]
) -> str:
	if public_url in converted_urls:
		return converted_urls[public_url]

	file_name = frappe.db.get_value(
		"File",
		{
			"file_url": public_url,
			"attached_to_doctype": CHAT_MESSAGE_DOCTYPE,
			"attached_to_name": message_name,
		},
		"name",
	)
	if not file_name:
		# Older chat uploads may predate attachment binding, but must still have a
		# File record so the public blob can be moved rather than merely hidden.
		file_name = frappe.db.get_value("File", {"file_url": public_url}, "name")
	if not file_name:
		raise frappe.ValidationError(
			f"Cannot privatize chat attachment {public_url} on message {message_name}: File record not found."
		)

	file_doc = frappe.get_doc("File", file_name)
	original_attached_to_field = file_doc.attached_to_field
	# A Long Text attachment list is JSON. Letting File.handle_is_private_changed
	# update it directly would replace the whole list with a single URL.
	file_doc.attached_to_field = None
	file_doc.is_private = 1
	file_doc.save(ignore_permissions=True)
	if original_attached_to_field:
		frappe.db.set_value(
			"File",
			file_doc.name,
			"attached_to_field",
			original_attached_to_field,
			update_modified=False,
		)

	converted_urls[public_url] = file_doc.file_url
	return file_doc.file_url
