from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from lex.lexpoint_estimation import (
	calculate_estimate,
	calculate_from_factors,
	ensure_default_lexpoint_rules,
)


class TestLexPointEstimationEngine(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		ensure_default_lexpoint_rules()

	def test_configurator_reference_scenarios_total_2978(self):
		scenarios = (
			("Legal Research Memo", 3, 10, 40, "Standard", "Canada", "Medium", 359),
			("Chronology Preparation", 2, 50, 40, "72 Hours", "Canada", "Medium", 306),
			("CLM Administration", 5, 25, 20, "Standard", "Canada", "Low", 722),
			("First-Level Document Review", 10, 100, 20, "Standard", "Canada", "Low", 1040),
			("Compliance Research", 2, 10, 40, "Standard", "Canada", "Medium", 250),
			("Virtual Paralegal Support", 1, 20, 20, "Standard", "Canada", "Low", 301),
		)
		results = []
		for service, tasks, volume, score, priority, jurisdiction, risk, expected in scenarios:
			result = calculate_from_factors(
				service_name=service,
				task_count=tasks,
				volume=volume,
				complexity_score=score,
				priority=priority,
				jurisdiction=jurisdiction,
				risk=risk,
				reviewer_level="Junior Associate",
			)
			self.assertEqual(result["lexpoints"], expected, service)
			results.append(result["lexpoints"])
		self.assertEqual(sum(results), 2978)

	def test_ai_supplies_factors_but_cannot_set_lexpoints(self):
		doc = frappe._dict(
			service_type="Legal Research",
			jurisdiction="Canada",
			priority="Medium",
			requested_delivery_date=None,
		)
		profile = {
			"document_type": "Memorandum",
			"document_type_confidence": 95,
			"practice_modules": ["Research"],
			"recommended_service": "Legal Research Memo",
			"legal_domain": "Commercial",
			"jurisdiction": "Canada",
			"jurisdiction_confidence": 94,
			"complexity_score": 40,
			"risk_level": "Medium",
			"reviewer_level": "Junior Associate",
			"volume": 10,
			"task_count": 3,
			"confidence": 93,
			"lexpoints": 999999,
		}
		files = [frappe._dict(file_name=f"memo-{index}.txt", file_size=100, name=f"FAKE-{index}") for index in range(3)]
		result = calculate_estimate(doc, files, "commercial research memorandum " * 80, ai_profile=profile)
		self.assertEqual(result["lexpoints"], 359)
		self.assertEqual(result["formula_version"], "LEXPOINTS-1.0")
		self.assertIn("governed upward rounding", result["explanation"])

	def test_complexity_score_selects_governed_band(self):
		for score, expected in ((1, "Routine"), (25, "Routine"), (26, "Moderate"), (50, "Moderate"), (51, "Complex"), (75, "Complex"), (76, "Specialist"), (100, "Specialist")):
			result = calculate_from_factors(
				service_name="NDA Review", task_count=1, volume=10, complexity_score=score,
				priority="Standard", jurisdiction="India", risk="Low", reviewer_level="Junior Associate",
			)
			self.assertEqual(result["complexity_classification"], expected)
