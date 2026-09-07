from __future__ import annotations

import frappe


ACTIVE_DELIVERY_STATUSES = {"Assigned", "In Progress", "On Hold", "QA Review", "Ready for Delivery"}


def execute():
	if not frappe.db.exists("DocType", "LPO QA Review"):
		return

	for review in frappe.get_all(
		"LPO QA Review",
		fields=["name", "job", "reviewer", "review_status", "reviewed_document"],
		limit_page_length=0,
	):
		job = frappe.db.get_value(
			"LPO Job",
			review.job,
			[
				"assigned_analyst", "job_status", "delivery_document",
				"delivery_document_checksum", "delivery_document_version",
			],
			as_dict=True,
		)
		if not job:
			continue
		independent = int(review.reviewer != job.assigned_analyst)
		reviewed_document, checksum, version = _review_artifact_snapshot(review, job)
		values = {
			"reviewed_document": reviewed_document,
			"reviewed_document_checksum": checksum,
			"reviewed_document_version": version,
			"reviewer_independent": independent,
		}
		if not independent and review.review_status == "Approved" and job.job_status in ACTIVE_DELIVERY_STATUSES:
			values.update({"review_status": "In Review", "completed_on": None})
		frappe.db.set_value("LPO QA Review", review.name, values, update_modified=False)

	for job_name in frappe.get_all(
		"LPO Job",
		filters={"job_status": "Ready for Delivery", "qa_required": 1},
		pluck="name",
		limit_page_length=0,
	):
		job = frappe.db.get_value(
			"LPO Job",
			job_name,
			["delivery_document", "delivery_document_checksum", "delivery_document_version"],
			as_dict=True,
		)
		approved = frappe.db.exists("LPO QA Review", {
			"job": job_name,
			"review_status": "Approved",
			"reviewer_independent": 1,
			"reviewed_document": job.delivery_document,
			"reviewed_document_checksum": job.delivery_document_checksum,
			"reviewed_document_version": job.delivery_document_version,
		})
		if not approved:
			frappe.db.set_value("LPO Job", job_name, {
				"job_status": "QA Review",
				"client_approval_status": "Not Requested",
				"client_approved_by": None,
				"client_approved_on": None,
			}, update_modified=False)

	_failures = []
	from lex.sop_execution_engine import complete_qa_sop_steps, sync_job_sop_evidence
	from lex.workflow_runner import sync_job_workflow_execution

	for job_name in frappe.get_all(
		"LPO Job",
		filters={"job_status": ["in", list(ACTIVE_DELIVERY_STATUSES | {"Delivered", "Completed"})]},
		pluck="name",
		limit_page_length=0,
	):
		try:
			job = frappe.get_doc("LPO Job", job_name)
			sync_job_workflow_execution(job)
			sync_job_sop_evidence(job)
			review_name = frappe.db.get_value(
				"LPO QA Review",
				{
					"job": job.name,
					"review_status": "Approved",
					"reviewer_independent": 1,
					"reviewed_document": job.delivery_document,
					"reviewed_document_checksum": job.delivery_document_checksum,
					"reviewed_document_version": job.delivery_document_version,
				},
				"name",
			)
			if review_name:
				complete_qa_sop_steps(job, frappe.get_doc("LPO QA Review", review_name))
		except Exception as exc:
			_failures.append(f"{job_name}: {exc}")
	if _failures:
		frappe.log_error("\n".join(_failures[:100]), "Delivery governance migration exceptions")


def _review_artifact_snapshot(review, job):
	"""Preserve old review evidence instead of rebinding it to the latest Job file."""
	reviewed_document = review.reviewed_document or job.delivery_document
	if not reviewed_document:
		return None, None, 0
	if reviewed_document == job.delivery_document:
		return (
			reviewed_document,
			job.delivery_document_checksum,
			job.delivery_document_version or 0,
		)

	export = frappe.db.get_value(
		"LPO AI Document Export",
		{"job": review.job, "file_url": reviewed_document},
		["file_checksum", "version"],
		as_dict=True,
		order_by="version desc",
	)
	if export:
		return reviewed_document, export.file_checksum, export.version or 0

	checksum = None
	if frappe.get_meta("File").has_field("custom_lex_checksum"):
		checksum = frappe.db.get_value("File", {"file_url": reviewed_document}, "custom_lex_checksum")
	return reviewed_document, checksum, 0
