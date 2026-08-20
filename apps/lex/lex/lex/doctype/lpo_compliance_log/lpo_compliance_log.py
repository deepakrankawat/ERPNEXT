from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now_datetime


MANAGEMENT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager"}


class LPOComplianceLog(Document):
	def before_insert(self):
		self.reported_by = frappe.session.user

	def validate(self):
		self._load_operational_context()
		self._validate_dates()
		self._validate_resolution()

	def _load_operational_context(self):
		if self.job:
			job = frappe.db.get_value(
				"LPO Job", self.job, ["engagement", "customer"], as_dict=True
			)
			if not job:
				frappe.throw(_("LPO Job {0} does not exist.").format(frappe.bold(self.job)))
			self.engagement = job.engagement
			self.customer = job.customer
			return

		engagement = frappe.db.get_value(
			"LPO Matter", self.engagement, ["customer"], as_dict=True
		)
		if not engagement:
			frappe.throw(
				_("Client Matter {0} does not exist.").format(frappe.bold(self.engagement))
			)
		self.customer = engagement.customer

	def _validate_dates(self):
		if self.due_date and getdate(self.due_date) < getdate(self.detected_on):
			frappe.throw(
				_("Remediation Due Date cannot be before Detected On."),
				frappe.ValidationError,
			)

	def _validate_resolution(self):
		if self.status in {"Resolved", "Closed"}:
			if not self.remediation_action:
				frappe.throw(
					_("Remediation Action is required before resolving a compliance finding."),
					frappe.ValidationError,
				)
			if not self.resolved_on:
				self.resolved_on = now_datetime()


def _has_management_access(user: str) -> bool:
	return user == "Administrator" or bool(set(frappe.get_roles(user)).intersection(MANAGEMENT_ROLES))


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if _has_management_access(user):
		return True
	if "LPO_Analyst" not in frappe.get_roles(user) or ptype != "read" or not doc.job:
		return False
	return frappe.db.get_value("LPO Job", doc.job, "assigned_analyst") == user


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _has_management_access(user):
		return ""
	if "LPO_Analyst" not in frappe.get_roles(user):
		return "1=0"
	escaped_user = frappe.db.escape(user)
	return f"""
		exists (
			select 1 from `tabLPO Job` job
			where job.name = `tabLPO Compliance Log`.job
				and job.assigned_analyst = {escaped_user}
		)
	"""
