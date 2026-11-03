from __future__ import annotations

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import now_datetime


DEFAULT_WORKFLOW_ID = "LEX-LEGAL-OPS-DEFAULT"
DEFAULT_SOP_ID = "LEX-LEGAL-DELIVERY-DEFAULT"

# SOP-001 is enforced by lex.legal_research_sop; SOP-002 through SOP-006 are
# enforced by lex.service_sop. This maps each Job Type to its SOP code so the
# catalog (LPO SOP / LPO SOP Version) mirrors those real, already-enforced SOPs
# instead of every Job Type sharing one generic placeholder version.
JOB_TYPE_SOP_IDS = {
	"Legal Research": "SOP-001",
	"Litigation Support": "SOP-002",
	"Contract Review": "SOP-003",
	"Document Review": "SOP-004",
	"Compliance Review": "SOP-005",
	"Drafting": "SOP-006",
}


def _latest_policy_name(doctype: str, filters: dict, order_by: str) -> str | None:
	rows = frappe.get_all(
		doctype,
		filters=filters,
		pluck="name",
		order_by=order_by,
		limit_page_length=1,
	)
	return rows[0] if rows else None


def _get_or_create_sop(sop_code: str) -> str:
	name = frappe.db.get_value("LPO SOP", {"sop_id": sop_code}, "name")
	if not name:
		name = frappe.get_doc({"doctype": "LPO SOP", "sop_id": sop_code}).insert(ignore_permissions=True).name
	return str(name)


def _effective_version_for_sop(sop_name: str | None) -> str | None:
	if not sop_name:
		return None
	return _latest_policy_name("LPO SOP Version", {"sop_id": sop_name, "status": "Effective"}, "modified desc")


def _legal_research_steps() -> list[dict]:
	from lex.legal_research_sop import AI_REVIEW_CHECKS, SELF_REVIEW_REQUIRED_CHECKS, STAGE_CHECKS

	steps = [
		{
			"step_id": "scope", "title": "Confirm funded scope and SOP-001 client instructions",
			"is_mandatory": True, "requires_evidence": True, "role_scope": "LPO Analyst",
		},
		{
			"step_id": "sources", "title": "Verify clean sources: every case noted up, every statute checked in-force",
			"is_mandatory": True, "requires_evidence": True, "role_scope": "LPO Analyst",
		},
		{
			"step_id": "self_review", "title": "Legal Associate Self Review",
			"instructions": "; ".join(sorted(SELF_REVIEW_REQUIRED_CHECKS | AI_REVIEW_CHECKS)),
			"is_mandatory": True, "role_scope": "LPO Analyst",
		},
	]
	for stage, checks in STAGE_CHECKS.items():
		steps.append({
			"step_id": stage.lower().replace(" ", "_"), "title": stage,
			"instructions": "; ".join(sorted(checks)),
			"is_mandatory": True, "role_scope": "LPO Manager",
		})
	steps.append({
		"step_id": "deliverable",
		"title": "File versioned Research Memo ([ClientCode]-[MatterRef]-ResearchMemo-[YYYYMMDD]-v[X])",
		"is_mandatory": True, "requires_evidence": True, "role_scope": "LPO Analyst",
	})
	return steps


def _service_sop_steps(job_type: str) -> list[dict]:
	from lex.service_sop import PROFILES, SELF_REVIEW_CHECKS, STAGE_CHECKS

	config = PROFILES[job_type]
	steps = [
		{
			"step_id": "start_controls",
			"title": "Verify start controls: {0}".format(", ".join(config["start_controls"])),
			"is_mandatory": True, "requires_evidence": True, "role_scope": "LPO Analyst",
		},
		{
			"step_id": "self_review", "title": "Self Review",
			"instructions": "; ".join(SELF_REVIEW_CHECKS.get(job_type, ())),
			"is_mandatory": True, "role_scope": "LPO Analyst",
		},
	]
	stage_sequence = ["Peer Review"]
	if job_type == "Document Review":
		stage_sequence.append("QC Sampling")
	stage_sequence += ["Supervising Counsel Review", "Final QC"]
	for stage in stage_sequence:
		steps.append({
			"step_id": stage.lower().replace(" ", "_"), "title": stage,
			"instructions": STAGE_CHECKS.get(stage, ""),
			"is_mandatory": True, "role_scope": "LPO Manager",
		})
	steps.append({
		"step_id": "delivery_controls",
		"title": "Verify delivery controls: {0}".format(", ".join(config["delivery_controls"])),
		"is_mandatory": True, "requires_evidence": True, "role_scope": "LPO Manager",
	})
	return steps


def ensure_service_sop_versions() -> None:
	"""Seed SOP-001 through SOP-006 as distinct, Effective LPO SOP Versions.

	Each mirrors the checks already enforced in lex.legal_research_sop /
	lex.service_sop, so the catalog stops defaulting every Job Type to the
	same generic placeholder steps.
	"""
	if not all(frappe.db.exists("DocType", doctype) for doctype in ("LPO SOP", "LPO SOP Version")):
		return
	for job_type, sop_code in JOB_TYPE_SOP_IDS.items():
		sop_name = _get_or_create_sop(sop_code)
		if _effective_version_for_sop(sop_name):
			continue
		steps = _legal_research_steps() if job_type == "Legal Research" else _service_sop_steps(job_type)
		frappe.get_doc({
			"doctype": "LPO SOP Version",
			"sop_id": sop_name,
			"version": "1.0",
			"status": "Effective",
			"steps_json": json.dumps(steps, indent=2),
		}).insert(ignore_permissions=True)


