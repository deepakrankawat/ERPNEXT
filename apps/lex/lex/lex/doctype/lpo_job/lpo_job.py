from __future__ import annotations

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

from lex.client_access import (
	has_matter_access,
	has_portal_capability,
	is_client_user,
	job_sql_condition,
)


MANAGEMENT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager"}
ASSIGNABLE_ROLES = MANAGEMENT_ROLES | {"LPO_Analyst"}
ASSIGNMENT_REQUIRED_STATUSES = {
	"Assigned",
	"In Progress",
	"On Hold",
	"QA Review",
	"Ready for Delivery",
	"Delivered",
	"Completed",
}
LOCKED_FOR_ANALYSTS = {
	"engagement",
	"customer",
	"job_type",
	"priority",
	"assigned_analyst",
	"received_at",
	"due_date",
	"ai_processing_allowed",
}


class LPOJob(Document):
	def validate(self):
		self._load_engagement_context()
		self._protect_client_submission()
		self._validate_matter_activation()
		self._validate_execution_snapshots()
		self._capture_document_lineage()
		self._validate_schedule()
		self._validate_assignment()
		self._protect_governance_fields()
		self._set_completed_on()
		self._set_client_approval_state()
		self._set_delivery_receipt_state()

	def _load_engagement_context(self):
		if not self.engagement:
			frappe.throw(_("Parent Matter is mandatory."), frappe.MandatoryError)

		engagement = frappe.db.get_value(
			"LPO Matter",
			self.engagement,
			[
				"name",
				"customer",
				"practice_area",
				"jurisdictions",
				"billing_method",
				"confidentiality_level",
				"status",
				"end_date",
				"quote_status",
				"funding_status",
				"workflow_version_snapshot",
				"sop_version_snapshot",
			],
			as_dict=True,
		)
		if not engagement:
			frappe.throw(
				_("Parent Matter {0} does not exist.").format(frappe.bold(self.engagement)),
				frappe.DoesNotExistError,
			)
		self._lex_matter_context = engagement

		if self.is_new() and engagement.status in {"On Hold", "Completed", "Closed"}:
			frappe.throw(
				_("New jobs cannot be created under a matter with status {0}.").format(
					frappe.bold(engagement.status)
				),
				frappe.ValidationError,
			)

		for fieldname in (
			"customer",
			"customer_name",
			"practice_area",
			"jurisdictions",
			"confidentiality_level",
		):
			self.set(fieldname, engagement.get(fieldname))

	def _validate_matter_activation(self):
		if self.job_status == "Draft":
			return
		matter = self._lex_matter_context
		if matter.status != "Active":
			frappe.throw(_("The parent Matter must be Active before operational work begins."), frappe.ValidationError)
		if matter.billing_method == "Quoted Price" and matter.quote_status != "Approved":
			frappe.throw(_("The parent Matter quote has not been approved."), frappe.ValidationError)
		if matter.billing_method == "LexPack" and matter.funding_status != "Funded":
			frappe.throw(_("The parent Matter is not funded with reserved LexPoints."), frappe.ValidationError)

	def _validate_execution_snapshots(self):
		# Funding activates the job and starts its SLA before an analyst is assigned.
		# Governance snapshots become mandatory at assignment, not at funding.
		if self.job_status in {"Draft", "Activated"}:
			return
		matter = self._lex_matter_context
		self.workflow_version_snapshot = self.workflow_version_snapshot or matter.workflow_version_snapshot
		self.sop_version_snapshot = self.sop_version_snapshot or matter.sop_version_snapshot
		if not self.workflow_version_snapshot or not self.sop_version_snapshot:
			frappe.throw(
				_("Published Workflow and effective SOP version snapshots are required before assignment."),
				frappe.ValidationError,
			)
		if frappe.db.get_value("LPO Workflow Version", self.workflow_version_snapshot, "status") != "Published":
			frappe.throw(_("Workflow Version must be Published."), frappe.ValidationError)
		if frappe.db.get_value("LPO SOP Version", self.sop_version_snapshot, "status") != "Effective":
			frappe.throw(_("SOP Version must be Effective."), frappe.ValidationError)
		previous = self.get_doc_before_save()
		if previous and previous.job_status not in {"Draft", "Activated"}:
			for fieldname in ("workflow_version_snapshot", "sop_version_snapshot"):
				if previous.get(fieldname) != self.get(fieldname):
					frappe.throw(_("Job execution policy snapshots are immutable after assignment."), frappe.PermissionError)

	def _capture_document_lineage(self):
		previous = self.get_doc_before_save()
		for source_field, checksum_field, version_field, label in (
			("source_document", "source_document_checksum", "source_document_version", _("Source document")),
			("delivery_document", "delivery_document_checksum", "delivery_document_version", _("Delivery document")),
		):
			file_url = self.get(source_field)
			if not file_url:
				self.set(checksum_field, None)
				continue
			checksum = _file_checksum_and_security_status(file_url, label, require_clean=self.job_status != "Draft")
			old_checksum = previous.get(checksum_field) if previous else None
			old_url = previous.get(source_field) if previous else None
			if not previous or old_url != file_url or old_checksum != checksum:
				self.set(version_field, int((previous.get(version_field) if previous else 0) or 0) + 1)
			self.set(checksum_field, checksum)

	def _validate_schedule(self):
		if self.received_at and self.due_date:
			if get_datetime(self.due_date) < get_datetime(self.received_at):
				frappe.throw(_("Due Date cannot be before Received At."), frappe.ValidationError)

	def _protect_client_submission(self):
		if (
			not is_client_user()
			or _has_management_access(frappe.session.user)
			or getattr(frappe.flags, "lexocrates_portal_service", False)
		):
			return
		if not self.is_new():
			frappe.throw(_("Clients cannot modify an accepted work request."), frappe.PermissionError)
		if not has_portal_capability("can_create_matters") or not has_matter_access(
			self.engagement, "view"
		):
			frappe.throw(
				_("You are not authorized to submit work for this Matter."),
				frappe.PermissionError,
			)
		# Clients can submit instructions and a source document. Operational,
		# delivery, QA, and AI-governance fields remain server controlled.
		self.job_status = "Draft"
		self.assigned_analyst = None
		self.received_at = now_datetime()
		self.completed_on = None
		self.actual_hours = 0
		self.delivery_document = None
		self.ai_processing_allowed = 0
		self.ai_instructions = None
		self.qa_required = 1
		self.qa_reviewer = None
		self.qa_score = 0
		self.delivery_notes = None

	def _validate_assignment(self):
		if self.job_status in ASSIGNMENT_REQUIRED_STATUSES and not self.assigned_analyst:
			frappe.throw(
				_("Assigned Analyst is required when the job status is {0}.").format(
					frappe.bold(self.job_status)
				),
				frappe.ValidationError,
			)
		if not self.assigned_analyst:
			return

		if not frappe.db.get_value("User", self.assigned_analyst, "enabled"):
			frappe.throw(_("Assigned Analyst must be an enabled user."), frappe.ValidationError)
		roles = set(frappe.get_roles(self.assigned_analyst))
		if self.assigned_analyst != "Administrator" and not roles.intersection(ASSIGNABLE_ROLES):
			frappe.throw(
				_("Assigned Analyst must have an LPO role or the System Manager role."),
				frappe.ValidationError,
			)

	def _protect_governance_fields(self):
		if self.is_new() or _has_management_access(frappe.session.user):
			return
		if "LPO_Analyst" not in frappe.get_roles(frappe.session.user):
			return

		changed = [self.meta.get_label(field) for field in LOCKED_FOR_ANALYSTS if self.has_value_changed(field)]
		if changed:
			frappe.throw(
				_("Analysts cannot change governance fields: {0}.").format(", ".join(sorted(changed))),
				frappe.PermissionError,
			)

	def _set_completed_on(self):
		if self.job_status in {"Delivered", "Completed"} and not self.completed_on:
			self.completed_on = now_datetime()

	def _set_client_approval_state(self):
		"""Open a client decision whenever operations marks work ready for delivery."""
		if self.job_status == "Ready for Delivery" and (
			self.is_new() or self.has_value_changed("job_status")
		):
			self.client_approval_status = "Pending"
			self.client_approved_by = None
			self.client_approved_on = None
			self.client_approval_notes = None

	def _set_delivery_receipt_state(self):
		if self.job_status in {"Ready for Delivery", "Delivered", "Completed"} and not self.delivery_document:
			frappe.throw(_("A scanned delivery document is required for delivery."), frappe.ValidationError)
		if self.job_status in {"Delivered", "Completed"} and self.delivery_receipt_status in {None, "", "Not Delivered"}:
			self.delivery_receipt_status = "Awaiting Acknowledgement"


