from __future__ import annotations

import hashlib
from datetime import datetime, time, timedelta, timezone
from email.utils import formataddr
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.core.doctype.communication.email import make
from frappe.utils import getdate


DISPATCH_DOCTYPE = "Lexocrates Email Campaign Dispatch"
FINAL_DISPATCH_STATES = {"Queued", "Sent"}


def process_due_email_campaigns(now_utc: datetime | None = None):
	"""Queue every due timed campaign exactly once, including missed schedules."""
	now_utc = _aware_utc(now_utc)
	_sync_dispatch_delivery_states()
	campaign_names = frappe.get_all(
		"Email Campaign",
		filters={"time_scheduling_enabled": 1, "status": ["!=", "Unsubscribed"]},
		pluck="name",
		limit_page_length=0,
	)
	results = {"checked": len(campaign_names), "queued": 0, "failed": 0}
	for campaign_name in campaign_names:
		campaign = frappe.get_doc("Email Campaign", campaign_name)
		schedules = list(frappe.get_cached_doc("Campaign", campaign.campaign_name).campaign_schedules)
		for entry in schedules:
			scheduled_utc = None
			try:
				scheduled_utc = scheduled_datetime_utc(campaign, entry)
				if scheduled_utc > now_utc:
					continue
				if _queue_dispatch(campaign, entry, scheduled_utc):
					results["queued"] += 1
			except Exception:
				results["failed"] += 1
				_record_dispatch_error(campaign, entry, scheduled_utc or now_utc, frappe.get_traceback())
				frappe.log_error(
					frappe.get_traceback(),
					_("Timed Email Campaign Dispatch Failed: {0}").format(campaign.name),
				)
		_mark_campaign_complete_if_queued(campaign, schedules)
	return results


def scheduled_datetime_utc(campaign, entry) -> datetime:
	zone = ZoneInfo(campaign.time_zone or "Asia/Kolkata")
	send_date = getdate(campaign.start_date) + timedelta(days=int(entry.send_after_days or 0))
	send_time = _parse_time(entry.get("send_at_time") or campaign.start_time or "09:00:00")
	local_naive = datetime.combine(send_date, send_time)
	local_aware = local_naive.replace(tzinfo=zone)
	scheduled_utc = local_aware.astimezone(timezone.utc)
	# Reject nonexistent local clock values during a daylight-saving jump.
	if scheduled_utc.astimezone(zone).replace(tzinfo=None) != local_naive:
		frappe.throw(
			_("{0} does not exist in timezone {1} because of a daylight-saving transition.").format(
				local_naive, zone.key
			),
			frappe.ValidationError,
		)
	return scheduled_utc


def _queue_dispatch(campaign, entry, scheduled_utc: datetime) -> bool:
	dispatch_key = _dispatch_key(campaign.name, entry.name or entry.idx)
	frappe.db.sql(
		f"select name from `tab{DISPATCH_DOCTYPE}` where name=%s for update",
		dispatch_key,
	)
	dispatch = frappe.db.get_value(
		DISPATCH_DOCTYPE,
		dispatch_key,
		["name", "status", "communication"],
		as_dict=True,
	)
	if dispatch and dispatch.status in FINAL_DISPATCH_STATES:
		return False
	if dispatch and dispatch.communication and frappe.db.exists(
		"Email Queue", {"communication": dispatch.communication}
	):
		frappe.db.set_value(DISPATCH_DOCTYPE, dispatch.name, {"status": "Queued", "error": None})
		return False
	if not dispatch:
		dispatch_doc = frappe.get_doc({
			"doctype": DISPATCH_DOCTYPE,
			"dispatch_key": dispatch_key,
			"email_campaign": campaign.name,
			"campaign": campaign.campaign_name,
			"schedule_index": entry.idx,
			"email_template": entry.email_template,
			"scheduled_for_utc": scheduled_utc.replace(tzinfo=None),
			"time_zone": campaign.time_zone,
			"status": "Processing",
		}).insert(ignore_permissions=True)
	else:
		dispatch_doc = frappe.get_doc(DISPATCH_DOCTYPE, dispatch.name)
		dispatch_doc.status = "Processing"
		dispatch_doc.error = None
		dispatch_doc.save(ignore_permissions=True)

	recipients, context = _recipients_and_context(campaign)
	template = frappe.get_cached_doc("Email Template", entry.email_template)
	subject = frappe.render_template(template.subject, context)
	content = frappe.render_template(template.response_, context)
	sender = _formatted_sender(campaign.sender)

	communication_name = dispatch_doc.communication
	if not communication_name:
		communication = make(
			doctype="Email Campaign",
			name=campaign.name,
			subject=subject,
			content=content,
			sender=sender,
			recipients=recipients,
			communication_medium="Email",
			sent_or_received="Sent",
			send_email=False,
			email_template=template.name,
		)
		communication_name = communication["name"]
		dispatch_doc.communication = communication_name
		dispatch_doc.save(ignore_permissions=True)

	frappe.sendmail(
		recipients=recipients,
		subject=subject,
		content=content,
		sender=sender,
		communication=communication_name,
		queue_separately=True,
	)
	dispatch_doc.status = "Queued"
	dispatch_doc.error = None
	dispatch_doc.save(ignore_permissions=True)
	return True


