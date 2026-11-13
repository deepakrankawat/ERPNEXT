from __future__ import annotations

from urllib.parse import quote

import requests

import frappe
from frappe.utils import add_days, add_to_date, get_datetime, now_datetime, nowdate

CALLBACK_METHOD = "/api/method/lex.google_search_console.oauth_callback"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
SETTINGS_PAGE = "/app/search-console-settings"

# Search Console data has a 2-3 day reporting lag; re-pull a rolling window ending
# yesterday on every sync so late-finalized rows get corrected automatically.
SYNC_WINDOW_DAYS = 5


def _google_settings():
	settings = frappe.get_cached_doc("Google Settings")
	if not settings.enable or not settings.client_id:
		frappe.throw("Enable Google API and set a Client ID/Secret in Google Settings first.")
	return settings


def _redirect_uri() -> str:
	return frappe.utils.get_request_site_address(True) + CALLBACK_METHOD


@frappe.whitelist()
def get_authentication_url() -> str:
	"""Called by the Search Console Settings 'Connect' button. Returns the Google
	consent URL; the browser is redirected there directly."""
	settings = _google_settings()
	return (
		f"{AUTH_URL}?access_type=offline&response_type=code&prompt=consent"
		f"&client_id={quote(settings.client_id)}&scope={quote(SCOPE)}"
		f"&redirect_uri={quote(_redirect_uri())}"
	)


@frappe.whitelist(methods=["GET"])
def oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None):
	"""Google redirects here after consent. Exchanges the code for tokens, stores them
	on the Search Console Settings singleton, and redirects back to the settings page."""
	if error or not code:
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = f"{SETTINGS_PAGE}?gsc_error=1"
		return

	settings = _google_settings()
	resp = requests.post(
		TOKEN_URL,
		data={
			"code": code,
			"client_id": settings.client_id,
			"client_secret": settings.get_password("client_secret", raise_exception=False),
			"grant_type": "authorization_code",
			"redirect_uri": _redirect_uri(),
		},
		timeout=10,
	)
	body = resp.json()
	if not resp.ok or "error" in body:
		frappe.log_error(title="GSC OAuth token exchange failed", message=str(body)[:2000])
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = f"{SETTINGS_PAGE}?gsc_error=1"
		return

	values = {
		"access_token": body.get("access_token"),
		"token_expiry": add_to_date(now_datetime(), seconds=int(body.get("expires_in", 3600)) - 60),
	}
	# Google only returns refresh_token when prompt=consent forces re-consent (always,
	# here) - still, don't clobber a previously stored one on an empty response.
	if body.get("refresh_token"):
		values["refresh_token"] = body["refresh_token"]
	frappe.db.set_single_value("Search Console Settings", values)
	frappe.db.commit()

	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = SETTINGS_PAGE


def get_valid_access_token(settings=None) -> str:
	"""Returns a usable access token, refreshing via the refresh_token grant if expired."""
	settings = settings or frappe.get_cached_doc("Search Console Settings")
	refresh_token = settings.get_password("refresh_token", raise_exception=False)
	if not refresh_token:
		frappe.throw("Search Console is not connected. Go to Search Console Settings and click Connect.")

	if settings.token_expiry and get_datetime(settings.token_expiry) > now_datetime():
		token = settings.get_password("access_token", raise_exception=False)
		if token:
			return token

	gsettings = _google_settings()
	resp = requests.post(
		TOKEN_URL,
		data={
			"client_id": gsettings.client_id,
			"client_secret": gsettings.get_password("client_secret", raise_exception=False),
			"refresh_token": refresh_token,
			"grant_type": "refresh_token",
		},
		timeout=10,
	)
	body = resp.json()
	if not resp.ok or "error" in body:
		frappe.log_error(title="GSC access token refresh failed", message=str(body)[:2000])
		frappe.throw("Could not refresh the Google Search Console access token.")

	expiry = add_to_date(now_datetime(), seconds=int(body.get("expires_in", 3600)) - 60)
	frappe.db.set_single_value("Search Console Settings", {
		"access_token": body.get("access_token"),
		"token_expiry": expiry,
	})
	frappe.db.commit()
	return body.get("access_token")


