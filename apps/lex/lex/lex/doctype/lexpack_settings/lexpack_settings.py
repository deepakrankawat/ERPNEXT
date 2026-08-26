from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now_datetime


class LexPackSettings(Document):
	def validate(self):
		self.api_timeout_seconds = max(5, min(cint(self.api_timeout_seconds or 15), 60))
		if self.has_value_changed("auto_approve_ai_pricing") and not getattr(
			frappe.flags, "lexocrates_ceo_ai_auto_approval_update", False
		):
			frappe.throw(
				_("Use the CEO Auto-Approval action to change this protected policy."),
				frappe.PermissionError,
			)
		if cint(self.auto_approve_ai_pricing) and not cint(self.enable_ai_intake_analysis):
			frappe.throw(
				_("Enable Governed AI Intake Analysis before enabling AI estimate auto-approval."),
				frappe.ValidationError,
			)
		if self.enabled:
			from lex.lexpack import get_razorpay_readiness

			readiness = get_razorpay_readiness(self)
			if not readiness["configured"]:
				frappe.throw(
					_("Complete Razorpay setup before enabling payments: {0}").format(
						"; ".join(readiness["issues"])
					),
					frappe.ValidationError,
				)


def _require_ceo_policy_authority():
	user = frappe.session.user
	if user in {None, "", "Guest"}:
		frappe.throw(_("Authentication required."), frappe.AuthenticationError)
	if user != "Administrator" and "CEO" not in frappe.get_roles(user):
		frappe.throw(
			_("Only the CEO role can enable or disable AI estimate auto-approval."),
			frappe.PermissionError,
		)
	if user != "Administrator" and frappe.db.get_value("User", user, "user_type") != "System User":
		frappe.throw(_("This policy can be controlled only by an internal System User."), frappe.PermissionError)


@frappe.whitelist()
def set_ai_estimate_auto_approval(enabled: int = 0) -> dict:
	"""Activate or deactivate the CEO-owned, high-confidence AI pricing policy."""
	_require_ceo_policy_authority()
	settings = frappe.get_single("LexPack Settings")
	enabled = cint(enabled)
	provider = model = credential_name = None
	if enabled:
		if not cint(settings.enable_ai_intake_analysis):
			frappe.throw(
				_("Enable Governed AI Intake Analysis before enabling auto-approval."),
				frappe.ValidationError,
			)
		from lex.lex.doctype.lpo_ai_settings.lpo_ai_settings import resolve_ai_route

		provider, model, credential_name = resolve_ai_route(
			None,
			None,
			"Client Work Intake LexPoint Estimation",
		)
	settings.auto_approve_ai_pricing = enabled
	settings.auto_approve_ai_pricing_authorized_by = frappe.session.user if enabled else None
	settings.auto_approve_ai_pricing_authorized_on = now_datetime() if enabled else None
	previous_flag = getattr(frappe.flags, "lexocrates_ceo_ai_auto_approval_update", False)
	frappe.flags.lexocrates_ceo_ai_auto_approval_update = True
	try:
		settings.save(ignore_permissions=True)
	finally:
		frappe.flags.lexocrates_ceo_ai_auto_approval_update = previous_flag
	return {
		"enabled": bool(enabled),
		"authorized_by": settings.auto_approve_ai_pricing_authorized_by,
		"authorized_on": settings.auto_approve_ai_pricing_authorized_on,
		"provider": provider,
		"model": model,
		"credential_name": credential_name,
		"message": _("Eligible AI estimates will open funding without individual CEO approval.")
		if enabled
		else _("AI estimate auto-approval is disabled; individual CEO approval is required."),
	}
