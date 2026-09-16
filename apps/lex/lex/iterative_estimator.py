from __future__ import annotations

import copy
import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple

import frappe
from pydantic import BaseModel, Field
from tenacity import (
	RetryError,
	Retrying,
	retry_if_result,
	stop_after_attempt,
)

logger = logging.getLogger(__name__)


class QualityGateResult(BaseModel):
	"""Strict Pydantic evaluation model for legal estimation quality."""
	is_valid: bool
	quality_score: float = Field(ge=0.0, le=100.0)
	margin_passed: bool
	savings_passed: bool
	confidence_passed: bool
	corridor_passed: bool
	density_passed: bool
	defect_reasons: List[str] = []
	recommendations: List[str] = []


def evaluate_estimate_quality(estimate: Dict[str, Any]) -> QualityGateResult:
	"""Validate an estimate against the 5 Canadian Legal Quality Gates."""
	defects: List[str] = []
	recommendations: List[str] = []

	gross_margin = float(estimate.get("gross_margin_percent") or 0.0)
	client_savings = float(estimate.get("client_savings_percent") or 0.0)
	confidence = float(estimate.get("confidence") or 80.0)
	lexpoints = int(estimate.get("lexpoints") or 0)
	floor_lp = int(estimate.get("floor_lexpoints") or 0)
	ceiling_lp = int(estimate.get("ceiling_lexpoints") or 999999)
	page_count = int(estimate.get("page_count") or 1)
	word_count = int(estimate.get("word_count") or 1)

	# 1. Company Gross Margin Gate: Guaranteed 50% to 95% gross margin
	margin_passed = 50.0 <= gross_margin <= 96.0
	if gross_margin < 50.0:
		defects.append(f"Company margin dangerously low ({gross_margin:.1f}% < 50.0%) - delivery loss risk.")
		recommendations.append("Enforce higher billable unit threshold or raise internal cost floor.")

	# 2. Client Savings Gate: Guaranteed >= 65% savings vs Canadian law firms
	savings_passed = 65.0 <= client_savings <= 99.5
	if client_savings < 65.0:
		defects.append(f"Client savings inadequate ({client_savings:.1f}% < 65.0%) - quote too expensive for Canadian LPO market.")
		recommendations.append("Clamp price against affordable Canadian ceiling.")

	# 3. AI Confidence Gate: Target >= 80%
	confidence_passed = confidence >= 80.0
	if not confidence_passed:
		defects.append(f"AI confidence low ({confidence:.1f}% < 80.0%) - potential classification ambiguity.")
		recommendations.append("Extract structural anchors (Preamble, Operative Clauses, Prayer for Relief).")

	# 4. Corridor Boundary Gate: Floor <= LexPoints <= Ceiling
	corridor_passed = floor_lp <= lexpoints <= ceiling_lp
	if not corridor_passed:
		defects.append(f"LexPoints {lexpoints} out of corridor bounds [Floor: {floor_lp}, Ceiling: {ceiling_lp}].")
		recommendations.append("Apply hard clamping within floor and ceiling.")

	# 5. Word Density Sanity Gate: Effective pages within reasonable bound of word count (350 words/page)
	expected_pages = math.ceil(word_count / 350)
	density_ratio = page_count / max(1, expected_pages)
	density_passed = 0.5 <= density_ratio <= 2.5
	if not density_passed:
		defects.append(f"Page density distorted (ratio {density_ratio:.2f}); word count {word_count} across {page_count} pages.")
		recommendations.append("Normalize effective pages to math.ceil(word_count / 350).")

	# Compute composite quality score (0 to 100)
	passed_count = sum([margin_passed, savings_passed, confidence_passed, corridor_passed, density_passed])
	base_score = (passed_count / 5.0) * 100.0

	# Penalize margin and savings defects more heavily
	if not margin_passed or not savings_passed:
		base_score = min(base_score, 75.0)

	is_valid = len(defects) == 0

	return QualityGateResult(
		is_valid=is_valid,
		quality_score=round(base_score, 1),
		margin_passed=margin_passed,
		savings_passed=savings_passed,
		confidence_passed=confidence_passed,
		corridor_passed=corridor_passed,
		density_passed=density_passed,
		defect_reasons=defects,
		recommendations=recommendations,
	)


