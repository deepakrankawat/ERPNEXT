from __future__ import annotations

import hashlib
import secrets

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, now_datetime, validate_email_address
from frappe.utils.password_strength import test_password_strength

from lex.client_access import get_portal_user, require_client_administrator
from lex.client_schema import new_client_id
from lex.lex.doctype.lexocrates_portal_user.lexocrates_portal_user import (
	PORTAL_ROLE_TO_FRAPPE_ROLE,
)
from lex.portal_audit import create_portal_audit_event


INVITATION_HOURS = 72
REGISTRATION_HOURS = 24
REGISTRATION_ACTIVATION_HOURS = 48
MANAGEMENT_ROLES = {"LPO_Admin", "LPO_Manager", "System Manager", "Lexocrates Compliance Officer"}


def _is_internal(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)).intersection(MANAGEMENT_ROLES))


def _token_hash(token: str) -> str:
	return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _validate_password(password: str, user_inputs: list[str]):
	if not password or len(password) < 10:
		frappe.throw(_("Use a password containing at least 10 characters."), frappe.ValidationError)
	result = test_password_strength(password, user_inputs=user_inputs)
	minimum = int(frappe.db.get_single_value("System Settings", "minimum_password_score") or 2)
	if result.get("score", 0) < minimum:
		frappe.throw(_("Choose a stronger password that is not based on your name or email."), frappe.ValidationError)


def _with_service_flag(handler):
	previous = getattr(frappe.flags, "lexocrates_portal_service", False)
	frappe.flags.lexocrates_portal_service = True
	try:
		return handler()
	finally:
		frappe.flags.lexocrates_portal_service = previous


@frappe.whitelist()
def invite_portal_user(
	invitee_name: str,
	invitee_email: str,
	portal_role: str,
	client: str | None = None,
	designation: str | None = None,
	department: str | None = None,
	mfa_required: int = 0,
):
	actor = None
	if _is_internal():
		if not client:
			frappe.throw(_("Client is required."), frappe.MandatoryError)
	else:
		actor = require_client_administrator()
		client = actor.client
	invitee_name = (invitee_name or "").strip()
	invitee_email = validate_email_address((invitee_email or "").strip().lower(), throw=True)
	if not invitee_name:
		frappe.throw(_("Invitee Name is required."), frappe.MandatoryError)
	if portal_role not in PORTAL_ROLE_TO_FRAPPE_ROLE:
		frappe.throw(_("Select a valid Portal Role."), frappe.ValidationError)
	if frappe.db.exists("User", invitee_email) or frappe.db.exists("Lexocrates Portal User", {"email": invitee_email}):
		frappe.throw(_("This email already has a Lexocrates account."), frappe.DuplicateEntryError)
	if department and frappe.db.get_value("Lexocrates Client Department", department, "client") != client:
		frappe.throw(_("Department must belong to the same Client."), frappe.ValidationError)
	if frappe.db.exists(
		"Lexocrates Portal Invitation",
		{"client": client, "invitee_email": invitee_email, "status": "Pending", "expires_on": [">", now_datetime()]},
	):
		frappe.throw(_("An active invitation already exists for this email."), frappe.DuplicateEntryError)

	token = secrets.token_urlsafe(32)
	invited_on = now_datetime()
	expires_on = add_to_date(invited_on, hours=INVITATION_HOURS)
	invitation = _with_service_flag(
		lambda: frappe.get_doc(
			{
				"doctype": "Lexocrates Portal Invitation",
				"client": client,
				"invitee_name": invitee_name,
				"invitee_email": invitee_email,
				"designation": designation,
				"department": department,
				"portal_role": portal_role,
				"status": "Pending",
				"invited_by": frappe.session.user,
				"invited_on": invited_on,
				"expires_on": expires_on,
				"token_hash": _token_hash(token),
				"mfa_required": int(bool(mfa_required)),
			}
		).insert(ignore_permissions=True)
	)
	activation_url = frappe.utils.get_url(f"/client-invitation?token={token}")
	if not getattr(frappe.flags, "in_test", False):
		frappe.sendmail(
			recipients=[invitee_email],
			subject=_("Your secure Lexocrates Portal invitation"),
			message=_(
				"You have been invited to the Lexocrates Portal. Complete activation within {0} hours: <a href=\"{1}\">Activate account</a>."
			).format(INVITATION_HOURS, activation_url),
			now=False,
		)
	create_portal_audit_event(
		client=client,
		portal_user=actor.name if actor else None,
		action="Portal User Invited",
		object_type=invitation.doctype,
		object_id=invitation.name,
		new_value={"email": invitee_email, "role": portal_role, "expires_on": expires_on},
	)
	result = {"invitation": invitation.name, "expires_on": str(expires_on), "email_sent": not getattr(frappe.flags, "in_test", False)}
	if getattr(frappe.flags, "in_test", False):
		result["test_token"] = token
	return result


