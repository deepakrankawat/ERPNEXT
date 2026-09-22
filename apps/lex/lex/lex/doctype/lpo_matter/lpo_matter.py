from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from lex.client_access import (
	get_portal_user,
	has_matter_access,
	has_portal_capability,
	is_client_user,
	matter_sql_condition,
)
from lex.portal_audit import create_portal_audit_event


ACTIVE_JOB_STATUSES = (
	"Draft",
	"Activated",
	"Assigned",
	"In Progress",
	"On Hold",
	"QA Review",
	"Ready for Delivery",
)


class LPOMatter(Document):
	def validate(self):
		self._protect_client_submission()
		self._validate_parties()
		self._validate_dates()
		self._set_job_based_commercial_handling()
		self._validate_activation_gates()
		self._set_default_execution_snapshots()
		self._protect_execution_snapshots()
		self._validate_authorized_portal_users()
		self._validate_closure()

	def after_insert(self):
		self._sync_chat_channel()
		if is_client_user():
			portal_user = get_portal_user()
			create_portal_audit_event(
				client=self.customer,
				portal_user=portal_user.name if portal_user else None,
				matter=self.name,
				action="Matter Created",
				new_value={"billing_method": self.billing_method, "status": self.status},
			)
		self._audit_authorization_changes(None)
		if getattr(self.flags, "run_conflict_in_test", False) or (
			not getattr(frappe.flags, "in_test", False) and not getattr(self.flags, "in_test", False)
		):
			from lex.conflict_check import run_conflict_check
			run_conflict_check(self.name, trigger_reason="Matter Created")
			self.reload()

	def on_update(self):
		self._sync_chat_channel()
		previous = self.get_doc_before_save()
		if previous:
			self._audit_authorization_changes(previous)
			from lex.conflict_check import check_matter_for_conflict_recheck
			check_matter_for_conflict_recheck(self)

	def _sync_chat_channel(self):
		from lex.lexocrates_chat_sync import ensure_matter_chat_channel

		channel_name = ensure_matter_chat_channel(self.name)
		channel_status = "Archived" if self.status in {"Completed", "Closed"} else "Active"
		frappe.db.set_value(
			"Lexocrates Chat Channel",
			channel_name,
			"status",
			channel_status,
			update_modified=False,
		)

	def _protect_client_submission(self):
		if (
			not is_client_user()
			or _has_management_access(frappe.session.user)
			or getattr(frappe.flags, "lexocrates_portal_service", False)
		):
			return
		if not self.is_new():
			frappe.throw(_("Portal Users cannot modify an accepted Matter."), frappe.PermissionError)
		portal_user = get_portal_user()
		if not portal_user or not has_portal_capability("can_create_matters"):
			frappe.throw(_("You are not authorized to create Matters."), frappe.PermissionError)
		self.customer = portal_user.client
		self.status = "Draft"
		self.matter_manager = "Administrator"
		self.allow_ai_processing_by_default = 0
		self.set("authorized_portal_users", [])
		self.append(
			"authorized_portal_users",
			{
				"portal_user": portal_user.name,
				"user": portal_user.user,
				"can_view": 1,
				"can_upload": int(bool(portal_user.can_upload_documents)),
				"can_comment": int(bool(portal_user.can_comment)),
				"can_approve": int(portal_user.approval_authority not in {None, "", "None"}),
				"can_view_billing": int(bool(portal_user.billing_access)),
			},
		)

	def _validate_dates(self):
		if self.end_date and getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("End Date cannot be before Start Date."), frappe.ValidationError)

	def _validate_parties(self):
		# A Matter is the legal context/container.  Uploaded evidence and working
		# documents deliberately live on its child Jobs, never on the Matter.
		self.represented_party_name = (self.represented_party_name or self.customer_name or self.customer or "").strip()
		self.counterparty_name = (self.counterparty_name or "").strip() or None
		seen = set()
		for row in self.additional_parties:
			key = (row.party_name or "").strip().casefold()
			if not key:
				frappe.throw(_("Every Additional Party must have a Party Name."), frappe.ValidationError)
			if key in seen:
				frappe.throw(_("The same Additional Party cannot be added twice."), frappe.ValidationError)
			seen.add(key)

	def _set_job_based_commercial_handling(self):
		"""Matter is legal context only; every quote and funding record belongs to a Job."""
		self.billing_method = "Job Based"

	def _validate_activation_gates(self):
		if self.status != "Active":
			return
		if self.matter_acceptance_status == "Declined":
			frappe.throw(_("Cannot activate a Matter with 'Declined' acceptance status."), frappe.ValidationError)
		if self.conflict_check_status == "Escalated":
			frappe.throw(_("Cannot activate a Matter while Conflict Check is Escalated."), frappe.ValidationError)
	def _protect_execution_snapshots(self):
		previous = self.get_doc_before_save()
		if not previous or previous.status == "Draft":
			return
		for fieldname in ("workflow_version_snapshot", "sop_version_snapshot"):
			previous_value = str(previous.get(fieldname) or "")
			current_value = str(self.get(fieldname) or "")
			if previous_value and current_value != previous_value:
				frappe.throw(
					_("Execution policy snapshot {0} cannot change after Matter activation.").format(
						frappe.bold(fieldname)
					),
					frappe.PermissionError,
				)

	def _set_default_execution_snapshots(self):
		if self.status != "Active" or (self.workflow_version_snapshot and self.sop_version_snapshot):
			return
		from lex.execution_policies import get_execution_policy_snapshots

		workflow_version, sop_version = get_execution_policy_snapshots()
		self.workflow_version_snapshot = self.workflow_version_snapshot or workflow_version
		self.sop_version_snapshot = self.sop_version_snapshot or sop_version

	def _validate_authorized_portal_users(self):
		seen = set()
		for row in self.authorized_portal_users:
			if row.portal_user in seen:
				frappe.throw(_("A Portal User can only appear once in Matter Authorization."), frappe.ValidationError)
			seen.add(row.portal_user)
			portal_user = frappe.db.get_value(
				"Lexocrates Portal User",
				row.portal_user,
				[
					"user", "client", "account_status", "can_upload_documents", "can_comment",
					"billing_access", "approval_authority",
				],
				as_dict=True,
			)
			if not portal_user or portal_user.client != self.customer:
				frappe.throw(_("Every authorized Portal User must belong to this Client."), frappe.ValidationError)
			if portal_user.account_status != "Active":
				frappe.throw(_("Only active Portal Users can receive Matter access."), frappe.ValidationError)
			row.user = portal_user.user
			if row.can_upload and not portal_user.can_upload_documents:
				frappe.throw(_("Upload permission exceeds the Portal User's functional permission."), frappe.ValidationError)
			if row.can_comment and not portal_user.can_comment:
				frappe.throw(_("Comment permission exceeds the Portal User's functional permission."), frappe.ValidationError)
			if row.can_approve and portal_user.approval_authority in {None, "", "None"}:
				frappe.throw(_("Approval permission exceeds the Portal User's approval authority."), frappe.ValidationError)
			if row.can_view_billing and not portal_user.billing_access:
				frappe.throw(_("Billing permission exceeds the Portal User's financial permission."), frappe.ValidationError)

	def _validate_closure(self):
		if self.is_new() or self.status not in {"Completed", "Closed"}:
			return
		open_job = frappe.db.get_value(
			"LPO Job",
			{"engagement": self.name, "job_status": ("in", ACTIVE_JOB_STATUSES)},
			"name",
		)
		if open_job:
			frappe.throw(
				_("Complete or cancel open job {0} before closing this matter.").format(
					frappe.bold(open_job)
				),
				frappe.ValidationError,
			)

	def _audit_authorization_changes(self, previous):
		old = _authorization_map(previous.authorized_portal_users) if previous else {}
		new = _authorization_map(self.authorized_portal_users)
		if old == new:
			return
		create_portal_audit_event(
			client=self.customer,
			matter=self.name,
			action="Matter Access Changed",
			object_type=self.doctype,
			object_id=self.name,
			previous_value=old,
			new_value=new,
		)


