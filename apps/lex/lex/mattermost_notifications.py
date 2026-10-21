"""Mirrors Frappe's internal Notification Log into per-user Mattermost DMs.

Notification Log already captures every internal notification (assignment,
mention, share, energy point, etc.) regardless of producer, so hooking its
after_insert is sufficient to cover the whole notification stream without
touching each individual event. Only System Users (internal staff) are
contacted; client/portal users have no Mattermost account to DM.
"""

from __future__ import annotations

import hmac

import requests

import frappe
from frappe.utils import get_datetime, get_url, get_url_to_form, now_datetime, strip_html

CACHE_TTL = 3600


def enqueue_forward_to_mattermost(doc, method=None):
	frappe.enqueue(
		"lex.mattermost_notifications.forward_to_mattermost",
		queue="short",
		enqueue_after_commit=True,
		notification_log=doc.name,
	)


def forward_to_mattermost(notification_log: str):
	settings = _get_settings()
	if not settings:
		return
	base_url, token, _team = settings

	doc = frappe.get_doc("Notification Log", notification_log)
	if not doc.for_user or doc.for_user in ("Administrator", "Guest"):
		return
	if frappe.db.get_value("User", doc.for_user, "user_type") != "System User":
		return

	try:
		mm_user_id = _resolve_mattermost_user_id(base_url, token, doc.for_user)
		if not mm_user_id:
			return
		bot_user_id = _resolve_bot_user_id(base_url, token)
		channel_id = _get_or_create_dm_channel(base_url, token, bot_user_id, mm_user_id)
		_post_message(base_url, token, channel_id, _build_message(doc))
	except requests.RequestException:
		frappe.log_error(title="Mattermost notification forward failed")


def notify(
	for_user: str | None,
	subject: str,
	*,
	document_type: str | None = None,
	document_name: str | None = None,
	notification_type: str = "Alert",
):
	"""Create a Notification Log for `for_user`.

	This is the single entry point every other feature (SLA warnings, QA
	rejections, compliance/escalation alerts, ...) should call to reach a
	specific internal user: it lands in Frappe's own notification bell AND
	gets DM'd to Mattermost by forward_to_mattermost above, for free.
	"""
	if not for_user:
		return
	frappe.get_doc({
		"doctype": "Notification Log",
		"for_user": for_user,
		"type": notification_type,
		"subject": subject,
		"document_type": document_type,
		"document_name": document_name,
	}).insert(ignore_permissions=True)


def _get_settings() -> tuple[str, str, str] | None:
	mm_settings = frappe.get_cached_doc("Mattermost Settings")
	if not mm_settings.enabled:
		return None
	token = mm_settings.get_password("bot_access_token", raise_exception=False)
	url = (mm_settings.mattermost_url or "").rstrip("/")
	team = mm_settings.mattermost_team or "lexocrates"
	if not token or not url:
		return None
	return url, token, team


def _headers(token: str) -> dict:
	return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _resolve_bot_user_id(base_url: str, token: str) -> str:
	cache_key = f"mattermost_bot_user_id:{base_url}"
	cached = frappe.cache().get_value(cache_key)
	if cached:
		return cached
	response = requests.get(f"{base_url}/api/v4/users/me", headers=_headers(token), timeout=10)
	response.raise_for_status()
	user_id = response.json()["id"]
	frappe.cache().set_value(cache_key, user_id, expires_in_sec=CACHE_TTL)
	return user_id


def _resolve_mattermost_user_id(base_url: str, token: str, email: str) -> str | None:
	cache_key = f"mattermost_user_id:{email}"
	cached = frappe.cache().get_value(cache_key)
	if cached:
		return cached
	response = requests.get(
		f"{base_url}/api/v4/users/email/{email}", headers=_headers(token), timeout=10
	)
	if response.status_code == 404:
		return None
	response.raise_for_status()
	user_id = response.json()["id"]
	frappe.cache().set_value(cache_key, user_id, expires_in_sec=CACHE_TTL)
	return user_id


