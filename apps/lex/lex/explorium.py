"""Explorium B2B data search -> Lead creation.

Two free preview searches (companies, then people at the selected companies)
let Legal Ops/Sales shortlist prospects without spending credits. Credits are
spent only in create_leads_from_prospects, which enriches real contact
details for the prospects actually chosen and writes them to Lead.
"""

from __future__ import annotations

import frappe
import requests
from frappe import _
from frappe.utils import cint

API_ROOT = "https://api.explorium.ai"
ALLOWED_ROLES = {"System Manager", "Lexocrates Sales & Marketing", "LPO_Admin", "Lexocrates Director"}


def _require_access():
	if frappe.session.user == "Administrator":
		return
	if not set(frappe.get_roles()).intersection(ALLOWED_ROLES):
		frappe.throw(_("You are not permitted to use the Explorium integration."), frappe.PermissionError)


def _api_key() -> str:
	try:
		key = frappe.get_single("Explorium Settings").get_password("api_key", raise_exception=False)
	except frappe.DoesNotExistError:
		key = None
	if not key:
		frappe.throw(_("Add the Explorium API key in Explorium Settings before searching."), frappe.ValidationError)
	return key


def _request(path: str, payload: dict) -> dict:
	try:
		response = requests.post(
			f"{API_ROOT}{path}",
			headers={"api_key": _api_key(), "content-type": "application/json", "accept": "application/json"},
			json=payload,
			timeout=20,
		)
		response.raise_for_status()
		return response.json()
	except requests.RequestException as exc:
		message = _("Explorium could not process this request.")
		if getattr(exc, "response", None) is not None:
			try:
				message = str((exc.response.json() or {}).get("message") or message)[:500]
			except ValueError:
				pass
		frappe.throw(message, frappe.ValidationError)


@frappe.whitelist()
def search_businesses(filters: dict, page: int = 1, page_size: int = 25):
	"""Free preview search for companies matching an ICP. Spends no credits."""
	_require_access()
	data = _request("/v1/businesses", {
		"mode": "preview",
		"page": cint(page) or 1,
		"page_size": min(cint(page_size) or 25, 100),
		"filters": filters or {},
	})
	return {
		"results": data.get("data", []),
		"total_results": data.get("total_results"),
		"total_pages": data.get("total_pages"),
	}


@frappe.whitelist()
def search_prospects(business_ids: list, filters: dict, page: int = 1, page_size: int = 25):
	"""Free preview search for people at the given companies. Spends no credits."""
	_require_access()
	if not business_ids:
		frappe.throw(_("Select at least one company first."), frappe.ValidationError)
	scoped_filters = dict(filters or {})
	scoped_filters["business_id"] = {"values": business_ids}
	data = _request("/v1/prospects", {
		"mode": "preview",
		"page": cint(page) or 1,
		"page_size": min(cint(page_size) or 25, 100),
		"filters": scoped_filters,
	})
	return {
		"results": data.get("data", []),
		"total_results": data.get("total_results"),
		"total_pages": data.get("total_pages"),
	}


def _ensure_lead_source():
	if not frappe.db.exists("Lead Source", "Explorium"):
		frappe.get_doc({"doctype": "Lead Source", "source_name": "Explorium"}).insert(ignore_permissions=True)


def _resolve_country(country_name: str | None) -> str | None:
	if not country_name:
		return None
	candidate = country_name.strip().title()
	return candidate if frappe.db.exists("Country", candidate) else None


@frappe.whitelist()
def create_leads_from_prospects(prospects: list):
	"""Enrich real contact details (spends 1 credit per prospect) and upsert Lead by email."""
	_require_access()
	if not prospects:
		frappe.throw(_("Select at least one prospect."), frappe.ValidationError)
	_ensure_lead_source()

	created, updated, skipped = [], [], []
	for prospect in prospects:
		prospect_id = prospect.get("prospect_id")
		if not prospect_id:
			continue
		contact = (_request("/v1/prospects/contacts_information/enrich", {"prospect_id": prospect_id}) or {}).get("data") or {}
		emails = contact.get("emails") or []
		email = (contact.get("professions_email") or (emails[0] if emails else "") or "").strip()
		if not email:
			skipped.append({"prospect_id": prospect_id, "name": prospect.get("full_name"), "reason": "No email returned"})
			continue

		existing = frappe.db.get_value("Lead", {"email_id": email}, "name")
		lead = frappe.get_doc("Lead", existing) if existing else frappe.new_doc("Lead")
		lead.update({
			"lead_name": prospect.get("full_name") or f"{prospect.get('first_name') or ''} {prospect.get('last_name') or ''}".strip(),
			"first_name": prospect.get("first_name"),
			"last_name": prospect.get("last_name"),
			"email_id": email,
			"phone": contact.get("phone_numbers") or contact.get("mobile_phone") or "",
			"company_name": prospect.get("company_name"),
			"website": prospect.get("company_website"),
			"job_title": prospect.get("job_title"),
			"city": prospect.get("city"),
			"state": prospect.get("region_name"),
			"country": _resolve_country(prospect.get("country_name")),
			"source": "Explorium",
		})
		lead.save(ignore_permissions=True)
		(updated if existing else created).append(lead.name)

	return {"created": created, "updated": updated, "skipped": skipped}