@frappe.whitelist(allow_guest=True)
def accept_portal_invitation(token: str, password: str):
	invitation = _pending_record("Lexocrates Portal Invitation", token, "Pending")
	_validate_password(password, [invitation.invitee_name, invitation.invitee_email])
	if frappe.db.exists("User", invitation.invitee_email):
		frappe.throw(_("This invitation can no longer be activated."), frappe.PermissionError)

	def activate():
		user = _create_client_website_user(invitation.invitee_email, invitation.invitee_name, password)
		portal_user = frappe.get_doc(
			{
				"doctype": "Lexocrates Portal User",
				"user": user.name,
				"client": invitation.client,
				"portal_role": invitation.portal_role,
				"designation": invitation.designation,
				"department": invitation.department,
				"account_status": "Active",
				"matter_access_scope": "Assigned Matters",
				"mfa_required": invitation.mfa_required,
			}
		).insert(ignore_permissions=True)
		invitation.status = "Accepted"
		invitation.accepted_on = now_datetime()
		invitation.user = user.name
		invitation.portal_user = portal_user.name
		invitation.save(ignore_permissions=True)
		return user, portal_user

	user, portal_user = _with_service_flag(activate)
	create_portal_audit_event(
		client=invitation.client,
		portal_user=portal_user.name,
		user=user.name,
		action="Portal User Activated",
		object_type="Lexocrates Portal User",
		object_id=portal_user.name,
	)
	return {"activated": True, "portal_user": portal_user.name, "redirect": "/client-portal"}


@frappe.whitelist()
def deactivate_portal_user(
	portal_user: str,
	reason: str,
	status: str = "Disabled",
	lock_until: str | None = None,
):
	"""Apply an auditable lifecycle state; revoked identities cannot self-reactivate."""
	doc = frappe.get_doc("Lexocrates Portal User", portal_user)
	if not _is_internal():
		actor = require_client_administrator()
		if actor.client != doc.client:
			frappe.throw(_("You cannot administer this Client."), frappe.PermissionError)
	if status not in {"Locked", "Suspended", "Disabled", "Revoked"}:
		frappe.throw(_("Status must be Locked, Suspended, Disabled, or Revoked."), frappe.ValidationError)
	if not (reason or "").strip():
		frappe.throw(_("A lifecycle reason is required."), frappe.MandatoryError)
	if status == "Locked":
		if not lock_until or get_datetime(lock_until) <= now_datetime():
			frappe.throw(_("Locked Until must be a future date and time."), frappe.ValidationError)
		doc.lock_until = get_datetime(lock_until)
	if doc.portal_role == "Client Administrator":
		other_admin = frappe.db.exists(
			"Lexocrates Portal User",
			{"name": ["!=", doc.name], "client": doc.client, "portal_role": "Client Administrator", "account_status": "Active"},
		)
		if not other_admin:
			frappe.throw(_("Activate another Client Administrator before disabling the last one."), frappe.ValidationError)
	doc.account_status = status
	doc.deactivation_reason = (reason or "").strip()
	_with_service_flag(lambda: doc.save(ignore_permissions=True))
	return {"portal_user": doc.name, "status": doc.account_status, "lock_until": doc.lock_until}


@frappe.whitelist()
def reactivate_portal_user(portal_user: str, reason: str):
	doc = frappe.get_doc("Lexocrates Portal User", portal_user)
	if not _is_internal():
		actor = require_client_administrator()
		if actor.client != doc.client:
			frappe.throw(_("You cannot administer this Client."), frappe.PermissionError)
		if doc.account_status == "Revoked":
			frappe.throw(_("Only Lexocrates staff can reactivate a revoked account."), frappe.PermissionError)
	if doc.account_status == "Active":
		return {"portal_user": doc.name, "status": doc.account_status}
	previous_status = doc.account_status
	doc.account_status = "Active"
	doc.deactivation_reason = None
	doc.lock_until = None
	_with_service_flag(lambda: doc.save(ignore_permissions=True))
	create_portal_audit_event(
		client=doc.client,
		portal_user=doc.name,
		action="Portal User Reactivated",
		object_type=doc.doctype,
		object_id=doc.name,
		previous_value={"status": previous_status},
		new_value={"status": "Active", "reason": (reason or "").strip()},
	)
	return {"portal_user": doc.name, "status": doc.account_status}