def _get_or_create_dm_channel(base_url: str, token: str, bot_user_id: str, target_user_id: str) -> str:
	response = requests.post(
		f"{base_url}/api/v4/channels/direct",
		headers=_headers(token),
		json=[bot_user_id, target_user_id],
		timeout=10,
	)
	response.raise_for_status()
	return response.json()["id"]


def _post_message(base_url: str, token: str, channel_id: str, message: str):
	response = requests.post(
		f"{base_url}/api/v4/posts",
		headers=_headers(token),
		json={"channel_id": channel_id, "message": message},
		timeout=10,
	)
	response.raise_for_status()


def _build_message(doc) -> str:
	title = strip_html(doc.title or doc.subject or "You have a new notification")
	lines = [f"**{title}**"]
	# Producers (e.g. assign_to.notify_assignment) almost never set `link` themselves;
	# the document's form URL is derived from document_type/document_name instead.
	link = get_url(doc.link) if doc.link else None
	if not link and doc.document_type and doc.document_name:
		link = get_url_to_form(doc.document_type, doc.document_name)
	if link:
		lines.append(f"[Open {doc.document_type}: {doc.document_name}]({link})" if doc.document_type else f"[Open]({link})")
	return "\n".join(lines)


# ---------------------------------------------------------------------------
# Channel posting (daily digest, etc.)
# ---------------------------------------------------------------------------

def post_to_channel(channel_name: str, message: str):
	settings = _get_settings()
	if not settings:
		return
	base_url, token, team = settings
	try:
		channel_id = _resolve_channel_id(base_url, token, team, channel_name)
		if not channel_id:
			frappe.log_error(title=f"Mattermost channel not found: {channel_name}")
			return
		try:
			_post_message(base_url, token, channel_id, message)
		except requests.HTTPError as exc:
			# Bot exists and the channel exists, but the bot was never added to it.
			if exc.response is not None and exc.response.status_code == 403:
				_join_channel(base_url, token, channel_id)
				_post_message(base_url, token, channel_id, message)
			else:
				raise
	except requests.RequestException:
		frappe.log_error(title="Mattermost channel post failed")


def _resolve_channel_id(base_url: str, token: str, team: str, channel_name: str) -> str | None:
	cache_key = f"mattermost_channel_id:{team}:{channel_name}"
	cached = frappe.cache().get_value(cache_key)
	if cached:
		return cached
	response = requests.get(
		f"{base_url}/api/v4/teams/name/{team}/channels/name/{channel_name}",
		headers=_headers(token),
		timeout=10,
	)
	if response.status_code == 404:
		return None
	response.raise_for_status()
	channel_id = response.json()["id"]
	frappe.cache().set_value(cache_key, channel_id, expires_in_sec=CACHE_TTL)
	return channel_id


def _join_channel(base_url: str, token: str, channel_id: str):
	bot_user_id = _resolve_bot_user_id(base_url, token)
	response = requests.post(
		f"{base_url}/api/v4/channels/{channel_id}/members",
		headers=_headers(token),
		json={"user_id": bot_user_id},
		timeout=10,
	)
	response.raise_for_status()


# ---------------------------------------------------------------------------
# Daily digest — overdue / at-risk LPO Jobs, posted once a day to a channel.
# ---------------------------------------------------------------------------

OPEN_JOB_STATUSES = ["Work Commenced", "In Progress", "QA Review", "Ready for Delivery", "SLA Paused"]