def sync_search_analytics():
	"""Scheduled daily job: pulls the rolling window from Search Console and replaces
	each day's rows in GSC Search Analytics."""
	settings = frappe.get_cached_doc("Search Console Settings")
	if not settings.enabled or not settings.site_url:
		return
	if not settings.get_password("refresh_token", raise_exception=False):
		return

	try:
		access_token = get_valid_access_token(settings)
	except Exception:
		frappe.log_error(title="GSC sync aborted: could not get access token")
		return

	end = add_days(nowdate(), -1)
	start = add_days(end, -(SYNC_WINDOW_DAYS - 1))

	url = f"https://www.googleapis.com/webmasters/v3/sites/{quote(settings.site_url, safe='')}/searchAnalytics/query"
	resp = requests.post(
		url,
		headers={"Authorization": f"Bearer {access_token}"},
		json={"startDate": start, "endDate": end, "dimensions": ["date", "query"], "rowLimit": 25000},
		timeout=30,
	)
	if not resp.ok:
		frappe.log_error(title="GSC searchAnalytics.query failed", message=resp.text[:2000])
		return

	rows_by_date: dict[str, list] = {}
	for row in resp.json().get("rows", []):
		row_date, row_query = row["keys"]
		rows_by_date.setdefault(row_date, []).append((row_query, row))

	current = start
	while current <= end:
		try:
			frappe.db.delete("GSC Search Analytics", {"date": current})
			for row_query, row in rows_by_date.get(current, []):
				frappe.get_doc({
					"doctype": "GSC Search Analytics",
					"date": current,
					"query": row_query,
					"clicks": row.get("clicks", 0),
					"impressions": row.get("impressions", 0),
					"ctr": row.get("ctr", 0) * 100,
					"position": row.get("position", 0),
				}).insert(ignore_permissions=True)
			frappe.db.commit()
		except Exception:
			frappe.log_error(title=f"GSC sync failed for {current}")
			frappe.db.rollback()
		current = add_days(current, 1)

	frappe.db.set_single_value("Search Console Settings", "last_synced", now_datetime())
	frappe.db.commit()


def _sum_last_30_days(fieldname: str) -> float:
	since = add_days(nowdate(), -30)
	value = frappe.db.sql(
		f"SELECT COALESCE(SUM({fieldname}), 0) FROM `tabGSC Search Analytics` WHERE date >= %s",
		(since,),
	)[0][0]
	return value or 0


def _avg_last_30_days(fieldname: str) -> float:
	since = add_days(nowdate(), -30)
	value = frappe.db.sql(
		f"SELECT COALESCE(AVG({fieldname}), 0) FROM `tabGSC Search Analytics` WHERE date >= %s",
		(since,),
	)[0][0]
	return value or 0


@frappe.whitelist()
def clicks_last_30_days(filters=None):
	return {"value": int(_sum_last_30_days("clicks")), "fieldtype": "Int", "route": ["List", "GSC Search Analytics"]}


@frappe.whitelist()
def impressions_last_30_days(filters=None):
	return {"value": int(_sum_last_30_days("impressions")), "fieldtype": "Int", "route": ["List", "GSC Search Analytics"]}


@frappe.whitelist()
def avg_ctr_last_30_days(filters=None):
	return {"value": round(float(_avg_last_30_days("ctr")), 2), "fieldtype": "Percent", "route": ["List", "GSC Search Analytics"]}


@frappe.whitelist()
def avg_position_last_30_days(filters=None):
	return {"value": round(float(_avg_last_30_days("position")), 1), "fieldtype": "Float", "route": ["List", "GSC Search Analytics"]}