@frappe.whitelist()
def grant_temporary_client_administrator(
	portal_user: str,
	expires_on: str,
	reason: str,
):
	"""Delegate Client user administration for at most 30 days without changing the permanent role."""
	doc = frappe.get_doc("Lexocrates Portal User", portal_user)
	if not _is_internal():
		actor = require_client_administrator()
		if actor.client != doc.client:
			frappe.throw(_("You cannot administer this Client."), frappe.PermissionError)
	if doc.account_status != "Active":
		frappe.throw(_("Temporary authority can only be granted to an active Portal User."), frappe.ValidationError)
	expires = get_datetime(expires_on)
	now = now_datetime()
	if expires <= now or expires > add_to_date(now, days=30):
		frappe.throw(_("Delegated administration must expire within 30 days."), frappe.ValidationError)
	if not (reason or "").strip():
		frappe.throw(_("A delegation reason is required."), frappe.MandatoryError)
	doc.delegated_admin_until = expires
	doc.delegated_by = frappe.session.user
	doc.delegation_reason = reason.strip()
	_with_service_flag(lambda: doc.save(ignore_permissions=True))
	create_portal_audit_event(
		client=doc.client,
		portal_user=doc.name,
		action="Temporary Client Administration Granted",
		object_type=doc.doctype,
		object_id=doc.name,
		new_value={"expires_on": str(expires), "delegated_by": frappe.session.user, "reason": reason.strip()},
	)
	return {"portal_user": doc.name, "delegated_admin_until": str(expires)}


def expire_portal_security_states():
	"""Hourly control that unlocks timed locks and removes expired delegated authority."""
	now = now_datetime()
	for name in frappe.get_all(
		"Lexocrates Portal User",
		filters={"account_status": "Locked", "lock_until": ["<=", now]},
		pluck="name",
	):
		doc = frappe.get_doc("Lexocrates Portal User", name)
		doc.account_status = "Active"
		doc.deactivation_reason = None
		doc.lock_until = None
		_with_service_flag(lambda doc=doc: doc.save(ignore_permissions=True))
	for name in frappe.get_all(
		"Lexocrates Portal User",
		filters={"delegated_admin_until": ["<=", now]},
		pluck="name",
	):
		doc = frappe.get_doc("Lexocrates Portal User", name)
		doc.delegated_admin_until = None
		doc.delegated_by = None
		doc.delegation_reason = None
		_with_service_flag(lambda doc=doc: doc.save(ignore_permissions=True))


@frappe.whitelist()
def update_portal_user_permissions(portal_user: str, values=None):
	doc = frappe.get_doc("Lexocrates Portal User", portal_user)
	if not _is_internal():
		actor = require_client_administrator()
		if actor.client != doc.client:
			frappe.throw(_("You cannot administer this Client."), frappe.PermissionError)
	if isinstance(values, str):
		values = frappe.parse_json(values)
	if not isinstance(values, dict):
		frappe.throw(_("Permission values must be supplied as an object."), frappe.ValidationError)
	allowed = {
		"portal_role", "department", "matter_access_scope", "can_create_matters",
		"can_upload_documents", "can_comment", "billing_access", "lexpack_view_access",
		"lexpack_purchase_access", "approval_authority", "user_management_authority",
		"report_access", "mfa_required",
	}
	unknown = set(values) - allowed
	if unknown:
		frappe.throw(_("Unsupported permission fields: {0}.").format(", ".join(sorted(unknown))), frappe.ValidationError)
	new_role = values.get("portal_role", doc.portal_role)
	removes_admin = doc.portal_role == "Client Administrator" and new_role != "Client Administrator"
	removes_authority = doc.portal_role == "Client Administrator" and "user_management_authority" in values and not int(values["user_management_authority"])
	if removes_admin or removes_authority:
		if not frappe.db.exists(
			"Lexocrates Portal User",
			{"name": ["!=", doc.name], "client": doc.client, "portal_role": "Client Administrator", "account_status": "Active"},
		):
			frappe.throw(_("Another active Client Administrator is required before removing this authority."), frappe.ValidationError)
	if new_role != doc.portal_role:
		doc.portal_role = new_role
		doc.apply_role_defaults()
	for fieldname, value in values.items():
		doc.set(fieldname, value)
	_with_service_flag(lambda: doc.save(ignore_permissions=True))
	return {"portal_user": doc.name, "portal_role": doc.portal_role, "account_status": doc.account_status}


