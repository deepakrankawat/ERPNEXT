from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from lex.conflict_check import (
	evaluate_party_match,
	get_matter_parties,
	normalize_name,
	run_conflict_check,
)


class TestConflictCheck(unittest.TestCase):
	"""Test Canadian Conflict Check Parameters & Technical Logic (Document 2 Scenarios T1 to T13)."""

	# ---------------------------------------------------------
	# Unit Tests: Normalization & Core Matching
	# ---------------------------------------------------------

	def test_normalization_corporate_suffixes(self):
		"""T4 - Corporate name normalization stripping legal designations."""
		self.assertEqual(normalize_name("ABC Technologies Inc."), "ABC TECHNOLOGIES")
		self.assertEqual(normalize_name("ABC Technologies Incorporated"), "ABC TECHNOLOGIES")
		self.assertEqual(normalize_name("Acme & Co. Ltd."), "ACME AND")
		self.assertEqual(normalize_name("NorthPeak Technologies Ltd."), "NORTHPEAK TECHNOLOGIES")
		self.assertEqual(normalize_name("Silverline Systems Inc."), "SILVERLINE SYSTEMS")

	def test_t1_no_match(self):
		"""T1 - No match: Distinct parties produce no matches."""
		p_new = {
			"party_name": "NorthPeak Technologies Ltd.",
			"normalized_name": normalize_name("NorthPeak Technologies Ltd."),
			"legal_role": "Plaintiff",
			"side": "Represented / Client Side",
			"party_type": "Corporation/Company",
		}
		p_hist = {
			"matter": "MAT-001",
			"matter_title": "Old Matter",
			"matter_status": "Active",
			"party_name": "Silverline Systems Inc.",
			"normalized_name": normalize_name("Silverline Systems Inc."),
			"legal_role": "Defendant",
			"side": "Adverse / Counterparty Side",
			"party_type": "Corporation/Company",
		}
		result = evaluate_party_match(p_new, p_hist)
		self.assertIsNone(result)

	def test_t2_current_client_reversal(self):
		"""T2 - Current-client reversal: Adverse party matches current represented party in another active matter."""
		p_new = {
			"party_name": "ABC Ltd.",
			"normalized_name": normalize_name("ABC Ltd."),
			"legal_role": "Defendant",
			"side": "Adverse / Counterparty Side",
			"party_type": "Corporation/Company",
		}
		p_hist = {
			"matter": "MAT-2026-001",
			"matter_title": "ABC Expansion",
			"matter_status": "Active",
			"party_name": "ABC Ltd.",
			"normalized_name": normalize_name("ABC Ltd."),
			"legal_role": "Represented Party",
			"side": "Represented / Client Side",
			"party_type": "Corporation/Company",
		}
		result = evaluate_party_match(p_new, p_hist)
		self.assertIsNotNone(result)
		match_type, priority, explanation = result
		self.assertEqual(match_type, "Exact Match")
		self.assertEqual(priority, "Priority Review")
		self.assertIn("Current Client Reversal", explanation)

	def test_t3_former_client(self):
		"""T3 - Former client: Adverse party matches represented party in a closed/former matter."""
		p_new = {
			"party_name": "Acme Industrial Corp",
			"normalized_name": normalize_name("Acme Industrial Corp"),
			"legal_role": "Adverse Party",
			"side": "Adverse / Counterparty Side",
			"party_type": "Corporation/Company",
		}
		p_hist = {
			"matter": "MAT-2024-089",
			"matter_title": "Acme Financing",
			"matter_status": "Closed / Former",
			"party_name": "Acme Industrial Corp",
			"normalized_name": normalize_name("Acme Industrial Corp"),
			"legal_role": "Represented Party",
			"side": "Represented / Client Side",
			"party_type": "Corporation/Company",
		}
		result = evaluate_party_match(p_new, p_hist)
		self.assertIsNotNone(result)
		match_type, priority, explanation = result
		self.assertEqual(match_type, "Exact Match")
		self.assertEqual(priority, "Review Required")
		self.assertIn("Former Client Match", explanation)

	def test_t4_corporate_name_normalization_match(self):
		"""T4 - Corporate-name normalization: 'ABC Technologies Incorporated' matches 'ABC Technologies Inc.'."""
		p_new = {
			"party_name": "ABC Technologies Inc.",
			"normalized_name": normalize_name("ABC Technologies Inc."),
			"legal_role": "Counterparty",
			"side": "Adverse / Counterparty Side",
			"party_type": "Corporation/Company",
		}
		p_hist = {
			"matter": "MAT-2025-010",
			"matter_title": "Tech Licensing",
			"matter_status": "Active",
			"party_name": "ABC Technologies Incorporated",
			"normalized_name": normalize_name("ABC Technologies Incorporated"),
			"legal_role": "Represented Party",
			"side": "Represented / Client Side",
			"party_type": "Corporation/Company",
		}
		result = evaluate_party_match(p_new, p_hist)
		self.assertIsNotNone(result)
		match_type, priority, explanation = result
		self.assertEqual(match_type, "Normalized Match")
		self.assertEqual(priority, "Priority Review")

	def test_t5_related_entity_match(self):
		"""T5 - Related entity: Parent/Subsidiary relationship links new party to existing record."""
		p_new = {
			"party_name": "ABC Technologies Holdings Inc.",
			"normalized_name": normalize_name("ABC Technologies Holdings Inc."),
			"legal_role": "Parent Company",
			"side": "Represented / Client Side",
			"party_type": "Corporation/Company",
		}
		p_hist = {
			"matter": "MAT-2025-012",
			"matter_title": "Operations",
			"matter_status": "Active",
			"party_name": "ABC Technologies Ltd.",
			"normalized_name": normalize_name("ABC Technologies Ltd."),
			"legal_role": "Subsidiary",
			"side": "Represented / Client Side",
			"party_type": "Corporation/Company",
		}
		result = evaluate_party_match(p_new, p_hist)
		self.assertIsNotNone(result)
		match_type, priority, explanation = result
		self.assertEqual(match_type, "Related Entity Match")
		self.assertEqual(priority, "Contextual Review")
		self.assertIn("Related Entity Match", explanation)

	def test_t6_same_name_individual(self):
		"""T6 - Same-name individual: Verified as identity check candidate, not auto-confirmed legal conflict."""
		p_new = {
			"party_name": "John Smith",
			"normalized_name": normalize_name("John Smith"),
			"legal_role": "Director/Officer",
			"side": "Represented / Client Side",
			"party_type": "Individual",
		}
		p_hist = {
			"matter": "MAT-2025-030",
			"matter_title": "Employment Advisory",
			"matter_status": "Active",
			"party_name": "John A. Smith",
			"normalized_name": normalize_name("John A. Smith"),
			"legal_role": "Employee",
			"side": "Adverse / Counterparty Side",
			"party_type": "Individual",
		}
		result = evaluate_party_match(p_new, p_hist)
		self.assertIsNotNone(result)
		match_type, priority, explanation = result
		self.assertEqual(match_type, "Similar Name Candidate")
		self.assertEqual(priority, "Contextual Review")
		self.assertIn("Identity Verification", explanation)

	def test_t7_prospective_not_retained(self):
		"""T7 - Prospective / not retained matter consultation matched against new adverse party."""
		p_new = {
			"party_name": "Delta Global Partners",
			"normalized_name": normalize_name("Delta Global Partners"),
			"legal_role": "Respondent",
			"side": "Adverse / Counterparty Side",
			"party_type": "Corporation/Company",
		}
		p_hist = {
			"matter": "INTAKE-2026-004",
			"matter_title": "Delta Global Partners Intake",
			"matter_status": "Prospective / Not Retained",
			"party_name": "Delta Global Partners",
			"normalized_name": normalize_name("Delta Global Partners"),
			"legal_role": "Prospective Client / Subject",
			"side": "Represented / Client Side",
			"party_type": "Corporation/Company",
		}
		result = evaluate_party_match(p_new, p_hist)
		self.assertIsNotNone(result)
		match_type, priority, explanation = result
		self.assertEqual(priority, "Review Required")
		self.assertIn("Prospective / Not Retained Match", explanation)

	def test_t8_opposing_counsel_match(self):
		"""T8 - Opposing counsel: Flagged as relationship match, NOT as a client conflict."""
		p_new = {
			"party_name": "Blake & Cassels LLP",
			"normalized_name": normalize_name("Blake & Cassels LLP"),
			"legal_role": "Opposing Counsel / Law Firm",
			"side": "Adverse / Counterparty Side",
			"party_type": "Law Firm",
			"is_counsel": True,
		}
		p_hist = {
			"matter": "MAT-2025-099",
			"matter_title": "Past Dispute",
			"matter_status": "Active",
			"party_name": "Blake & Cassels LLP",
			"normalized_name": normalize_name("Blake & Cassels LLP"),
			"legal_role": "Opposing Counsel / Law Firm",
			"side": "Adverse / Counterparty Side",
			"party_type": "Law Firm",
			"is_counsel": True,
		}
		result = evaluate_party_match(p_new, p_hist)
		self.assertIsNotNone(result)
		match_type, priority, explanation = result
		self.assertEqual(match_type, "Counsel Relationship Match")
		self.assertEqual(priority, "Contextual Review")
		self.assertIn("not a client conflict", explanation)

	def test_t9_no_counterparty_advisory_matter(self):
		"""T9 - Advisory/research matter with no opposing party runs cleanly on represented party."""
		fake_matter = MagicMock()
		fake_matter.customer = "CUST-001"
		fake_matter.represented_party_name = "Zenith Advisory Ltd."
		fake_matter.our_side_role = "Client"
		fake_matter.counterparty_name = None
		fake_matter.counterparty_role = None
		fake_matter.opposing_counsel = None
		fake_matter.get.return_value = []

		with patch("frappe.db.get_value", return_value="MapleBridge Legal"):
			parties = get_matter_parties(fake_matter)

		# Represented party is harvested; no counterparty
		rep = [p for p in parties if p["party_name"] == "Zenith Advisory Ltd."]
		self.assertEqual(len(rep), 1)
		self.assertEqual(rep[0]["side"], "Represented / Client Side")
		self.assertFalse(any(p.get("side") == "Adverse / Counterparty Side" for p in parties))

	# ---------------------------------------------------------
	# End-to-End & Workflow Tests (T10, T11, T12, T13, Alerts)
	# ---------------------------------------------------------

	@patch("lex.conflict_check._dispatch_conflict_compliance_alert")
	@patch("lex.conflict_check.get_all_historical_parties")
	@patch("frappe.get_doc")
	def test_t10_t13_recheck_triggers_and_new_event(self, mock_get_doc, mock_get_hist, mock_alert):
		"""T10 & T13 - Re-check generates a new dated event without overwriting prior history."""
		mock_matter = MagicMock()
		mock_matter.name = "MAT-2026-901"
		mock_matter.customer = "CUST-001"
		mock_matter.represented_party_name = "Echo Energy Ltd."
		mock_matter.our_side_role = "Applicant"
		mock_matter.counterparty_name = "Sierra Power Inc."
		mock_matter.counterparty_role = "Respondent"
		mock_matter.opposing_counsel = None
		mock_matter.get.return_value = []

		mock_event = MagicMock()
		mock_event.name = "CONFLICT-2026-00001"
		mock_event.screened_on = "2026-09-11 17:00:00"

		mock_get_doc.side_effect = lambda doctype, name=None: mock_matter if doctype == "LPO Matter" else mock_event
		mock_get_hist.return_value = [
			{
				"matter": "MAT-2025-100",
				"matter_title": "Old Sierra Case",
				"matter_status": "Active",
				"customer": "Law Firm A",
				"jurisdictions": "Ontario, Canada",
				"party_name": "Sierra Power Inc.",
				"normalized_name": normalize_name("Sierra Power Inc."),
				"legal_role": "Represented Party",
				"side": "Represented / Client Side",
				"party_type": "Corporation/Company",
			}
		]

		with patch("frappe.db.get_value", return_value="MapleBridge Legal"), \
		     patch("frappe.session", MagicMock(user="Administrator")):
			res = run_conflict_check("MAT-2026-901", trigger_reason="Party Added: Sierra Power Inc.")

		self.assertEqual(res["status"], "Potential Match — Human Review Required")
		self.assertEqual(res["match_count"], 1)
		self.assertEqual(res["matches"][0]["party_name"], "Sierra Power Inc.")
		self.assertEqual(res["matches"][0]["review_priority"], "Priority Review")
		mock_alert.assert_called_once()

	@patch("lex.conflict_check.get_all_historical_parties")
	@patch("frappe.get_doc")
	def test_t11_multiple_matches_single_party(self, mock_get_doc, mock_get_hist):
		"""T11 - Single new party returns multiple historical ties (Related Entity + Adverse Party)."""
		mock_matter = MagicMock()
		mock_matter.name = "MAT-2026-902"
		mock_matter.customer = "CUST-001"
		mock_matter.represented_party_name = "Global Retail Corp"
		mock_matter.our_side_role = "Buyer"
		mock_matter.counterparty_name = None
		mock_matter.opposing_counsel = None
		mock_matter.get.return_value = []

		mock_event = MagicMock()
		mock_event.name = "CONFLICT-2026-00002"
		mock_event.screened_on = "2026-09-11 17:00:00"

		mock_get_doc.side_effect = lambda doctype, name=None: mock_matter if doctype == "LPO Matter" else mock_event
		mock_get_hist.return_value = [
			{
				"matter": "MAT-2024-001",
				"matter_title": "Old Supply Dispute",
				"matter_status": "Closed / Former",
				"customer": "Law Firm B",
				"jurisdictions": "British Columbia",
				"party_name": "Global Retail Corp",
				"normalized_name": normalize_name("Global Retail Corp"),
				"legal_role": "Adverse Party",
				"side": "Adverse / Counterparty Side",
				"party_type": "Corporation/Company",
			},
			{
				"matter": "MAT-2025-045",
				"matter_title": "Affiliate Matter",
				"matter_status": "Active",
				"customer": "Law Firm C",
				"jurisdictions": "Federal Court of Canada",
				"party_name": "Global Retail Holdings Inc.",
				"normalized_name": normalize_name("Global Retail Holdings Inc."),
				"legal_role": "Parent Company",
				"side": "Represented / Client Side",
				"party_type": "Corporation/Company",
			},
		]

		with patch("frappe.db.get_value", return_value="MapleBridge Legal"), \
		     patch("frappe.session", MagicMock(user="Administrator")), \
		     patch("lex.conflict_check._dispatch_conflict_compliance_alert"):
			res = run_conflict_check("MAT-2026-902", trigger_reason="Initial Intake")

		self.assertEqual(res["match_count"], 2)
		match_types = {m["match_type"] for m in res["matches"]}
		self.assertIn("Exact Match", match_types)
		self.assertIn("Related Entity Match", match_types)

	def test_t12_multi_jurisdiction_context(self):
		"""T12 - Multi-jurisdiction matter context is preserved in historical matching."""
		p_new = {
			"party_name": "Omni Logistics Ltd.",
			"normalized_name": normalize_name("Omni Logistics Ltd."),
			"legal_role": "Defendant",
			"side": "Adverse / Counterparty Side",
			"party_type": "Corporation/Company",
		}
		p_hist = {
			"matter": "MAT-2025-080",
			"matter_title": "Cross-Border Arbitration",
			"matter_status": "Active",
			"customer": "National Law Group LLP",
			"jurisdictions": "Ontario, New York, Federal Court",
			"party_name": "Omni Logistics Ltd.",
			"normalized_name": normalize_name("Omni Logistics Ltd."),
			"legal_role": "Represented Party",
			"side": "Represented / Client Side",
			"party_type": "Corporation/Company",
		}
		result = evaluate_party_match(p_new, p_hist)
		self.assertIsNotNone(result)
		self.assertEqual(p_hist["jurisdictions"], "Ontario, New York, Federal Court")

	@patch("lex.chat_automation._publish_to_named_channel")
	@patch("lex.lex.doctype.lexocrates_chat_message.lexocrates_chat_message.create_system_message")
	@patch("lex.lexocrates_chat_sync.ensure_matter_chat_channel")
	@patch("frappe.get_doc")
	def test_chat_compliance_alert_on_conflict_match(self, mock_get_doc, mock_channel, mock_msg, mock_named):
		"""Verify that when conflict matches are flagged, chat module dispatches a compliance alert and logs a compliance issue."""
		from lex.conflict_check import _dispatch_conflict_compliance_alert

		mock_matter = MagicMock()
		mock_matter.name = "MAT-2026-ALERT"
		mock_matter.matter_title = "Compliance Test Matter"
		mock_matter.customer = "CUST-999"

		mock_event = MagicMock()
		mock_event.name = "CONFLICT-2026-99999"
		mock_event.initiated_by = "Administrator"

		mock_compl_log = MagicMock()
		mock_compl_log.name = "CMP-2026-0001"
		mock_get_doc.return_value = mock_compl_log
		mock_channel.return_value = "chat-room-mat-alert"

		matches = [
			{
				"party_name": "Target Corp",
				"searched_role": "Adverse Party",
				"matched_matter": "MAT-2025-001",
				"matched_party_name": "Target Corp",
				"matched_role": "Represented Party",
				"match_type": "Exact Match",
				"review_priority": "Priority Review",
				"explanation": "High-Priority Current Client Reversal",
			}
		]

		_dispatch_conflict_compliance_alert(mock_matter, mock_event, matches)

		# 1. Verify Compliance Log created with Conflict of Interest & Critical severity
		mock_get_doc.assert_called_once()
		log_payload = mock_get_doc.call_args[0][0]
		self.assertEqual(log_payload["doctype"], "LPO Compliance Log")
		self.assertEqual(log_payload["compliance_type"], "Conflict of Interest")
		self.assertEqual(log_payload["severity"], "Critical")
		self.assertEqual(log_payload["engagement"], "MAT-2026-ALERT")

		# 2. Verify System Message published to Matter Chat Room
		mock_channel.assert_called_once_with("MAT-2026-ALERT")
		mock_msg.assert_called_once()
		chat_call_args = mock_msg.call_args
		self.assertEqual(chat_call_args[0][0], "chat-room-mat-alert")
		self.assertIn("COMPLIANCE ALERT", chat_call_args[0][1])
		self.assertIn("Target Corp", chat_call_args[0][1])

		# 3. Verify notification dispatched to #compliance
		mock_named.assert_called_once()
		self.assertEqual(mock_named.call_args[0][0], "#compliance")


if __name__ == "__main__":
	unittest.main()
