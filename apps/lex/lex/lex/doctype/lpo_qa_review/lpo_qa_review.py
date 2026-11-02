from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


MANAGEMENT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager"}
FINAL_REVIEW_STATUSES = {"Approved", "Changes Required", "Rejected"}
FINAL_REVIEW_STAGES = {"Final QA", "Final QC"}


class LPOQAReview(Document):
	def validate(self):
		self._load_job_context()
		from lex.legal_research_sop import populate_self_review_checklist, validate_review
		from lex.service_sop import (
			populate_review_checklist as populate_service_sop_checklist,
			validate_review as validate_service_sop_review,
		)

		populate_self_review_checklist(self, self._lex_job_context)
		populate_service_sop_checklist(self, self._lex_job_context)
		validate_review(self, self._lex_job_context)
		validate_service_sop_review(self, self._lex_job_context)
		self._validate_reviewer()
		self._bind_reviewed_document()
		self._validate_outcome()

	def on_update(self):
		if self.is_new() or self.has_value_changed("review_status"):
			self._synchronize_job_quality_state()

	def _load_job_context(self):
		job = frappe.db.get_value(
			"LPO Job",
			self.job,
			[
				"name", "engagement", "customer", "assigned_analyst", "job_status", "delivery_document",
				"delivery_document_checksum", "delivery_document_version", "qa_required", "job_type",
				"peer_reviewer", "supervising_counsel", "ai_processing_allowed",
				"service_sop_review_tier",
			],
			as_dict=True,
		)
		if not job:
			frappe.throw(_("LPO Job {0} does not exist.").format(frappe.bold(self.job)))
		self.engagement = job.engagement
		self.customer = job.customer
		self._lex_job_context = job
		if not job.qa_required:
			frappe.throw(_("This Job does not require a QA Review."), frappe.ValidationError)
		if job.job_status not in {"QA Review", "In Progress"}:
			frappe.throw(_("QA Reviews can be recorded only while the Job is in progress or under QA Review."), frappe.ValidationError)

	def _validate_reviewer(self):
		if not frappe.db.get_value("User", self.reviewer, "enabled"):
			frappe.throw(_("Reviewer must be an enabled user."), frappe.ValidationError)
		if frappe.db.get_value("User", self.reviewer, "user_type") != "System User":
			frappe.throw(_("Reviewer must be a System User."), frappe.ValidationError)
		roles = set(frappe.get_roles(self.reviewer))
		if self.reviewer != "Administrator" and not roles.intersection(
			MANAGEMENT_ROLES | {"LPO_Analyst"}
		):
			frappe.throw(_("Reviewer must have an LPO role."), frappe.ValidationError)
		stage = self.review_stage or "Final QC"
		self.reviewer_independent = int(self.reviewer != self._lex_job_context.assigned_analyst)
		from lex.service_sop import is_profiled_service
		if stage == "Self Review" and (self._lex_job_context.job_type == "Legal Research" or is_profiled_service(self._lex_job_context.job_type)):
			if self.reviewer_independent:
				frappe.throw(_("Self Review must be completed by the assigned analyst."), frappe.ValidationError)
			return
		if stage in FINAL_REVIEW_STAGES and (
			self._lex_job_context.job_type == "Legal Research"
			or is_profiled_service(self._lex_job_context.job_type)
		):
			# These SOPs permit the assigned associate or an independent QC reviewer
			# to complete Final QC; the record keeps the independence fact either way.
			return
		if not self.reviewer_independent:
			frappe.throw(_("The assigned analyst cannot review their own Job deliverable."), frappe.ValidationError)

	def _bind_reviewed_document(self):
		job = self._lex_job_context
		previous = self.get_doc_before_save()
		if previous and previous.reviewed_document and (
			previous.reviewed_document != self.reviewed_document
			or previous.reviewed_document_checksum != self.reviewed_document_checksum
			or int(previous.reviewed_document_version or 0) != int(self.reviewed_document_version or 0)
		):
			frappe.throw(_("The reviewed deliverable snapshot is immutable."), frappe.PermissionError)
		if not self.reviewed_document and job.delivery_document:
			self.reviewed_document = job.delivery_document
			self.reviewed_document_checksum = job.delivery_document_checksum
			self.reviewed_document_version = job.delivery_document_version
		is_final_qa = (self.review_stage or "Final QC") in FINAL_REVIEW_STAGES
		if self.review_status in FINAL_REVIEW_STATUSES and is_final_qa:
			if not self.reviewed_document:
				frappe.throw(_("A delivery document is required before completing QA."), frappe.ValidationError)
			if (
				self.reviewed_document != job.delivery_document
				or self.reviewed_document_checksum != job.delivery_document_checksum
				or int(self.reviewed_document_version or 0) != int(job.delivery_document_version or 0)
			):
				frappe.throw(_("QA must be completed against the current delivery document version."), frappe.ValidationError)

	def _validate_outcome(self):
		is_final_qa = (self.review_stage or "Final QC") in FINAL_REVIEW_STAGES
		if self.review_status in FINAL_REVIEW_STATUSES and is_final_qa and self._lex_job_context.job_status != "QA Review":
			frappe.throw(_("Finish a QA decision only while the Job is in QA Review."), frappe.ValidationError)
		if self.review_status in FINAL_REVIEW_STATUSES and frappe.session.user != self.reviewer:
			frappe.throw(_("Only the selected independent reviewer can submit the QA decision."), frappe.PermissionError)
		if self.review_status == "Changes Required" and not self.corrective_actions:
			frappe.throw(
				_("Required Corrective Actions are mandatory when changes are requested."),
				frappe.ValidationError,
			)
		if self.review_status in {"Approved", "Rejected"} and not self.completed_on:
			self.completed_on = now_datetime()
		if self.review_status == "Approved" and is_final_qa and not self._lex_job_context.delivery_document:
			frappe.throw(_("A delivery document is required before QA approval."), frappe.ValidationError)
		if self.review_status == "Approved" and self.qa_checklist:
			failed = [row.check_name for row in self.qa_checklist if row.result == "Fail"]
			if failed:
				frappe.throw(
					_("QA cannot be approved while checklist items are marked Fail: {0}").format(", ".join(failed)),
					frappe.ValidationError,
				)
		if self.review_status == "Approved":
			from lex.legal_research_sop import validate_final_review_gate, validate_self_review_checklist, validate_stage_checklist
			from lex.service_sop import validate_review_checklist as validate_service_sop_checklist

			validate_self_review_checklist(self, self._lex_job_context)
			validate_stage_checklist(self, self._lex_job_context)
			validate_final_review_gate(self, self._lex_job_context)
			validate_service_sop_checklist(self, self._lex_job_context)

	def _synchronize_job_quality_state(self):
		if self.review_status not in {"Approved", "Changes Required", "Rejected"}:
			return
		if (self.review_stage or "Final QC") not in FINAL_REVIEW_STAGES:
			return
		job = frappe.get_doc("LPO Job", self.job)
		job.qa_reviewer = self.reviewer
		job.qa_score = self.score or 0
		if self.review_status == "Approved":
			from lex.sop_execution_engine import complete_qa_sop_steps

			complete_qa_sop_steps(job, self)
			job.job_status = "Ready for Delivery"
		else:
			job.job_status = "In Progress"
			job.client_approval_status = "Not Requested"
			job.client_approved_by = None
			job.client_approved_on = None
			job.delivery_receipt_status = "Not Delivered"
		job.save(ignore_permissions=True)


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
