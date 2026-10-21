from __future__ import annotations

import hashlib
import re
from datetime import datetime, time, timedelta, timezone
from email.utils import formataddr
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.core.doctype.communication.email import make
from frappe.email.email_body import get_formatted_html
from frappe.utils import getdate, parse_addr


DISPATCH_DOCTYPE = "Lexocrates Email Campaign Dispatch"
EMAIL_IN_TEXT_RE = re.compile(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+")
FINAL_DISPATCH_STATES = {"Queued", "Sent"}


def process_due_email_campaigns(now_utc: datetime | None = None):
	"""Queue every due timed campaign exactly once, including missed schedules."""
	now_utc = _aware_utc(now_utc)
	_sync_dispatch_delivery_states()
	campaign_names = frappe.get_all(
		"Email Campaign",
		# A "Completed" campaign has nothing left to send by definition (see
		# _mark_campaign_complete_if_queued) -- excluding it here is what makes
		# that status permanent. Without this, resaving the Campaign's own
		# schedule row (e.g. while editing the Email Template it points to)
		# changes that row's name, which changes _dispatch_key()'s hash, which
		# makes every already-"Sent" dispatch invisible to the lookup in
		# _queue_single_dispatch -- so the next scheduler tick re-sends the
		# whole campaign to everyone in the group again. Observed in production
		# resending the same recruitment email to ~130 candidates a second and
		# third time.
		filters={"time_scheduling_enabled": 1, "status": ["not in", ["Unsubscribed", "Completed"]]},
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
				results["queued"] += _queue_dispatch(campaign, entry, scheduled_utc)
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


def _queue_dispatch(campaign, entry, scheduled_utc: datetime) -> int:
	"""Queue this schedule entry. Lead Group targets are fanned out one dispatch
	per member so each Lead's own fields (first_name, etc.) render into their
	copy of the email -- a group send is otherwise a single shared broadcast
	with no per-recipient personalization available."""
	if campaign.email_campaign_for != "Lead Group":
		return _queue_single_dispatch(campaign, entry, scheduled_utc)

	queued = 0
	for member in _lead_group_members(campaign.recipient):
		try:
			queued += _queue_single_dispatch(campaign, entry, scheduled_utc, lead=member.lead, email=member.email)
		except Exception:
			_record_dispatch_error(campaign, entry, scheduled_utc, frappe.get_traceback(), member=member.lead)
			frappe.log_error(
				frappe.get_traceback(),
				_("Timed Email Campaign Dispatch Failed: {0} ({1})").format(campaign.name, member.lead),
			)
	return queued


def _lead_group_members(recipient):
	members = frappe.get_all(
		"Lead Group Member",
		filters={"lead_group": recipient, "unsubscribed": 0, "email": ["is", "set"]},
		fields=["lead", "email"],
	)
	if not members:
		frappe.throw(
			_("No subscribed Leads with an email address were found in Lead Group {0}.").format(recipient),
			frappe.ValidationError,
		)
	return members


def _queue_single_dispatch(campaign, entry, scheduled_utc: datetime, lead: str | None = None, email: str | None = None) -> int:
	dispatch_key = _dispatch_key(campaign.name, _schedule_identifier(entry), lead)
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
		return 0
	if dispatch and dispatch.communication and frappe.db.exists(
		"Email Queue", {"communication": dispatch.communication}
	):
		frappe.db.set_value(DISPATCH_DOCTYPE, dispatch.name, {"status": "Queued", "error": None})
		return 0
	# Reply-tracking needs a Lead to point back to; a Lead Group send already
	# knows the member's Lead, a single "Lead" campaign's recipient IS the Lead.
	dispatch_lead = lead or (campaign.recipient if campaign.email_campaign_for == "Lead" else None)

	if not dispatch:
		dispatch_doc = frappe.get_doc({
			"doctype": DISPATCH_DOCTYPE,
			"dispatch_key": dispatch_key,
			"email_campaign": campaign.name,
			"campaign": campaign.campaign_name,
			"lead": dispatch_lead,
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
		if not dispatch_doc.lead and dispatch_lead:
			dispatch_doc.lead = dispatch_lead
		dispatch_doc.save(ignore_permissions=True)

	if lead:
		recipients = [email]
		context = frappe.get_doc("Lead", lead).as_dict()
	else:
		recipients, context = _recipients_and_context(campaign)
	template = frappe.get_cached_doc("Email Template", entry.email_template)
	subject = frappe.render_template(template.subject, context)
	content = frappe.render_template(template.response_, context)
	sender = _formatted_sender(campaign.sender)
	template_files = _template_attachments(template.name)

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
			attachments=template_files,
		)
		communication_name = communication["name"]
		# The Communication doc is the audit trail shown in the Desk timeline --
		# store it with the same header/footer wrapping the actual outgoing
		# email gets, so what a reviewer sees there matches what was sent.
		# frappe.sendmail() below still renders the *unwrapped* fragment (its
		# own pipeline wraps it once); passing the already-wrapped HTML there
		# too would nest the wrapper inside itself.
		try:
			frappe.db.set_value("Communication", communication_name, "content", get_formatted_html(subject, content))
		except Exception:
			frappe.log_error(frappe.get_traceback(), _("Could not store formatted preview for {0}").format(communication_name))
		# make(..., send_email=False) skips comm.send_email(), which is the
		# only place core Frappe would otherwise fill in email_account -- so
		# this Communication would stay permanently invisible under any
		# specific-mailbox or "All Accounts" Inbox filter (both key off that
		# field) despite having genuinely been sent through it.
		sender_email = parse_addr(sender)[1] if sender else None
		outgoing_account = _resolve_outgoing_email_account(sender_email)
		if outgoing_account:
			frappe.db.set_value("Communication", communication_name, "email_account", outgoing_account)
		dispatch_doc.communication = communication_name
		dispatch_doc.save(ignore_permissions=True)
		# queue_separately=True hands the email off to a background worker that
		# may pick it up before this function's caller commits, and that worker
		# validates the Communication link in its own DB connection. Without an
		# explicit commit here, the worker can run against a transaction where
		# this Communication doesn't exist yet and fail with
		# "Could not find Communication: <name>", silently dropping the send.
		frappe.db.commit()

	frappe.sendmail(
		recipients=recipients,
		subject=subject,
		content=content,
		sender=sender,
		communication=communication_name,
		queue_separately=True,
		attachments=[{"fid": f} for f in template_files] or None,
	)
	dispatch_doc.status = "Queued"
	dispatch_doc.error = None
	dispatch_doc.save(ignore_permissions=True)
	return 1


def _template_attachments(email_template: str) -> list[str]:
	"""File docnames attached to an Email Template, so a file added there goes
	out with every campaign email using it -- Email Template's own "Add
	Template" flow in Desk only copies subject/body text, never attachments,
	so this doesn't happen on its own."""
	return frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Email Template", "attached_to_name": email_template, "is_folder": 0},
		pluck="name",
	)


def _resolve_outgoing_email_account(sender_email: str | None) -> str | None:
	"""The Email Account docname that owns this address for sending, if any."""
	if not sender_email:
		return None
	return frappe.db.get_value("Email Account", {"email_id": sender_email, "enable_outgoing": 1}, "name")


def _formatted_sender(sender_user: str | None) -> str | None:
	"""Resolve a campaign's sender User to `"Lexocrates" <email>`, matching the
	display name every other outgoing system email uses (see
	auth_overrides.SUPPORT_SENDER, compliance_pages.SALES_SENDER) -- not the
	Email Account's own "sales"/"support" label, which recipients were
	seeing instead of the company name.

	Falls back to the bare email if no matching outgoing Email Account is found,
	so the mail is never blocked for missing display-name config.
	"""
	if not sender_user:
		return None
	sender_email = frappe.db.get_value("User", sender_user, "email")
	if not sender_email:
		return None
	has_outgoing_account = bool(_resolve_outgoing_email_account(sender_email))
	return formataddr((_("Lexocrates"), sender_email)) if has_outgoing_account else sender_email


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
	keys = []
	for entry in schedules:
		if campaign.email_campaign_for == "Lead Group":
			leads = frappe.get_all(
				"Lead Group Member",
				filters={"lead_group": campaign.recipient, "unsubscribed": 0, "email": ["is", "set"]},
				pluck="lead",
			)
			keys.extend(_dispatch_key(campaign.name, _schedule_identifier(entry), lead) for lead in leads)
		else:
			keys.append(_dispatch_key(campaign.name, _schedule_identifier(entry)))
	if not keys:
		return
	completed = frappe.get_all(
		DISPATCH_DOCTYPE,
		filters={"name": ["in", keys], "status": ["in", list(FINAL_DISPATCH_STATES)]},
		pluck="name",
	)
	if len(set(completed)) == len(keys) and campaign.status != "Completed":
		frappe.db.set_value("Email Campaign", campaign.name, "status", "Completed")


def _record_dispatch_error(campaign, entry, scheduled_utc, error, member: str | None = None):
	key = _dispatch_key(campaign.name, _schedule_identifier(entry), member)
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


def _schedule_identifier(entry) -> str:
	"""A Campaign Email Schedule row's own `name`/`idx` changes if that row is
	ever deleted and re-added (e.g. editing the step in the Campaign's grid) --
	using it in the dispatch key means a cosmetic no-op edit can make every
	already-"Sent" dispatch for that step invisible, triggering a full resend.
	(day, template) is what a schedule step actually *means* and stays stable
	across row-identity churn."""
	return f"{entry.send_after_days or 0}:{entry.email_template}"


def _dispatch_key(campaign_name: str, schedule_identifier, member: str | None = None) -> str:
	key = f"{campaign_name}:{schedule_identifier}"
	if member:
		key = f"{key}:{member}"
	return hashlib.sha256(key.encode()).hexdigest()


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


@frappe.whitelist()
def create_bulk_email_campaigns(leads, campaign_name, sender, start_date, start_time, time_zone):
	"""One Email Campaign per selected Lead, since the doctype's `recipient`
	is a single Dynamic Link -- this is how a multi-lead send is composed
	while keeping per-lead personalization ({{ first_name }} etc.) intact."""
	if isinstance(leads, str):
		leads = frappe.parse_json(leads)
	if not leads:
		frappe.throw(_("Select at least one Lead."), frappe.ValidationError)
	if not frappe.db.exists("Campaign", campaign_name):
		frappe.throw(_("Campaign {0} does not exist.").format(campaign_name), frappe.ValidationError)

	created, skipped = [], []
	for lead in leads:
		email_id = frappe.db.get_value("Lead", lead, "email_id")
		if not email_id:
			skipped.append({"lead": lead, "reason": "No email address on file"})
			continue
		if frappe.db.exists("Email Campaign", {"campaign_name": campaign_name, "recipient": lead, "email_campaign_for": "Lead"}):
			skipped.append({"lead": lead, "reason": "Already has this campaign"})
			continue
		doc = frappe.get_doc({
			"doctype": "Email Campaign",
			"campaign_name": campaign_name,
			"email_campaign_for": "Lead",
			"recipient": lead,
			"sender": sender,
			"start_date": start_date,
			"start_time": start_time,
			"time_zone": time_zone,
			"time_scheduling_enabled": 1,
		}).insert(ignore_permissions=True)
		created.append(doc.name)
	frappe.db.commit()
	return {"created": created, "skipped": skipped}


@frappe.whitelist()
def add_communications_to_email_group(communications, email_group):
	"""Add the sender of each selected inbox email to an Email Group, creating
	the group if it doesn't exist yet -- mirrors lead_group.add_leads, but for
	inbox senders that don't have (and don't need) a Lead/Contact record of
	their own before being added as a campaign recipient."""
	if isinstance(communications, str):
		communications = frappe.parse_json(communications)
	if not communications:
		frappe.throw(_("Select at least one email."), frappe.ValidationError)

	if frappe.db.exists("Email Group", email_group):
		group = frappe.get_doc("Email Group", email_group)
		group.check_permission("write")
	else:
		group = frappe.get_doc({"doctype": "Email Group", "title": email_group}).insert()

	added, skipped = [], []
	for name in communications:
		sender = frappe.db.get_value("Communication", name, "sender")
		email = parse_addr(sender)[1] if sender else None
		if not email:
			skipped.append({"communication": name, "reason": "No sender email address found"})
			continue
		if frappe.db.exists("Email Group Member", {"email_group": group.name, "email": email}):
			skipped.append({"communication": name, "email": email, "reason": "Already in the group"})
			continue
		frappe.get_doc({
			"doctype": "Email Group Member",
			"email_group": group.name,
			"email": email,
		}).insert(ignore_permissions=True)
		added.append(email)

	frappe.db.commit()
	return {"email_group": group.name, "added": added, "skipped": skipped}


@frappe.whitelist()
def import_csv_to_email_group(email_group, file_url):
	"""Add every email address found anywhere in an uploaded CSV to an Email
	Group, creating the group if needed.

	Deliberately column-name-agnostic: a CSV exported from the Lead list, the
	Communication inbox, or anywhere else never agrees on a header ("Email"
	vs "ID" vs "Sender"), so the Data Import tool's strict template kept
	rejecting these exports. Scanning every cell for an email-shaped string
	sidesteps that entirely.
	"""
	if not file_url:
		frappe.throw(_("Upload a CSV file first."), frappe.ValidationError)

	if frappe.db.exists("Email Group", email_group):
		group = frappe.get_doc("Email Group", email_group)
		group.check_permission("write")
	else:
		group = frappe.get_doc({"doctype": "Email Group", "title": email_group}).insert()

	file_doc = frappe.get_doc("File", {"file_url": file_url})
	content = file_doc.get_content()
	if isinstance(content, bytes):
		content = content.decode("utf-8", errors="ignore")

	found_emails = {match.lower() for match in EMAIL_IN_TEXT_RE.findall(content)}

	added, skipped = [], []
	for email in sorted(found_emails):
		if frappe.db.exists("Email Group Member", {"email_group": group.name, "email": email}):
			skipped.append(email)
			continue
		frappe.get_doc({
			"doctype": "Email Group Member",
			"email_group": group.name,
			"email": email,
		}).insert(ignore_permissions=True)
		added.append(email)

	frappe.db.commit()
	return {"email_group": group.name, "added": added, "skipped": skipped, "total_found": len(found_emails)}


def delete_dispatch_records(doc, method=None):
	"""Clear this campaign's dispatch log before Frappe's link check runs,
	so deleting an Email Campaign isn't blocked by its own tracking records."""
	for name in frappe.get_all(DISPATCH_DOCTYPE, filters={"email_campaign": doc.name}, pluck="name"):
		frappe.delete_doc(DISPATCH_DOCTYPE, name, ignore_permissions=True, force=True)


def delete_dispatch_records_for_campaign(doc, method=None):
	"""Same as delete_dispatch_records, but for the Campaign (schedule template)
	side of the link -- dispatch rows also point at the Campaign they used."""
	for name in frappe.get_all(DISPATCH_DOCTYPE, filters={"campaign": doc.name}, pluck="name"):
		frappe.delete_doc(DISPATCH_DOCTYPE, name, ignore_permissions=True, force=True)
