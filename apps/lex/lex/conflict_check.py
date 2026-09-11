from __future__ import annotations

import difflib
import json
import re
from html import escape

import frappe
from frappe import _
from frappe.utils import cstr, get_datetime, now_datetime, nowdate


# Legal corporate form suffixes normalized per Document 2 Section 7
CORPORATE_SUFFIX_REGEX = re.compile(
	r"\b("
	r"INCORPORATED|INC\.?|"
	r"CORPORATION|CORP\.?|"
	r"LIMITED|LTD\.?|"
	r"LIMITED LIABILITY COMPANY|L\.L\.C\.?|LLC|"
	r"LIMITED LIABILITY PARTNERSHIP|L\.L\.P\.?|LLP|"
	r"PRIVATE LIMITED|PVT\.?\s*LTD\.?|"
	r"COMPANY|CO\.?|"
	r"HOLDINGS|HOLDING|GRP|GROUP|"
	r"GMBH|S\.A\.?|SA|P\.C\.?|PC|PARTNERSHIP"
	r")\b",
	re.IGNORECASE,
)

PUNCTUATION_REGEX = re.compile(r"[^\w\s]")
WHITESPACE_REGEX = re.compile(r"\s+")

RELATED_ENTITY_ROLES = {"Parent Company", "Subsidiary", "Affiliate"}
CONNECTED_INDIVIDUAL_ROLES = {"Director/Officer", "Shareholder"}
INTERNAL_ROLES = {"System Manager", "LPO_Admin", "LPO_Manager", "Legal Operations"}


def normalize_name(name: str | None, party_type: str | None = None) -> str:
	"""Standardize entity and individual names for explainable matching.

	Handles corporate suffix cleanup, punctuation removal, case folding and whitespace.
	Preserves the stem to detect 'ABC Technologies Inc.' == 'ABC Technologies Incorporated'.
	"""
	if not name:
		return ""
	cleaned = cstr(name).strip().upper()
	# Standardize ampersand
	cleaned = cleaned.replace("&", " AND ")
	# Strip legal corporate designations
	cleaned = CORPORATE_SUFFIX_REGEX.sub(" ", cleaned)
	# Strip punctuation
	cleaned = PUNCTUATION_REGEX.sub(" ", cleaned)
	# Collapse whitespace
	cleaned = WHITESPACE_REGEX.sub(" ", cleaned).strip()
	return cleaned


def get_matter_parties(matter_doc) -> list[dict]:
	"""Extract all declared parties from an LPO Matter."""
	parties = []
	customer_name = frappe.db.get_value("Customer", matter_doc.customer, "customer_name") or matter_doc.customer
	if customer_name:
		parties.append({
			"party_name": customer_name,
			"normalized_name": normalize_name(customer_name),
			"party_type": "Law Firm" if "LLP" in customer_name.upper() or "LEGAL" in customer_name.upper() else "Corporation/Company",
			"legal_role": "Instructing Law Firm",
			"side": "Represented / Client Side",
			"is_instructing_firm": True,
		})

	if matter_doc.represented_party_name:
		parties.append({
			"party_name": matter_doc.represented_party_name.strip(),
			"normalized_name": normalize_name(matter_doc.represented_party_name),
			"party_type": "Corporation/Company",
			"legal_role": matter_doc.our_side_role or "Represented Party",
			"side": "Represented / Client Side",
			"is_instructing_firm": False,
		})

	if matter_doc.counterparty_name:
		parties.append({
			"party_name": matter_doc.counterparty_name.strip(),
			"normalized_name": normalize_name(matter_doc.counterparty_name),
			"party_type": "Corporation/Company",
			"legal_role": matter_doc.counterparty_role or "Counterparty",
			"side": "Adverse / Counterparty Side",
			"is_instructing_firm": False,
		})

	if matter_doc.opposing_counsel:
		parties.append({
			"party_name": matter_doc.opposing_counsel.strip(),
			"normalized_name": normalize_name(matter_doc.opposing_counsel),
			"party_type": "Law Firm",
			"legal_role": "Opposing Counsel / Law Firm",
			"side": "Adverse / Counterparty Side",
			"is_instructing_firm": False,
			"is_counsel": True,
		})

	for row in matter_doc.get("additional_parties") or []:
		if not row.party_name:
			continue
		parties.append({
			"party_name": row.party_name.strip(),
			"normalized_name": normalize_name(row.party_name),
			"party_type": row.party_type or "Other Entity",
			"legal_role": row.party_role or "Other",
			"side": row.side or ("Adverse / Counterparty Side" if row.is_adverse else "Neutral / Third Party"),
			"is_instructing_firm": False,
		})

	return parties


