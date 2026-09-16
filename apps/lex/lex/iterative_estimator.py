from __future__ import annotations

import copy
import logging
import math
from typing import Any

from pydantic import BaseModel, Field
from tenacity import Retrying, retry_if_result, stop_after_attempt

logger = logging.getLogger(__name__)

MINIMUM_GROSS_MARGIN_PERCENT = 60.0
MINIMUM_CLIENT_SAVINGS_PERCENT = 65.0
MINIMUM_AI_CONFIDENCE_PERCENT = 80.0


class QualityGateResult(BaseModel):
	"""Strict Pydantic evaluation model for legal estimation quality."""

	is_valid: bool
	quality_score: float = Field(ge=0.0, le=100.0)
	margin_passed: bool
	savings_passed: bool
	confidence_passed: bool
	confidence_gate_applicable: bool = True
	corridor_passed: bool
	density_passed: bool
	defect_reasons: list[str] = Field(default_factory=list)
	recommendations: list[str] = Field(default_factory=list)


def evaluate_estimate_quality(estimate: dict[str, Any]) -> QualityGateResult:
	"""Validate an estimate against the five Canadian legal-pricing gates."""

	defects: list[str] = []
	recommendations: list[str] = []

	gross_margin = float(estimate.get("gross_margin_percent") or 0.0)
	client_savings = float(estimate.get("client_savings_percent") or 0.0)
	confidence = float(estimate.get("confidence") or 0.0)
	lexpoints = int(estimate.get("lexpoints") or 0)
	floor_lp = int(estimate.get("floor_lexpoints") or 0)
	ceiling_lp = int(estimate.get("ceiling_lexpoints") or 0)
	page_count = int(estimate.get("page_count") or 1)
	word_count = int(estimate.get("word_count") or 1)

	# 1. Company Gross Margin Gate: at least 60% against the governed cost model.
	margin_passed = gross_margin >= MINIMUM_GROSS_MARGIN_PERCENT
	if not margin_passed:
		defects.append(
			f"Company gross margin too low ({gross_margin:.1f}% < "
			f"{MINIMUM_GROSS_MARGIN_PERCENT:.1f}%)."
		)
		recommendations.append("Reduce or split scope, or approve a custom quote above the standard cap.")

	# 2. Client Savings Gate: at least 65% versus the Canadian benchmark.
	savings_passed = client_savings >= MINIMUM_CLIENT_SAVINGS_PERCENT
	if not savings_passed:
		defects.append(
			f"Client savings inadequate ({client_savings:.1f}% < "
			f"{MINIMUM_CLIENT_SAVINGS_PERCENT:.1f}%)."
		)
		recommendations.append("Review the service classification and Canadian benchmark before release.")

	# 3. AI Confidence Gate. Deterministic formula fallback has no AI confidence
	# to validate, so this gate is explicitly recorded as not applicable.
	confidence_gate_applicable = estimate.get("classification_source") != "Deterministic Formula"
	confidence_passed = (
		not confidence_gate_applicable or confidence >= MINIMUM_AI_CONFIDENCE_PERCENT
	)
	if not confidence_passed:
		defects.append(
			f"AI confidence low ({confidence:.1f}% < {MINIMUM_AI_CONFIDENCE_PERCENT:.1f}%)."
		)
		recommendations.append("Re-run classification or require Legal Operations review.")

	# 4. Corridor Boundary Gate. A cost floor above the hard cap is never
	# silently converted into a larger 'ceiling'; it requires custom scoping.
	corridor_feasible = bool(estimate.get("corridor_feasible", floor_lp <= ceiling_lp))
	corridor_passed = corridor_feasible and floor_lp <= lexpoints <= ceiling_lp
	if not corridor_passed:
		if not corridor_feasible:
			defects.append(
				f"No safe standard quote exists: required floor {floor_lp} LP exceeds "
				f"the hard ceiling {ceiling_lp} LP."
			)
			recommendations.append("Split/reduce scope or approve an explicit custom quote.")
		else:
			defects.append(
				f"LexPoints {lexpoints} outside corridor [floor {floor_lp}, ceiling {ceiling_lp}]."
			)
			recommendations.append("Clamp the quote within the governed floor and ceiling.")

	# 5. Word Density Sanity Gate: effective pages should remain reasonably
	# consistent with extracted text at the governed 350 words/page density.
	expected_pages = math.ceil(word_count / 350)
	density_ratio = page_count / max(1, expected_pages)
	density_passed = 0.5 <= density_ratio <= 2.5
	if not density_passed:
		defects.append(
			f"Page density distorted (ratio {density_ratio:.2f}); "
			f"{word_count} extracted words across {page_count} effective pages."
		)
		recommendations.append("Verify OCR/page extraction before releasing the quote.")

	gate_results = (
		margin_passed,
		savings_passed,
		confidence_passed,
		corridor_passed,
		density_passed,
	)
	quality_score = round((sum(gate_results) / len(gate_results)) * 100.0, 1)
	is_valid = all(gate_results)

	return QualityGateResult(
		is_valid=is_valid,
		quality_score=quality_score,
		margin_passed=margin_passed,
		savings_passed=savings_passed,
		confidence_passed=confidence_passed,
		confidence_gate_applicable=confidence_gate_applicable,
		corridor_passed=corridor_passed,
		density_passed=density_passed,
		defect_reasons=defects,
		recommendations=recommendations,
	)


