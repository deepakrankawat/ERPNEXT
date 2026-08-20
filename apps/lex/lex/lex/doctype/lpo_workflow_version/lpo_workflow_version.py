# Copyright (c) 2026, Lexocrates and contributors
# For license information, please see license.txt

import hashlib
import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from lex.workflow_validator import validate_workflow_graph


class LPOWorkflowVersion(Document):
	def validate(self):
		validation = validate_workflow_graph(self.graph_json or "{}")
		if not validation["is_valid"]:
			frappe.throw(_("Invalid Workflow graph: {0}").format(", ".join(validation["errors"])), frappe.ValidationError)
		graph = json.loads(self.graph_json)
		canonical = json.dumps(graph, sort_keys=True, separators=(",", ":"))
		self.graph_json = canonical
		self.graph_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
		if self.status in {"Approved", "Published"} and not self.approved_by:
			self.approved_by = frappe.session.user
		if self.status == "Published" and not self.published_at:
			self.published_at = now_datetime()
		previous = self.get_doc_before_save()
		if previous and previous.status == "Published":
			for fieldname in ("workflow_id", "version", "graph_json", "graph_hash"):
				if previous.get(fieldname) != self.get(fieldname):
					frappe.throw(_("Published Workflow versions are immutable; create a new version."), frappe.PermissionError)

	def on_trash(self):
		if self.status == "Published":
			frappe.throw(_("Published Workflow versions cannot be deleted."), frappe.PermissionError)