def get_all_historical_parties(exclude_matter: str | None = None) -> list[dict]:
	"""Harvest all current and historical party relationships across the ERP."""
	historical = []

	# 1. Active and Closed Matters
	matters = frappe.get_all(
		"LPO Matter",
		fields=[
			"name", "matter_title", "status", "customer", "jurisdictions", "description",
			"represented_party_name", "our_side_role", "counterparty_name",
			"counterparty_role", "opposing_counsel",
		],
		limit_page_length=2000,
	)

	for m in matters:
		if exclude_matter and m.name == exclude_matter:
			continue

		matter_status = "Active" if m.status in {"Active", "Draft", "On Hold"} else "Closed / Former"
		cust_name = frappe.db.get_value("Customer", m.customer, "customer_name") or m.customer

		if m.represented_party_name:
			historical.append({
				"matter": m.name,
				"matter_title": m.matter_title,
				"matter_status": matter_status,
				"customer": cust_name,
				"jurisdictions": m.jurisdictions or "",
				"party_name": m.represented_party_name.strip(),
				"normalized_name": normalize_name(m.represented_party_name),
				"legal_role": m.our_side_role or "Represented Party",
				"side": "Represented / Client Side",
				"party_type": "Corporation/Company",
				"source_type": "Matter",
			})

		if m.counterparty_name:
			historical.append({
				"matter": m.name,
				"matter_title": m.matter_title,
				"matter_status": matter_status,
				"customer": cust_name,
				"jurisdictions": m.jurisdictions or "",
				"party_name": m.counterparty_name.strip(),
				"normalized_name": normalize_name(m.counterparty_name),
				"legal_role": m.counterparty_role or "Counterparty",
				"side": "Adverse / Counterparty Side",
				"party_type": "Corporation/Company",
				"source_type": "Matter",
			})

		if m.opposing_counsel:
			historical.append({
				"matter": m.name,
				"matter_title": m.matter_title,
				"matter_status": matter_status,
				"customer": cust_name,
				"jurisdictions": m.jurisdictions or "",
				"party_name": m.opposing_counsel.strip(),
				"normalized_name": normalize_name(m.opposing_counsel),
				"legal_role": "Opposing Counsel / Law Firm",
				"side": "Adverse / Counterparty Side",
				"party_type": "Law Firm",
				"is_counsel": True,
				"source_type": "Matter",
			})

	# 2. Additional Parties on all matters
	additional_rows = frappe.db.sql(
		"""
		select
			p.parent as matter, m.matter_title, m.status as m_status, m.customer, m.jurisdictions,
			p.party_name, p.party_type, p.party_role, p.side, p.is_adverse
		from `tabLPO Matter Party` p
		join `tabLPO Matter` m on m.name = p.parent
		where p.parent != %s
		""",
		(exclude_matter or ""),
		as_dict=True,
	)
	for row in additional_rows:
		matter_status = "Active" if row.m_status in {"Active", "Draft", "On Hold"} else "Closed / Former"
		cust_name = frappe.db.get_value("Customer", row.customer, "customer_name") or row.customer
		historical.append({
			"matter": row.matter,
			"matter_title": row.matter_title,
			"matter_status": matter_status,
			"customer": cust_name,
			"jurisdictions": row.jurisdictions or "",
			"party_name": row.party_name.strip(),
			"normalized_name": normalize_name(row.party_name),
			"legal_role": row.party_role or "Additional Party",
			"side": row.side or ("Adverse / Counterparty Side" if row.is_adverse else "Neutral / Third Party"),
			"party_type": row.party_type or "Other Entity",
			"source_type": "Matter Additional Party",
		})

	# 3. Prospective / Not Retained Intakes (Work Intakes where Matter was not confirmed or cancelled)
	intakes = frappe.get_all(
		"Lexocrates Work Intake",
		filters={"status": ["in", ["Cancelled", "SLA Pending", "Documents Pending", "Security Review"]]},
		fields=["name", "intake_title", "client", "service_type", "jurisdiction", "status"],
		limit_page_length=500,
	)
	for i in intakes:
		cust_name = frappe.db.get_value("Customer", i.client, "customer_name") or i.client
		historical.append({
			"matter": i.name,
			"matter_title": i.intake_title,
			"matter_status": "Prospective / Not Retained",
			"customer": cust_name,
			"jurisdictions": i.jurisdiction or "",
			"party_name": i.intake_title,
			"normalized_name": normalize_name(i.intake_title),
			"legal_role": "Prospective Client / Subject",
			"side": "Represented / Client Side",
			"party_type": "Corporation/Company",
			"source_type": "Work Intake",
		})

	return historical