def adapt_profile_for_retry(
	ai_profile: dict[str, Any],
	metadata: dict[str, Any],
	quality_report: QualityGateResult,
	estimate: dict[str, Any],
	iteration: int,
) -> dict[str, Any]:
	"""Apply evidence-backed, non-commercial corrections before a retry."""

	new_profile = copy.deepcopy(ai_profile)

	# Corroborating legal anchors can resolve a borderline classifier result,
	# but never conceal a cost/cap conflict or rewrite objective file volume.
	if quality_report.confidence_gate_applicable and not quality_report.confidence_passed:
		extracted = metadata.get("extracted_sample", "")
		keyword_count = sum(
			1
			for keyword in (
				"indemnity",
				"liability",
				"termination",
				"confidential",
				"claim",
				"plaintiff",
				"defendant",
				"court",
				"breach",
			)
			if keyword in extracted.lower()
		)
		boost = min(15, keyword_count * 2)
		current_confidence = float(
			new_profile.get("confidence") or estimate.get("confidence") or 0
		)
		new_profile["confidence"] = min(95, current_confidence + boost)
		new_profile["confidence_recalibration_iteration"] = iteration

	if not quality_report.corridor_passed or not quality_report.margin_passed:
		new_profile["requires_human_review"] = True

	return new_profile


def _quality_payload(quality: QualityGateResult) -> dict[str, Any]:
	return quality.model_dump() if hasattr(quality, "model_dump") else quality.dict()


def _attach_quality_evidence(
	estimate: dict[str, Any],
	quality: QualityGateResult,
	iteration_history: list[dict[str, Any]],
	convergence_status: str,
) -> dict[str, Any]:
	quality_payload = _quality_payload(quality)
	estimate["quality_report"] = quality_payload
	estimate["iteration_history"] = iteration_history
	estimate["convergence_status"] = convergence_status
	estimate["iterations_count"] = len(iteration_history)
	estimate["quality_gate_passed"] = quality.is_valid
	if not quality.is_valid:
		estimate["requires_human_review"] = 1

	factor_breakdown = dict(estimate.get("factor_breakdown") or {})
	factor_breakdown["quality_assurance"] = {
		"gate_count": 5,
		"quality_report": quality_payload,
		"iterations_count": len(iteration_history),
		"convergence_status": convergence_status,
		"iteration_history": iteration_history,
	}
	estimate["factor_breakdown"] = factor_breakdown
	return estimate


def run_iterative_estimation(
	doc: Any,
	files: list[Any],
	extracted: str,
	initial_profile: dict[str, Any] | None = None,
	max_attempts: int = 3,
) -> dict[str, Any]:
	"""Compute, validate and retry an estimate; fail closed to human review."""

	from lex.lexpoint_estimation import calculate_estimate, collect_document_metadata

	metadata = collect_document_metadata(files, extracted)
	metadata["extracted_sample"] = extracted[:5000]
	current_profile = copy.deepcopy(initial_profile or {})
	iteration_history: list[dict[str, Any]] = []
	best_estimate: dict[str, Any] | None = None
	best_quality: QualityGateResult | None = None

	def estimate_once() -> dict[str, Any]:
		nonlocal current_profile, best_estimate, best_quality
		iteration_number = len(iteration_history) + 1
		estimate = calculate_estimate(
			doc,
			files,
			extracted,
			ai_profile=current_profile if initial_profile is not None else None,
			auto_converge=False,
		)
		quality = evaluate_estimate_quality(estimate)
		iteration_history.append(
			{
				"iteration": iteration_number,
				"lexpoints": estimate["lexpoints"],
				"quote_cad": estimate["quoted_price_cad"],
				"gross_margin": estimate["gross_margin_percent"],
				"client_savings": estimate["client_savings_percent"],
				"quality_score": quality.quality_score,
				"is_valid": quality.is_valid,
				"defects": quality.defect_reasons,
			}
		)

		if best_quality is None or quality.quality_score > best_quality.quality_score:
			best_estimate = estimate
			best_quality = quality

		if not quality.is_valid:
			current_profile = adapt_profile_for_retry(
				current_profile,
				metadata,
				quality,
				estimate,
				iteration_number,
			)
		return {"estimate": estimate, "quality": quality}

	retryer = Retrying(
		stop=stop_after_attempt(max(1, int(max_attempts))),
		retry=retry_if_result(lambda outcome: not outcome["quality"].is_valid),
		retry_error_callback=lambda retry_state: retry_state.outcome.result(),
		reraise=False,
	)
	last_outcome = retryer(estimate_once)
	last_estimate = last_outcome["estimate"]
	last_quality = last_outcome["quality"]

	if last_quality.is_valid:
		return _attach_quality_evidence(
			last_estimate,
			last_quality,
			iteration_history,
			"Converged on Quality Gates",
		)

	final_estimate = best_estimate or last_estimate
	final_quality = best_quality or last_quality
	logger.warning(
		"LexPoint estimate failed quality gates after %s attempt(s): %s",
		len(iteration_history),
		"; ".join(final_quality.defect_reasons),
	)
	return _attach_quality_evidence(
		final_estimate,
		final_quality,
		iteration_history,
		"Human Review Required - Quality Gates Not Met",
	)