@frappe.whitelist()
def set_matter_authorization(
	matter: str,
	portal_user: str,
	can_view: int = 1,
	can_upload: int = 0,
	can_comment: int = 0,
	can_approve: int = 0,
	can_view_billing: int = 0,
):
	actor = None if _is_internal() else require_client_administrator()
	doc = frappe.get_doc("LPO Matter", matter)
	target = frappe.get_doc("Lexocrates Portal User", portal_user)
	if target.client != doc.customer or (actor and actor.client != doc.customer):
		frappe.throw(_("Matter and Portal User must belong to the same Client."), frappe.PermissionError)
	row = next((item for item in doc.authorized_portal_users if item.portal_user == portal_user), None)
	values = {
		"portal_user": portal_user,
		"can_view": int(bool(can_view)),
		"can_upload": int(bool(can_upload)),
		"can_comment": int(bool(can_comment)),
		"can_approve": int(bool(can_approve)),
		"can_view_billing": int(bool(can_view_billing)),
	}
	if row:
		row.update(values)
	else:
		doc.append("authorized_portal_users", values)
	_with_service_flag(lambda: doc.save(ignore_permissions=True))
	return {"matter": doc.name, "portal_user": portal_user, **values}


@frappe.whitelist(allow_guest=True)
def request_client_registration(
	organization_name: str,
	organization_type: str,
	country: str,
	primary_user_name: str,
	designation: str,
	email: str,
	state_province: str | None = None,
	website: str | None = None,
	primary_jurisdiction: str | None = None,
	industry_practice_type: str | None = None,
	billing_currency: str | None = None,
	tax_information: str | None = None,
	mobile: str | None = None,
):
	organization_name = (organization_name or "").strip()
	primary_user_name = (primary_user_name or "").strip()
	designation = (designation or "").strip()
	email = validate_email_address((email or "").strip().lower(), throw=True)
	if not all((organization_name, organization_type, country, primary_user_name, designation, email)):
		frappe.throw(_("Complete every mandatory registration field."), frappe.MandatoryError)
	if frappe.db.exists("User", email):
		frappe.throw(_("An account already exists for this email."), frappe.DuplicateEntryError)
	if frappe.db.exists("Customer", {"customer_name": organization_name}):
		frappe.throw(_("This organization is already registered. Ask its Client Administrator for an invitation."), frappe.DuplicateEntryError)

	token = secrets.token_urlsafe(32)
	requested_on = now_datetime()
	expires_on = add_to_date(requested_on, hours=REGISTRATION_HOURS)
	registration = _with_service_flag(
		lambda: frappe.get_doc(
			{
				"doctype": "Lexocrates Client Registration",
				"organization_name": organization_name,
				"organization_type": organization_type,
				"country": country,
				"state_province": state_province,
				"website": website,
				"primary_jurisdiction": primary_jurisdiction,
				"industry_practice_type": industry_practice_type,
				"billing_currency": billing_currency,
				"tax_information": tax_information,
				"primary_user_name": primary_user_name,
				"designation": designation,
				"email": email,
				"mobile": mobile,
				"status": "Pending Verification",
				"requested_on": requested_on,
				"expires_on": expires_on,
				"token_hash": _token_hash(token),
			}
		).insert(ignore_permissions=True)
	)
	verification_url = frappe.utils.get_url(f"/client-registration?token={token}")
	if not getattr(frappe.flags, "in_test", False):
		try:
			frappe.sendmail(
				recipients=[email],
				subject=_("Verify your Lexocrates Client registration"),
				message=_("Verify your organization registration within {0} hours: <a href=\"{1}\">Verify registration</a>.").format(REGISTRATION_HOURS, verification_url),
				now=True,
			)
		except Exception:
			frappe.log_error("Client Registration Email Failed", frappe.get_traceback())
	result = {
		"registration": registration.name,
		"verification_sent": not getattr(frappe.flags, "in_test", False),
	}
	if getattr(frappe.flags, "in_test", False) or cint(frappe.conf.get("developer_mode")):
		result["verification_url"] = verification_url
		result["test_token"] = token
	return result


@frappe.whitelist(allow_guest=True)
def verify_client_registration(token: str, password: str | None = None):
	"""Verify ownership of the applicant email without provisioning a tenant.

	The password argument remains optional for backward API compatibility, but is
	intentionally not stored or used. Credentials are only accepted after all
	compliance gates have approved the registration.
	"""
	registration = _pending_record("Lexocrates Client Registration", token, "Pending Verification")

	def verify():
		registration.status = "Pending Compliance Review"
		registration.email_verified_on = now_datetime()
		registration.token_hash = None
		registration.save(ignore_permissions=True)
		return registration

	registration = _with_service_flag(verify)
	create_portal_audit_event(
		client=None,
		user=None,
		action="Client Registration Email Verified",
		object_type=registration.doctype,
		object_id=registration.name,
		new_value={"status": registration.status, "email": registration.email},
	)
	return {
		"verified": True,
		"pending_compliance_review": True,
		"registration": registration.name,
		"status": registration.status,
	}


