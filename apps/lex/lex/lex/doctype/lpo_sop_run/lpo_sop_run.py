# Copyright (c) 2026, Lexocrates and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class LPOSOPRun(Document):
	def on_trash(self):
		frappe.throw(_("SOP Runs are operational evidence and cannot be deleted."), frappe.PermissionError)