def _authorization_map(rows):
	return {
		row.portal_user: {
			"view": bool(row.can_view),
			"upload": bool(row.can_upload),
			"comment": bool(row.can_comment),
			"approve": bool(row.can_approve),
			"billing": bool(row.can_view_billing),
		}
		for row in rows
	}


def _has_management_access(user: str) -> bool:
	roles = set(frappe.get_roles(user))
	return user == "Administrator" or bool(roles.intersection({"LPO_Admin", "LPO_Manager", "System Manager"}))


def has_permission(doc, ptype="read", user=None, debug=False):
	user = user or frappe.session.user
	if _has_management_access(user):
		return True
	if is_client_user(user):
		if ptype == "create":
			return has_portal_capability("can_create_matters", user)
		return ptype == "read" and has_matter_access(doc.name, "view", user)
	if "LPO_Analyst" not in frappe.get_roles(user) or ptype != "read":
		return False
	return bool(
		doc.matter_manager == user
		or frappe.db.exists("LPO Job", {"engagement": doc.name, "assigned_analyst": user})
	)


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _has_management_access(user):
		return ""
	if is_client_user(user):
		return matter_sql_condition(user=user)
	if "LPO_Analyst" not in frappe.get_roles(user):
		return "1=0"
	escaped_user = frappe.db.escape(user)
	return f"""
		(`tabLPO Matter`.matter_manager = {escaped_user}
		or exists (
			select 1 from `tabLPO Job` job
			where job.engagement = `tabLPO Matter`.name
				and job.assigned_analyst = {escaped_user}
		))
	"""