def evaluate_party_match(new_party: dict, historical_party: dict) -> tuple[str, str, str] | None:
	"""Check if new_party matches historical_party.

	Returns (match_type, review_priority, explanation) or None if no match.
	"""
	p1_raw = new_party["party_name"].strip()
	p2_raw = historical_party["party_name"].strip()
	p1_norm = new_party["normalized_name"]
	p2_norm = historical_party["normalized_name"]

	if not p1_norm or not p2_norm:
		return None

	# Counsel special check
	if new_party.get("is_counsel") or historical_party.get("is_counsel"):
		if p1_norm == p2_norm or p1_raw.lower() == p2_raw.lower():
			return (
				"Counsel Relationship Match",
				"Contextual Review",
				f"Opposing counsel '{p1_raw}' matches counsel record in {historical_party['matter']}. Contextual relationship awareness only — not a client conflict.",
			)
		return None

	# Instructing law firm is not equivalent to represented party
	if new_party.get("is_instructing_firm") and not historical_party.get("is_instructing_firm"):
		return None

	is_exact = p1_raw.lower() == p2_raw.lower()
	related_role = (
		historical_party.get("legal_role") in RELATED_ENTITY_ROLES
		or new_party.get("legal_role") in RELATED_ENTITY_ROLES
	)

	# Related Entity check: if explicitly marked with a related entity role or corporate group hierarchy
	is_related_entity = False
	if not is_exact and related_role:
		if (p1_norm == p2_norm) or (p1_norm in p2_norm or p2_norm in p1_norm):
			is_related_entity = True
	elif not is_exact and (
		len(p1_norm) > 4
		and len(p2_norm) > 4
		and (p1_norm.startswith(p2_norm) or p2_norm.startswith(p1_norm))
		and p1_norm != p2_norm
	):
		is_related_entity = True

	is_norm = (p1_norm == p2_norm) and not is_exact and not is_related_entity

	# Individual Similar Name Candidate
	is_similar_individual = False
	if (
		not (is_exact or is_norm or is_related_entity)
		and new_party.get("party_type") == "Individual"
		and historical_party.get("party_type") == "Individual"
	):
		ratio = difflib.SequenceMatcher(None, p1_norm, p2_norm).ratio()
		if ratio >= 0.82:
			is_similar_individual = True

	if not (is_exact or is_norm or is_related_entity or is_similar_individual):
		return None

	# Determine Match Type
	if is_exact:
		match_type = "Exact Match"
	elif is_related_entity:
		match_type = "Related Entity Match"
	elif is_norm:
		match_type = "Normalized Match"
	else:
		match_type = "Similar Name Candidate"

	# Determine Review Priority according to Section 8 Significance Rules
	new_side = new_party.get("side") or ""
	old_side = historical_party.get("side") or ""
	old_status = historical_party.get("matter_status") or "Active"
	is_adversary = "Adverse" in new_side

	if is_related_entity:
		priority = "Contextual Review"
		explanation = (
			f"Related Entity Match: '{p1_raw}' links to '{p2_raw}' recorded as {historical_party['legal_role']} "
			f"in Matter {historical_party['matter']}. Contextual review required."
		)
	elif is_similar_individual:
		priority = "Contextual Review"
		explanation = (
			f"Possible Match / Identity Verification: Individual name '{p1_raw}' is similar to '{p2_raw}' in "
			f"Matter {historical_party['matter']}. Verify identity; not an automatic conflict."
		)
	elif old_status == "Prospective / Not Retained":
		priority = "Review Required"
		explanation = (
			f"Prospective / Not Retained Match: '{p1_raw}' matches prospective consultation in {historical_party['matter']}. "
			f"Review confidential information received and relevance to this matter."
		)
	elif is_adversary and "Represented" in old_side and old_status == "Active":
		priority = "Priority Review"
		explanation = (
			f"High-Priority Potential Conflict (Current Client Reversal): New adverse party '{p1_raw}' is currently a "
			f"Represented Party in active Matter {historical_party['matter']} ({historical_party['matter_title']}). Hold acceptance."
		)
	elif "Represented" in new_side and "Adverse" in old_side and old_status == "Active":
		priority = "Priority Review"
		explanation = (
			f"High-Priority Potential Conflict: New represented party '{p1_raw}' is recorded as an Adverse Counterparty "
			f"in active Matter {historical_party['matter']} ({historical_party['matter_title']}). Human review required."
		)
	elif is_adversary and "Represented" in old_side and "Closed" in old_status:
		priority = "Review Required"
		explanation = (
			f"Former Client Match: New adverse party '{p1_raw}' was a Represented Party in closed/former Matter "
			f"{historical_party['matter']}. Review prior scope for related-matter or confidential information issues."
		)
	elif new_side and old_side and new_side != old_side:
		priority = "Priority Review"
		explanation = (
			f"Party Alignment Shift: '{p1_raw}' appears on {new_side} here, but appeared on {old_side} in "
			f"Matter {historical_party['matter']}. Priority review required."
		)
	elif historical_party.get("legal_role") in CONNECTED_INDIVIDUAL_ROLES:
		priority = "Contextual Review"
		explanation = (
			f"Connected Individual Match: '{p1_raw}' matches {historical_party['legal_role']} in Matter "
			f"{historical_party['matter']}. Contextual review required."
		)
	else:
		priority = "Review Required" if "Represented" in old_side else "Contextual Review"
		explanation = (
			f"Potential Match ({match_type}): '{p1_raw}' matches historical record '{p2_raw}' ({historical_party['legal_role']}, "
			f"{old_side}) in Matter {historical_party['matter']} [{old_status}]."
		)

	return match_type, priority, explanation