def _file_checksum_and_security_status(file_url: str, label: str, *, require_clean: bool) -> str:
	file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_name:
		frappe.throw(_("{0} must reference a managed File record.").format(label), frappe.ValidationError)
	file_doc = frappe.get_doc("File", file_name)
	if require_clean and file_doc.meta.has_field("custom_lex_scan_status"):
		if file_doc.get("custom_lex_scan_status") != "Clean":
			frappe.throw(
				_("{0} is quarantined until its malware scan passes.").format(label),
				frappe.ValidationError,
			)
	content = file_doc.get_content()
	if isinstance(content, str):
		content = content.encode("utf-8")
	return hashlib.sha256(content).hexdigest()


def _has_management_access(user: str) -> bool:
	return user == "Administrator" or bool(set(frappe.get_roles(user)).intersection(MANAGEMENT_ROLES))


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if _has_management_access(user):
		return True
	if is_client_user(user):
		if ptype == "create":
			return has_portal_capability("can_create_matters", user)
		return ptype == "read" and has_matter_access(doc.engagement, "view", user)
	if "LPO_Analyst" not in frappe.get_roles(user):
		return False
	if ptype in {"create", "delete", "share"}:
		return False
	return doc.assigned_analyst == user


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _has_management_access(user):
		return ""
	if is_client_user(user):
		return job_sql_condition(user=user)
	if "LPO_Analyst" not in frappe.get_roles(user):
		return "1=0"

	return f"`tabLPO Job`.assigned_analyst = {frappe.db.escape(user)}"
