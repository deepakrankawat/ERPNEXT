from __future__ import annotations

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import now_datetime


DEFAULT_WORKFLOW_ID = "LEX-LEGAL-OPS-DEFAULT"
DEFAULT_SOP_ID = "LEX-LEGAL-DELIVERY-DEFAULT"


def _latest_policy_name(doctype: str, filters: dict, order_by: str) -> str | None:
	rows = frappe.get_all(
		doctype,
		filters=filters,
		pluck="name",
		order_by=order_by,
		limit_page_length=1,
	)
	return rows[0] if rows else None


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

	sop_version = _latest_policy_name("LPO SOP Version", {"status": "Effective"}, "modified desc")
	if not sop_version:
		sop = frappe.db.get_value("LPO SOP", {"sop_id": DEFAULT_SOP_ID}, "name")
		if not sop:
			sop = frappe.get_doc({"doctype": "LPO SOP", "sop_id": DEFAULT_SOP_ID}).insert(ignore_permissions=True).name
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
	sop_version = _latest_policy_name("LPO SOP Version", {"status": "Effective"}, "modified desc")
	if not workflow_version or not sop_version:
		frappe.throw(_("Published Workflow and effective SOP policies are not configured."), frappe.ValidationError)
	# Autoincrement DocTypes can return integer names at insert time while Link fields
	# reload as strings. Normalize them to keep immutable snapshot comparisons stable.
	return str(workflow_version), str(sop_version)
