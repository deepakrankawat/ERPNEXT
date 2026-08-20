from __future__ import annotations

import hashlib
import json
import frappe
from frappe import _

from lex.client_access import get_portal_user


GENESIS_HASH = "GENESIS_HASH"
HASH_FIELDS = (
	"event_timestamp",
	"action",
	"result",
	"client",
	"portal_user",
	"user",
	"matter",
	"object_type",
	"object_id",
	"ip_address",
	"session_id",
	"previous_value",
	"new_value",
	"details",
)


def compute_audit_event_hash(event_doc: dict, previous_hash: str = "") -> str:
	"""Compute SHA-256 tamper-evident hash for audit event record (AUD-002)."""
	payload = {fieldname: event_doc.get(fieldname) for fieldname in HASH_FIELDS}
	payload["event_timestamp"] = str(payload.get("event_timestamp") or event_doc.get("creation") or "")
	payload["previous_hash"] = previous_hash or GENESIS_HASH
	payload["hash_version"] = 1
	raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
	return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@frappe.whitelist()
def verify_audit_trail_integrity(client_id: str | None = None) -> dict:
	"""Verify WORM hash chain integrity across audit events (AUD-002)."""
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	is_internal = user == "Administrator" or bool(roles.intersection({"LPO_Admin", "LPO_Manager", "System Manager", "Lexocrates Compliance Officer"}))
	portal_user = None if is_internal else get_portal_user(user)
	if not is_internal:
		if not portal_user:
			frappe.throw(_("Audit verification permission is required."), frappe.PermissionError)
		if client_id and client_id != portal_user.client:
			frappe.throw(_("You cannot verify another Client's audit trail."), frappe.PermissionError)
		client_id = portal_user.client
	filters = {"client": client_id} if client_id else {}
	events = frappe.get_all(
		"Lexocrates Portal Audit Event",
		filters=filters,
		fields=["name", *HASH_FIELDS, "creation", "chain_scope", "previous_hash", "event_hash", "hash_version"],
		order_by="chain_scope asc, event_timestamp asc, creation asc, name asc",
		limit_page_length=10000,
	)

	previous_by_scope = {}
	tampered_events = []

	for event in events:
		scope = event.chain_scope or event.client or "__GLOBAL__"
		previous_hash = previous_by_scope.get(scope, GENESIS_HASH)
		computed = compute_audit_event_hash(event, previous_hash)
		if event.previous_hash != previous_hash or event.event_hash != computed or event.hash_version != 1:
			tampered_events.append(event.name)
		previous_by_scope[scope] = event.event_hash or computed

	return {
		"verified": len(tampered_events) == 0,
		"total_events_checked": len(events),
		"tampered_events_count": len(tampered_events),
		"tampered_events": tampered_events,
		"final_chain_hashes": previous_by_scope,
	}


def backfill_audit_hash_chain():
	"""One-time migration for legacy immutable events created before hash columns existed."""
	if not frappe.db.exists("DocType", "Lexocrates Portal Audit Event"):
		return
	events = frappe.get_all(
		"Lexocrates Portal Audit Event",
		fields=["name", *HASH_FIELDS, "creation", "client"],
		order_by="event_timestamp asc, creation asc, name asc",
		limit_page_length=0,
	)
	previous_by_scope = {}
	for event in events:
		scope = event.client or "__GLOBAL__"
		previous_hash = previous_by_scope.get(scope, GENESIS_HASH)
		event_hash = compute_audit_event_hash(event, previous_hash)
		frappe.db.set_value(
			"Lexocrates Portal Audit Event",
			event.name,
			{
				"chain_scope": scope,
				"previous_hash": previous_hash,
				"event_hash": event_hash,
				"hash_version": 1,
			},
			update_modified=False,
		)
		previous_by_scope[scope] = event_hash
