from __future__ import annotations

import json
import hashlib
import zipfile
import io
import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime
from lex.portal_audit import create_portal_audit_event


@frappe.whitelist()
def resolve_applicable_sop_steps(sop_version_name: str, work_type: str | None = None, jurisdiction: str | None = None, document_classification: str | None = None):
	"""Resolve conditional SOP steps based on work type, jurisdiction, and metadata (SOP-004)."""
	if not frappe.db.exists("LPO SOP Version", sop_version_name):
		frappe.throw(_("SOP Version not found."), frappe.DoesNotExistError)

	sop_version = frappe.get_doc("LPO SOP Version", sop_version_name)
	raw_steps = json.loads(sop_version.get("steps_json") or "[]")
	steps = []
	for idx, step in enumerate(raw_steps):
		# Conditional applicability check
		app_jurisdiction = step.get("jurisdiction")
		app_work_type = step.get("work_type")
		if app_jurisdiction and jurisdiction and app_jurisdiction != jurisdiction:
			continue
		if app_work_type and work_type and app_work_type != work_type:
			continue

		steps.append({
			"step_id": step.get("step_id") or f"step_{idx+1}",
			"title": step.get("title") or f"Step {idx+1}",
			"instructions": step.get("instructions") or "",
			"is_mandatory": bool(step.get("is_mandatory", True)),
			"requires_evidence": bool(step.get("requires_evidence", False)),
			"evidence_type": step.get("evidence_type") or "Document",
			"role_scope": step.get("role_scope") or "Junior Associate",
		})

	return steps


@frappe.whitelist()
def start_sop_run(job_name: str, sop_version_name: str):
	"""Bind job to exact SOP version and start execution run (SOP-002)."""
	if not frappe.db.exists("LPO Job", job_name):
		frappe.throw(_("LPO Job not found."), frappe.DoesNotExistError)

	job = frappe.get_doc("LPO Job", job_name)
	frappe.has_permission("LPO Job", "read", doc=job, throw=True)
	sop_version = frappe.get_doc("LPO SOP Version", sop_version_name)

	if sop_version.status != "Effective":
		frappe.throw(_("Only Effective SOP versions can start runs."), frappe.ValidationError)
	if job.sop_version_snapshot != sop_version_name:
		frappe.throw(_("SOP Version does not match the Job's pinned execution snapshot."), frappe.ValidationError)
	if frappe.db.exists("LPO SOP Run", {"job_id": job_name, "status": ["in", ["In Progress", "Completed"]]}):
		frappe.throw(_("This Job already has an active or completed SOP Run."), frappe.DuplicateEntryError)

	steps = resolve_applicable_sop_steps(
		sop_version_name,
		job.get("job_type"),
		job.get("jurisdictions"),
	)

	sop_run = frappe.get_doc({
		"doctype": "LPO SOP Run",
		"sop_version": sop_version_name,
		"job_id": job_name,
		"status": "In Progress",
		"started_at": now_datetime(),
		"started_by": frappe.session.user,
		"resolved_steps_json": json.dumps(steps),
		"completed_steps_json": json.dumps([]),
		"evidence_manifest_json": json.dumps({}),
		"exceptions_json": json.dumps([]),
		"exception_status": "None",
	}).insert(ignore_permissions=True)

	create_portal_audit_event(
		client=job.get("customer"),
		user=frappe.session.user,
		action="SOP Run Started",
		object_type="LPO SOP Run",
		object_id=sop_run.name,
		new_value={"sop_version": sop_version_name, "job": job_name},
	)

	return sop_run.name


@frappe.whitelist()
def record_sop_step_completion(sop_run_name: str, step_id: str, evidence_doc_id: str | None = None, comment: str | None = None):
	"""Record completed SOP step with evidence validation (SOP-003, SOP-005)."""
	sop_run = frappe.get_doc("LPO SOP Run", sop_run_name)
	job = frappe.get_doc("LPO Job", sop_run.job_id)
	frappe.has_permission("LPO Job", "read", doc=job, throw=True)
	if sop_run.status != "In Progress":
		frappe.throw(_("SOP Run is not active."), frappe.ValidationError)

	resolved_steps = json.loads(sop_run.resolved_steps_json or "[]")
	completed_steps = json.loads(sop_run.completed_steps_json or "[]")
	evidence_manifest = json.loads(sop_run.evidence_manifest_json or "{}")

	target_step = next((s for s in resolved_steps if s["step_id"] == step_id), None)
	if not target_step:
		frappe.throw(_("Invalid step ID for this SOP Run."), frappe.ValidationError)

	if target_step["requires_evidence"] and not evidence_doc_id:
		frappe.throw(_("Evidence is required for step '{0}'.").format(target_step["title"]), frappe.MandatoryError)

	if any(row.get("step_id") == step_id for row in completed_steps):
		frappe.throw(_("This SOP step is already complete."), frappe.DuplicateEntryError)
	evidence = _validate_sop_evidence(job, evidence_doc_id) if evidence_doc_id else None

	completed_entry = {
		"step_id": step_id,
		"title": target_step["title"],
		"completed_by": frappe.session.user,
		"completed_at": str(now_datetime()),
		"evidence_doc_id": evidence_doc_id,
		"evidence_checksum": evidence.get("checksum") if evidence else None,
		"comment": comment,
	}

	completed_steps.append(completed_entry)
	if evidence_doc_id:
		evidence_manifest[step_id] = evidence_doc_id

	sop_run.completed_steps_json = json.dumps(completed_steps)
	sop_run.evidence_manifest_json = json.dumps(evidence_manifest)

	# Check if all mandatory steps are complete
	completed_ids = {c["step_id"] for c in completed_steps}
	all_mandatory_done = all(s["step_id"] in completed_ids for s in resolved_steps if s["is_mandatory"])

	if all_mandatory_done:
		sop_run.status = "Completed"
		sop_run.completed_at = now_datetime()

	sop_run.save(ignore_permissions=True)

	return {"status": sop_run.status, "completed_step": step_id}