@frappe.whitelist()
def record_registration_compliance(
	registration: str,
	kyc_status: str,
	conflict_check_status: str,
	sanctions_check_status: str,
	commercial_approval_status: str,
	review_notes: str | None = None,
):
	"""Record the four-eye onboarding decision and issue activation only if all gates pass."""
	if not _is_internal():
		frappe.throw(_("Only authorized staff can approve Client onboarding."), frappe.PermissionError)
	doc = frappe.get_doc("Lexocrates Client Registration", registration)
	if doc.status not in {"Pending Compliance Review", "Changes Required"}:
		frappe.throw(_("This registration is not awaiting compliance review."), frappe.ValidationError)

	check_values = {"Pending", "Passed", "Failed", "Needs Review"}
	if any(value not in check_values for value in (kyc_status, conflict_check_status, sanctions_check_status)):
		frappe.throw(_("Select a valid KYC, conflict, and sanctions decision."), frappe.ValidationError)
	if commercial_approval_status not in {"Pending", "Approved", "Rejected"}:
		frappe.throw(_("Select a valid commercial approval decision."), frappe.ValidationError)

	previous = {
		"kyc": doc.kyc_status,
		"conflict": doc.conflict_check_status,
		"sanctions": doc.sanctions_check_status,
		"commercial": doc.commercial_approval_status,
		"status": doc.status,
	}
	doc.kyc_status = kyc_status
	doc.conflict_check_status = conflict_check_status
	doc.sanctions_check_status = sanctions_check_status
	doc.commercial_approval_status = commercial_approval_status
	doc.reviewed_by = frappe.session.user
	doc.reviewed_on = now_datetime()
	doc.review_notes = (review_notes or "").strip()

	hard_failure = "Failed" in {kyc_status, conflict_check_status, sanctions_check_status} or commercial_approval_status == "Rejected"
	approved = (
		{kyc_status, conflict_check_status, sanctions_check_status} == {"Passed"}
		and commercial_approval_status == "Approved"
	)
	activation_token = None
	if hard_failure:
		doc.status = "Rejected"
		doc.activation_token_hash = None
		doc.activation_expires_on = None
	elif approved:
		doc.status = "Approved for Activation"
		activation_token = secrets.token_urlsafe(32)
		doc.activation_token_hash = _token_hash(activation_token)
		doc.activation_expires_on = add_to_date(now_datetime(), hours=REGISTRATION_ACTIVATION_HOURS)
	else:
		doc.status = "Pending Compliance Review"
		doc.activation_token_hash = None
		doc.activation_expires_on = None

	_with_service_flag(lambda: doc.save(ignore_permissions=True))
	current = {
		"kyc": doc.kyc_status,
		"conflict": doc.conflict_check_status,
		"sanctions": doc.sanctions_check_status,
		"commercial": doc.commercial_approval_status,
		"status": doc.status,
	}
	create_portal_audit_event(
		client=None,
		action="Client Registration Compliance Decision",
		object_type=doc.doctype,
		object_id=doc.name,
		previous_value=previous,
		new_value=current,
		details=doc.review_notes,
	)

	result = {"registration": doc.name, "status": doc.status, "approved": approved}
	if activation_token:
		activation_url = frappe.utils.get_url(f"/client-registration?activation={activation_token}")
		if not getattr(frappe.flags, "in_test", False):
			frappe.sendmail(
				recipients=[doc.email],
				subject=_("Your Lexocrates Client registration is approved"),
				message=_("Activate your approved account within {0} hours: <a href=\"{1}\">Activate account</a>.").format(
					REGISTRATION_ACTIVATION_HOURS, activation_url
				),
				now=True,
			)
		result["activation_url"] = activation_url
		if getattr(frappe.flags, "in_test", False):
			result["test_activation_token"] = activation_token
	return result


