# Copyright (c) 2026, Lexocrates and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class LPOAIDocumentService(Document):
	def validate(self):
		if not self.service_code:
			self.service_code = frappe.scrub(self.service_name).upper()
		self.service_code = self.service_code.strip().upper()
