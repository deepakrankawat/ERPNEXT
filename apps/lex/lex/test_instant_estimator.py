from __future__ import annotations

import io
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfWriter

from lex.instant_estimator import (
	FIXED_SERVICE_RATES_CAD,
	PAGES_PER_HOUR,
	calculate_page_based_pricing,
	extract_pdf_pages_and_text,
	round_up_to_cad_five,
)
from lex.work_intake import _checkout_payload, normalize_intake_service_type


def _generate_test_pdf(num_pages: int = 3, text_content: str = "Test agreement review clause") -> bytes:
	"""Generate an in-memory PDF with num_pages using pypdf."""
	writer = PdfWriter()
	for _ in range(num_pages):
		writer.add_blank_page(width=612, height=792)
	stream = io.BytesIO()
	writer.write(stream)
	return stream.getvalue()


class TestInstantEstimator(unittest.TestCase):
	def test_pricing_catalogue_names_normalize_to_doctype_service_types(self):
		self.assertEqual(normalize_intake_service_type("eDiscovery & Document Review"), "Document Review")
		self.assertEqual(normalize_intake_service_type("Compliance & Regulatory Support"), "Compliance Review")
		self.assertEqual(normalize_intake_service_type("Legal Operations Support"), "Other")
		self.assertEqual(normalize_intake_service_type("Litigation Support"), "Litigation Support")

	def test_fixed_rate_card_is_cad_only(self):
		self.assertEqual(FIXED_SERVICE_RATES_CAD["Legal Research & Writing"], Decimal("24.50"))
		self.assertEqual(FIXED_SERVICE_RATES_CAD["Legal Operations Support"], Decimal("38.51"))

	def test_rounding_to_whole_cad_five(self):
		self.assertEqual(round_up_to_cad_five(Decimal("124.50")), Decimal("125"))
		self.assertEqual(round_up_to_cad_five(Decimal("127.40")), Decimal("130"))
		self.assertEqual(round_up_to_cad_five(Decimal("125.00")), Decimal("125"))

	def test_fewer_than_thirty_pages(self):
		pricing = calculate_page_based_pricing(1, "Contract Review")
		self.assertEqual(pricing["exact_hours"], Decimal(1) / Decimal(30))
		self.assertEqual(pricing["raw_price_cad"], Decimal("0.98"))
		self.assertEqual(pricing["final_price_cad"], Decimal("5"))

	def test_thirty_pages_uses_one_hour(self):
		pricing = calculate_page_based_pricing(30, "Contract Review")
		self.assertEqual(pricing["exact_hours"], Decimal("1"))
		self.assertEqual(pricing["final_price_cad"], Decimal("30"))

	def test_one_hundred_pages_rounds_up(self):
		pricing = calculate_page_based_pricing(100, "Contract Review")
		self.assertEqual(pricing["raw_price_cad"], Decimal("98.00"))
		self.assertEqual(pricing["final_price_cad"], Decimal("100"))

	def test_one_hundred_fifty_three_pages_rounds_up(self):
		pricing = calculate_page_based_pricing(153, "Contract Review")
		self.assertEqual(pricing["raw_price_cad"], Decimal("149.94"))
		self.assertEqual(pricing["final_price_cad"], Decimal("150"))
		self.assertEqual(pricing["currency"], "CAD")
		self.assertNotIn("-", pricing["price_amount"])

	def test_exact_five_multiple_remains_unchanged(self):
		pricing = calculate_page_based_pricing(75, "Litigation Support")
		self.assertEqual(pricing["raw_price_cad"], Decimal("70.00"))
		self.assertEqual(pricing["final_price_cad"], Decimal("70"))

	def test_same_pdf_service_and_turnaround_are_deterministic(self):
		first = calculate_page_based_pricing(100, "Contract Review", "Rush (24-48 Hours)")
		second = calculate_page_based_pricing(100, "Contract Review", "Rush (24-48 Hours)")
		self.assertEqual(first["final_price_cad"], Decimal("100"))
		self.assertEqual(first["final_price_cad"], second["final_price_cad"])

	def test_invalid_page_counts_are_rejected(self):
		for pages in (0, -1, 1.5, True, "30"):
			with self.subTest(pages=pages), self.assertRaises(ValueError):
				calculate_page_based_pricing(pages, "Contract Review")

	def test_unknown_service_is_rejected(self):
		with self.assertRaises(ValueError):
			calculate_page_based_pricing(30, "Auto-Detect from Document")

	def test_pdf_extraction(self):
		pdf_bytes = _generate_test_pdf(num_pages=5)
		pages, text = extract_pdf_pages_and_text(pdf_bytes)
		self.assertEqual(pages, 5)

	def test_direct_quote_checkout_payload_is_explicitly_live(self):
		doc = SimpleNamespace(
			name="WI-TEST-0001",
			razorpay_order_id="order_test_0001",
			currency="CAD",
			intake_title="Quick Lextimator estimate",
		)
		settings = SimpleNamespace(key_id="rzp_test_example", checkout_name=None, checkout_theme_color=None)
		with patch("lex.lexpack._checkout_prefill", return_value={"email": "client@example.com"}):
			checkout = _checkout_payload(doc, SimpleNamespace(), settings, {"amount": 6000})
		self.assertTrue(checkout["is_live_order"])
		self.assertEqual(checkout["order_id"], "order_test_0001")
		self.assertEqual(checkout["amount"], 6000)