@frappe.whitelist(allow_guest=True)
def activate_approved_registration(token: str, password: str):
	registration = _approved_registration(token)
	_validate_password(password, [registration.primary_user_name, registration.email, registration.organization_name])

	def activate():
		customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		territory = frappe.db.get_value("Territory", {"is_group": 0}, "name")
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": registration.organization_name,
				"customer_type": "Company",
				"customer_group": customer_group,
				"territory": territory,
				"website": registration.website,
			}
		)
		for fieldname, value in {
			"custom_lexocrates_client_id": new_client_id(),
			"custom_organization_type": registration.organization_type,
			"custom_state_province": registration.state_province,
			"custom_primary_jurisdiction": registration.primary_jurisdiction,
			"custom_industry_practice_type": registration.industry_practice_type,
			"custom_tax_information": registration.tax_information,
			"default_currency": registration.billing_currency,
		}.items():
			if customer.meta.has_field(fieldname) and value:
				customer.set(fieldname, value)
		customer.insert(ignore_permissions=True)
		user = _create_client_website_user(registration.email, registration.primary_user_name, password)
		portal_user = frappe.get_doc(
			{
				"doctype": "Lexocrates Portal User",
				"user": user.name,
				"client": customer.name,
				"portal_role": "Client Administrator",
				"designation": registration.designation,
				"mobile": registration.mobile,
				"account_status": "Active",
				"matter_access_scope": "Assigned Matters",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "Lexocrates Client Wallet", "client": customer.name, "status": "Active"}).insert(ignore_permissions=True)
		registration.status = "Activated"
		registration.activated_on = now_datetime()
		registration.activation_token_hash = None
		registration.customer = customer.name
		registration.portal_user = portal_user.name
		registration.save(ignore_permissions=True)
		return customer, user, portal_user

	customer, user, portal_user = _with_service_flag(activate)
	create_portal_audit_event(
		client=customer.name,
		portal_user=portal_user.name,
		user=user.name,
		action="Client Registration Activated",
		object_type="Customer",
		object_id=customer.name,
		new_value={"client_id": customer.get("custom_lexocrates_client_id"), "organization": customer.customer_name},
	)
	return {"activated": True, "client": customer.name, "portal_user": portal_user.name, "redirect": "/client-portal"}


def _approved_registration(token: str):
	if not token or len(token) < 32:
		frappe.throw(_("The activation link is invalid."), frappe.PermissionError)
	name = frappe.db.get_value(
		"Lexocrates Client Registration", {"activation_token_hash": _token_hash(token)}, "name"
	)
	if not name:
		frappe.throw(_("The activation link is invalid."), frappe.PermissionError)
	doc = frappe.get_doc("Lexocrates Client Registration", name)
	if (
		doc.status != "Approved for Activation"
		or not doc.activation_expires_on
		or get_datetime(doc.activation_expires_on) < now_datetime()
	):
		frappe.throw(_("The activation link has expired or was already used."), frappe.PermissionError)
	if not (
		doc.kyc_status == "Passed"
		and doc.conflict_check_status == "Passed"
		and doc.sanctions_check_status == "Passed"
		and doc.commercial_approval_status == "Approved"
	):
		frappe.throw(_("Compliance approval is incomplete."), frappe.PermissionError)
	return doc


def _pending_record(doctype: str, token: str, expected_status: str):
	if not token or len(token) < 32:
		frappe.throw(_("The activation link is invalid."), frappe.PermissionError)
	name = frappe.db.get_value(doctype, {"token_hash": _token_hash(token)}, "name")
	if not name:
		frappe.throw(_("The activation link is invalid."), frappe.PermissionError)
	doc = frappe.get_doc(doctype, name)
	if doc.status != expected_status or get_datetime(doc.expires_on) < now_datetime():
		if doc.status == expected_status:
			_with_service_flag(lambda: _mark_expired(doc))
		frappe.throw(_("The activation link has expired or was already used."), frappe.PermissionError)
	return doc


def _mark_expired(doc):
	doc.status = "Expired"
	doc.save(ignore_permissions=True)


def _create_client_website_user(email: str, full_name: str, password: str):
	parts = full_name.strip().split(None, 1)
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": parts[0],
			"last_name": parts[1] if len(parts) > 1 else "",
			"enabled": 1,
			"user_type": "Website User",
			"send_welcome_email": 0,
			"new_password": password,
		}
	).insert(ignore_permissions=True)