@frappe.whitelist()
def run_conflict_check(matter_name: str, trigger_reason: str = "Initial Intake", user: str | None = None) -> dict:
	"""Execute full deterministic conflict screening for an LPO Matter."""
	matter = frappe.get_doc("LPO Matter", matter_name)
	user = user or frappe.session.user
	parties = get_matter_parties(matter)
	historical = get_all_historical_parties(exclude_matter=matter.name)

	matches_found = []
	for p in parties:
		for h in historical:
			result = evaluate_party_match(p, h)
			if result:
				match_type, priority, explanation = result
				matches_found.append({
					"party_name": p["party_name"],
					"normalized_name": p["normalized_name"],
					"searched_role": p.get("legal_role") or "Party",
					"searched_side": p.get("side") or "Not Specified",
					"match_type": match_type,
					"review_priority": priority,
					"matched_matter": h["matter"],
					"matched_matter_title": h.get("matter_title") or "",
					"matched_matter_status": h.get("matter_status") or "Active",
					"matched_party_name": h["party_name"],
					"matched_role": h.get("legal_role") or "",
					"matched_side": h.get("side") or "",
					"matched_customer": h.get("customer") or "",
					"jurisdictions": h.get("jurisdictions") or "",
					"explanation": explanation,
				})

	# Deduplicate identical (party_name, matched_matter, matched_party_name, match_type)
	unique_matches = []
	seen = set()
	for item in matches_found:
		key = (item["party_name"], item["matched_matter"], item["matched_party_name"], item["match_type"])
		if key not in seen:
			seen.add(key)
			unique_matches.append(item)

	status = (
		"Potential Match — Human Review Required"
		if unique_matches
		else "No Match Found"
	)

	# Create dated immutable screening event
	event = frappe.get_doc({
		"doctype": "LPO Conflict Screening Event",
		"matter": matter.name,
		"screened_on": now_datetime(),
		"initiated_by": user,
		"trigger_reason": trigger_reason,
		"status": status,
		"match_count": len(unique_matches),
		"searched_parties_summary": json.dumps([p["party_name"] for p in parties], indent=2),
		"decision": "Pending" if unique_matches else "Cleared",
		"decision_reason": "Automated screening: No relevant records found." if not unique_matches else None,
		"matches": unique_matches,
	}).insert(ignore_permissions=True)

	# Update Matter conflict status
	matter.conflict_check_status = status
	matter.latest_conflict_event = event.name
	if not unique_matches:
		matter.conflict_reviewed_by = user
		matter.conflict_reviewed_on = now_datetime()
		matter.conflict_review_notes = "Automated screening cleared: No searchable relationship detected."
	matter.conflict_matches_html = _render_matches_html(event, unique_matches)
	matter.flags.ignore_conflict_recheck = True
	matter.save(ignore_permissions=True)

	# Trigger chat & compliance alerts if matches are found
	if unique_matches:
		_dispatch_conflict_compliance_alert(matter, event, unique_matches)

	return {
		"matter": matter.name,
		"event": event.name,
		"status": status,
		"match_count": len(unique_matches),
		"matches": unique_matches,
	}


