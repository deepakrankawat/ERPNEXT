from __future__ import annotations

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_datetime, now_datetime

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
ALLOWED_STATUS_TRANSITIONS = {
	# Client-facing intake and pre-confirmation review (spec: "Legal Assignment" lifecycle).
	"Draft": {"Activated", "Submitted", "Cancelled", "Declined"},
	"Submitted": {"Conflict Check", "Cancelled", "Declined"},
	"Conflict Check": {"Under Review", "Cancelled", "Declined"},
	"Under Review": {"Lextimator Assessment", "Awaiting Internal Scope Review", "Cancelled", "Declined"},
	"Lextimator Assessment": {"Awaiting Internal Scope Review", "Cancelled", "Declined"},
	"Awaiting Internal Scope Review": {"Awaiting Client Approval", "Cancelled", "Declined"},
	"Awaiting Client Approval": {"Confirmed", "Awaiting Internal Scope Review", "Cancelled", "Declined"},
	"Confirmed": {"Work Commenced", "Activated", "Cancelled"},
	# Legacy pre-SLA-engine path, kept so in-flight Jobs created before this feature
	# continue to work unchanged.
	"Activated": {"Assigned", "Work Commenced", "Cancelled"},
	"Work Commenced": {"In Progress", "Assigned", "Cancelled"},
	"Assigned": {"In Progress", "On Hold", "Cancelled"},
	"In Progress": {"On Hold", "SLA Paused", "QA Review", "Cancelled"},
	"On Hold": {"In Progress", "Cancelled"},
	"SLA Paused": {"In Progress", "QA Review", "Cancelled"},
	"QA Review": {"In Progress", "SLA Paused", "Ready for Delivery", "Cancelled"},
	"Ready for Delivery": {"In Progress", "Delivered", "Completed", "Cancelled"},
	"Delivered": {"Correction Requested", "Completed"},
	"Correction Requested": {"In Progress", "QA Review", "Completed"},
	"Completed": set(),
	"Cancelled": set(),
	"Declined": set(),
	"Suspended": set(),
}
PRE_CONFIRMATION_REVIEW_STATES = {
	"Submitted",
	"Conflict Check",
	"Under Review",
	"Lextimator Assessment",
	"Awaiting Internal Scope Review",
	"Awaiting Client Approval",
}
# "Confirmed" is scope/date approval only; funding and execution-policy snapshots
# remain gated at true operational start ("Work Commenced"), authoritatively via
# sla_engine.try_start_sla()'s 8-point checklist rather than this method.
PRE_WORK_COMMENCEMENT_STATES = PRE_CONFIRMATION_REVIEW_STATES | {"Confirmed"}
LOCKED_FOR_ANALYSTS = {
	"engagement",
	"customer",
	"job_type",
	"priority",
	"assigned_analyst",
	"received_at",
	"due_date",
	"ai_processing_allowed",
	"confirmed_delivery_date",
	"quoted_amount",
	"assignment_confirmation",
}


