"""Executable controls for SOP-001: Legal Research and Writing.

Client instructions belong to ``Lexocrates Work Intake``.  Research evidence,
review and delivery controls belong to the linked ``LPO Job``.  This module is
deliberately service-scoped so other Lexocrates services retain their own SOPs.
"""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime


LEGAL_RESEARCH_SERVICE = "Legal Research"
SELF_REVIEW_REQUIRED_CHECKS = {
	"All mandatory intake fields were complete before research began",
	"Conflict clearance was confirmed before the assignment was opened",
	"AI-tool restrictions were checked and respected",
	"Every client issue is addressed — no more, no less",
	"Brief Answer directly answers each issue in plain terms",
	"Every conclusion is supported by primary authority",
	"Every case relied upon was noted up and remains good law",
	"Every statute cited was checked against the current in-force version",
	"Unsettled or conflicting law is clearly flagged",
	"Facts and assumptions relied upon are explicitly stated",
	"Header contains client/matter, date, jurisdiction, author, reviewers and confidentiality marking",
	"Memo uses the standard Issue, Brief Answer, Facts, Analysis, Conclusion and Sources order",
	"All citations follow the required style and include pinpoints",
	"Executive summary included where memo exceeds eight pages",
	"Final file is correctly named and ready to file",
}
AI_REVIEW_CHECKS = {
	"Each AI-sourced citation or proposition was verified against a primary source",
	"Material AI assistance is recorded in the research log",
}
FINAL_REVIEW_STAGES = {"Final QA", "Final QC"}
RESEARCH_TURNAROUND_BUSINESS_DAYS = {"Standard": 5, "Complex": 10}
LEGAL_RESEARCH_INTAKE_SNAPSHOT_FIELDS = (
	"research_deliverable_format",
	"research_citation_style",
	"research_data_handling_restrictions",
	"research_instructing_contact_name",
	"research_instructing_contact_role",
	"research_instructing_contact_email",
	"research_confidentiality_level",
	"research_client_prohibits_ai",
)
STAGE_CHECKS = {
	"Peer Review": {"Legal Research Verification", "Citation Checking"},
	"Supervising Counsel Review": {"Senior Legal Review", "Legal Research Verification"},
	"Final QC": {"Citation Checking", "Formatting Review", "Document Completeness"},
}


def is_legal_research(value) -> bool:
	return (value or "").strip() == LEGAL_RESEARCH_SERVICE


def validate_intake(doc) -> None:
	"""Validate the service-specific part of the client-facing intake."""
	if not is_legal_research(doc.get("service_type")):
		return
	mandatory = {
		"legal_questions": _("Legal Question(s)"),
		"factual_background": _("Relevant Factual Background"),
		"deliverable_format": _("Requested Deliverable Format"),
		"citation_style": _("Citation Style"),
		"instructing_contact_name": _("Instructing Individual"),
		"instructing_contact_role": _("Instructing Individual Role"),
		"instructing_contact_email": _("Instructing Individual Email"),
		"data_handling_restrictions": _("Data Handling / Residency Instructions"),
	}
	missing = [label for field, label in mandatory.items() if not (doc.get(field) or "").strip()]
	# Existing records created before SOP-001 fields were introduced must remain
	# serviceable (for payment, delivery and audit updates). New creation is
	# protected both here and at the whitelisted API boundary below.
	is_new_method = getattr(doc, "is_new", None)
	is_new = is_new_method() if callable(is_new_method) else True
	if missing and is_new:
		frappe.throw(
			_("Complete the Legal Research & Writing intake fields before submitting: {0}").format(", ".join(missing)),
			frappe.MandatoryError,
		)