def _render_matches_html(event, matches: list[dict]) -> str:
	if not matches:
		return (
			f'<div class="alert alert-success" style="margin-top: 10px;">'
			f'<strong>Screening Status: No Match Found</strong><br>'
			f'Screened on {event.screened_on}. No prior conflicting relationships identified.'
			f'</div>'
		)

	rows = []
	for m in matches:
		p_class = "danger" if m["review_priority"] == "Priority Review" else "warning" if m["review_priority"] == "Review Required" else "info"
		rows.append(
			f'<tr>'
			f'<td><strong>{escape(m["party_name"])}</strong><br><small class="text-muted">{escape(m["searched_role"])} · {escape(m["searched_side"])}</small></td>'
			f'<td><span class="badge badge-{p_class}">{escape(m["match_type"])}</span><br><small>{escape(m["review_priority"])}</small></td>'
			f'<td><a href="/app/lpo-matter/{escape(m["matched_matter"])}"><strong>{escape(m["matched_matter"])}</strong></a> ({escape(m["matched_matter_status"])})<br><small>{escape(m["matched_matter_title"] or "")}</small></td>'
			f'<td><strong>{escape(m["matched_party_name"])}</strong><br><small>{escape(m["matched_role"])} · {escape(m["matched_side"])}</small></td>'
			f'<td><small>{escape(m["explanation"])}</small></td>'
			f'</tr>'
		)

	return (
		f'<div class="lex-conflict-matches-wrap" style="margin-top: 10px;">'
		f'<div class="alert alert-danger"><strong>Potential Matches Identified ({len(matches)})</strong> · Human Review Required before Matter Acceptance.</div>'
		f'<table class="table table-bordered table-condensed" style="font-size: 12.5px;">'
		f'<thead><tr><th>Searched Party</th><th>Match Type / Priority</th><th>Prior Matter</th><th>Matched Party</th><th>Explanation</th></tr></thead>'
		f'<tbody>{"".join(rows)}</tbody>'
		f'</table>'
		f'</div>'
	)


