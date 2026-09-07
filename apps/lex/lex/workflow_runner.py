from __future__ import annotations

import json
import hashlib
import frappe
from frappe import _
from frappe.utils import flt, now_datetime
from lex.portal_audit import create_portal_audit_event
from lex.workflow_validator import validate_workflow_graph


EXECUTION_REQUIRED_STATUSES = {
	"Assigned", "In Progress", "On Hold", "QA Review", "Ready for Delivery", "Delivered", "Completed",
}


@frappe.whitelist()
def execute_workflow_version(workflow_version_name: str, matter_id: str | None = None, job_id: str | None = None, payload: dict | None = None):
	"""Execute pinned workflow version for Matter/Job (WFL-004)."""
	if not frappe.db.exists("LPO Workflow Version", workflow_version_name):
		frappe.throw(_("Workflow Version not found."), frappe.DoesNotExistError)

	version_doc = frappe.get_doc("LPO Workflow Version", workflow_version_name)
	if bool(matter_id) == bool(job_id):
		frappe.throw(_("Provide exactly one Matter or Job subject."), frappe.ValidationError)
	if version_doc.status != "Published":
		frappe.throw(_("Only Published Workflow versions can execute."), frappe.ValidationError)
	validation = validate_workflow_graph(version_doc.graph_json)
	if not validation["is_valid"]:
		frappe.throw(_("Cannot execute invalid workflow graph: {0}").format(", ".join(validation["errors"])), frappe.ValidationError)
	canonical = json.dumps(json.loads(version_doc.graph_json), sort_keys=True, separators=(",", ":"))
	graph_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
	if version_doc.graph_hash != graph_hash:
		frappe.throw(_("Workflow graph hash does not match the approved version."), frappe.ValidationError)
	subject_doctype = "LPO Job" if job_id else "LPO Matter"
	subject_name = job_id or matter_id
	subject = frappe.get_doc(subject_doctype, subject_name)
	frappe.has_permission(subject_doctype, "read", doc=subject, throw=True)
	if subject.get("workflow_version_snapshot") != workflow_version_name:
		frappe.throw(_("The requested Workflow does not match the subject's pinned version."), frappe.ValidationError)

	execution = frappe.get_doc({
		"doctype": "LPO Workflow Execution",
		"workflow_version": workflow_version_name,
		"graph_hash_snapshot": graph_hash,
		"subject_type": "LPO Job" if job_id else "LPO Matter" if matter_id else None,
		"subject_id": job_id or matter_id,
		"status": "Running",
		"started": now_datetime(),
		"payload_json": json.dumps(payload or {}),
		"execution_log_json": json.dumps([]),
	}).insert(ignore_permissions=True)

	create_portal_audit_event(
		client=(
			frappe.db.get_value("LPO Matter", matter_id, "customer")
			if matter_id
			else frappe.db.get_value("LPO Job", job_id, "customer") if job_id else None
		),
		user=frappe.session.user,
		action="Workflow Execution Started",
		object_type="LPO Workflow Execution",
		object_id=execution.name,
		new_value={"version": workflow_version_name, "matter": matter_id, "job": job_id},
	)

	return execution.name


def sync_job_workflow_execution(job):
	"""Maintain a pinned, append-only lifecycle execution for an operational Job."""
	if job.job_status not in EXECUTION_REQUIRED_STATUSES:
		return None
	version = frappe.get_doc("LPO Workflow Version", job.workflow_version_snapshot)
	if version.status != "Published":
		frappe.throw(_("The Job workflow snapshot is not Published."), frappe.ValidationError)
	canonical = json.dumps(json.loads(version.graph_json), sort_keys=True, separators=(",", ":"))
	graph_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
	if version.graph_hash != graph_hash:
		frappe.throw(_("Workflow graph hash does not match the approved version."), frappe.ValidationError)
	name = frappe.db.get_value(
		"LPO Workflow Execution",
		{"subject_type": "LPO Job", "subject_id": job.name, "status": ["!=", "Cancelled"]},
		"name",
		order_by="creation desc",
	)
	if name:
		execution = frappe.get_doc("LPO Workflow Execution", name)
		if (
			str(execution.workflow_version) != str(job.workflow_version_snapshot)
			or execution.graph_hash_snapshot != graph_hash
		):
			frappe.throw(_("Workflow execution does not match the Job's immutable snapshot."), frappe.ValidationError)
	else:
		execution = frappe.get_doc({
			"doctype": "LPO Workflow Execution",
			"workflow_version": job.workflow_version_snapshot,
			"graph_hash_snapshot": graph_hash,
			"subject_type": "LPO Job",
			"subject_id": job.name,
			"status": "Running",
			"started": now_datetime(),
			"payload_json": json.dumps({"job": job.name}),
			"execution_log_json": json.dumps([]),
		}).insert(ignore_permissions=True)

	log = json.loads(execution.execution_log_json or "[]")
	if not log or log[-1].get("job_status") != job.job_status:
		log.append({
			"event": "Job Status Reached",
			"job_status": job.job_status,
			"recorded_at": str(now_datetime()),
			"recorded_by": frappe.session.user,
		})
	execution.execution_log_json = json.dumps(log)
	if job.job_status == "Completed":
		execution.status = "Completed"
		execution.ended = now_datetime()
	elif execution.status != "Completed":
		execution.status = "Running"
		execution.ended = None
	execution.save(ignore_permissions=True)
	return execution


def validate_job_workflow_execution(job):
	execution = sync_job_workflow_execution(job)
	if not execution or execution.status not in {"Running", "Completed"}:
		frappe.throw(_("A valid pinned Workflow Execution is required for this Job."), frappe.ValidationError)
	if job.job_status == "Completed" and execution.status != "Completed":
		frappe.throw(_("Workflow Execution must complete with the Job."), frappe.ValidationError)
	return execution


@frappe.whitelist()
def simulate_workflow_execution(workflow_version_name: str, synthetic_payload: dict | None = None):
	"""Dry-run simulation mode with synthetic data executing without side effects (WFL-010)."""
	if not frappe.db.exists("LPO Workflow Version", workflow_version_name):
		frappe.throw(_("Workflow Version not found."), frappe.DoesNotExistError)

	version_doc = frappe.get_doc("LPO Workflow Version", workflow_version_name)
	graph = json.loads(version_doc.graph_json or '{"nodes":[], "edges":[]}')

	simulation_steps = []
	estimated_latency_sec = 0.0
	estimated_cost_points = 0.0

	for node in graph.get("nodes", []):
		n_type = node.get("type", "Action")
		step_latency = 1.0 if n_type in {"Trigger", "Action"} else (5.0 if n_type == "AI" else 30.0)
		step_cost = 5.0 if n_type == "AI" else 0.0

		estimated_latency_sec += step_latency
		estimated_cost_points += step_cost

		simulation_steps.append({
			"node_id": node.get("id"),
			"type": n_type,
			"simulated_status": "Success",
			"estimated_latency_sec": step_latency,
			"estimated_cost_points": step_cost,
		})

	return {
		"workflow_version": workflow_version_name,
		"simulation_mode": True,
		"is_dry_run": True,
		"estimated_total_latency_sec": estimated_latency_sec,
		"estimated_total_cost_points": estimated_cost_points,
		"steps": simulation_steps,
	}
