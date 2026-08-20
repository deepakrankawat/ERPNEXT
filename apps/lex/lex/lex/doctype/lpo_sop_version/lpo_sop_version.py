# Copyright (c) 2026, Lexocrates and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document


class LPOSOPVersion(Document):
	def validate(self):
		try:
			steps = json.loads(self.steps_json or "[]")
		except (TypeError, ValueError):
			frappe.throw(_("SOP Steps must be valid JSON."), frappe.ValidationError)
		if not isinstance(steps, list) or not steps:
			frappe.throw(_("An SOP Version must contain at least one step."), frappe.ValidationError)
		seen = set()
		for index, step in enumerate(steps, start=1):
			if not isinstance(step, dict):
				frappe.throw(_("SOP step {0} must be an object.").format(index), frappe.ValidationError)
			step_id = (step.get("step_id") or "").strip()
			if not step_id or step_id in seen:
				frappe.throw(_("Every SOP step requires a unique step_id."), frappe.ValidationError)
			if not (step.get("title") or "").strip():
				frappe.throw(_("Every SOP step requires a title."), frappe.ValidationError)
			seen.add(step_id)
		self.steps_json = json.dumps(steps, sort_keys=True, separators=(",", ":"))
		previous = self.get_doc_before_save()
		if previous and previous.status == "Effective":
			for fieldname in ("sop_id", "version", "steps_json"):
				if previous.get(fieldname) != self.get(fieldname):
					frappe.throw(_("Effective SOP versions are immutable; create a new version."), frappe.PermissionError)

	def on_trash(self):
		if self.status == "Effective":
			frappe.throw(_("Effective SOP versions cannot be deleted."), frappe.PermissionError)
