from __future__ import annotations

import io
import os

import frappe
from frappe.tests.utils import FrappeTestCase
from pypdf import PdfReader

from lex import install
from lex.iterative_estimator import evaluate_estimate_quality, run_iterative_estimation
from lex.lexpoint_estimation import ensure_default_lexpoint_rules
from lex.sample_docs.generate_sample_pdfs import SAMPLE_DIR, generate_all_sample_pdfs


class TestIterativeEstimator(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		install.ensure_lexpack_master_data()
		install.ensure_lexpack_catalog()
		ensure_default_lexpoint_rules()
		if not os.path.exists(os.path.join(SAMPLE_DIR, "canadian_mutual_nda_ontario.pdf")):
			generate_all_sample_pdfs()

	def test_quality_gate_evaluator_detects_defects_and_passes(self):
		perfect_estimate = {
			"gross_margin_percent": 75.0,
			"client_savings_percent": 70.0,
			"confidence": 90.0,
			"classification_source": "AI",
			"lexpoints": 35,
			"floor_lexpoints": 20,
			"ceiling_lexpoints": 35,
			"corridor_feasible": True,
			"page_count": 5,
			"word_count": 1750,
		}
		result = evaluate_estimate_quality(perfect_estimate)
		self.assertTrue(result.is_valid)
		self.assertEqual(result.quality_score, 100.0)
		self.assertEqual(result.defect_reasons, [])

		bad_estimate = {
			"gross_margin_percent": 30.0,
			"client_savings_percent": 50.0,
			"confidence": 65.0,
			"classification_source": "AI",
			"lexpoints": 120,
			"floor_lexpoints": 40,
			"ceiling_lexpoints": 35,
			"corridor_feasible": False,
			"page_count": 5,
			"word_count": 1750,
		}
		bad_result = evaluate_estimate_quality(bad_estimate)
		self.assertFalse(bad_result.is_valid)
		self.assertLess(bad_result.quality_score, 75.0)
		self.assertGreater(len(bad_result.defect_reasons), 0)

		# High savings/margins are not defects merely because they exceed an
		# arbitrary upper bound.
		strong_estimate = {
			**perfect_estimate,
			"gross_margin_percent": 97.0,
			"client_savings_percent": 99.8,
		}
		strong_result = evaluate_estimate_quality(strong_estimate)
		self.assertTrue(strong_result.is_valid)
		self.assertTrue(strong_result.margin_passed)
		self.assertTrue(strong_result.savings_passed)

	def test_iterative_adaptation_on_sample_nda(self):
		filepath = os.path.join(SAMPLE_DIR, "canadian_mutual_nda_ontario.pdf")
		with open(filepath, "rb") as source:
			content = source.read()
		reader = PdfReader(io.BytesIO(content))
		text = "\n".join(page.extract_text() or "" for page in reader.pages)
		mock_doc = frappe._dict(
			service_type="Contract Review",
			jurisdiction="Canada",
			priority="Standard",
			requested_delivery_date=None,
			expected_outcome="Review mutual NDA",
			detailed_instructions="Review all confidentiality terms and Ontario governing law.",
		)
		mock_files = [{"file_name": "canadian_mutual_nda_ontario.pdf", "file_size": len(content)}]
		initial_profile = {
			"recommended_service": "NDA Review",
			"document_type": "NDA",
			"complexity_score": 10,
			"risk_level": "Low",
			"jurisdiction": "Canada",
			"reviewer_level": "Junior Associate",
			"confidence": 72,
		}

		result = run_iterative_estimation(
			mock_doc, mock_files, text, initial_profile=initial_profile, max_attempts=3
		)
		self.assertTrue(result["quality_report"]["is_valid"])
		self.assertEqual(result["quality_report"]["quality_score"], 100.0)
		self.assertGreaterEqual(result["gross_margin_percent"], 60.0)
		self.assertGreaterEqual(result["client_savings_percent"], 65.0)
		self.assertGreaterEqual(len(result["iteration_history"]), 2)

	def test_end_to_end_convergence_on_northstar_litigation_file(self):
		"""Lock all three approved 153-page Northstar pricing outcomes."""

		anchors = (
			"northstar redline plaintiff defendant court claim breach evidence "
			"contract motion chronology liability exhibit correspondence"
		).split()
		text = " ".join(anchors[index % len(anchors)] for index in range(53348))
		mock_doc = frappe._dict(
			service_type="Litigation Support",
			jurisdiction="Canada",
			priority="Standard",
			requested_delivery_date=None,
			expected_outcome="Comprehensive analysis of the case record",
			detailed_instructions="Analyze the 153-page Northstar v. Redline record.",
		)
		mock_files = [{"file_name": "northstar-redline.txt", "file_size": len(text)}]

		for service, points, quote, cost, margin, units in (
			("Chronology Preparation", 35, 105.0, 20.16, 80.8, 1.645),
			("Issue Matrix", 35, 105.0, 20.16, 80.8, 1.645),
			("Pleading / Motion Draft Support", 50, 150.0, 38.46, 74.4, 2.174),
		):
			profile = {
				"recommended_service": service,
				"document_type": "Case Record & Evidence Index",
				"complexity_score": 68,
				"risk_level": "High",
				"jurisdiction": "Canada",
				"reviewer_level": "Senior Associate",
				"confidence": 88,
			}
			result = run_iterative_estimation(
				mock_doc, mock_files, text, initial_profile=profile, max_attempts=3
			)
			self.assertTrue(result["quality_report"]["is_valid"], service)
			self.assertEqual(result["quality_report"]["quality_score"], 100.0, service)
			self.assertEqual(result["page_count"], 153, service)
			self.assertEqual(result["billable_units"], units, service)
			self.assertEqual(result["lexpoints"], points, service)
			self.assertEqual(result["quoted_price_cad"], quote, service)
			self.assertEqual(result["internal_delivery_cost_cad"], cost, service)
			self.assertEqual(result["gross_margin_percent"], margin, service)
			self.assertEqual(result["currency"], "CAD", service)
			self.assertIn("Converged", result["convergence_status"], service)

	def test_cost_floor_conflict_fails_closed_at_hard_cap(self):
		mock_doc = frappe._dict(
			service_type="Litigation Support",
			jurisdiction="Canada",
			priority="Medium",
			requested_delivery_date=None,
		)
		profile = {
			"recommended_service": "Chronology Preparation",
			"complexity_score": 68,
			"risk_level": "High",
			"jurisdiction": "Canada",
			"reviewer_level": "Senior Associate",
			"task_count": 10,
			"confidence": 90,
		}
		text = " ".join(["court claim breach evidence chronology"] * 10700)
		result = run_iterative_estimation(
			mock_doc,
			[{"file_name": "large-case.txt", "file_size": len(text)}],
			text,
			initial_profile=profile,
		)
		self.assertEqual(result["lexpoints"], 35)
		self.assertEqual(result["ceiling_lexpoints"], 35)
		self.assertGreater(result["floor_lexpoints"], result["ceiling_lexpoints"])
		self.assertFalse(result["corridor_feasible"])
		self.assertTrue(result["custom_scope_required"])
		self.assertFalse(result["quality_report"]["is_valid"])
		self.assertTrue(result["requires_human_review"])
		self.assertIn("Human Review Required", result["convergence_status"])
