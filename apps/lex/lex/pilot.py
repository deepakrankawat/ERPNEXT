"""One-assignment complimentary pilot policy, separate from prepaid Legal Capacity."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, now_datetime


PILOT_MARKETS = {"CAD": "Canada", "USD": "United States", "GBP": "United Kingdom"}


def ensure_initial_pilot_limit():
	"""Keep the existing Canadian example as a configurable market row."""
	settings = frappe.get_single("LexPack Settings")
	if settings.complimentary_pilot_limits:
		return
	settings.append("complimentary_pilot_limits", {
		"market": "Canada", "currency": "CAD", "complimentary_pilot_value_limit": 200, "enabled": 1,
	})
	settings.save(ignore_permissions=True)


def pilot_limits():
	"""Return only explicitly enabled market limits; never invent an exchange rate."""
	settings = frappe.get_single("LexPack Settings")
	return {
		row.currency: flt(row.complimentary_pilot_value_limit, 2)
		for row in settings.complimentary_pilot_limits or []
		if row.enabled and row.market == PILOT_MARKETS.get(row.currency)
		and flt(row.complimentary_pilot_value_limit) > 0
	}


def pilot_offer_for_client(client: str):
	from lex.lexpack import _country_currency_for_client

	currency = _country_currency_for_client(client)
	limit = pilot_limits().get(currency)
	status = "Available" if limit else "Not Configured"
	for row in frappe.get_all(
		"Lexocrates Work Intake",
		filters={"client": client, "pilot_status": ["in", ["Requested", "Approved"]]},
		fields=["name", "pilot_status", "status", "funding_status"],
		limit_page_length=0,
	):
		if row.pilot_status == "Approved":
			status = "Used"
			break
		if row.status != "Cancelled" and row.funding_status != "Funded":
			status = "Requested"
	return {"status": status, "currency": currency, "value_limit": limit, "market": PILOT_MARKETS.get(currency)}


def _lock_client(client: str):
	# The customer row serializes pilot decisions across all users and intakes
	# belonging to the same organisation.
	frappe.db.sql("select name from `tabCustomer` where name=%s for update", client)


@frappe.whitelist()
def request_complimentary_pilot(intake: str):
	from lex import work_intake

	doc, actor = work_intake._require_intake_access(intake)
	if not actor:
		frappe.throw(_("A client portal account is required to request a pilot."), frappe.PermissionError)
	_lock_client(doc.client)
	doc.reload()
	work_intake._validate_ready_quote(doc)
	if doc.funding_status in {"Payment Pending", "Funded"}:
		frappe.throw(_("This assignment already has a funding decision."), frappe.ValidationError)
	if doc.pilot_status not in {None, "", "Not Requested"}:
		frappe.throw(_("This assignment already has a pilot decision."), frappe.ValidationError)
	offer = pilot_offer_for_client(doc.client)
	if offer["status"] != "Available":
		frappe.throw(_("A complimentary pilot is unavailable for this client organisation."), frappe.ValidationError)
	if doc.currency != offer["currency"]:
		frappe.throw(_("The assignment currency does not match the client market."), frappe.ValidationError)
	if flt(doc.quoted_amount, 2) > offer["value_limit"]:
		frappe.throw(_("This assignment exceeds the applicable Complimentary Pilot Value Limit."), frappe.ValidationError)
	with work_intake._service_writes():
		doc.pilot_status = "Requested"
		doc.save(ignore_permissions=True)
	work_intake._audit(doc, "Complimentary Pilot Requested", {"currency": doc.currency, "quoted_amount": doc.quoted_amount})
	return {"status": "Requested", "intake": doc.name}


@frappe.whitelist()
def decide_complimentary_pilot(intake: str, decision: str, notes: str | None = None):
	"""Legal Operations approves the scope and consumes the one-time pilot."""
	from lex import work_intake

	if frappe.session.user != "Administrator" and not set(frappe.get_roles()).intersection(
		{"System Manager", "LPO_Admin", "LPO_Manager", "CEO"}
	):
		frappe.throw(_("Legal Operations approval is required for a complimentary pilot."), frappe.PermissionError)
	if decision not in {"Approved", "Declined"}:
		frappe.throw(_("Choose Approved or Declined."), frappe.ValidationError)
	doc = frappe.get_doc("Lexocrates Work Intake", intake)
	_lock_client(doc.client)
	doc.reload()
	if doc.pilot_status != "Requested" or doc.funding_status in {"Payment Pending", "Funded"}:
		frappe.throw(_("This pilot request is no longer pending."), frappe.ValidationError)
	if decision == "Declined":
		if not (notes or "").strip():
			frappe.throw(_("A reason is required when declining a pilot."), frappe.ValidationError)
		with work_intake._service_writes():
			doc.pilot_status = "Declined"
			doc.save(ignore_permissions=True)
		work_intake._audit(doc, "Complimentary Pilot Declined", {"notes": notes})
		return {"status": "Declined", "intake": doc.name}
	work_intake._validate_ready_quote(doc)
	offer = pilot_offer_for_client(doc.client)
	if offer["status"] == "Used" or not offer["value_limit"] or doc.currency != offer["currency"]:
		frappe.throw(_("The complimentary pilot is unavailable for this client organisation or currency."), frappe.ValidationError)
	if flt(doc.quoted_amount, 2) > offer["value_limit"]:
		frappe.throw(_("This assignment exceeds the applicable Complimentary Pilot Value Limit."), frappe.ValidationError)
	with work_intake._service_writes():
		doc.pilot_status = "Approved"
		doc.pilot_value_limit = offer["value_limit"]
		doc.pilot_approved_by = frappe.session.user
		doc.pilot_approved_on = now_datetime()
		doc.funding_route = "Complimentary Pilot"
		doc.funding_status = "Funded"
		doc.funded_on = now_datetime()
		doc.quote_status = "Accepted"
		doc.status = "Funded"
		doc.save(ignore_permissions=True)
	result = work_intake._confirm_funded_intake(doc)
	work_intake._audit(doc, "Complimentary Pilot Approved", {
		"currency": doc.currency, "quoted_amount": doc.quoted_amount,
		"value_limit": offer["value_limit"], "notes": notes,
	})
	return {"status": "Approved", "intake": doc.name, "matter": result["matter"], "job": result["job"]}
