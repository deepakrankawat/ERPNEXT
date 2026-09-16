from __future__ import annotations

import json
import os
from pypdf import PdfReader
import frappe

from lex.iterative_estimator import run_iterative_estimation


def run_estimation():
	path = "/home/frappe/frappe-bench/sites/development.localhost/private/files/Synthetic Litigation Case – Northstar v. Redline – Complete Case File.pdf"
	if not os.path.exists(path):
		for root, dirs, files in os.walk("/home/frappe/frappe-bench"):
			for f in files:
				if "Northstar" in f and f.endswith(".pdf"):
					path = os.path.join(root, f)
					break

	with open(path, "rb") as f:
		content = f.read()
	reader = PdfReader(path)
	text = "\n".join(p.extract_text() or "" for p in reader.pages)

	mock_files = [{"file_name": os.path.basename(path), "file_size": len(content)}]

	results = []
	services = [
		("Chronology Preparation", "Litigation Support", "Comprehensive Chronology of all breach events"),
		("Issue Matrix", "Litigation Support", "Issue Matrix mapping claims, facts, defenses, and documentary evidence"),
		("Pleading / Motion Draft Support", "Litigation Support", "Drafting Statement of Defence / Counterclaim support"),
	]

	for service_name, service_type, outcome in services:
		mock_doc = frappe._dict({
			"service_type": service_type,
			"jurisdiction": "Canada",
			"priority": "Standard",
			"requested_delivery_date": None,
			"expected_outcome": outcome,
			"detailed_instructions": "Analyze all 153 pages of Ontario Superior Court pleadings, exhibits, software contracts, and correspondence in Northstar v. Redline.",
		})
		ai_profile = {
			"recommended_service": service_name,
			"detected_document_type": "Case Record & Evidence Index",
			"complexity_score": 68,
			"risk_level": "High",
			"jurisdiction": "Canada",
			"reviewer_level": "Senior Associate",
			"billing_measure": "pages",
			"confidence": 88,
		}
		est = run_iterative_estimation(mock_doc, mock_files, text, initial_profile=ai_profile, max_attempts=3)
		results.append({
			"service_name": service_name,
			"convergence_status": est.get("convergence_status"),
			"iterations_count": est.get("iterations_count"),
			"quality_score": est.get("quality_report", {}).get("quality_score"),
			"billable_units": est["billable_units"],
			"effective_pages": est["page_count"],
			"word_count": est["word_count"],
			"lexpoints": est["lexpoints"],
			"quote_cad": est["quoted_price_cad"],
			"canadian_market_benchmark_cad": est["canadian_market_benchmark_cad"],
			"client_savings_percent": est["client_savings_percent"],
			"client_savings_cad": est["client_savings_cad"],
			"company_gross_margin_percent": est["gross_margin_percent"],
			"internal_delivery_cost_cad": est["internal_delivery_cost_cad"],
			"corridor_floor": est["floor_lexpoints"],
			"corridor_ceiling": est["ceiling_lexpoints"],
			"sla_hours": est["delivery_hours"],
			"tier_options": est["tier_options"],
			"iteration_history": est.get("iteration_history"),
		})

	print("=== NORTHSTAR V. REDLINE ITERATIVE ESTIMATION RESULTS ===")
	print(json.dumps(results, indent=2))
	return results
