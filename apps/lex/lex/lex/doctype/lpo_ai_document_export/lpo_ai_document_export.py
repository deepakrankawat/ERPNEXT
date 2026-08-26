from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from lex.lex.doctype.lpo_job.lpo_job import get_permission_query_conditions as job_permission_query


class LPOAIDocumentExport(Document):
	def validate(self):
		if not self.is_new():
			frappe.throw(_("Generated export records are immutable. Create a new version instead."), frappe.ValidationError)

	def on_trash(self):
		frappe.throw(_("Generated export records cannot be deleted. Their audit history must be retained."), frappe.PermissionError)


def has_permission(doc, ptype="read", user=None, debug=False):
	"""An export is visible only when its parent Job is visible to the same user."""
	user = user or frappe.session.user
	if ptype not in {"read", "print", "email", "export"}:
		return False
	return bool(frappe.has_permission("LPO Job", "read", doc=doc.job, user=user))


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	job_condition = job_permission_query(user)
	if not job_condition:
		return ""
	return (
		"exists (select 1 from `tabLPO Job` "
		"where `tabLPO Job`.name = `tabLPO AI Document Export`.job "
		f"and ({job_condition}))"
	)