def validate_intake_payload(values: dict) -> None:
	"""Reject API fallbacks: the client must expressly provide SOP-001 instructions."""
	if not is_legal_research(values.get("service_type")):
		return
	mandatory = {
		"legal_questions": _("Legal Question(s)"),
		"factual_background": _("Relevant Factual Background"),
		"deliverable_format": _("Requested Deliverable Format"),
		"citation_style": _("Citation Style"),
		"instructing_contact_name": _("Instructing Individual"),
		"instructing_contact_role": _("Instructing Individual Role"),
		"instructing_contact_email": _("Instructing Individual Email"),
		"data_handling_restrictions": _("Data Handling / Residency Instructions"),
	}
	missing = [label for field, label in mandatory.items() if not (values.get(field) or "").strip()]
	if missing:
		frappe.throw(
			_("Complete the Legal Research & Writing intake fields before submitting: {0}").format(", ".join(missing)),
			frappe.MandatoryError,
		)


def legal_research_turnaround(tier: str, *, start=None):
	"""Return the SOP-001 target deadline for a confirmed complexity tier.

	Urgent work has no unilateral default: the Team Lead must confirm a written
	deadline because SOP-001 permits only an expressly agreed, narrow scope.
	"""
	tier = (tier or "Standard").strip()
	if tier not in {"Standard", "Complex", "Urgent"}:
		frappe.throw(_("Legal Research Complexity Tier must be Standard, Complex or Urgent."), frappe.ValidationError)
	if tier == "Urgent":
		return None, _("Urgent deadline requires written Team Lead confirmation.")
	from lex.sla_engine import add_business_days

	days = RESEARCH_TURNAROUND_BUSINESS_DAYS[tier]
	return add_business_days(start or now_datetime(), days), _("{0} business-day SOP-001 target.").format(days)


def copy_intake_snapshot_to_job(job, intake) -> None:
	"""Persist authoritative client instructions on the operational Job."""
	if not is_legal_research(job.get("job_type")):
		return
	job.research_deliverable_format = intake.deliverable_format
	job.research_citation_style = intake.citation_style
	job.research_data_handling_restrictions = intake.data_handling_restrictions
	job.research_instructing_contact_name = intake.instructing_contact_name
	job.research_instructing_contact_role = intake.instructing_contact_role
	job.research_instructing_contact_email = intake.instructing_contact_email
	job.research_confidentiality_level = intake.confidentiality_level
	job.research_client_prohibits_ai = int(bool(intake.no_ai_tools))
	job.ai_processing_allowed = 0 if intake.no_ai_tools else 1


def validate_intake_snapshot_lock(job) -> None:
	"""Client confidentiality, deliverable and AI instructions cannot be rewritten on a Job."""
	if not is_legal_research(job.get("job_type")) or job.is_new():
		return
	previous = job.get_doc_before_save()
	if not previous:
		return
	changed = [field for field in LEGAL_RESEARCH_INTAKE_SNAPSHOT_FIELDS if job.has_value_changed(field)]
	if changed:
		labels = [job.meta.get_label(field) or field for field in changed]
		frappe.throw(_("SOP-001 client instructions are immutable on the Job: {0}").format(", ".join(labels)), frappe.PermissionError)