@frappe.whitelist()
def assisted_internal_registration(
	organization_name: str,
	organization_type: str,
	country: str,
	primary_user_name: str,
	designation: str,
	email: str,
	billing_currency: str | None = None,
	state_province: str | None = None,
	primary_jurisdiction: str | None = None,
	industry_practice_type: str | None = None,
	website: str | None = None,
	mobile: str | None = None,
	tax_information: str | None = None,
):
	"""Assisted registration by internal staff using identical validation controls (REG-010)."""
	if not _is_internal():
		frappe.throw(_("Staff permission is required for assisted registration."), frappe.PermissionError)

	result = request_client_registration(
		organization_name=organization_name,
		organization_type=organization_type,
		country=country,
		primary_user_name=primary_user_name,
		designation=designation,
		email=email,
		billing_currency=billing_currency,
		state_province=state_province,
		primary_jurisdiction=primary_jurisdiction,
		industry_practice_type=industry_practice_type,
		website=website,
		mobile=mobile,
		tax_information=tax_information,
	)
	create_portal_audit_event(
		client=None,
		user=frappe.session.user,
		action="Staff Assisted Registration Created",
		object_type="Lexocrates Client Registration",
		object_id=result.get("registration"),
		new_value={"assisted_by": frappe.session.user, "email": email},
	)
	return result


@frappe.whitelist()
def cleanup_abandoned_registrations(retention_days: int = 30):
	"""Scheduled retention job producing evidence and anonymizing abandoned intake snapshots (REG-009)."""
	if not _is_internal():
		frappe.throw(_("Administrator permission is required."), frappe.PermissionError)

	cutoff = add_to_date(now_datetime(), days=-cint(retention_days))
	abandoned = frappe.get_all(
		"Lexocrates Client Registration",
		filters={"status": ["in", ["Pending Verification", "Pending Compliance Review", "Changes Required", "Expired", "Rejected"]], "creation": ["<", cutoff]},
		fields=["name", "organization_name", "email", "status"],
	)

	cleaned_count = 0
	for item in abandoned:
		frappe.db.set_value(
			"Lexocrates Client Registration",
			item.name,
			{
				"organization_name": f"[ANONYMIZED REGISTRATION {item.name}]",
				"primary_user_name": "Anonymized Applicant",
				"email": f"anonymized-{item.name}@privacy.invalid",
				"mobile": "",
				"tax_information": "",
				"status": "Abandoned & Anonymized",
			},
			update_modified=False,
		)
		create_portal_audit_event(
			client=None,
			user=frappe.session.user,
			action="Registration Anonymized By Retention Policy",
			object_type="Lexocrates Client Registration",
			object_id=item.name,
			new_value={"retention_cutoff": str(cutoff), "prior_status": item.status},
		)
		cleaned_count += 1

	return {"cleaned_records": cleaned_count, "cutoff": str(cutoff)}


@frappe.whitelist()
def revoke_user_sessions(portal_user_name: str, reason: str = "Administrator Session Revocation"):
	"""Revoke active web sessions for a Portal User (USR-007)."""
	portal_user = frappe.get_doc("Lexocrates Portal User", portal_user_name)
	if not _is_internal():
		actor = require_client_administrator()
		if portal_user.client != actor.client:
			frappe.throw(_("Access denied."), frappe.PermissionError)

	user_email = portal_user.user
	sessions = frappe.get_all("Sessions", filters={"user": user_email}, pluck="sid")
	for sid in sessions:
		frappe.db.delete("Sessions", {"sid": sid})

	frappe.clear_cache(user=user_email)
	create_portal_audit_event(
		client=portal_user.client,
		portal_user=portal_user.name,
		user=user_email,
		action="Active Sessions Revoked",
		object_type="User",
		object_id=user_email,
		new_value={"revoked_count": len(sessions), "reason": reason},
	)
	return {"revoked_sessions": len(sessions), "user": user_email}


@frappe.whitelist()
def anonymize_user_data(portal_user_name: str, legal_reason: str):
	"""Anonymize user PII while preserving authored audit logs and domain evidence (USR-008)."""
	if not _is_internal():
		frappe.throw(_("Staff permission is required for PII anonymization."), frappe.PermissionError)
	if not (legal_reason or "").strip():
		frappe.throw(_("A documented legal basis is required for anonymization."), frappe.MandatoryError)

	portal_user = frappe.get_doc("Lexocrates Portal User", portal_user_name)
	user_email = portal_user.user
	client_id = portal_user.client

	anonymized_name = f"Anonymized User {portal_user.name}"

	# Remove mutable profile PII first. The immutable User identifier is retained
	# only as the legal audit actor key; the account is revoked and cannot login.
	if frappe.db.exists("User", user_email):
		user_doc = frappe.get_doc("User", user_email)
		user_doc.first_name = "Anonymized"
		user_doc.last_name = portal_user.name
		user_doc.enabled = 0
		for fieldname in ("mobile_no", "phone", "location", "bio", "birth_date", "gender"):
			if user_doc.meta.has_field(fieldname):
				user_doc.set(fieldname, None)
		user_doc.save(ignore_permissions=True)

	# Update the direct Portal User profile after the base identity so fetched
	# display fields are also pseudonymized.
	portal_user.full_name = anonymized_name
	portal_user.designation = ""
	portal_user.mobile = ""
	portal_user.account_status = "Revoked"
	portal_user.deactivation_reason = (legal_reason or "").strip()
	portal_user.delegated_admin_until = None
	portal_user.delegated_by = None
	portal_user.delegation_reason = None
	_with_service_flag(lambda: portal_user.save(ignore_permissions=True))

	create_portal_audit_event(
		client=client_id,
		portal_user=portal_user.name,
		action="Portal User Personal Data Anonymized",
		object_type="Lexocrates Portal User",
		object_id=portal_user.name,
		new_value={"anonymized": True, "status": "Revoked", "legal_reason": legal_reason},
	)
	return {"portal_user": portal_user.name, "anonymized": True, "status": portal_user.account_status}

