from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


MANAGEMENT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager"}


class LPOQAReview(Document):
	def validate(self):
		self._load_job_context()
		self._validate_reviewer()
		self._validate_outcome()

	def _load_job_context(self):
		job = frappe.db.get_value(
			"LPO Job",
			self.job,
			["engagement", "customer", "assigned_analyst"],
			as_dict=True,
		)
		if not job:
			frappe.throw(_("LPO Job {0} does not exist.").format(frappe.bold(self.job)))
		self.engagement = job.engagement
		self.customer = job.customer

	def _validate_reviewer(self):
		if not frappe.db.get_value("User", self.reviewer, "enabled"):
			frappe.throw(_("Reviewer must be an enabled user."), frappe.ValidationError)
		roles = set(frappe.get_roles(self.reviewer))
		if self.reviewer != "Administrator" and not roles.intersection(
			MANAGEMENT_ROLES | {"LPO_Analyst"}
		):
			frappe.throw(_("Reviewer must have an LPO role."), frappe.ValidationError)

	def _validate_outcome(self):
		if self.review_status == "Changes Required" and not self.corrective_actions:
			frappe.throw(
				_("Required Corrective Actions are mandatory when changes are requested."),
				frappe.ValidationError,
			)
		if self.review_status in {"Approved", "Rejected"} and not self.completed_on:
			self.completed_on = now_datetime()


def _has_management_access(user: str) -> bool:
	return user == "Administrator" or bool(set(frappe.get_roles(user)).intersection(MANAGEMENT_ROLES))


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if _has_management_access(user):
		return True
	if "LPO_Analyst" not in frappe.get_roles(user) or ptype in {"delete", "share"}:
		return False
	return bool(
		doc.reviewer == user
		or frappe.db.get_value("LPO Job", doc.job, "assigned_analyst") == user
	)


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _has_management_access(user):
		return ""
	if "LPO_Analyst" not in frappe.get_roles(user):
		return "1=0"
	escaped_user = frappe.db.escape(user)
	return f"""
		(`tabLPO QA Review`.reviewer = {escaped_user}
		or exists (
			select 1 from `tabLPO Job` job
			where job.name = `tabLPO QA Review`.job
				and job.assigned_analyst = {escaped_user}
		))
	"""