def validate_execution(job) -> None:
	"""Block a Legal Research Job from QA/delivery without SOP evidence."""
	if not is_legal_research(job.get("job_type")):
		return
	if job.get("job_status") not in {"QA Review", "Ready for Delivery", "Delivered", "Completed"}:
		return
	missing = []
	if not (job.get("research_plan") or "").strip():
		missing.append(_("Internal Research Plan"))
	if not job.get("research_log"):
		missing.append(_("Research Log"))
	if not job.get("primary_sources_verified"):
		missing.append(_("Primary Sources Verified"))
	if not job.get("secondary_sources_reviewed"):
		missing.append(_("Secondary Sources Used Only as Support"))
	if not job.get("noting_up_completed"):
		missing.append(_("Noting-Up and Currency Checks"))
	if not job.get("peer_reviewer"):
		missing.append(_("Peer Reviewer"))
	if not job.get("supervising_counsel"):
		missing.append(_("Supervising Counsel"))
	if job.get("job_status") in {"Ready for Delivery", "Delivered", "Completed"} and not job.get("research_archive_complete"):
		missing.append(_("Research archive confirmation"))
	if job.get("job_status") in {"Ready for Delivery", "Delivered", "Completed"} and not (job.get("research_archive_note") or "").strip():
		missing.append(_("Research archive / Matter folder note"))
	uncleared_currency = [
		row.source_checked
		for row in job.get("research_log")
		if row.authority_type in {"Case Currency Check", "Statute Currency Check"}
		and (not row.currency_checked or not (row.currency_result or "").strip())
	]
	if uncleared_currency:
		missing.append(_("completed currency results for: {0}").format(", ".join(uncleared_currency)))
	unverified_ai = [
		row.source_checked for row in job.get("research_log")
		if row.ai_assisted and not row.primary_source_verified
	]
	if unverified_ai:
		missing.append(_("primary-source verification for AI-assisted entries: {0}").format(", ".join(unverified_ai)))
	if missing:
		frappe.throw(
			_("SOP-001 evidence is incomplete: {0}").format(", ".join(missing)),
			frappe.ValidationError,
		)
	if job.get("peer_reviewer") == job.get("assigned_analyst"):
		frappe.throw(_("The Peer Reviewer must be independent from the assigned Legal Associate."), frappe.ValidationError)
	if job.get("supervising_counsel") == job.get("assigned_analyst"):
		frappe.throw(_("Supervising Counsel must be independent from the assigned Legal Associate."), frappe.ValidationError)
	if job.get("supervising_counsel"):
		roles = set(frappe.get_roles(job.supervising_counsel))
		if job.supervising_counsel != "Administrator" and not roles.intersection({"LPO_Admin", "LPO_Manager", "System Manager"}):
			frappe.throw(_("Supervising Counsel must hold an authorized management role."), frappe.ValidationError)
	_validate_delivery_filename(job)


def _validate_delivery_filename(job) -> None:
	if job.get("job_status") not in {"Ready for Delivery", "Delivered", "Completed"} or not job.get("delivery_document"):
		return
	file_name = frappe.db.get_value("File", {"file_url": job.delivery_document}, "file_name") or ""
	if not re.match(r"^[A-Za-z0-9]+-MATTER-[A-Za-z0-9-]+-ResearchMemo-\d{8}-v\d+\.(pdf|docx)$", file_name, re.IGNORECASE):
		frappe.throw(
			_("SOP-001 final memo filename must follow [ClientCode]-[MatterRef]-ResearchMemo-[YYYYMMDD]-v[X].pdf or .docx."),
			frappe.ValidationError,
		)


def validate_review(review, job) -> None:
	"""Apply the four mandatory SOP-001 review gates to Legal Research work."""
	if not is_legal_research(job.get("job_type")):
		return
	stage = review.get("review_stage") or "Final QC"
	reviewer = review.get("reviewer")
	if stage == "Self Review":
		if reviewer != job.get("assigned_analyst"):
			frappe.throw(_("The assigned Legal Associate must complete the SOP-001 self-review."), frappe.PermissionError)
		return
	if stage == "Peer Review":
		if not job.get("peer_reviewer"):
			frappe.throw(_("Assign a Peer Reviewer on the Legal Research Job before recording peer review."), frappe.ValidationError)
		if reviewer != job.get("peer_reviewer"):
			frappe.throw(_("Only the assigned Peer Reviewer can complete this review."), frappe.PermissionError)
		if review.get("review_status") == "Approved" and not _review_is_approved(job.name, "Self Review"):
			frappe.throw(_("SOP-001 requires the Legal Associate's approved Self Review before Peer Review approval."), frappe.ValidationError)
		return
	if stage == "Supervising Counsel Review":
		if not job.get("supervising_counsel"):
			frappe.throw(_("Assign Supervising Counsel on the Legal Research Job before recording counsel review."), frappe.ValidationError)
		if reviewer != job.get("supervising_counsel"):
			frappe.throw(_("Only the assigned Supervising Counsel can complete this review."), frappe.PermissionError)
		if review.get("review_status") == "Approved" and not _review_is_approved(job.name, "Peer Review"):
			frappe.throw(_("SOP-001 requires approved Peer Review before Supervising Counsel approval."), frappe.ValidationError)


