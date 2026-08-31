from __future__ import annotations

import frappe
from frappe import _


def block_matter_attachment(doc, method=None):
	"""Keep source evidence on Jobs so every estimate has an exact corpus."""
	if doc.attached_to_doctype == "LPO Matter":
		frappe.throw(
			_("Documents cannot be attached directly to a Matter. Create or open a Job and upload the document there."),
			frappe.ValidationError,
		)