@frappe.whitelist(allow_guest=True)
def send_email_login_link(email: str, redirect_to: str | None = None):
	"""Send passwordless email login link / Magic Link to user (Login with Email)."""
	email = validate_email_address((email or "").strip().lower(), throw=True)
	if not frappe.db.exists("User", email):
		frappe.throw(_("No registered user account found with this email address."), frappe.DoesNotExistError)

	user_doc = frappe.get_doc("User", email)
	if not user_doc.enabled:
		frappe.throw(_("This user account is disabled."), frappe.PermissionError)

	token = secrets.token_urlsafe(32)
	now = now_datetime()
	expires_on = add_to_date(now, minutes=15)

	# Store token in Cache for 15 minutes
	cache_key = f"email_login_token_{_token_hash(token)}"
	frappe.cache().set_value(cache_key, {"user": email, "redirect_to": redirect_to or "/client-portal"}, expires_in_sec=900)

	login_url = frappe.utils.get_url(f"/login-link?token={token}")

	if not getattr(frappe.flags, "in_test", False):
		frappe.sendmail(
			recipients=[email],
			subject=_("Your Lexocrates Secure Login Link"),
			message=_(
				"Click the link below to sign in to Lexocrates (valid for 15 minutes):<br><br><a href=\"{0}\"><strong>Sign In to Lexocrates</strong></a>"
			).format(login_url),
			now=False,
		)

	create_portal_audit_event(
		client=None,
		user=email,
		action="Email Login Link Requested",
		object_type="User",
		object_id=email,
		new_value={"expires_on": str(expires_on)},
	)

	result = {"status": "sent", "email": email, "expires_in_minutes": 15}
	if getattr(frappe.flags, "in_test", False):
		result["test_token"] = token
	return result


@frappe.whitelist(allow_guest=True)
def verify_email_login_token(token: str):
	"""Verify passwordless login token and authenticate user session."""
	if not token or len(token) < 32:
		frappe.throw(_("Invalid or expired login link."), frappe.PermissionError)

	cache_key = f"email_login_token_{_token_hash(token)}"
	token_data = frappe.cache().get_value(cache_key)

	if not token_data or not isinstance(token_data, dict):
		frappe.throw(_("The login link has expired or was already used."), frappe.PermissionError)

	# Single-use token: remove from cache immediately
	frappe.cache().delete_value(cache_key)

	user = token_data.get("user")
	redirect_to = token_data.get("redirect_to") or "/client-portal"

	if not frappe.db.exists("User", user):
		frappe.throw(_("User account not found."), frappe.DoesNotExistError)

	# Authenticate user session
	frappe.local.login_manager.login_as(user)

	create_portal_audit_event(
		client=None,
		user=user,
		action="Login via Email Link Successful",
		object_type="User",
		object_id=user,
	)

	return {"status": "success", "user": user, "redirect": redirect_to}


@frappe.whitelist(allow_guest=True)
def get_website_user_home_page(user: str | None = None) -> str:
	user = user or frappe.session.user
	if not user or user == "Guest":
		return "login"
	user_type = frappe.db.get_value("User", user, "user_type")
	if user_type == "System User":
		return "app"
	if user_type == "Website User":
		return "client-portal"
	roles = set(frappe.get_roles(user))
	portal_roles = {
		"Lexocrates Client",
		"Lexocrates Client Administrator",
		"Lexocrates Partner General Counsel",
		"Lexocrates Legal User",
		"Lexocrates Operations User",
		"Lexocrates Finance User",
		"Lexocrates Procurement User",
		"Lexocrates Compliance User",
		"Lexocrates Read Only User",
		"Customer",
	}
	if roles.intersection(portal_roles):
		return "client-portal"
	return "app"