def _review_is_approved(job_name: str, stage: str) -> bool:
	return bool(frappe.db.exists("LPO QA Review", {"job": job_name, "review_stage": stage, "review_status": "Approved"}))


def validate_generated_memo(markdown_text: str) -> None:
	"""Require the SOP-001 skeleton when Lexocrates generates the final memo."""
	text = (markdown_text or "").lower()
	required_sections = ("issue", "brief answer", "facts", "analysis", "conclusion", "sources")
	missing = [section.title() for section in required_sections if section not in text]
	if missing:
		frappe.throw(
			_("SOP-001 Research Memo is missing required section(s): {0}.").format(", ".join(missing)),
			frappe.ValidationError,
		)


def validate_self_review_checklist(review, job) -> None:
	if not is_legal_research(job.get("job_type")) or review.get("review_stage") != "Self Review":
		return
	results = {row.check_name: row.result for row in review.get("qa_checklist")}
	required = set(SELF_REVIEW_REQUIRED_CHECKS)
	if any(row.ai_assisted for row in job.get("research_log")):
		required.update(AI_REVIEW_CHECKS)
	confirmed = {row.check_name: bool(row.confirmed) for row in review.get("qa_checklist")}
	missing = sorted(name for name in required if results.get(name) != "Pass" or not confirmed.get(name))
	if missing:
		frappe.throw(
			_("SOP-001 self-review cannot be approved until every required check passes: {0}").format(", ".join(missing)),
			frappe.ValidationError,
		)


def validate_final_review_gate(review, job) -> None:
	if not is_legal_research(job.get("job_type")) or review.get("review_stage") not in FINAL_REVIEW_STAGES:
		return
	if review.get("review_status") != "Approved":
		return
	for stage in ("Self Review", "Peer Review", "Supervising Counsel Review"):
		if not frappe.db.exists("LPO QA Review", {"job": job.name, "review_stage": stage, "review_status": "Approved"}):
			frappe.throw(_("SOP-001 requires an approved {0} before Final QC.").format(stage), frappe.ValidationError)


def populate_self_review_checklist(review, job) -> None:
	"""Give the drafter the exact Appendix A checklist instead of a blank grid."""
	if not is_legal_research(job.get("job_type")) or review.get("qa_checklist"):
		return
	stage = review.get("review_stage") or "Final QC"
	if stage == "Final QA":
		stage = "Final QC"
	checks = SELF_REVIEW_REQUIRED_CHECKS | AI_REVIEW_CHECKS if stage == "Self Review" else STAGE_CHECKS.get(stage, set())
	for name in sorted(checks):
		review.append("qa_checklist", {"check_name": name, "confirmed": 0, "result": "N/A"})


def validate_stage_checklist(review, job) -> None:
	"""Require the SOP table's documented verification at each non-self-review gate."""
	if not is_legal_research(job.get("job_type")):
		return
	stage = review.get("review_stage") or "Final QC"
	if stage == "Final QA":
		stage = "Final QC"
	required = STAGE_CHECKS.get(stage, set())
	if not required:
		return
	results = {row.check_name: row.result for row in review.get("qa_checklist")}
	confirmed = {row.check_name: bool(row.confirmed) for row in review.get("qa_checklist")}
	missing = sorted(name for name in required if results.get(name) != "Pass" or not confirmed.get(name))
	if missing:
		frappe.throw(
			_("SOP-001 {0} cannot be approved until these verification checks are confirmed and pass: {1}").format(stage, ", ".join(missing)),
			frappe.ValidationError,
		)