def _dispatch_conflict_compliance_alert(matter, event, matches: list[dict]):
	"""Send real-time alerts into Chat channels and create an LPO Compliance Log."""
	# 1. Create an LPO Compliance Log record
	try:
		has_priority = any(m["review_priority"] == "Priority Review" for m in matches)
		severity = "Critical" if has_priority else "High"
		compl_log = frappe.get_doc({
			"doctype": "LPO Compliance Log",
			"engagement": matter.name,
			"customer": matter.customer,
			"compliance_type": "Conflict of Interest",
			"severity": severity,
			"status": "Open",
			"reported_by": event.initiated_by or frappe.session.user,
			"detected_on": now_datetime(),
			"description": (
				f"Conflict screening event {event.name} identified {len(matches)} potential match(es) for Matter "
				f"{matter.name} ({matter.matter_title}). Top match: {matches[0]['explanation']}"
			),
			"remediation_action": "Authorized legal reviewer must examine matched relationships and record Cleared or Escalated decision.",
		}).insert(ignore_permissions=True)

		event.compliance_log = compl_log.name
		event.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"Conflict Compliance Log creation {matter.name}")

	# 2. Publish System Alert to the Matter's Chat Room
	try:
		from lex.lexocrates_chat_sync import ensure_matter_chat_channel
		from lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message import create_system_message

		channel_name = ensure_matter_chat_channel(matter.name)
		match_list_html = "".join(
			f"<li><strong>{escape(m['party_name'])}</strong> ({escape(m['searched_role'])}) matches <strong>{escape(m['matched_party_name'])}</strong> in <a href='/app/lpo-matter/{escape(m['matched_matter'])}'>@{escape(m['matched_matter'])}</a> — <em>{escape(m['match_type'])} [{escape(m['review_priority'])}]</em></li>"
			for m in matches[:5]
		)

		chat_html = (
			f"<p>⚠️ <strong>COMPLIANCE ALERT · Potential Conflict of Interest Detected</strong></p>"
			f"<p>Conflict Screening Event <strong>{escape(event.name)}</strong> flagged <strong>{len(matches)} potential match(es)</strong>:</p>"
			f"<ul>{match_list_html}</ul>"
			f"<p><em>Matter acceptance is held pending authorized legal review.</em></p>"
		)

		create_system_message(
			channel_name,
			chat_html,
			source_doctype="LPO Conflict Screening Event",
			source_name=event.name,
			automation_key=f"conflict-alert:{event.name}",
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"Conflict chat alert {matter.name}")

	# 3. Publish to #compliance channel if configured
	try:
		from lex.chat_automation import _publish_to_named_channel

		comp_msg = (
			f"<p>⚠️ <strong>Conflict Alert:</strong> Matter <a href='/app/lpo-matter/{escape(matter.name)}'>@{escape(matter.name)}</a> "
			f"({escape(matter.matter_title)}) flagged {len(matches)} potential match(es). Status: <strong>{escape(event.status)}</strong>.</p>"
		)
		_publish_to_named_channel(
			"#compliance",
			comp_msg,
			source_doctype="LPO Conflict Screening Event",
			source_name=event.name,
			automation_event=f"conflict-screen:{event.name}",
		)
	except Exception:
		pass


