# Copyright (c) 2026, Lexocrates and contributors
# For license information, please see license.txt

import hashlib
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class LPOAIDocumentProcessor(Document):
	def validate(self):
		if self.job and not self.matter:
			self.matter = frappe.db.get_value("LPO Job", self.job, "engagement")
		if self.matter and not self.customer:
			self.customer = frappe.db.get_value("LPO Matter", self.matter, "customer")

		if self.extracted_text:
			self.char_count = len(self.extracted_text)
			self.word_count = len(self.extracted_text.split())

	def before_insert(self):
		if not self.status:
			self.status = "Draft"