class LPOJob(Document):
	def validate(self):
		self._load_engagement_context()
		self._protect_client_submission()
		self._validate_status_transition()
		self._validate_lifecycle_gates()
		self._validate_confirmed_delivery_date()
		# A client "delete" is an auditable pre-funding cancellation.  The Job
		# remains in the database, and a Draft Job may not yet have the funded
		# execution snapshots or clean-document gates required by active work.
		if self._is_prefunding_cancellation():
			return
		self._validate_currency_pricing()
		self._validate_matter_activation()
		self._validate_execution_snapshots()
		self._validate_job_documents()
		self._capture_document_lineage()
		self._validate_schedule()
		self._validate_assignment()
		self._validate_execution_controls()
		self._protect_governance_fields()
		self._set_completed_on()
		self._set_client_approval_state()
		self._set_delivery_receipt_state()
		self._validate_quality_and_client_gates()

	def _validate_status_transition(self):
		if self.is_new() or getattr(frappe.flags, "lex_job_transition_override", False):
			return
		previous = self.get_doc_before_save()
		if not previous or previous.job_status == self.job_status:
			return
		if self.job_status == "Suspended":
			if not _has_management_access(frappe.session.user):
				frappe.throw(_("Only Legal Operations may suspend an Assignment."), frappe.PermissionError)
			return
		allowed = ALLOWED_STATUS_TRANSITIONS.get(previous.job_status, set())
		if self.job_status not in allowed:
			frappe.throw(
				_("Job status cannot move directly from {0} to {1}.").format(
					frappe.bold(previous.job_status), frappe.bold(self.job_status)
				),
				frappe.ValidationError,
			)

	def _validate_lifecycle_gates(self):
		"""Enforce the spec's stage gates directly in validate(), independent of
		which caller (Desk, API, portal action) drove the status change."""
		if self.is_new() or getattr(frappe.flags, "lex_job_transition_override", False):
			return
		previous = self.get_doc_before_save()
		if not previous or previous.job_status == self.job_status:
			return
		if self.job_status == "Under Review" and previous.job_status == "Conflict Check":
			status = frappe.db.get_value("LPO Matter", self.engagement, "conflict_check_status")
			if status not in {"Cleared", "No Match Found"}:
				frappe.throw(
					_("The Matter's conflict check must be Cleared before this Assignment moves to Under Review."),
					frappe.ValidationError,
				)
		if self.job_status == "Confirmed" and previous.job_status == "Awaiting Client Approval":
			approved = bool(
				self.assignment_confirmation
				and frappe.db.get_value(
					"LPO Assignment Confirmation", self.assignment_confirmation, "client_decision"
				)
				== "Approved"
			)
			if not approved:
				frappe.throw(
					_("The Client must approve the current Assignment Confirmation before this Assignment is Confirmed."),
					frappe.ValidationError,
				)
		if self.job_status == "Correction Requested" and previous.job_status == "Delivered":
			from lex.sla_engine import add_business_days, _settings

			window = cint(_settings().get("correction_request_window_business_days") or 5)
			deadline = add_business_days(self.completed_on or now_datetime(), window)
			if now_datetime() > get_datetime(deadline):
				frappe.throw(
					_("The correction request window for this delivery has closed."),
					frappe.ValidationError,
				)

	def _validate_confirmed_delivery_date(self):
		previous = self.get_doc_before_save()
		if not previous or self.is_new():
			return
		if previous.confirmed_delivery_date and self.has_value_changed("confirmed_delivery_date"):
			# A server-mediated write (e.g. an approved Assignment Scope Change acted on
			# by the client) is already authorized by its own whitelisted function; only
			# a direct Desk/API edit needs the management-role check here.
			trusted_service_write = getattr(frappe.flags, "lexocrates_portal_service", False)
			if not trusted_service_write and not _has_management_access(frappe.session.user):
				frappe.throw(
					_("Only Legal Operations may revise a locked Confirmed Delivery Date."),
					frappe.PermissionError,
				)
			if not (self.delivery_date_revision_reason or "").strip():
				frappe.throw(
					_("Provide a reason for revising the Confirmed Delivery Date."),
					frappe.MandatoryError,
				)

	def _is_prefunding_cancellation(self):
		if self.is_new() or self.job_status != "Cancelled":
			return False
		previous = self.get_doc_before_save()
		if not previous or previous.job_status != "Draft":
			return False
		verified_pending_cancellation = getattr(
			frappe.flags, "lexocrates_client_prefunding_cancellation", False
		)
		if (
			previous.funding_status == "Funded"
			or (previous.funding_status == "Payment Pending" and not verified_pending_cancellation)
			or any(
			(previous.wallet_reservation, previous.sales_invoice, previous.payment_entry)
			)
		):
			frappe.throw(
				_("A Job cannot be cancelled after payment or funding starts."),
				frappe.PermissionError,
			)
		if self.funding_status != "Cancelled":
			frappe.throw(
				_("A cancelled pre-payment Job must be marked as unfunded and cancelled."),
				frappe.ValidationError,
			)
		return True

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

	def _validate_currency_pricing(self):
		"""Keep a Job's quote and Legal Capacity in one real currency."""
		self._validate_fixed_quote_protection()
		if self.estimate_status not in {"Ready", "Accepted"}:
			return
		if self.currency not in {"CAD", "USD", "GBP", "INR"}:
			frappe.throw(_("A Job estimate must use CAD, USD, GBP or INR."), frappe.ValidationError)
		if flt(self.quoted_amount) <= 0 or flt(self.required_legal_capacity) <= 0:
			frappe.throw(_("A ready Job estimate needs a positive fixed quote and Legal Capacity."), frappe.ValidationError)
		if abs(flt(self.quoted_amount) - flt(self.required_legal_capacity)) > 0.001:
			frappe.throw(
				_("Legal Capacity must equal the fixed quote in the Job currency."),
				frappe.ValidationError,
			)
		if not self.selected_pricing_service or cint(self.exact_pdf_page_count) <= 0:
			frappe.throw(
				_("A ready Job estimate requires its selected service and exact native PDF page count."),
				frappe.ValidationError,
			)

	def _validate_fixed_quote_protection(self):
		"""Spec section 14: once a quote is Accepted, it may rise only through an
		Approved Assignment Scope Change — never merely because internal effort was
		underestimated."""
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous or previous.estimate_status != "Accepted":
			return
		if not self.has_value_changed("quoted_amount") or flt(self.quoted_amount) <= flt(previous.quoted_amount):
			return
		delta = flt(self.quoted_amount) - flt(previous.quoted_amount)
		covered = frappe.db.exists(
			"LPO Assignment Scope Change",
			{"job": self.name, "status": "Approved", "additional_price": delta},
		)
		if not covered:
			frappe.throw(
				_(
					"The Fixed Quote cannot be increased without a matching Approved "
					"Assignment Scope Change. Request a Scope Change first."
				),
				frappe.ValidationError,
			)

	def _validate_matter_activation(self):
		if self.job_status == "Draft":
			return
		matter = self._lex_matter_context
		if matter.status != "Active":
			frappe.throw(_("The parent Matter must be Active before operational work begins."), frappe.ValidationError)
		if self.job_status in PRE_WORK_COMMENCEMENT_STATES:
			# Conflict check, internal review, Lextimator assessment and Confirmed
			# (scope/date approval) are pre-operational stages; funding is required only
			# once work is about to commence, enforced by sla_engine.try_start_sla().
			return
		if matter.billing_method == "Job Based":
			if self.funding_status != "Funded":
				payment_hold = (
					getattr(frappe.flags, "lexocrates_payment_adjustment_service", False)
					and self.funding_status in {"Refund Pending", "Partially Refunded", "Refunded", "Disputed", "Chargeback"}
					and self.job_status in {"On Hold", "Delivered", "Completed", "Cancelled"}
				)
				if not payment_hold:
					frappe.throw(_("This Job must be funded before operational work begins."), frappe.ValidationError)
			if not self.work_intake or self.estimate_status != "Accepted" or flt(self.quote_version) <= 0:
				frappe.throw(_("A current accepted Job estimate is required before activation."), frappe.ValidationError)
			if self.job_billing_method == "LexPack" and (
				flt(self.required_legal_capacity) <= 0 or not self.wallet_reservation
			):
				frappe.throw(_("Reserved Legal Capacity is required before activating this Job."), frappe.ValidationError)
			if self.job_billing_method == "Direct Quote" and (
				flt(self.quoted_amount) <= 0 or not self.sales_invoice or not self.payment_entry
			):
				frappe.throw(_("A paid Direct Quote is required before activating this Job."), frappe.ValidationError)
	def _validate_job_documents(self):
		for row in self.job_documents:
			file_row = frappe.db.get_value(
				"File",
				row.file,
				["name", "file_name", "file_url", "attached_to_doctype", "attached_to_name", "custom_lex_scan_status", "custom_lex_checksum"],
				as_dict=True,
			)
			if not file_row or file_row.attached_to_doctype != "LPO Job" or file_row.attached_to_name != self.name:
				frappe.throw(_("Every Job Document must be attached to this Job."), frappe.ValidationError)
			row.file_name = file_row.file_name
			row.scan_status = file_row.custom_lex_scan_status or "Pending"
			row.checksum = file_row.custom_lex_checksum
			if self.job_status != "Draft" and row.scan_status != "Clean":
				frappe.throw(_("All Job Documents must pass security scanning before activation."), frappe.ValidationError)

	def _validate_execution_snapshots(self):
		# Funding activates the job and starts its SLA before an analyst is assigned.
		# Governance snapshots become mandatory at assignment, not at funding, and are
		# not required merely to move through pre-confirmation internal review stages.
		if self.job_status in {"Draft", "Activated"} | PRE_WORK_COMMENCEMENT_STATES:
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
				previous_value = str(previous.get(fieldname) or "")
				if previous_value and previous_value != str(self.get(fieldname) or ""):
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
		if getattr(frappe.flags, "lexocrates_payment_adjustment_service", False) and self.job_status == "On Hold":
			return
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
		if frappe.db.get_value("User", self.assigned_analyst, "user_type") != "System User":
			frappe.throw(_("Assigned Analyst must be a System User."), frappe.ValidationError)
		roles = set(frappe.get_roles(self.assigned_analyst))
		if self.assigned_analyst != "Administrator" and not roles.intersection(ASSIGNABLE_ROLES):
			frappe.throw(
				_("Assigned Analyst must have an LPO role or the System Manager role."),
				frappe.ValidationError,
			)

	def _validate_execution_controls(self):
		if getattr(frappe.flags, "lexocrates_payment_adjustment_service", False) and self.job_status == "On Hold":
			return
		if self.job_status not in ASSIGNMENT_REQUIRED_STATUSES:
			return
		from lex.sop_execution_engine import sync_job_sop_evidence, validate_job_sop_gate
		from lex.workflow_runner import validate_job_workflow_execution

		validate_job_workflow_execution(self)
		sync_job_sop_evidence(self)
		if self.job_status == "QA Review":
			validate_job_sop_gate(self, "pre_qa")
		elif self.job_status in {"Ready for Delivery", "Delivered", "Completed"}:
			validate_job_sop_gate(self, "delivery")

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

	def _validate_quality_and_client_gates(self):
		if self.job_status in {"Ready for Delivery", "Delivered", "Completed"} and self.qa_required:
			approved_review = frappe.db.exists("LPO QA Review", {
				"job": self.name,
				"review_status": "Approved",
				"reviewer_independent": 1,
				"reviewed_document": self.delivery_document,
				"reviewed_document_checksum": self.delivery_document_checksum,
				"reviewed_document_version": self.delivery_document_version,
			})
			if not approved_review:
				previous = self.get_doc_before_save()
				legacy_terminal = bool(
					previous
					and previous.job_status in {"Delivered", "Completed"}
					and previous.job_status == self.job_status
					and previous.delivery_document == self.delivery_document
				)
				if not legacy_terminal:
					frappe.throw(
						_("An approved QA Review for the current delivery version is required before client delivery."),
						frappe.ValidationError,
					)
		if self.job_status in {"Delivered", "Completed"} and self.client_approval_status != "Approved":
			frappe.throw(
				_("Client approval is required before the Job can be delivered or completed."),
				frappe.ValidationError,
			)


def _file_checksum_and_security_status(file_url: str, label: str, *, require_clean: bool) -> str:
	# A URL may have historical File rows after regeneration. Always validate the
	# newest clean managed attachment instead of relying on an unordered get_value call.
	filters = {"file_url": file_url}
	if require_clean and frappe.get_meta("File").has_field("custom_lex_scan_status"):
		filters["custom_lex_scan_status"] = "Clean"
	files = frappe.get_all(
		"File",
		filters=filters,
		pluck="name",
		order_by="creation desc",
		limit=1,
	)
	file_name = files[0] if files else None
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
	checksum = hashlib.sha256(content).hexdigest()
	stored_checksum = file_doc.get("custom_lex_checksum") if file_doc.meta.has_field("custom_lex_checksum") else None
	if require_clean and stored_checksum and checksum != stored_checksum:
		frappe.throw(_("{0} changed after its security scan.").format(label), frappe.ValidationError)
	return checksum


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