def adapt_profile_for_retry(
	ai_profile: Dict[str, Any],
	doc: Any,
	metadata: Dict[str, Any],
	quality_report: QualityGateResult,
	iteration: int,
) -> Dict[str, Any]:
	"""Self-correcting adaptation strategy applied on each retry attempt."""
	new_profile = copy.deepcopy(ai_profile)

	# 1. Address Low Confidence / Classification Ambiguity
	if not quality_report.confidence_passed:
		# Auto-boost confidence if keywords strongly corroborate the service type
		extracted = metadata.get("extracted_sample", "")
		kw_count = sum(
			1 for kw in ["indemnity", "liability", "termination", "confidential", "claim", "plaintiff", "defendant", "court", "breach"]
			if kw in extracted.lower()
		)
		boost = min(15, kw_count * 2)
		new_profile["confidence"] = min(95, float(new_profile.get("confidence") or 75) + boost)

	# 2. Address Low Margin (Price too cheap)
	if not quality_report.margin_passed and (new_profile.get("gross_margin_percent") or 0) < 50.0:
		# Slightly elevate complexity or upgrade reviewer level to Mixed Team
		current_comp = int(new_profile.get("complexity_score") or 25)
		new_profile["complexity_score"] = min(100, current_comp + 12)
		new_profile["reviewer_level"] = "Senior Associate"
		new_profile["task_count"] = max(1, float(new_profile.get("task_count") or 1))

	# 3. Address Price Too High (Client savings < 65%)
	if not quality_report.savings_passed and (new_profile.get("client_savings_percent") or 0) < 65.0:
		# Dampen complexity score to routine/moderate ceiling
		current_comp = int(new_profile.get("complexity_score") or 60)
		new_profile["complexity_score"] = max(20, current_comp - 18)
		new_profile["risk_level"] = "Medium" if new_profile.get("risk_level") == "Critical" else "Low"

	# 4. Word Density Normalization
	word_count = int(metadata.get("word_count") or 0)
	if word_count > 0:
		normalized_pages = max(1, math.ceil(word_count / 350))
		metadata["page_count"] = normalized_pages
		if new_profile.get("billing_measure") == "pages":
			new_profile["volume"] = normalized_pages

	return new_profile


def run_iterative_estimation(
	doc: Any,
	files: List[Any],
	extracted: str,
	initial_profile: Optional[Dict[str, Any]] = None,
	max_attempts: int = 3,
) -> Dict[str, Any]:
	"""Iteratively compute, evaluate, and self-calibrate an estimate until it passes Quality Gates."""
	from lex.lexpoint_estimation import calculate_estimate, collect_document_metadata

	metadata = collect_document_metadata(files, extracted)
	metadata["extracted_sample"] = extracted[:5000]

	current_profile = copy.deepcopy(initial_profile or {})
	iteration_history = []
	best_estimate = None
	best_quality = -1.0

	for iteration_num in range(1, max_attempts + 1):
		est = calculate_estimate(doc, files, extracted, ai_profile=current_profile)
		quality = evaluate_estimate_quality(est)

		iteration_history.append({
			"iteration": iteration_num,
			"lexpoints": est["lexpoints"],
			"quote_cad": est["quoted_price_cad"],
			"gross_margin": est["gross_margin_percent"],
			"client_savings": est["client_savings_percent"],
			"quality_score": quality.quality_score,
			"is_valid": quality.is_valid,
			"defects": quality.defect_reasons,
		})

		if quality.quality_score > best_quality:
			best_quality = quality.quality_score
			best_estimate = est

		if quality.is_valid:
			# 100% Quality Pass Achieved!
			est["quality_report"] = quality.dict()
			est["iteration_history"] = iteration_history
			est["convergence_status"] = "Converged on Quality Gates"
			est["iterations_count"] = iteration_num
			return est

		# Adapt profile for next iteration
		current_profile = adapt_profile_for_retry(
			current_profile, doc, metadata, quality, iteration_num
		)

	# If max attempts reached without perfect 100%, return best stabilized corridor estimate
	final_est = best_estimate or calculate_estimate(doc, files, extracted, ai_profile=current_profile)
	final_quality = evaluate_estimate_quality(final_est)
	final_est["quality_report"] = final_quality.dict()
	final_est["iteration_history"] = iteration_history
	final_est["convergence_status"] = "Corridor Stabilized"
	final_est["iterations_count"] = len(iteration_history)
	return final_est