@frappe.whitelist()
def record_sop_exception(sop_run_name: str, step_id: str, reason: str, decision: str):
	"""Record an explicitly approved or rejected SOP deviation; silent skips are prohibited."""
	roles = set(frappe.get_roles(frappe.session.user))
	if frappe.session.user != "Administrator" and not roles.intersection({"LPO_Admin", "LPO_Manager", "System Manager"}):
		frappe.throw(_("SOP exception approval requires management authority."), frappe.PermissionError)
	if decision not in {"Approved", "Rejected"}:
		frappe.throw(_("Exception decision must be Approved or Rejected."), frappe.ValidationError)
	if not (reason or "").strip():
		frappe.throw(_("An SOP exception reason is required."), frappe.MandatoryError)
	sop_run = frappe.get_doc("LPO SOP Run", sop_run_name)
	steps = json.loads(sop_run.resolved_steps_json or "[]")
	if not any(step.get("step_id") == step_id for step in steps):
		frappe.throw(_("Invalid step ID for this SOP Run."), frappe.ValidationError)
	exceptions = json.loads(sop_run.exceptions_json or "[]")
	exceptions.append({
		"step_id": step_id,
		"reason": reason.strip(),
		"decision": decision,
		"decided_by": frappe.session.user,
		"decided_at": str(now_datetime()),
	})
	sop_run.exceptions_json = json.dumps(exceptions)
	sop_run.exception_status = decision
	sop_run.save(ignore_permissions=True)
	job = frappe.get_doc("LPO Job", sop_run.job_id)
	create_portal_audit_event(
		client=job.customer,
		matter=job.engagement,
		action="SOP Exception Decision",
		object_type="LPO SOP Run",
		object_id=sop_run.name,
		new_value=exceptions[-1],
	)
	return {"sop_run": sop_run.name, "step_id": step_id, "decision": decision}


@frappe.whitelist()
def export_sop_evidence_package(sop_run_name: str):
	"""Export full evidence package ZIP containing manifest and documents (SOP-005)."""
	sop_run = frappe.get_doc("LPO SOP Run", sop_run_name)
	job = frappe.get_doc("LPO Job", sop_run.job_id)
	frappe.has_permission("LPO Job", "read", doc=job, throw=True)
	evidence_manifest = json.loads(sop_run.evidence_manifest_json or "{}")
	completed_steps = json.loads(sop_run.completed_steps_json or "[]")

	zip_buffer = io.BytesIO()
	with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
		# Add manifest json
		manifest_data = {
			"sop_run": sop_run.name,
			"sop_version": sop_run.sop_version,
			"job": sop_run.job_id,
			"completed_at": str(sop_run.completed_at),
			"completed_steps": completed_steps,
			"evidence_manifest": evidence_manifest,
			"exceptions": json.loads(sop_run.exceptions_json or "[]"),
		}
		zip_file.writestr("manifest.json", json.dumps(manifest_data, indent=2))

		# Add exact evidence bytes; the manifest contains the stored checksum.
		for step_id, doc_id in evidence_manifest.items():
			if frappe.db.exists("File", doc_id):
				doc = frappe.get_doc("File", doc_id)
				zip_file.writestr(f"evidence/{step_id}_{doc.file_name or doc.name}", doc.get_content())

	frappe.response["filename"] = f"SOP_Evidence_Package_{sop_run.name}.zip"
	frappe.response["filecontent"] = zip_buffer.getvalue()
	frappe.response["type"] = "binary"


def _validate_sop_evidence(job, evidence_doc_id):
	if not frappe.db.exists("File", evidence_doc_id):
		frappe.throw(_("SOP evidence must be a managed File record."), frappe.ValidationError)
	file_doc = frappe.get_doc("File", evidence_doc_id)
	valid_parent = (
		(file_doc.attached_to_doctype == "LPO Job" and file_doc.attached_to_name == job.name)
		or (file_doc.attached_to_doctype == "LPO Matter" and file_doc.attached_to_name == job.engagement)
	)
	if not valid_parent:
		frappe.throw(_("SOP evidence must belong to the same Job or parent Matter."), frappe.ValidationError)
	if file_doc.meta.has_field("custom_lex_scan_status") and file_doc.custom_lex_scan_status != "Clean":
		frappe.throw(_("SOP evidence is quarantined until its malware scan passes."), frappe.ValidationError)
	content = file_doc.get_content()
	if isinstance(content, str):
		content = content.encode("utf-8")
	return {"file": file_doc.name, "checksum": hashlib.sha256(content).hexdigest()}
