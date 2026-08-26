from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from lex.ai_providers import DEFAULT_ENDPOINT_TYPES, is_text_model_candidate, normalize_provider


class LPOAIModelRegistry(Document):
	def validate(self):
		self.provider = normalize_provider(self.provider)
		self.model_id = str(self.model_id or "").replace("models/", "").strip()
		if not self.model_id:
			frappe.throw(_("Model ID is required."), frappe.MandatoryError)
		if not is_text_model_candidate(self.provider, self.model_id):
			frappe.throw(_("Only compatible text-generation models may be registered."), frappe.ValidationError)
		self.display_name = self.display_name or self.model_id
		self.endpoint_type = self.endpoint_type or DEFAULT_ENDPOINT_TYPES[self.provider]
		if self.verified:
			self.verification_status = "Verified"

	def on_trash(self):
		frappe.throw(_("AI model records must be disabled, not deleted."), frappe.PermissionError)


def on_doctype_update():
	frappe.db.add_unique(
		"LPO AI Model Registry",
		["provider", "model_id"],
		constraint_name="lpo_ai_model_provider_model_unique",
	)
