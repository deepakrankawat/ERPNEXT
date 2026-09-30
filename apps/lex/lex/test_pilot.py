from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from lex import pilot


class TestComplimentaryPilot(unittest.TestCase):
	def test_limits_are_explicit_and_market_matched(self):
		settings = SimpleNamespace(complimentary_pilot_limits=[
			SimpleNamespace(market="Canada", currency="CAD", complimentary_pilot_value_limit=200, enabled=1),
			SimpleNamespace(market="United States", currency="USD", complimentary_pilot_value_limit=150, enabled=1),
			SimpleNamespace(market="United Kingdom", currency="GBP", complimentary_pilot_value_limit=100, enabled=0),
		])
		with patch("frappe.get_single", return_value=settings):
			self.assertEqual(pilot.pilot_limits(), {"CAD": 200.0, "USD": 150.0})

	def test_one_approved_pilot_uses_the_organisation_allowance(self):
		rows = [frappe._dict({"name": "INTAKE-1", "pilot_status": "Approved", "status": "Matter Confirmed", "funding_status": "Funded"})]
		with patch("lex.lexpack._country_currency_for_client", return_value="GBP"), \
			patch("lex.pilot.pilot_limits", return_value={"GBP": 125.0}), \
			patch("frappe.get_all", return_value=rows):
			offer = pilot.pilot_offer_for_client("CLIENT-1")
		self.assertEqual(offer, {"status": "Used", "currency": "GBP", "value_limit": 125.0, "market": "United Kingdom"})

	def test_cancelled_request_releases_allowance_without_consuming_it(self):
		rows = [frappe._dict({"name": "INTAKE-1", "pilot_status": "Requested", "status": "Cancelled", "funding_status": "Cancelled"})]
		with patch("lex.lexpack._country_currency_for_client", return_value="CAD"), \
			patch("lex.pilot.pilot_limits", return_value={"CAD": 200.0}), \
			patch("frappe.get_all", return_value=rows):
			offer = pilot.pilot_offer_for_client("CLIENT-1")
		self.assertEqual(offer["status"], "Available")
