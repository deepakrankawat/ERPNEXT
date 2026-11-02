"""Executable controls for SOP-002 through SOP-006.

Client instructions are collected on Work Intake.  The operational evidence,
independent verification, escalation trail and release controls live on the
linked Job, which is the server-side source of truth.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, getdate, now_datetime


PROFILES = {
	"Litigation Support": {
		"code": "SOP-002", "coordinator": "Docketing / Deadlines Coordinator",
		"fields": {
			"court_tribunal": "Court or tribunal", "court_file_number": "Court file number or uncommenced confirmation",
			"party_details": "All parties, roles and represented side", "procedural_stage": "Current procedural stage",
			"known_deadlines": "Known deadlines or limitation dates", "supporting_documents": "Supporting court documents and orders",
			"deliverable_type": "Requested deliverable type and format", "data_handling_restrictions": "Data residency and handling restrictions",
		},
		"standard_days": 5, "complex_days": 7, "warning_days": (14, 7, 2),
		"start_controls": ("Court / Limitation Deadline",), "delivery_controls": ("Litigation Closure / Filing Record",),
	},
	"Contract Review": {
		"code": "SOP-003", "coordinator": "Contract Management Coordinator",
		"fields": {
			"contract_type": "Contract type", "counterparty_names": "Counterparty name(s)",
			"governing_law": "Governing law and jurisdiction", "business_terms": "Key business terms or instructions",
			"key_dates": "Renewal date, notice period and key obligations", "supporting_documents": "Contract version, template and supporting documents",
			"deliverable_type": "Requested deliverable type and format", "data_handling_restrictions": "Data residency and handling restrictions",
		},
		"standard_days": 4, "complex_days": 8, "warning_days": (90, 60, 30),
		"start_controls": ("Key Date / Obligation",), "delivery_controls": ("Contract Closure / Repository Record",),
	},
	"Document Review": {
		"code": "SOP-004", "coordinator": "Review QC / Privilege Coordinator",
		"fields": {
			"matter_context": "Matter / litigation or regulatory context", "custodians_data_sources": "Custodians and data sources",
			"known_parties": "Known parties relevant to conflict screening", "review_protocol": "Review protocol and coding scheme",
			"volume_format": "Document / ESI volume and format", "preservation_confirmation": "Litigation Hold / preservation confirmation",
			"production_specs": "Production deadline, Bates and format requirements", "supporting_documents": "Protective order, prior privilege log or search terms",
			"data_handling_restrictions": "Data residency and handling restrictions",
		},
		"standard_days": 3, "complex_days": 5, "warning_days": (10, 5, 2),
		"start_controls": ("Preservation / Hold", "Review Protocol"), "delivery_controls": ("Privilege / Production Record", "QC Sampling Record"),
	},
	"Compliance Review": {
		"code": "SOP-005", "coordinator": "Compliance Calendar Coordinator",
		"fields": {
			"industry_regime": "Industry and applicable regulatory regime", "operating_jurisdictions": "Jurisdictions of operation",
			"current_policies": "Current policies or compliance program documents", "regulatory_dates": "Regulatory filing, renewal and reporting dates",
			"supporting_documents": "Regulator correspondence and supporting documents", "deliverable_type": "Requested deliverable type",
			"data_handling_restrictions": "Data residency and handling restrictions",
		},
		"standard_days": 7, "complex_days": 15, "warning_days": (60, 30, 10),
		"start_controls": ("Regulatory Date / Renewal",), "delivery_controls": ("Regulatory Mapping / Gap Assessment",),
	},
	"Drafting": {
		"code": "SOP-006", "coordinator": "Task / Deadline Coordinator",
		"fields": {
			"task_category": "Task type / category", "task_instructions": "Task description and specific instructions",
			"recurrence_schedule": "One-time or recurring schedule and standing instructions", "task_deadlines": "Deadline or scheduling constraint",
			"required_access": "Required documents or system access", "supporting_documents": "Source documents and templates",
			"deliverable_type": "Requested deliverable format", "data_handling_restrictions": "Data residency and handling restrictions",
			"review_tier": "Review tier (Routine, Client-Facing or Filing/Court-Facing)",
		},
		"standard_days": 1, "complex_days": 2, "warning_days": (7, 2, 1),
		"start_controls": ("Task Deadline / Recurrence",), "delivery_controls": ("Task Closure / Next Occurrence",),
	},
}


SELF_REVIEW_CHECKS = {
	"Litigation Support": (
		"Court file, style of cause, party names and every deadline match independently verified records",
		"Court-rule, filing-form, confidentiality and procedural requirements were checked",
		"Every AI-derived procedural detail, citation or rule reference was verified against a primary source",
	),
	"Contract Review": (
		"Every clause was checked against the Clause Library and each deviation has a Standard, Negotiable or High-Risk rating",
		"Every High-Risk issue has a plain-language explanation and proposed fallback; every substantive redline has a rationale",
		"Party names, defined terms and key dates match the contract or independently verified instruction",
	),
	"Document Review": (
		"Coding follows the confirmed protocol and each potentially privileged document has a documented privilege basis",
		"Ambiguous responsiveness or privilege calls were escalated instead of guessed",
		"Human QC sampling, production specifications, Bates sequence and privileged-document safeguards were checked",
	),
	"Compliance Review": (
		"Every applicable requirement is mapped to evidence, with a documented rating of Complete, Partially Compliant, Non-Compliant or Not Assessed",
		"Missing evidence is recorded as Not Assessed and each regulatory source was checked for currency",
		"Each jurisdiction is assessed separately and ambiguous questions or active breaches are escalated",
	),
	"Drafting": (
		"Task facts, deadline, recurrence and source materials were verified before execution",
		"Output was checked against the applicable template and the review tier was not downgraded",
		"For recurring work, the next occurrence and standing instructions were confirmed before closure",
	),
}

STAGE_CHECKS = {
	"Peer Review": "Independent peer review of reasoning, accuracy, consistency and applicable SOP controls completed",
	"QC Sampling": "QC sample was independently re-coded; error rate and any batch re-review were documented",
	"Supervising Counsel Review": "Supervising Counsel reviewed substantive risk, privilege or escalation issues",
	"Final QC": "Final formatting, confidentiality marking, file naming, cover note and archive readiness verified",
}


def profile(service_type: str | None):
	return PROFILES.get((service_type or "").strip())


def is_profiled_service(service_type: str | None) -> bool:
	return bool(profile(service_type))


def parse_details(value) -> dict:
	if isinstance(value, dict):
		return value
	if not value:
		return {}
	try:
		parsed = json.loads(value)
	except (TypeError, ValueError):
		frappe.throw(_("Service-specific instructions must be valid structured data."), frappe.ValidationError)
	if not isinstance(parsed, dict):
		frappe.throw(_("Service-specific instructions must be an object."), frappe.ValidationError)
	return parsed


def validate_intake_payload(service_type: str, details) -> dict:
	config = profile(service_type)
	parsed = parse_details(details)
	if not config:
		return parsed
	missing = [label for key, label in config["fields"].items() if not str(parsed.get(key) or "").strip()]
	if missing:
		frappe.throw(
			_("Complete the {0} intake fields before submitting: {1}").format(config["code"], ", ".join(missing)),
			frappe.MandatoryError,
		)
	if service_type == "Drafting" and parsed.get("review_tier") not in {"Routine", "Client-Facing", "Filing/Court-Facing"}:
		frappe.throw(_("Choose a valid SOP-006 Review Tier."), frappe.ValidationError)
	# Commercial pricing is already controlled by the fixed-price server process.
	parsed.setdefault("fee_budget_reference", "Lexocrates confirmed fixed-price workflow")
	return parsed


def copy_intake_snapshot_to_job(job, intake) -> None:
	config = profile(job.get("job_type"))
	if not config:
		return
	job.service_sop_code = config["code"]
	job.service_sop_instruction_snapshot = intake.service_sop_details
	job.service_sop_coordinator_role = config["coordinator"]
	details = parse_details(intake.service_sop_details)
	job.service_sop_review_tier = details.get("review_tier") or "Full"
	job.service_sop_client_prohibits_ai = int(bool(intake.no_ai_tools))
	job.ai_processing_allowed = 0 if intake.no_ai_tools else 1
	set_turnaround(job)


def set_turnaround(job) -> None:
	config = profile(job.get("job_type"))
	if not config:
		return
	tier = job.get("service_sop_complexity_tier") or "Standard"
	if tier not in {"Standard", "Complex", "Urgent"}:
		frappe.throw(_("Complexity Tier must be Standard, Complex or Urgent."), frappe.ValidationError)
	if tier == "Urgent":
		job.service_sop_target_business_days = 0
		job.service_sop_turnaround_note = _("Urgent scope and deadline require written Team Lead confirmation; review controls cannot be skipped.")
		return
	job.service_sop_target_business_days = config["standard_days"] if tier == "Standard" else config["complex_days"]
	job.service_sop_turnaround_note = _("{0} planned SOP target: {1} business day(s).").format(config["code"], job.service_sop_target_business_days)


def _controls(job):
	return list(job.get("service_sop_controls") or [])


def _control(job, control_type):
	return next((row for row in _controls(job) if (row.control_type or "").strip() == control_type), None)


def _require_verified_control(job, control_type, *, require_date=False):
	row = _control(job, control_type)
	if not row:
		return _("{0} control record").format(control_type)
	if not row.independently_verified or not row.verified_by or not row.verification_date:
		return _("independently verified {0}").format(control_type)
	if not (row.source_reference or "").strip():
		return _("source reference for {0}").format(control_type)
	if require_date and not row.event_date:
		return _("relevant date for {0}").format(control_type)
	return None


def _required_peer_and_counsel(job):
	if job.job_type == "Drafting":
		tier = job.get("service_sop_review_tier") or "Filing/Court-Facing"
		return tier in {"Client-Facing", "Filing/Court-Facing"}, tier == "Filing/Court-Facing"
	return True, True


def _matter_conflict_cleared(job):
	if not job.get("engagement"):
		return False
	return frappe.db.get_value("LPO Matter", job.engagement, "conflict_check_status") in {"Cleared", "No Match Found"}


def normalize_controls(job) -> None:
	config = profile(job.get("job_type"))
	if not config:
		return
	intervals = " / ".join(str(day) for day in config["warning_days"]) + " business days"
	for row in _controls(job):
		if not row.warning_intervals:
			row.warning_intervals = intervals
		if row.independently_verified and row.verified_by and row.verification_date and row.status == "Pending":
			row.status = "Verified"


def validate_execution(job) -> None:
	config = profile(job.get("job_type"))
	if not config or job.get("job_status") not in {"In Progress", "QA Review", "Ready for Delivery", "Delivered", "Completed"}:
		return
	normalize_controls(job)
	missing = []
	if not job.get("service_sop_preconditions_verified"):
		missing.append(_("verified {0} preconditions").format(config["code"]))
	if not (job.get("service_sop_coordinator") or "").strip():
		missing.append(_("assigned {0}").format(config["coordinator"]))
	if not job.get("service_sop_data_residency_checked"):
		missing.append(_("data residency and handling check"))
	if not _matter_conflict_cleared(job):
		missing.append(_("Matter conflict clearance"))
	if not (job.get("service_sop_work_log") or "").strip():
		missing.append(_("contemporaneous work log"))
	peer_needed, counsel_needed = _required_peer_and_counsel(job)
	if peer_needed and not job.get("peer_reviewer"):
		missing.append(_("named Peer Reviewer"))
	if counsel_needed and not job.get("supervising_counsel"):
		missing.append(_("named Supervising Counsel"))
	for control_type in config["start_controls"]:
		issue = _require_verified_control(job, control_type, require_date=control_type != "Review Protocol")
		if issue:
			missing.append(issue)
	if job.get("service_sop_client_prohibits_ai") and job.get("service_sop_ai_used"):
		missing.append(_("removal of prohibited AI / TAR use"))
	if job.get("service_sop_ai_used") and not (job.get("service_sop_ai_verification_note") or "").strip():
		missing.append(_("AI / TAR independent verification note"))
	if job.get("job_status") in {"Ready for Delivery", "Delivered", "Completed"}:
		if not job.get("service_sop_archive_complete"):
			missing.append(_("archive confirmation"))
		if not (job.get("service_sop_archive_note") or "").strip():
			missing.append(_("archive / Matter folder note"))
		if not (job.get("service_sop_delivery_cover_note") or "").strip():
			missing.append(_("client cover note / outstanding-items statement"))
		for control_type in config["delivery_controls"]:
			issue = _require_verified_control(job, control_type)
			if issue:
				missing.append(issue)
	if missing:
		frappe.throw(_("{0} evidence is incomplete: {1}").format(config["code"], ", ".join(missing)), frappe.ValidationError)


def required_review_stages(job) -> tuple[str, ...]:
	if not profile(job.get("job_type")):
		return ()
	if job.job_type == "Document Review":
		return ("Self Review", "Peer Review", "QC Sampling", "Supervising Counsel Review", "Final QC")
	if job.job_type == "Drafting":
		tier = job.get("service_sop_review_tier") or "Filing/Court-Facing"
		return {
			"Routine": ("Self Review", "Final QC"),
			"Client-Facing": ("Self Review", "Peer Review", "Final QC"),
			"Filing/Court-Facing": ("Self Review", "Peer Review", "Supervising Counsel Review", "Final QC"),
		}.get(tier, ("Self Review", "Peer Review", "Supervising Counsel Review", "Final QC"))
	return ("Self Review", "Peer Review", "Supervising Counsel Review", "Final QC")


def validate_review(review, job) -> None:
	if not profile(job.get("job_type")):
		return
	stage = review.get("review_stage") or "Final QC"
	if stage == "QC Sampling" and job.job_type != "Document Review":
		frappe.throw(_("QC Sampling applies only to SOP-004 Document Review."), frappe.ValidationError)
	if stage == "Peer Review" and review.reviewer != job.get("peer_reviewer"):
		frappe.throw(_("Only the assigned Peer Reviewer can approve this SOP review."), frappe.PermissionError)
	if stage == "Supervising Counsel Review" and review.reviewer != job.get("supervising_counsel"):
		frappe.throw(_("Only the assigned Supervising Counsel can approve this SOP review."), frappe.PermissionError)
	if review.get("review_status") != "Approved":
		return
	stages = required_review_stages(job)
	if stage not in stages:
		frappe.throw(_("This review stage is not applicable to the selected SOP service/tier."), frappe.ValidationError)
	index = stages.index(stage)
	for required in stages[:index]:
		if not frappe.db.exists("LPO QA Review", {"job": job.name, "review_stage": required, "review_status": "Approved"}):
			frappe.throw(_("{0} requires approved {1} first.").format(profile(job.job_type)["code"], required), frappe.ValidationError)


def _expected_checklist_items(review, job) -> tuple[str, ...]:
	if not profile(job.get("job_type")):
		return ()
	stage = review.get("review_stage") or "Final QC"
	if stage == "Self Review":
		return SELF_REVIEW_CHECKS.get(job.job_type, ())
	item = STAGE_CHECKS.get(stage)
	return (item,) if item and stage in required_review_stages(job) else ()


def populate_review_checklist(review, job) -> None:
	if review.get("qa_checklist") is None:
		return
	existing = {row.check_name for row in review.qa_checklist}
	for check_name in _expected_checklist_items(review, job):
		if check_name not in existing:
			review.append("qa_checklist", {"check_name": check_name, "confirmed": 0, "result": "N/A"})


def validate_review_checklist(review, job) -> None:
	if not profile(job.get("job_type")) or review.get("review_status") != "Approved":
		return
	expected = set(_expected_checklist_items(review, job))
	if not expected:
		return
	passed = {row.check_name for row in review.qa_checklist if row.confirmed and row.result == "Pass"}
	missing = expected - passed
	if missing:
		frappe.throw(
			_("{0} approval requires confirmed Pass checklist items: {1}").format(profile(job.job_type)["code"], ", ".join(sorted(missing))),
			frappe.ValidationError,
		)


def validate_delivery_reviews(job) -> None:
	for stage in required_review_stages(job):
		if not frappe.db.exists("LPO QA Review", {"job": job.name, "review_stage": stage, "review_status": "Approved"}):
			frappe.throw(_("{0} requires approved {1} before delivery.").format(profile(job.job_type)["code"], stage), frappe.ValidationError)


def update_kpis(job) -> None:
	if not profile(job.get("job_type")):
		return
	controls = _controls(job)
	verified = [row for row in controls if row.independently_verified and row.verified_by and row.verification_date]
	job.service_sop_kpi_control_verification = round((len(verified) / len(controls) * 100), 2) if controls else 0
	job.service_sop_kpi_ai_verification = int(not job.get("service_sop_ai_used") or bool(job.get("service_sop_ai_verification_note")))
	if job.get("name"):
		job.service_sop_kpi_escalation_count = frappe.db.count("LPO Service Escalation", {"job": job.name})
		job.service_sop_kpi_first_pass_qc = int(not frappe.db.exists("LPO QA Review", {"job": job.name, "review_status": ["in", ["Changes Required", "Rejected"]]}))
	if job.get("completed_on") and job.get("confirmed_delivery_date"):
		job.service_sop_kpi_turnaround_met = int(job.completed_on <= job.confirmed_delivery_date)


def monitor_service_sop_controls() -> int:
	"""Daily warning/escalation monitor for independently recorded SOP dates."""
	from lex.lex.doctype.lpo_service_escalation.lpo_service_escalation import raise_escalation
	from lex.sla_engine import add_business_days

	count = 0
	active = {"In Progress", "QA Review", "Ready for Delivery", "On Hold", "SLA Paused"}
	for row in frappe.get_all("LPO Job", filters={"job_status": ["in", list(active)]}, fields=["name", "job_type"]):
		config = profile(row.job_type)
		if not config:
			continue
		job = frappe.get_doc("LPO Job", row.name)
		for control in _controls(job):
			if not control.event_date or control.status in {"Resolved"}:
				continue
			due = getdate(control.event_date)
			today = getdate()
			at_risk = due < today
			warning = at_risk or any(due <= getdate(add_business_days(today, days)) for days in config["warning_days"])
			if not warning:
				continue
			reason = _("{0}: {1} is {2}.").format(config["code"], control.control_type, "overdue" if at_risk else _("approaching on {0}").format(due))
			if frappe.db.exists("LPO Service Escalation", {"job": job.name, "status": "Open", "escalation_reason": reason}):
				continue
			try:
				escalation = raise_escalation(job.name, "1", reason)
				control.status = "At Risk"
				control.escalation = escalation["name"]
				job.save(ignore_permissions=True)
				count += 1
			except Exception:
				frappe.log_error(frappe.get_traceback(), "Service SOP control warning")
	return count