def post_daily_digest():
	mm_settings = frappe.get_cached_doc("Mattermost Settings")
	if not mm_settings.enabled:
		return
	jobs = frappe.get_all(
		"LPO Job",
		filters={
			"job_status": ["in", OPEN_JOB_STATUSES],
			"confirmed_delivery_date": ["is", "set"],
		},
		fields=["name", "job_title", "confirmed_delivery_date", "assigned_analyst"],
	)
	if not jobs:
		return

	now = now_datetime()
	overdue, at_risk = [], []
	for job in jobs:
		remaining_hours = (get_datetime(job.confirmed_delivery_date) - now).total_seconds() / 3600
		if remaining_hours <= 0:
			overdue.append(job)
		elif remaining_hours <= 24:
			at_risk.append(job)

	if not overdue and not at_risk:
		return

	lines = ["**Daily LPO Status Digest**"]
	for label, bucket in (("Overdue", overdue), ("Due within 24h", at_risk)):
		if not bucket:
			continue
		lines.append(f"\n**{label} ({len(bucket)}):**")
		for job in bucket[:25]:
			analyst = f" — {job.assigned_analyst}" if job.assigned_analyst else ""
			lines.append(f"- [{job.name}]({get_url_to_form('LPO Job', job.name)}) {job.job_title or ''}{analyst}")

	channel_name = mm_settings.digest_channel_name or "town-square"
	post_to_channel(channel_name, "\n".join(lines))


# ---------------------------------------------------------------------------
# Slash command — "/matter <Job or Matter ID>" looked up live from Mattermost.
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def slash_command_lookup():
	"""Mattermost posts application/x-www-form-urlencoded data here (token,
	text, user_name, ...) per https://developers.mattermost.com/integrate/slash-commands/.
	The response must be a bare JSON object, not Frappe's {"message": ...} envelope."""
	form = frappe.local.form_dict
	mm_settings = frappe.get_cached_doc("Mattermost Settings")
	expected_token = mm_settings.get_password("slash_command_token", raise_exception=False)
	provided_token = form.get("token") or ""
	if not expected_token or not hmac.compare_digest(str(provided_token), str(expected_token)):
		frappe.local.response = frappe._dict({"response_type": "ephemeral", "text": "Not authorized."})
		return

	query = (form.get("text") or "").strip()
	if not query:
		frappe.local.response = frappe._dict(
			{"response_type": "ephemeral", "text": "Usage: `/matter <Job or Matter ID>` e.g. `/matter LPOJ-2026-00001`"}
		)
		return

	frappe.local.response = frappe._dict(_lookup_matter_or_job(query))


def _lookup_matter_or_job(query: str) -> dict:
	if frappe.db.exists("LPO Job", query):
		job = frappe.get_doc("LPO Job", query)
		text = (
			f"**[{job.name}]({get_url_to_form('LPO Job', job.name)})** — {job.job_title or ''}\n"
			f"Status: **{job.job_status}** · Priority: {job.priority or 'Not set'}\n"
			f"Assigned to: {job.assigned_analyst or 'Unassigned'}\n"
			f"Confirmed Delivery Date: {job.confirmed_delivery_date or 'Not set'}\n"
			f"Matter: {job.engagement or 'Not set'}"
		)
		return {"response_type": "in_channel", "text": text}

	if frappe.db.exists("LPO Matter", query):
		matter = frappe.get_doc("LPO Matter", query)
		open_jobs = frappe.get_all(
			"LPO Job",
			filters={"engagement": matter.name, "job_status": ["in", OPEN_JOB_STATUSES]},
			fields=["name", "job_status"],
			limit_page_length=10,
		)
		jobs_text = (
			"\n".join(f"- {j.name} ({j.job_status})" for j in open_jobs) if open_jobs else "No open jobs."
		)
		text = (
			f"**[{matter.name}]({get_url_to_form('LPO Matter', matter.name)})** — {matter.matter_title or ''}\n"
			f"Status: **{matter.status}** · Manager: {matter.matter_manager or 'Not set'}\n"
			f"Open jobs:\n{jobs_text}"
		)
		return {"response_type": "in_channel", "text": text}

	return {"response_type": "ephemeral", "text": f"No LPO Job or Matter found matching `{query}`."}