@frappe.whitelist()
def record_conflict_decision(event_name: str, decision: str, reason: str, reviewer: str | None = None) -> dict:
	"""Record an authorized human reviewer's decision on a conflict screening event."""
	reviewer = reviewer or frappe.session.user
	if decision not in {"Cleared", "Escalated"}:
		frappe.throw(_("Decision must be Cleared or Escalated."), frappe.ValidationError)
	if not (reason or "").strip():
		frappe.throw(_("Reason / Notes are mandatory when recording a conflict decision."), frappe.MandatoryError)

	event = frappe.get_doc("LPO Conflict Screening Event", event_name)
	matter = frappe.get_doc("LPO Matter", event.matter)

	event.reviewed_by = reviewer
	event.reviewed_on = now_datetime()
	event.decision = decision
	event.decision_reason = reason.strip()
	event.status = decision
	event.save(ignore_permissions=True)

	matter.conflict_check_status = decision
	matter.conflict_reviewed_by = reviewer
	matter.conflict_reviewed_on = now_datetime()
	matter.conflict_review_notes = reason.strip()
	matter.conflict_matches_html = (
		f'<div class="alert alert-{"success" if decision == "Cleared" else "warning"}" style="margin-top: 10px;">'
		f'<strong>Conflict Check Decision: {escape(decision)}</strong><br>'
		f'Reviewed by {escape(reviewer)} on {matter.conflict_reviewed_on}.<br>'
		f'<strong>Reason:</strong> {escape(reason.strip())}'
		f'</div>'
	)
	matter.flags.ignore_conflict_recheck = True
	matter.save(ignore_permissions=True)

	# Update compliance log if linked
	if event.compliance_log and frappe.db.exists("LPO Compliance Log", event.compliance_log):
		compl = frappe.get_doc("LPO Compliance Log", event.compliance_log)
		compl.status = "Resolved" if decision == "Cleared" else "Remediation Required"
		compl.resolved_on = now_datetime() if decision == "Cleared" else None
		compl.remediation_action = f"{decision} by {reviewer}: {reason.strip()}"
		compl.save(ignore_permissions=True)

	# Post resolution notice to Matter Chat Room
	try:
		from lex.lexocrates_chat_sync import ensure_matter_chat_channel
		from lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message import create_system_message

		channel_name = ensure_matter_chat_channel(matter.name)
		icon = "✅" if decision == "Cleared" else "🚨"
		notice = (
			f"<p>{icon} <strong>Conflict Check Decision Recorded: {escape(decision)}</strong></p>"
			f"<p><strong>Reviewer:</strong> {escape(reviewer)}<br>"
			f"<strong>Reason:</strong> {escape(reason.strip())}</p>"
		)
		create_system_message(
			channel_name,
			notice,
			source_doctype="LPO Conflict Screening Event",
			source_name=event.name,
			automation_key=f"conflict-decision:{event.name}:{decision}",
		)
	except Exception:
		pass

	return {"event": event.name, "matter": matter.name, "status": decision}


@frappe.whitelist()
def record_matter_acceptance(matter_name: str, status: str, notes: str | None = None, reviewer: str | None = None) -> dict:
	"""Record the separate authorized business decision of matter acceptance."""
	reviewer = reviewer or frappe.session.user
	if status not in {"Pending", "Accepted", "Declined", "On Hold"}:
		frappe.throw(_("Acceptance status must be Pending, Accepted, Declined, or On Hold."), frappe.ValidationError)

	matter = frappe.get_doc("LPO Matter", matter_name)

	# Acceptance Gate: cannot accept matter if conflict is unreviewed or unresolved
	if status == "Accepted" and matter.conflict_check_status in {"Potential Match — Human Review Required", "Escalated", "Not Run"}:
		frappe.throw(
			_("Cannot accept Matter while Conflict Check status is '{0}'. An authorized clearance is required.").format(
				matter.conflict_check_status
			),
			frappe.ValidationError,
		)

	matter.matter_acceptance_status = status
	if notes:
		matter.add_comment("Comment", f"Matter Acceptance set to '{status}' by {reviewer}. Notes: {notes}")
	matter.flags.ignore_conflict_recheck = True
	matter.save(ignore_permissions=True)

	return {"matter": matter.name, "matter_acceptance_status": status}


def check_matter_for_conflict_recheck(doc, method=None):
	"""Hook on LPO Matter save: detects if parties or roles changed and triggers a re-check."""
	if getattr(doc.flags, "ignore_conflict_recheck", False):
		return
	if not doc.get_doc_before_save():
		return

	previous = doc.get_doc_before_save()
	party_fields = ["represented_party_name", "our_side_role", "counterparty_name", "counterparty_role", "opposing_counsel"]
	changed = [f for f in party_fields if doc.get(f) != previous.get(f)]

	# Also check additional_parties table changes
	p_old = {row.name: (row.party_name, row.party_role, row.side) for row in previous.get("additional_parties") or []}
	p_new = {row.name: (row.party_name, row.party_role, row.side) for row in doc.get("additional_parties") or []}
	additional_changed = p_old != p_new

	if changed or additional_changed:
		trigger_reason = f"Party or Role Modified: {', '.join(changed)}" if changed else "Additional Parties Modified"
		run_conflict_check(doc.name, trigger_reason=trigger_reason)
