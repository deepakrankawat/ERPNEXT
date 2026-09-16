from __future__ import annotations

import io
import os
from pypdf import PdfReader

import frappe
from frappe.tests.utils import FrappeTestCase

from lex import install
from lex.lexpoint_estimation import (
	calculate_estimate,
	collect_document_metadata,
	ensure_default_lexpoint_rules,
)
from lex.sample_docs.generate_sample_pdfs import SAMPLE_DIR, generate_all_sample_pdfs


class TestCanadianEstimationBenchmark(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		install.ensure_lexpack_master_data()
		install.ensure_lexpack_catalog()
		ensure_default_lexpoint_rules()
		generate_all_sample_pdfs()

	def _load_sample_pdf(self, filename: str) -> tuple[bytes, str, int]:
		filepath = os.path.join(SAMPLE_DIR, filename)
		with open(filepath, "rb") as f:
			content = f.read()
		reader = PdfReader(io.BytesIO(content))
		text = "\n".join(page.extract_text() or "" for page in reader.pages)
		return content, text, len(reader.pages)

	def test_sample_1_canadian_mutual_nda_ontario(self):
		"""Test Canadian Mutual NDA (Ontario) estimation under governed additive corridor."""
		content, extracted, physical_pages = self._load_sample_pdf("canadian_mutual_nda_ontario.pdf")
		self.assertGreater(len(extracted.split()), 300)

		# Mock intake doc
		mock_doc = frappe._dict({
			"service_type": "Contract Review",
			"jurisdiction": "Canada",
			"priority": "Standard",
			"requested_delivery_date": None,
			"expected_outcome": "Review mutual NDA for Canadian IP partnership",
			"detailed_instructions": "Review all confidentiality, term, governing law and trade secret provisions.",
		})

		mock_files = [{"file_name": "canadian_mutual_nda_ontario.pdf", "file_size": len(content)}]

		ai_profile = {
			"recommended_service": "NDA Review",
			"detected_document_type": "NDA",
			"complexity_score": 22,
			"risk_level": "Low",
			"jurisdiction": "Canada",
			"reviewer_level": "Junior Associate",
			"billing_measure": "pages",
			"confidence": 92,
		}

		result = calculate_estimate(mock_doc, mock_files, extracted, ai_profile=ai_profile)

		# Verifications
		self.assertEqual(result["recommended_service"], "NDA Review")
		self.assertEqual(result["complexity_classification"], "Routine")
		self.assertEqual(result["jurisdiction"], "Canada")

		# Golden Corridor Guardrails
		self.assertGreaterEqual(result["lexpoints"], result["floor_lexpoints"])
		self.assertLessEqual(result["lexpoints"], result["ceiling_lexpoints"])

		# Company Margin Protection (>= 50% gross profit)
		self.assertGreaterEqual(result["gross_margin_percent"], 50.0)

		# Client Savings Guarantee (>= 65% savings vs Canadian law firms)
		self.assertGreaterEqual(result["client_savings_percent"], 65.0)

		# 3-tier options available
		self.assertIn("essential", result["tier_options"])
		self.assertIn("standard", result["tier_options"])
		self.assertIn("deep_dive", result["tier_options"])

		# Print summary for reporting
		print("\n" + "=" * 70)
		print("BENCHMARK SAMPLE 1: CANADIAN MUTUAL NDA (ONTARIO)")
		print(f"Physical Pages: {result.get('physical_pages', physical_pages)} | Effective Pages: {result['page_count']} | Words: {result['word_count']}")
		print(f"Final Quote: {result['lexpoints']} LexPoints (${result['quoted_price_cad']:.2f} CAD)")
		print(f"Canadian Firm Benchmark: ${result['canadian_market_benchmark_cad']:.2f} CAD")
		print(f"Client Savings: {result['client_savings_percent']}% (You Save ${result['client_savings_cad']:.2f} CAD)")
		print(f"Company Gross Margin: {result['gross_margin_percent']}% (Delivery Cost: ${result['internal_delivery_cost_cad']:.2f} CAD)")
		print(f"Golden Corridor: Floor = {result['floor_lexpoints']} LP | Ceiling = {result['ceiling_lexpoints']} LP")
		print(f"Tiers: Essential: {result['tier_options']['essential']['lexpoints']} LP | Standard: {result['tier_options']['standard']['lexpoints']} LP | Deep-Dive: {result['tier_options']['deep_dive']['lexpoints']} LP")
		print("=" * 70)

	def test_sample_2_canadian_master_saas_agreement_bc(self):
		"""Test Canadian Master SaaS Agreement (BC) estimation under governed additive corridor."""
		content, extracted, physical_pages = self._load_sample_pdf("canadian_master_saas_agreement_bc.pdf")
		self.assertGreater(len(extracted.split()), 600)

		mock_doc = frappe._dict({
			"service_type": "Contract Review",
			"jurisdiction": "Canada",
			"priority": "Standard",
			"requested_delivery_date": None,
			"expected_outcome": "Review enterprise cloud agreement for BC compliance and risk",
			"detailed_instructions": "Review limitation of liability, IP indemnity, PIPEDA compliance, and VanIAC arbitration.",
		})

		mock_files = [{"file_name": "canadian_master_saas_agreement_bc.pdf", "file_size": len(content)}]

		ai_profile = {
			"recommended_service": "Standard Contract Review",
			"detected_document_type": "Master Services Agreement",
			"complexity_score": 62,
			"risk_level": "High",
			"jurisdiction": "Canada",
			"reviewer_level": "Senior Associate",
			"billing_measure": "pages",
			"confidence": 88,
		}

		result = calculate_estimate(mock_doc, mock_files, extracted, ai_profile=ai_profile)

		self.assertEqual(result["recommended_service"], "Standard Contract Review")
		self.assertEqual(result["complexity_classification"], "Complex")
		self.assertEqual(result["risk_level"], "High")

		# Corridor bounds
		self.assertGreaterEqual(result["lexpoints"], result["floor_lexpoints"])
		self.assertLessEqual(result["lexpoints"], result["ceiling_lexpoints"])
		self.assertGreaterEqual(result["gross_margin_percent"], 50.0)
		self.assertGreaterEqual(result["client_savings_percent"], 65.0)

		print("\n" + "=" * 70)
		print("BENCHMARK SAMPLE 2: CANADIAN MASTER SAAS AGREEMENT (BRITISH COLUMBIA)")
		print(f"Physical Pages: {result.get('physical_pages', physical_pages)} | Effective Pages: {result['page_count']} | Words: {result['word_count']}")
		print(f"Final Quote: {result['lexpoints']} LexPoints (${result['quoted_price_cad']:.2f} CAD)")
		print(f"Canadian Firm Benchmark: ${result['canadian_market_benchmark_cad']:.2f} CAD")
		print(f"Client Savings: {result['client_savings_percent']}% (You Save ${result['client_savings_cad']:.2f} CAD)")
		print(f"Company Gross Margin: {result['gross_margin_percent']}% (Delivery Cost: ${result['internal_delivery_cost_cad']:.2f} CAD)")
		print(f"Golden Corridor: Floor = {result['floor_lexpoints']} LP | Ceiling = {result['ceiling_lexpoints']} LP")
		print(f"Tiers: Essential: {result['tier_options']['essential']['lexpoints']} LP | Standard: {result['tier_options']['standard']['lexpoints']} LP | Deep-Dive: {result['tier_options']['deep_dive']['lexpoints']} LP")
		print("=" * 70)

	def test_sample_3_canadian_court_motion_research_memo(self):
		"""Test Canadian Court Motion & Precedent Research Brief estimation."""
		content, extracted, physical_pages = self._load_sample_pdf("canadian_court_motion_research_memo.pdf")
		self.assertGreater(len(extracted.split()), 500)

		mock_doc = frappe._dict({
			"service_type": "Legal Research",
			"jurisdiction": "Canada",
			"priority": "Standard",
			"requested_delivery_date": None,
			"expected_outcome": "Research injunction precedents under RJR-MacDonald",
			"detailed_instructions": "Analyze CanLII decisions, Federal Court injunction standards, and irreparable harm jurisprudence.",
		})

		mock_files = [{"file_name": "canadian_court_motion_research_memo.pdf", "file_size": len(content)}]

		ai_profile = {
			"recommended_service": "Legal Research Memo",
			"detected_document_type": "Memorandum",
			"complexity_score": 70,
			"risk_level": "High",
			"jurisdiction": "Canada",
			"reviewer_level": "Senior Associate",
			"billing_measure": "pages",
			"confidence": 90,
		}

		result = calculate_estimate(mock_doc, mock_files, extracted, ai_profile=ai_profile)

		self.assertEqual(result["recommended_service"], "Legal Research Memo")
		self.assertIn(result["complexity_classification"], {"Complex", "Specialist"})

		# Corridor bounds
		self.assertGreaterEqual(result["lexpoints"], result["floor_lexpoints"])
		self.assertLessEqual(result["lexpoints"], result["ceiling_lexpoints"])
		self.assertGreaterEqual(result["gross_margin_percent"], 50.0)
		self.assertGreaterEqual(result["client_savings_percent"], 65.0)

		print("\n" + "=" * 70)
		print("BENCHMARK SAMPLE 3: CANADIAN COURT MOTION & RESEARCH BRIEF (FEDERAL COURT)")
		print(f"Physical Pages: {result.get('physical_pages', physical_pages)} | Effective Pages: {result['page_count']} | Words: {result['word_count']}")
		print(f"Final Quote: {result['lexpoints']} LexPoints (${result['quoted_price_cad']:.2f} CAD)")
		print(f"Canadian Firm Benchmark: ${result['canadian_market_benchmark_cad']:.2f} CAD")
		print(f"Client Savings: {result['client_savings_percent']}% (You Save ${result['client_savings_cad']:.2f} CAD)")
		print(f"Company Gross Margin: {result['gross_margin_percent']}% (Delivery Cost: ${result['internal_delivery_cost_cad']:.2f} CAD)")
		print(f"Golden Corridor: Floor = {result['floor_lexpoints']} LP | Ceiling = {result['ceiling_lexpoints']} LP")
		print(f"Tiers: Essential: {result['tier_options']['essential']['lexpoints']} LP | Standard: {result['tier_options']['standard']['lexpoints']} LP | Deep-Dive: {result['tier_options']['deep_dive']['lexpoints']} LP")
		print("=" * 70)
