from __future__ import annotations

import io
import os
from pypdf import PdfReader

import frappe
from frappe.tests.utils import FrappeTestCase

from lex import install
from lex.iterative_estimator import (
	evaluate_estimate_quality,
	run_iterative_estimation,
)
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
		generate_all_sample_pdfs()

	def test_quality_gate_evaluator_detects_defects_and_passes(self):
		"""Verify Pydantic Quality Gate evaluation."""
		perfect_estimate = {
			"gross_margin_percent": 75.0,
			"client_savings_percent": 70.0,
			"confidence": 90.0,
			"lexpoints": 50,
			"floor_lexpoints": 20,
			"ceiling_lexpoints": 80,
			"page_count": 5,
			"word_count": 1750,
		}
		res = evaluate_estimate_quality(perfect_estimate)
		self.assertTrue(res.is_valid)
		self.assertEqual(res.quality_score, 100.0)
		self.assertEqual(len(res.defect_reasons), 0)

		# Defective estimate (low margin + low savings)
		bad_estimate = {
			"gross_margin_percent": 30.0,  # Below 50%
			"client_savings_percent": 50.0,  # Below 65%
			"confidence": 65.0,  # Below 80%
			"lexpoints": 120,
			"floor_lexpoints": 40,
			"ceiling_lexpoints": 100,  # Breaches ceiling!
			"page_count": 5,
			"word_count": 1750,
		}
		bad_res = evaluate_estimate_quality(bad_estimate)
		self.assertFalse(bad_res.is_valid)
		self.assertLess(bad_res.quality_score, 75.0)
		self.assertGreater(len(bad_res.defect_reasons), 0)

	def test_iterative_adaptation_on_sample_nda(self):
		"""Verify that iterative estimation converges cleanly on Ontario NDA."""
		filepath = os.path.join(SAMPLE_DIR, "canadian_mutual_nda_ontario.pdf")
		with open(filepath, "rb") as f:
			content = f.read()
		reader = PdfReader(io.BytesIO(content))
		text = "\n".join(page.extract_text() or "" for page in reader.pages)

		mock_doc = frappe._dict({
			"service_type": "Contract Review",
			"jurisdiction": "Canada",
			"priority": "Standard",
			"expected_outcome": "Review mutual NDA",
			"detailed_instructions": "Review all confidentiality terms and Ontario governing law.",
		})
		mock_files = [{"file_name": "canadian_mutual_nda_ontario.pdf", "file_size": len(content)}]

		# Start with slightly noisy/suboptimal profile to force retry/calibration
		initial_profile = {
			"recommended_service": "NDA Review",
			"detected_document_type": "NDA",
			"complexity_score": 10,
			"risk_level": "Low",
			"jurisdiction": "Canada",
			"reviewer_level": "Junior Associate",
			"billing_measure": "pages",
			"confidence": 72,  # Below 80% threshold to test self-healing
		}

		result = run_iterative_estimation(mock_doc, mock_files, text, initial_profile=initial_profile, max_attempts=3)

		self.assertIn("quality_report", result)
		self.assertIn("iteration_history", result)
		self.assertGreaterEqual(result["quality_report"]["quality_score"], 80.0)
		self.assertGreaterEqual(result["gross_margin_percent"], 50.0)
		self.assertGreaterEqual(result["client_savings_percent"], 65.0)
		self.assertGreaterEqual(len(result["iteration_history"]), 1)

	def test_end_to_end_convergence_on_northstar_litigation_file(self):
		"""Verify iterative convergence on the complete 153-page Northstar v. Redline file."""
		path = "/home/frappe/frappe-bench/sites/development.localhost/private/files/Synthetic Litigation Case – Northstar v. Redline – Complete Case File.pdf"
		if not os.path.exists(path):
			self.skipTest("Northstar case file not found on path.")

		with open(path, "rb") as f:
			content = f.read()
		reader = PdfReader(io.BytesIO(content))
		text = "\n".join(page.extract_text() or "" for page in reader.pages)

		mock_doc = frappe._dict({
			"service_type": "Litigation Support",
			"jurisdiction": "Canada",
			"priority": "Standard",
			"expected_outcome": "Comprehensive Case Chronology across 153 pages",
			"detailed_instructions": "Full analysis of Ontario Superior Court record in Northstar v. Redline.",
		})
		mock_files = [{"file_name": os.path.basename(path), "file_size": len(content)}]

		initial_profile = {
			"recommended_service": "Chronology Preparation",
			"detected_document_type": "Case Record",
			"complexity_score": 65,
			"risk_level": "High",
			"jurisdiction": "Canada",
			"reviewer_level": "Senior Associate",
			"billing_measure": "pages",
			"confidence": 85,
		}

		result = run_iterative_estimation(mock_doc, mock_files, text, initial_profile=initial_profile, max_attempts=3)

		self.assertTrue(result["quality_report"]["is_valid"])
		self.assertEqual(result["quality_report"]["quality_score"], 100.0)
		self.assertGreaterEqual(result["gross_margin_percent"], 50.0)
		self.assertGreaterEqual(result["client_savings_percent"], 65.0)
		self.assertIn("Converged", result["convergence_status"])
