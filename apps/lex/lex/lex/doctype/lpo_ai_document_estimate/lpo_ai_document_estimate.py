from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime


REVIEW_ROLES = {"System Manager", "LPO_Admin", "LPO_Manager", "Lexocrates Finance", "Accounts Manager"}
PROTECTED_FIELDS = {
	"work_intake", "client", "portal_user", "estimate_version", "created_on", "matter", "job",
	"document_count", "clean_document_count", "page_count", "extracted_word_count", "character_count",
	"file_size_bytes", "primary_language", "ocr_quality", "content_form", "has_tables", "has_images",
	"has_signatures", "has_annexures", "document_manifest_json",
	"source_corpus_hash", "analysis_status", "analysis_confidence", "low_confidence",
	"analysis_provider", "analysis_model", "ai_execution", "analysis_summary", "ai_reasoning",
	"detected_document_type", "document_type_confidence", "alternative_matches", "practice_module",
	"recommended_service", "legal_domain", "detected_jurisdiction", "jurisdiction_confidence",
	"complexity_score", "complexity_classification", "risk_level", "reviewer_level", "formula_version",
	"billing_measure", "estimated_volume", "task_count", "base_quantity", "base_lexpoints", "billable_units",
	"junior_hours", "senior_hours", "partner_hours", "normal_sla_hours", "fast_track_sla_hours",
	"express_sla_hours", "expected_completion", "factor_breakdown_json", "explanation",
	"estimate_source", "proposed_lexpoints", "proposed_amount", "currency",
	"proposed_delivery_hours", "proposed_scope", "status", "changed_from_proposal",
	"reviewed_by", "reviewed_on", "approval_status", "approved_by", "approved_on",
	"rejection_reason", "applied_to_intake_on",
	"variance_lexpoints", "variance_percent",
}
REVIEW_FIELDS = {
	"reviewed_lexpoints", "reviewed_amount", "reviewed_delivery_hours", "reviewed_scope", "review_notes",
}
FEEDBACK_FIELDS = {
	"actual_lexpoints", "actual_hours", "actual_delivery_hours", "actual_internal_cost", "actual_margin",
	"actual_reviewer", "completed_on", "calibration_status", "reviewer_corrections", "client_feedback", "variance_reason",
}


