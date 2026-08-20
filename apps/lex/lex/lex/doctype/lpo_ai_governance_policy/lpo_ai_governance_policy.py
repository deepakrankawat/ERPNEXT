from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class LPOAIGovernancePolicy(Document):
	def validate(self):
		self.target_name = (self.target_name or "*").strip()
		if self.scope_type == "Global":
			self.target_name = "*"
		if self.retry_limit is None or int(self.retry_limit) < 0 or int(self.retry_limit) > 5:
			frappe.throw(_("AI retry limit must be between 0 and 5."), frappe.ValidationError)
		if int(self.retention_days or 0) < 1:
			frappe.throw(_("AI retention must be at least one day."), frappe.ValidationError)

	def on_trash(self):
		frappe.throw(_("AI governance policies must be disabled, not deleted."), frappe.PermissionError)


def on_doctype_update():
	frappe.db.add_unique(
		"LPO AI Governance Policy",
		["scope_type", "target_name"],
		constraint_name="lpo_ai_policy_scope_target_unique",
	)