def _formatted_sender(sender_user: str | None) -> str | None:
	"""Resolve a campaign's sender User to `"Display Name" <email>`.

	Falls back to the bare email if no matching outgoing Email Account is found,
	so the mail is never blocked for missing display-name config.
	"""
	if not sender_user:
		return None
	sender_email = frappe.db.get_value("User", sender_user, "email")
	if not sender_email:
		return None
	display_name = frappe.db.get_value(
		"Email Account",
		{"email_id": sender_email, "enable_outgoing": 1},
		"email_account_name",
	)
	return formataddr((display_name, sender_email)) if display_name else sender_email


def _recipients_and_context(campaign):
	# Flat field context (not {"doc": ...}) to match how Frappe's own Email
	# Template rendering (EmailTemplate.get_formatted_response, used by every
	# "select template" compose box across the system) passes the reference
	# document's fields directly — templates written as {{ field }} then work
	# whether dispatched by this scheduler or sent manually.
	if campaign.email_campaign_for == "Email Group":
		recipients = frappe.get_all(
			"Email Group Member",
			filters={"email_group": campaign.recipient, "unsubscribed": 0},
			pluck="email",
		)
		context = frappe.get_doc("Email Group", campaign.recipient).as_dict()
	else:
		email = frappe.db.get_value(campaign.email_campaign_for, campaign.recipient, "email_id")
		recipients = [email] if email else []
		context = frappe.get_doc(campaign.email_campaign_for, campaign.recipient).as_dict()
	if not recipients:
		frappe.throw(
			_("No subscribed email recipients were found for Email Campaign {0}.").format(campaign.name),
			frappe.ValidationError,
		)
	return recipients, context


def _sync_dispatch_delivery_states():
	for dispatch in frappe.get_all(
		DISPATCH_DOCTYPE,
		filters={"status": ["in", ["Processing", "Queued", "Error"]], "communication": ["is", "set"]},
		fields=["name", "communication", "status"],
		limit_page_length=500,
	):
		states = frappe.get_all("Email Queue", filters={"communication": dispatch.communication}, pluck="status")
		if states and all(state == "Sent" for state in states):
			frappe.db.set_value(DISPATCH_DOCTYPE, dispatch.name, {"status": "Sent", "error": None})
		elif any(state in {"Error", "Partially Sent"} for state in states):
			frappe.db.set_value(
				DISPATCH_DOCTYPE,
				dispatch.name,
				{"status": "Error", "error": "One or more recipient Email Queue records failed."},
			)


def _mark_campaign_complete_if_queued(campaign, schedules):
	if not schedules:
		return
	keys = [_dispatch_key(campaign.name, entry.name or entry.idx) for entry in schedules]
	completed = frappe.get_all(
		DISPATCH_DOCTYPE,
		filters={"name": ["in", keys], "status": ["in", list(FINAL_DISPATCH_STATES)]},
		pluck="name",
	)
	if len(set(completed)) == len(keys) and campaign.status != "Completed":
		frappe.db.set_value("Email Campaign", campaign.name, "status", "Completed")


def _record_dispatch_error(campaign, entry, scheduled_utc, error):
	key = _dispatch_key(campaign.name, entry.name or entry.idx)
	values = {"status": "Error", "error": error[-10000:]}
	if frappe.db.exists(DISPATCH_DOCTYPE, key):
		frappe.db.set_value(DISPATCH_DOCTYPE, key, values)
	else:
		frappe.get_doc({
			"doctype": DISPATCH_DOCTYPE,
			"dispatch_key": key,
			"email_campaign": campaign.name,
			"campaign": campaign.campaign_name,
			"schedule_index": entry.idx,
			"email_template": entry.email_template,
			"scheduled_for_utc": scheduled_utc.replace(tzinfo=None),
			"time_zone": campaign.time_zone,
			**values,
		}).insert(ignore_permissions=True)


def _dispatch_key(campaign_name: str, schedule_identifier) -> str:
	return hashlib.sha256(f"{campaign_name}:{schedule_identifier}".encode()).hexdigest()


def _parse_time(value) -> time:
	if isinstance(value, time):
		return value.replace(tzinfo=None)
	if isinstance(value, timedelta):
		total = int(value.total_seconds()) % 86400
		return time(total // 3600, (total % 3600) // 60, total % 60)
	text = str(value or "09:00:00").split(".", 1)[0]
	return datetime.strptime(text, "%H:%M:%S" if text.count(":") == 2 else "%H:%M").time()


def _aware_utc(value: datetime | None) -> datetime:
	if value is None:
		return datetime.now(timezone.utc)
	if value.tzinfo is None:
		return value.replace(tzinfo=timezone.utc)
	return value.astimezone(timezone.utc)