class LPOAIDocumentEstimate(Document):
	def before_insert(self):
		if not getattr(frappe.flags, "lexocrates_estimate_service", False):
			frappe.throw(
				_("AI document estimates must be created by the controlled intake analysis service."),
				frappe.PermissionError,
			)
		self.created_on = self.created_on or now_datetime()

	def validate(self):
		for fieldname, label in (
			("proposed_lexpoints", _("Proposed LexPoints")),
			("proposed_amount", _("Proposed Amount")),
			("proposed_delivery_hours", _("Proposed Delivery Hours")),
			("reviewed_lexpoints", _("Reviewed LexPoints")),
			("reviewed_amount", _("Reviewed Amount")),
			("reviewed_delivery_hours", _("Reviewed Delivery Hours")),
		):
			if flt(self.get(fieldname)) <= 0:
				frappe.throw(_("{0} must be greater than zero.").format(label), frappe.ValidationError)
		if not (self.proposed_scope or "").strip() or not (self.reviewed_scope or "").strip():
			frappe.throw(_("Proposed and reviewed scope are required."), frappe.ValidationError)

		changed_from_proposal = cint(
			cint(self.reviewed_lexpoints) != cint(self.proposed_lexpoints)
			or flt(self.reviewed_amount, 2) != flt(self.proposed_amount, 2)
			or cint(self.reviewed_delivery_hours) != cint(self.proposed_delivery_hours)
			or (self.reviewed_scope or "").strip() != (self.proposed_scope or "").strip()
		)
		actual_points = cint(self.actual_lexpoints)
		variance_points = actual_points - cint(self.reviewed_lexpoints) if actual_points else 0
		variance_percent = (
			flt(variance_points / cint(self.reviewed_lexpoints) * 100, 2)
			if actual_points and cint(self.reviewed_lexpoints) else 0
		)
		calibration_status = self.calibration_status
		if actual_points and calibration_status != "Accepted":
			threshold = flt(frappe.db.get_single_value("LPO LexPoint Settings", "variance_alert_percent") or 10)
			calibration_status = "Needs Review" if abs(variance_percent) > threshold else "Within Tolerance"
		elif not actual_points:
			calibration_status = "Not Captured"
		previous = self.get_doc_before_save()
		if not previous or getattr(frappe.flags, "lexocrates_estimate_service", False):
			self.changed_from_proposal = changed_from_proposal
			self.variance_lexpoints = variance_points
			self.variance_percent = variance_percent
			self.calibration_status = calibration_status
			return
		if frappe.session.user != "Administrator" and not set(frappe.get_roles()).intersection(REVIEW_ROLES):
			frappe.throw(_("Legal Operations authority is required to edit an estimate."), frappe.PermissionError)
		protected_changes = [self.meta.get_label(field) for field in PROTECTED_FIELDS if self.has_value_changed(field)]
		if protected_changes:
			frappe.throw(
				_("AI-generated evidence is immutable: {0}").format(", ".join(sorted(protected_changes))),
				frappe.PermissionError,
			)
		self.changed_from_proposal = changed_from_proposal
		self.variance_lexpoints = variance_points
		self.variance_percent = variance_percent
		self.calibration_status = calibration_status
		if any(self.has_value_changed(field) for field in REVIEW_FIELDS):
			intake = frappe.get_doc("Lexocrates Work Intake", self.work_intake)
			if intake.funding_status in {"Payment Pending", "Funded"} or intake.status == "Matter Confirmed":
				frappe.throw(_("The estimate cannot be changed after payment or funding starts."), frappe.PermissionError)
			self.status = "Operations Review"
			self.approval_status = "Not Required"
			self.approved_by = None
			self.approved_on = None
			self.rejection_reason = None
			self.reviewed_by = frappe.session.user
			self.reviewed_on = now_datetime()
			self.flags.review_changed = True
		if any(self.has_value_changed(field) for field in FEEDBACK_FIELDS):
			self.flags.feedback_changed = True

	def on_update(self):
		if getattr(frappe.flags, "lexocrates_estimate_service", False):
			return
		intake = frappe.get_doc("Lexocrates Work Intake", self.work_intake)
		from lex.portal_audit import create_portal_audit_event
		from lex.work_intake import _service_writes

		if getattr(self.flags, "review_changed", False) and intake.ai_document_estimate == self.name:
			with _service_writes():
				intake.status = "Operations Review"
				intake.quote_status = "Operations Review"
				intake.pricing_approval_status = "Not Required"
				intake.pricing_approved_by = None
				intake.pricing_approved_on = None
				intake.save(ignore_permissions=True)
			create_portal_audit_event(
				client=self.client, portal_user=self.portal_user, action="AI Document Estimate Edited",
				object_type=self.doctype, object_id=self.name,
				new_value={
					"reviewed_lexpoints": self.reviewed_lexpoints, "reviewed_amount": self.reviewed_amount,
					"reviewed_delivery_hours": self.reviewed_delivery_hours,
					"changed_from_proposal": self.changed_from_proposal,
				},
			)
		if getattr(self.flags, "feedback_changed", False):
			create_portal_audit_event(
				client=self.client, portal_user=self.portal_user, action="LexPoint Estimate Outcome Captured",
				object_type=self.doctype, object_id=self.name,
				new_value={
					"actual_lexpoints": self.actual_lexpoints, "actual_hours": self.actual_hours,
					"variance_lexpoints": self.variance_lexpoints, "variance_percent": self.variance_percent,
					"calibration_status": self.calibration_status,
				},
			)

	def on_trash(self):
		frappe.throw(_("AI document estimate history cannot be deleted."), frappe.PermissionError)


def on_doctype_update():
	frappe.db.add_unique(
		"LPO AI Document Estimate",
		["work_intake", "estimate_version"],
		constraint_name="ai_document_estimate_intake_version_unique",
	)
	frappe.db.add_index(
		"LPO AI Document Estimate", ["client", "created_on"], index_name="ai_document_estimate_client_created"
	)
	frappe.db.add_index(
		"LPO AI Document Estimate", ["status", "modified"], index_name="ai_document_estimate_status_modified"
	)