def get_sop_version_for_job_type(job_type: str | None) -> str | None:
	"""Return the Effective SOP Version for this Job Type's SOP-001..006, or None if unmapped."""
	sop_code = JOB_TYPE_SOP_IDS.get((job_type or "").strip())
	if not sop_code:
		return None
	ensure_service_sop_versions()
	return _effective_version_for_sop(frappe.db.get_value("LPO SOP", {"sop_id": sop_code}, "name"))


def get_default_sop_version() -> str | None:
	"""Return the generic placeholder SOP Version (not any service-specific SOP-001..006)."""
	return _effective_version_for_sop(frappe.db.get_value("LPO SOP", {"sop_id": DEFAULT_SOP_ID}, "name"))


def ensure_default_execution_policies():
	"""Seed a minimal published Workflow and effective SOP for fresh installations."""
	if not all(
		frappe.db.exists("DocType", doctype)
		for doctype in ("LPO Workflow Definition", "LPO Workflow Version", "LPO SOP", "LPO SOP Version")
	):
		return

	workflow_version = _latest_policy_name(
		"LPO Workflow Version", {"status": "Published"}, "published_at desc, modified desc"
	)
	if not workflow_version:
		workflow = frappe.db.get_value(
			"LPO Workflow Definition", {"workflow_id": DEFAULT_WORKFLOW_ID}, "name"
		)
		if not workflow:
			workflow = frappe.get_doc(
				{"doctype": "LPO Workflow Definition", "workflow_id": DEFAULT_WORKFLOW_ID}
			).insert(ignore_permissions=True).name
		graph = {
			"nodes": [
				{"id": "activated", "type": "Trigger", "is_start": True, "title": "Job Activated"},
				{"id": "assigned", "type": "Human", "title": "Assign Analyst"},
				{"id": "execution", "type": "Human", "title": "Legal Operations Execution"},
				{"id": "qa", "type": "Human", "title": "Independent QA Review"},
				{"id": "client", "type": "Human", "title": "Client Approval"},
				{"id": "complete", "type": "Action", "title": "Complete and Deliver"},
			],
			"edges": [
				{"source": "activated", "target": "assigned"},
				{"source": "assigned", "target": "execution"},
				{"source": "execution", "target": "qa"},
				{"source": "qa", "target": "client"},
				{"source": "client", "target": "complete"},
			],
		}
		canonical = json.dumps(graph, sort_keys=True, separators=(",", ":"))
		workflow_version = frappe.get_doc(
			{
				"doctype": "LPO Workflow Version",
				"workflow_id": workflow,
				"version": "1.0",
				"graph_json": json.dumps(graph, indent=2),
				"graph_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
				"status": "Published",
				"approved_by": "Administrator",
				"published_at": now_datetime(),
			}
		).insert(ignore_permissions=True).name

	default_sop = frappe.db.get_value("LPO SOP", {"sop_id": DEFAULT_SOP_ID}, "name")
	sop_version = _effective_version_for_sop(default_sop)
	if not sop_version:
		sop = default_sop or frappe.get_doc({"doctype": "LPO SOP", "sop_id": DEFAULT_SOP_ID}).insert(ignore_permissions=True).name
		steps = [
			{"step_id": "scope", "title": "Confirm funded scope and instructions", "is_mandatory": True, "role_scope": "LPO Analyst"},
			{"step_id": "sources", "title": "Verify clean source documents and citations", "is_mandatory": True, "role_scope": "LPO Analyst"},
			{"step_id": "deliverable", "title": "Prepare versioned delivery document", "is_mandatory": True, "role_scope": "LPO Analyst"},
			{"step_id": "qa", "title": "Complete independent QA review", "is_mandatory": True, "role_scope": "LPO Manager"},
		]
		sop_version = frappe.get_doc(
			{
				"doctype": "LPO SOP Version",
				"sop_id": sop,
				"version": "1.0",
				"status": "Effective",
				"steps_json": json.dumps(steps, indent=2),
			}
		).insert(ignore_permissions=True).name

	return {"workflow_version": workflow_version, "sop_version": sop_version}


def get_execution_policy_snapshots() -> tuple[str, str]:
	ensure_default_execution_policies()
	workflow_version = _latest_policy_name(
		"LPO Workflow Version", {"status": "Published"}, "published_at desc, modified desc"
	)
	default_sop = frappe.db.get_value("LPO SOP", {"sop_id": DEFAULT_SOP_ID}, "name")
	sop_version = _effective_version_for_sop(default_sop)
	if not workflow_version or not sop_version:
		frappe.throw(_("Published Workflow and effective SOP policies are not configured."), frappe.ValidationError)
	# Autoincrement DocTypes can return integer names at insert time while Link fields
	# reload as strings. Normalize them to keep immutable snapshot comparisons stable.
	return str(workflow_version), str(sop_version)
