from __future__ import annotations

import io
import json
import math
import os
import re
from datetime import timedelta

import frappe
from frappe.utils import cint, flt, get_datetime, now_datetime


CALIBRATED_FORMULA_VERSION = "LEXPOINTS-2.0-CAD"
CALIBRATED_QUOTE_CURRENCY = "CAD"
DEFAULT_RATE_PER_POINT_CAD = 3.0
STANDARD_HARD_CEILING_LEXPOINTS = 35
DRAFTING_HARD_CEILING_LEXPOINTS = 50


SERVICE_RULES = (
	("QUICK_LEGAL_QUERY", "Research", "Quick Legal Query", "pages", 5, 1, 18, 18, "72 hours", 72, "Focused answer with limited authorities", "legal question,quick query"),
	("CASE_LAW_RESEARCH", "Research", "Case Law Research", "pages", 10, 2, 18, 36, "3 business days", 72, "Research note and authority list", "case law,authorities,precedent search"),
	("LEGAL_RESEARCH_MEMO", "Research", "Legal Research Memo", "pages", 10, 4, 18, 72, "5 business days", 120, "Structured memo with citations", "research assignment,memorandum,legal memo"),
	("COMPARATIVE_LEGAL_RESEARCH", "Research", "Comparative Legal Research", "jurisdictions", 1, 5, 18, 90, "5 business days", 120, "Per additional jurisdiction", "multi-jurisdiction research,comparative law"),
	("REGULATORY_UPDATE", "Research", "Legislative / Regulatory Update", "topics", 1, 2, 18, 36, "3 business days", 72, "One defined topic", "legislative update,regulatory update"),
	("CHRONOLOGY_PREPARATION", "Litigation", "Chronology Preparation", "pages", 50, 4, 20, 80, "5 business days", 120, "Source record review and chronology", "chronology,timeline"),
	("ISSUE_MATRIX", "Litigation", "Issue Matrix", "pages", 50, 4, 20, 80, "5 business days", 120, "Issues, facts and authorities", "issue matrix,issues list"),
	("HEARING_SUMMARY", "Litigation", "Deposition / Hearing Summary", "pages", 100, 5, 20, 100, "5 business days", 120, "Concise or detailed summary", "deposition summary,hearing summary,court transcript"),
	("PLEADING_DRAFT_SUPPORT", "Litigation", "Pleading / Motion Draft Support", "pages", 20, 6, 20, 120, "5 business days", 120, "Draft support, not filing counsel", "statement of claim,motion,pleading,affidavit,legal notice"),
	("HEARING_BUNDLE", "Litigation", "Trial / Hearing Bundle Preparation", "documents", 100, 6, 20, 120, "5 business days", 120, "Indexing, pagination and bundle prep", "trial bundle,hearing bundle,evidence bundle"),
	("NDA_REVIEW", "Contracts", "NDA Review", "pages", 10, 1.5, 25, 38, "48 hours", 48, "Review with risk comments", "nda,non-disclosure agreement,confidentiality agreement"),
	("STANDARD_CONTRACT_REVIEW", "Contracts", "Standard Contract Review", "pages", 20, 3, 25, 75, "3 business days", 72, "Clause review and risk flags", "msa,employment agreement,share purchase agreement,asset purchase agreement,lease,agreement,contract review"),
	("CONTRACT_REDLINING", "Contracts", "Contract Redlining", "pages", 20, 4, 25, 100, "3 business days", 72, "Redline against instructions/playbook", "redline,contract negotiation"),
	("CONTRACT_DRAFTING", "Contracts", "Contract Drafting", "pages", 20, 5, 25, 125, "5 business days", 120, "First draft from approved brief", "agreement drafting,draft contract"),
	("CONTRACT_ABSTRACTION", "Contracts", "Contract Abstraction", "pages", 25, 2, 25, 50, "3 business days", 72, "Key fields and obligations", "contract abstraction,obligation extraction"),
	("CLM_ADMINISTRATION", "Contracts", "CLM Administration", "contracts", 25, 5, 25, 125, "Monthly", 720, "Repository, status and renewal support", "contract lifecycle management,clm"),
	("FIRST_LEVEL_REVIEW", "eDiscovery", "First-Level Document Review", "documents", 100, 5, 18, 90, "Batch SLA", 120, "Relevance and issue coding", "document review,discovery production,first level review"),
	("PRIVILEGE_REVIEW", "eDiscovery", "Privilege Review", "documents", 100, 7, 18, 126, "Batch SLA", 120, "Higher judgment and QC", "privilege,privileged documents"),
	("DOCUMENT_CODING", "eDiscovery", "Document Coding / Indexing", "documents", 100, 4, 18, 72, "Batch SLA", 120, "Objective coding and indexing", "document coding,indexing"),
	("SECOND_LEVEL_REVIEW", "eDiscovery", "Second-Level / QC Review", "documents", 100, 6, 18, 108, "Batch SLA", 120, "Quality review of first-level coding", "second level review,qc review"),
	("COMPLIANCE_RESEARCH", "Compliance", "Compliance Research", "pages", 10, 3, 25, 75, "3 business days", 72, "One defined compliance question", "compliance review,compliance question"),
	("POLICY_DRAFTING", "Compliance", "Policy Drafting", "policies", 1, 5, 25, 125, "5 business days", 120, "One standard policy", "privacy policy,compliance manual,policy"),
	("REGULATORY_GAP_ASSESSMENT", "Compliance", "Regulatory Gap Assessment", "business units", 1, 10, 25, 250, "10 business days", 240, "Defined framework and scope", "gap assessment,regulatory assessment,due diligence"),
	("PRIVACY_COMPLIANCE", "Compliance", "Privacy Compliance Review", "business units", 1, 12, 25, 300, "10 business days", 240, "PIPEDA/GDPR or agreed framework", "privacy review,gdp,gdpr,pipeda"),
	("RISK_REGISTER", "Compliance", "Risk Register Preparation", "business units", 1, 8, 25, 200, "7 business days", 168, "Initial risk register", "risk register"),
	("VIRTUAL_PARALEGAL", "Operations", "Virtual Paralegal Support", "hours", 1, 1, 13, 13, "As agreed", 72, "General paralegal capacity", "paralegal,operations support"),
	("DOCUMENT_FORMATTING", "Operations", "Document Formatting", "pages", 25, 1, 13, 13, "48 hours", 48, "Formatting and style correction", "formatting,style correction"),
	("MATTER_FILE_ORGANISATION", "Operations", "Matter File Organisation", "documents", 100, 3, 13, 39, "3 business days", 72, "Foldering, naming and indexing", "file organisation,file organization"),
	("CLIENT_INTAKE_SUPPORT", "Operations", "Client Intake Support", "matters", 10, 3, 13, 39, "Weekly", 168, "Forms, checks and matter setup", "intake support,matter setup"),
	("CALENDAR_SUPPORT", "Operations", "Calendar / Docket Support", "matters", 25, 5, 13, 65, "Monthly", 720, "Routine docket and reminder support", "docket,calendar support"),
)

MULTIPLIER_RULES = (
	("Complexity", "Routine", 1.0, 1, 25),
	("Complexity", "Moderate", 1.25, 26, 50),
	("Complexity", "Complex", 1.6, 51, 75),
	("Complexity", "Specialist", 2.1, 76, 100),
	("Priority", "Standard", 1.0, None, None),
	("Priority", "72 Hours", 1.15, None, None),
	("Priority", "48 Hours", 1.35, None, None),
	("Priority", "24 Hours", 1.75, None, None),
	("Priority", "Same Day", 2.5, None, None),
	("Jurisdiction", "India", 1.0, None, None),
	("Jurisdiction", "Canada", 1.1, None, None),
	("Jurisdiction", "United Kingdom", 1.15, None, None),
	("Jurisdiction", "United States", 1.25, None, None),
	("Jurisdiction", "Multi-Jurisdiction", 1.5, None, None),
	("Risk", "Low", 1.0, None, None),
	("Risk", "Medium", 1.15, None, None),
	("Risk", "High", 1.4, None, None),
	("Risk", "Critical", 1.8, None, None),
	# Reviewer pricing is wired but neutral until Lexocrates approves calibrated commercial factors.
	("Reviewer Level", "Junior Associate", 1.0, None, None),
	("Reviewer Level", "Senior Associate", 1.0, None, None),
	("Reviewer Level", "Subject Matter Expert", 1.0, None, None),
	("Reviewer Level", "Partner", 1.0, None, None),
	("Reviewer Level", "Mixed Team", 1.0, None, None),
)

DEFAULT_SERVICE_BY_INTAKE = {
	"Contract Review": "Standard Contract Review",
	"Legal Research": "Legal Research Memo",
	"Document Review": "First-Level Document Review",
	"Due Diligence": "Regulatory Gap Assessment",
	"Compliance Review": "Compliance Research",
	"Litigation Support": "Pleading / Motion Draft Support",
	"Drafting": "Contract Drafting",
	"Summarization": "Deposition / Hearing Summary",
	"Other": "Virtual Paralegal Support",
}


def ensure_default_lexpoint_rules():
	"""Seed governed rules without overwriting management calibration."""
	if not frappe.db.exists("DocType", "LPO LexPoint Service Rule"):
		return
	ensure_calibrated_estimation_settings()
	if frappe.db.exists("DocType", "LexPack Settings"):
		frappe.db.set_single_value("LexPack Settings", "auto_approve_ai_pricing", 0)
	settings = frappe.get_single("LPO LexPoint Settings")
	if not settings.formula_version:
		settings.formula_version = CALIBRATED_FORMULA_VERSION
		settings.save(ignore_permissions=True)
	for code, family, name, measure, quantity, hours, midpoint, points, sla, sla_hours, notes, aliases in SERVICE_RULES:
		if frappe.db.exists("LPO LexPoint Service Rule", code):
			continue
		frappe.get_doc({
			"doctype": "LPO LexPoint Service Rule", "service_code": code, "service_family": family,
			"service_name": name, "billing_measure": measure, "base_quantity": quantity,
			"standard_hours": hours, "market_midpoint_per_hour": midpoint, "base_lexpoints": points,
			"default_sla_label": sla, "default_sla_hours": sla_hours, "notes": notes,
			"aliases": aliases, "active": 1,
		}).insert(ignore_permissions=True)
	if not frappe.db.exists("DocType", "LPO LexPoint Multiplier"):
		return
	for factor_type, factor_key, multiplier, minimum, maximum in MULTIPLIER_RULES:
		rule_key = f"{frappe.scrub(factor_type)}__{frappe.scrub(factor_key)}".upper()
		if frappe.db.exists("LPO LexPoint Multiplier", rule_key):
			continue
		frappe.get_doc({
			"doctype": "LPO LexPoint Multiplier", "rule_key": rule_key, "factor_type": factor_type,
			"factor_key": factor_key, "multiplier": multiplier, "minimum_score": minimum,
			"maximum_score": maximum, "active": 1,
		}).insert(ignore_permissions=True)
	frappe.clear_cache()


def ensure_calibrated_estimation_settings():
	"""Migrate untouched legacy defaults to the approved CAD calibration."""

	if frappe.db.exists("DocType", "LPO LexPoint Settings"):
		formula_version = frappe.db.get_single_value("LPO LexPoint Settings", "formula_version")
		if formula_version in {None, "", "LEXPOINTS-1.0"}:
			frappe.db.set_single_value(
				"LPO LexPoint Settings", "formula_version", CALIBRATED_FORMULA_VERSION
			)
		words_per_page = cint(
			frappe.db.get_single_value("LPO LexPoint Settings", "words_per_page") or 0
		)
		if words_per_page in {0, 500}:
			frappe.db.set_single_value("LPO LexPoint Settings", "words_per_page", 350)

	if not frappe.db.exists("DocType", "LexPack Settings"):
		return
	quote_currency = frappe.db.get_single_value("LexPack Settings", "quote_currency")
	rate_per_point = flt(
		frappe.db.get_single_value("LexPack Settings", "direct_quote_rate_per_point")
		or DEFAULT_RATE_PER_POINT_CAD
	)
	# Only migrate the untouched legacy USD/$3 default. Explicitly calibrated
	# custom rates/currencies remain management-controlled.
	legacy_default = quote_currency in {None, ""} or (
		quote_currency == "USD" and rate_per_point == DEFAULT_RATE_PER_POINT_CAD
	)
	if legacy_default and frappe.db.exists("Currency", CALIBRATED_QUOTE_CURRENCY):
		frappe.db.set_single_value(
			"LexPack Settings", "quote_currency", CALIBRATED_QUOTE_CURRENCY
		)
	frappe.clear_cache(doctype="LexPack Settings")


def collect_document_metadata(files, extracted: str):
	page_count = 0
	total_bytes = 0
	pdf_pages_known = 0
	for row in files:
		total_bytes += cint(row.get("file_size"))
		if os.path.splitext((row.get("file_name") or "").lower())[1] != ".pdf":
			continue
		try:
			from pypdf import PdfReader

			content = frappe.get_doc("File", row.get("name")).get_content()
			if isinstance(content, str):
				content = content.encode()
			pages = len(PdfReader(io.BytesIO(content)).pages)
			page_count += pages
			pdf_pages_known += 1
		except Exception:
			pass
	settings = frappe.get_single("LPO LexPoint Settings")
	words = len((extracted or "").split())
	# Canadian legal standard density: 350 words per billable page
	density_wpp = cint(settings.words_per_page or 350)
	if density_wpp > 400:
		density_wpp = 350
	effective_pages = max(1, page_count, math.ceil(words / max(1, density_wpp)))
	lower = (extracted or "").lower()
	return {
		"page_count": max(1, effective_pages),
		"physical_pages": max(1, page_count),
		"effective_pages": max(1, effective_pages),
		"word_count": words,
		"character_count": len(extracted or ""),
		"file_size_bytes": total_bytes,
		"document_count": len(files),
		"primary_language": _language_hint(extracted),
		"ocr_quality": "Good" if words >= max(40, page_count * 20) else "Low",
		"content_form": "Typed" if extracted.strip() else "Unknown",
		"has_tables": int(bool(re.search(r"\|.+\||\btable\b", lower))),
		"has_images": 0,
		"has_signatures": int(bool(re.search(r"\bsignature|signed by|in witness whereof\b", lower))),
		"has_annexures": int(bool(re.search(r"\bannex(?:ure)?|schedule|exhibit|appendix\b", lower))),
	}


def calculate_estimate(doc, files, extracted: str, ai_profile=None, auto_converge: bool = True):
	if auto_converge:
		from lex.iterative_estimator import run_iterative_estimation

		return run_iterative_estimation(doc, files, extracted, initial_profile=ai_profile)

	metadata = collect_document_metadata(files, extracted)
	profile = normalize_profile(ai_profile or {}, doc, metadata, extracted)
	profile["classification_source"] = "AI" if ai_profile is not None else "Deterministic Formula"
	calculation = calculate_from_factors(
		service_name=profile["recommended_service"],
		task_count=profile["task_count"],
		volume=profile["volume"],
		complexity_score=profile["complexity_score"],
		priority=profile["priority"],
		jurisdiction=profile["jurisdiction"],
		risk=profile["risk_level"],
		reviewer_level=profile["reviewer_level"],
	)
	profile.update(calculation)
	for key in ("page_count", "word_count", "character_count", "file_size_bytes", "document_count"):
		profile[key] = metadata[key]
	profile["expected_completion"] = now_datetime() + timedelta(hours=cint(profile["delivery_hours"]))
	profile["explanation_factors"] = _explanation(profile)
	profile["explanation"] = "; ".join(profile["explanation_factors"])
	return profile


def calculate_from_factors(
	*, service_name: str, task_count: float, volume: float, complexity_score: int,
	priority: str, jurisdiction: str, risk: str, reviewer_level: str,
):
	service = _service_rule(service_name)
	if not service:
		raise frappe.ValidationError(f"No active LexPoint Service Rule exists for {service_name}.")
	settings = frappe.get_single("LPO LexPoint Settings")
	complexity = _complexity_rule(complexity_score)
	priority = _factor_key("Priority", priority, "Standard")
	jurisdiction = _factor_key("Jurisdiction", jurisdiction, "Multi-Jurisdiction")
	risk = _factor_key("Risk", risk, "Medium")
	reviewer_level = _factor_key("Reviewer Level", reviewer_level, "Mixed Team")

	# Additive Surcharges (Replaces runaway exponential multiplication)
	complexity_surcharges = {
		"Routine": 0.0,
		"Moderate": 0.15,
		"Complex": 0.35,
		"Specialist": 0.60,
	}
	priority_surcharges = {
		"Standard": 0.0,
		"72 Hours": 0.15,
		"48 Hours": 0.25,
		"24 Hours": 0.45,
		"Same Day": 0.75,
	}
	jurisdiction_surcharges = {
		"India": 0.0,
		"Canada": 0.10,
		"United Kingdom": 0.15,
		"United States": 0.20,
		"Multi-Jurisdiction": 0.35,
	}
	risk_surcharges = {
		"Low": 0.0,
		"Medium": 0.10,
		"High": 0.20,
		"Critical": 0.35,
	}

	s_comp = complexity_surcharges.get(complexity.factor_key, 0.15)
	s_prio = priority_surcharges.get(priority, 0.0)
	s_juris = jurisdiction_surcharges.get(jurisdiction, 0.10)
	s_risk = risk_surcharges.get(risk, 0.10)
	s_rev = (
		(_multiplier("Reviewer Level", reviewer_level) - 1.0)
		if cint(settings.apply_reviewer_multiplier)
		else 0.0
	)
	combined_surcharge = round(1.0 + s_comp + s_prio + s_juris + s_risk + s_rev, 4)
	contingency = flt(settings.contingency_buffer or 1.05)

	tasks = max(1, math.ceil(flt(task_count)))

	# 1. Bulk Volume Tapering (Diminishing marginal workload for large document bundles)
	base_qty = flt(service.base_quantity)
	if volume <= base_qty:
		billable_units = 1.0
	else:
		excess = volume - base_qty
		billable_units = round(1.0 + (math.log2(1.0 + excess / base_qty) * 0.40), 3)

	# 2. AI-Assisted Operational Efficiency Factor (0.16x)
	# AI performs 90% of structural indexing and optical reading, reducing lawyer effort by ~80%
	ai_operational_factor = 0.16
	effective_base_lp = flt(service.base_lexpoints) * ai_operational_factor
	base_total = tasks * billable_units * effective_base_lp

	# Raw LexPoints computed via governed additive model
	raw = base_total * combined_surcharge * contingency
	increment = max(1, cint(settings.rounding_increment or 1))
	rounded_raw = int(math.ceil(raw / increment) * increment)

	effort = _effort(service, tasks, billable_units, complexity.factor_key, reviewer_level)
	# Human review effort under AI augmentation (hours)
	junior_hours = round(effort[0] * 0.25, 2)
	senior_hours = round(effort[1] * 0.25, 2)
	partner_hours = round(effort[2] * 0.25, 2)
	delivery_hours = _delivery_hours(cint(service.default_sla_hours), priority)

	# --- THE GOLDEN CORRIDOR: Ultra-Affordable Floor & Ceiling ---
	rate_per_point = flt(
		frappe.db.get_single_value("LexPack Settings", "direct_quote_rate_per_point")
		or DEFAULT_RATE_PER_POINT_CAD
	)
	quote_currency = (
		frappe.db.get_single_value("LexPack Settings", "quote_currency")
		or CALIBRATED_QUOTE_CURRENCY
	)
	if quote_currency != CALIBRATED_QUOTE_CURRENCY:
		raise frappe.ValidationError(
			"The calibrated LexPoint estimator requires quote currency CAD because its "
			"cost floor and Canadian benchmark are denominated in CAD."
		)

	# 1. Company Floor: internal delivery cost with guaranteed >= 60% gross margin
	# (Offshore Associate @ $6 CAD/hr, Senior QC @ $12 CAD/hr, Partner @ $25 CAD/hr, Tech/Token @ $1.5 CAD)
	internal_delivery_cost = round(
		(junior_hours * 6.0) + (senior_hours * 12.0) + (partner_hours * 25.0) + 1.5,
		2,
	)
	target_margin_floor = 0.60
	floor_amount_cad = round(internal_delivery_cost / (1.0 - target_margin_floor), 2)
	floor_lexpoints = max(cint(settings.minimum_charge or 10), int(math.ceil(floor_amount_cad / rate_per_point)))

	# 2. Client Ceiling: fixed at 35 LP for standard review/analysis and
	# 50 LP for pleading/drafting. If the modeled cost floor exceeds this cap,
	# the engine fails closed for custom scoping instead of silently raising it.
	service_identifier = f"{service.name} {service.service_name}".lower()
	ceiling_lexpoints = (
		DRAFTING_HARD_CEILING_LEXPOINTS
		if "pleading" in service_identifier or "draft" in service_identifier
		else STANDARD_HARD_CEILING_LEXPOINTS
	)
	corridor_feasible = floor_lexpoints <= ceiling_lexpoints
	custom_scope_required = not corridor_feasible

	# 3. Final Clamping within the hard corridor. A cap-conflict result is a
	# non-releasable preview and is forced to Operations review by the QA layer.
	lexpoints = (
		max(floor_lexpoints, min(rounded_raw, ceiling_lexpoints))
		if corridor_feasible
		else ceiling_lexpoints
	)
	quoted_price_cad = round(lexpoints * rate_per_point, 2)
	canadian_firm_hourly_tariff = 325.0
	standard_total_hours = flt(service.standard_hours) * tasks * max(1, math.ceil(volume / base_qty))
	canadian_market_benchmark_cad = round(standard_total_hours * canadian_firm_hourly_tariff, 2)
	client_savings_cad = max(0.0, round(canadian_market_benchmark_cad - quoted_price_cad, 2))
	client_savings_percent = (
		round((client_savings_cad / canadian_market_benchmark_cad) * 100, 1)
		if canadian_market_benchmark_cad
		else 0.0
	)
	gross_margin_percent = (
		round(((quoted_price_cad - internal_delivery_cost) / quoted_price_cad) * 100, 1)
		if quoted_price_cad
		else 0.0
	)

	# 4. Multi-tier Package Options for Client. No standard package is offered
	# when the cost floor and hard cap cannot both be satisfied.
	tier_options = {
		"essential": {
			"tier_code": "ESSENTIAL",
			"tier_name": "Essential Redline",
			"lexpoints": max(floor_lexpoints, int(math.ceil(lexpoints * 0.75))),
			"amount_cad": round(max(floor_lexpoints, int(math.ceil(lexpoints * 0.75))) * rate_per_point, 2),
			"sla_hours": delivery_hours,
			"scope_summary": "Core clause markup, critical legal issue spotting, and marked-up draft.",
		},
		"standard": {
			"tier_code": "STANDARD",
			"tier_name": "Standard Governed Review",
			"lexpoints": lexpoints,
			"amount_cad": quoted_price_cad,
			"sla_hours": delivery_hours,
			"scope_summary": "Full clause analysis, redline, Canadian compliance check, and risk matrix.",
			"is_recommended": True,
		},
		"deep_dive": {
			"tier_code": "DEEP_DIVE",
			"tier_name": "Comprehensive & Negotiation Playbook",
			"lexpoints": min(ceiling_lexpoints, int(math.ceil(lexpoints * 1.35))),
			"amount_cad": round(min(ceiling_lexpoints, int(math.ceil(lexpoints * 1.35))) * rate_per_point, 2),
			"sla_hours": delivery_hours + 24,
			"scope_summary": "Deep redline, negotiation playbook, alternative fallback clauses, and senior counsel call.",
		},
	} if corridor_feasible else {}

	return {
		"service_code": service.name,
		"service_family": service.service_family,
		"recommended_service": service.service_name,
		"billing_measure": service.billing_measure,
		"base_quantity": flt(service.base_quantity),
		"base_lexpoints": cint(service.base_lexpoints),
		"billable_units": billable_units,
		"task_count": tasks,
		"volume": volume,
		"complexity_classification": complexity.factor_key,
		"priority": priority,
		"jurisdiction": jurisdiction,
		"risk_level": risk,
		"reviewer_level": reviewer_level,
		"multipliers": {
			"complexity": round(1.0 + s_comp, 2),
			"priority": round(1.0 + s_prio, 2),
			"jurisdiction": round(1.0 + s_juris, 2),
			"risk": round(1.0 + s_risk, 2),
			"combined_surcharge": combined_surcharge,
			"contingency": contingency,
		},
		"raw_lexpoints": round(raw, 4),
		"lexpoints": lexpoints,
		"delivery_hours": delivery_hours,
		"normal_sla_hours": cint(service.default_sla_hours),
		"fast_track_sla_hours": min(cint(service.default_sla_hours), 48),
		"express_sla_hours": min(cint(service.default_sla_hours), 24),
		"junior_hours": junior_hours,
		"senior_hours": senior_hours,
		"partner_hours": partner_hours,
		"formula_version": settings.formula_version,
		"currency": quote_currency,
		"canadian_market_benchmark_cad": canadian_market_benchmark_cad,
		"internal_delivery_cost_cad": internal_delivery_cost,
		"quoted_price_cad": quoted_price_cad,
		"client_savings_cad": client_savings_cad,
		"client_savings_percent": client_savings_percent,
		"gross_margin_percent": gross_margin_percent,
		"floor_lexpoints": floor_lexpoints,
		"ceiling_lexpoints": ceiling_lexpoints,
		"corridor_feasible": corridor_feasible,
		"custom_scope_required": custom_scope_required,
		"required_floor_lexpoints": floor_lexpoints,
		"tier_options": tier_options,
		"factor_breakdown": {
			"formula": "base LP x (1.0 + sum(surcharges)) x contingency [clamped between floor and hard ceiling]",
			"tasks": tasks,
			"volume": volume,
			"base_quantity": flt(service.base_quantity),
			"billable_units": billable_units,
			"base_lexpoints": cint(service.base_lexpoints),
			"base_total": base_total,
			"combined_surcharge": combined_surcharge,
			"surcharges": {
				"complexity": s_comp,
				"priority": s_prio,
				"jurisdiction": s_juris,
				"risk": s_risk,
			},
			"unrounded_lexpoints": round(raw, 4),
			"floor_lexpoints": floor_lexpoints,
			"ceiling_lexpoints": ceiling_lexpoints,
			"corridor_feasible": corridor_feasible,
			"custom_scope_required": custom_scope_required,
			"minimum_charge": cint(settings.minimum_charge),
			"rounding_increment": increment,
			"currency": quote_currency,
			"canadian_market_benchmark_cad": canadian_market_benchmark_cad,
			"client_savings_percent": client_savings_percent,
			"gross_margin_percent": gross_margin_percent,
		},
	}


def normalize_profile(profile, doc, metadata, extracted):
	service = _resolve_service(profile, doc, extracted)
	complexity_score = max(1, min(100, cint(profile.get("complexity_score") or _fallback_complexity(metadata, extracted))))
	reviewer = str(profile.get("reviewer_level") or _reviewer_for_score(complexity_score)).strip()
	jurisdiction = _normalize_jurisdiction(profile.get("jurisdiction") or doc.jurisdiction)
	priority = _priority_bucket(doc)
	risk = str(profile.get("risk_level") or _fallback_risk(extracted)).title()
	measure = service.billing_measure
	volume = flt(profile.get("volume") or _volume_for_measure(measure, metadata, profile))
	confidence = max(0, min(100, flt(profile.get("confidence") or profile.get("overall_confidence") or 70)))
	needs_review = cint(profile.get("requires_human_review"))
	if not profile and doc.service_type in {"Due Diligence", "Litigation Support", "Summarization", "Other"}:
		# The supplied catalogue has no unambiguous one-to-one rule for these broad intake labels.
		needs_review = 1
	return {
		"detected_document_type": str(profile.get("document_type") or _document_type_hint(extracted))[:140],
		"document_type_confidence": max(0, min(100, flt(profile.get("document_type_confidence") or confidence))),
		"alternative_matches": profile.get("alternative_matches") or [],
		"practice_module": ", ".join(profile.get("practice_modules") or [service.service_family]),
		"recommended_service": service.service_name,
		"legal_domain": str(profile.get("legal_domain") or doc.service_type)[:140],
		"jurisdiction": jurisdiction,
		"detected_jurisdiction": str(profile.get("jurisdiction") or doc.jurisdiction)[:140],
		"jurisdiction_confidence": max(0, min(100, flt(profile.get("jurisdiction_confidence") or confidence))),
		"complexity_score": complexity_score,
		"risk_level": risk,
		"reviewer_level": reviewer,
		"priority": priority,
		"volume": max(0.01, volume),
		"task_count": max(1, flt(profile.get("task_count") or 1)),
		"confidence": confidence,
		"requires_human_review": needs_review,
		"ai_execution": profile.get("ai_execution"),
		"primary_language": str(profile.get("language") or metadata["primary_language"])[:140],
		"ocr_quality": str(profile.get("ocr_quality") or metadata["ocr_quality"])[:140],
		"content_form": str(profile.get("content_form") or metadata["content_form"])[:140],
		"has_tables": cint(profile.get("has_tables", metadata["has_tables"])),
		"has_images": cint(profile.get("has_images", metadata["has_images"])),
		"has_signatures": cint(profile.get("has_signatures", metadata["has_signatures"])),
		"has_annexures": cint(profile.get("has_annexures", metadata["has_annexures"])),
	}


def _service_rule(service_name):
	name = frappe.db.get_value("LPO LexPoint Service Rule", {"service_name": service_name, "active": 1}, "name")
	return frappe.get_doc("LPO LexPoint Service Rule", name) if name else None


def _resolve_service(profile, doc, extracted):
	candidates = [profile.get("recommended_service"), profile.get("document_type")]
	lower = (extracted or "").lower()
	rules = frappe.get_all(
		"LPO LexPoint Service Rule", filters={"active": 1},
		fields=["name", "service_name", "service_family", "aliases", "billing_measure"], limit_page_length=100,
	)
	for candidate in filter(None, candidates):
		candidate = str(candidate).strip().lower()
		for rule in rules:
			aliases = [item.strip().lower() for item in re.split(r"[,\n]", rule.aliases or "") if item.strip()]
			if candidate == rule.service_name.lower() or candidate in aliases:
				return frappe.get_doc("LPO LexPoint Service Rule", rule.name)
	for rule in rules:
		aliases = [item.strip().lower() for item in re.split(r"[,\n]", rule.aliases or "") if item.strip()]
		if any(re.search(rf"\b{re.escape(alias)}\b", lower) for alias in aliases if len(alias) >= 3):
			return frappe.get_doc("LPO LexPoint Service Rule", rule.name)
	return _service_rule(DEFAULT_SERVICE_BY_INTAKE.get(doc.service_type, "Virtual Paralegal Support"))


def _complexity_rule(score):
	rules = frappe.get_all(
		"LPO LexPoint Multiplier", filters={"factor_type": "Complexity", "active": 1},
		fields=["name", "factor_key", "multiplier", "minimum_score", "maximum_score"], order_by="minimum_score asc",
	)
	for rule in rules:
		if cint(rule.minimum_score) <= cint(score) <= cint(rule.maximum_score):
			return rule
	raise frappe.ValidationError(f"No active complexity multiplier covers score {score}.")


def _multiplier(factor_type, factor_key):
	value = frappe.db.get_value(
		"LPO LexPoint Multiplier", {"factor_type": factor_type, "factor_key": factor_key, "active": 1}, "multiplier"
	)
	if value is None:
		raise frappe.ValidationError(f"Missing active {factor_type} multiplier for {factor_key}.")
	return flt(value)


def _factor_key(factor_type, proposed, fallback):
	keys = frappe.get_all(
		"LPO LexPoint Multiplier", filters={"factor_type": factor_type, "active": 1}, pluck="factor_key"
	)
	for key in keys:
		if str(key).lower() == str(proposed or "").strip().lower():
			return key
	return fallback


def _priority_bucket(doc):
	if doc.requested_delivery_date:
		hours = (get_datetime(doc.requested_delivery_date) - now_datetime()).total_seconds() / 3600
		if hours <= 12:
			return "Same Day"
		if hours <= 24:
			return "24 Hours"
		if hours <= 48:
			return "48 Hours"
		if hours <= 72:
			return "72 Hours"
	return {"Urgent": "24 Hours", "High": "72 Hours", "Medium": "Standard", "Low": "Standard"}.get(doc.priority, "Standard")


def _normalize_jurisdiction(value):
	value = str(value or "").strip()
	if re.search(r"[,;/]|\band\b", value, re.I):
		return "Multi-Jurisdiction"
	aliases = {
		"india": "India", "canada": "Canada", "united kingdom": "United Kingdom", "uk": "United Kingdom",
		"england": "United Kingdom", "united states": "United States", "usa": "United States", "us": "United States",
		"multi-jurisdiction": "Multi-Jurisdiction", "multi jurisdiction": "Multi-Jurisdiction",
	}
	return aliases.get(value.lower(), "Multi-Jurisdiction")


def _volume_for_measure(measure, metadata, profile):
	if measure == "pages":
		return metadata["page_count"]
	if measure == "documents":
		return metadata["document_count"]
	if measure == "hours":
		return flt(profile.get("estimated_hours") or 1)
	if measure == "jurisdictions":
		return max(1, len(re.split(r"[,;/]", str(profile.get("jurisdiction") or ""))))
	if measure in {"contracts", "policies", "evidence records"}:
		return metadata["document_count"]
	return 1


def _fallback_complexity(metadata, extracted):
	score = 12 + min(28, math.ceil(metadata["word_count"] / 1000) * 2) + min(15, max(0, metadata["document_count"] - 1) * 3)
	lower = (extracted or "").lower()
	markers = (
		"cross-border", "regulatory", "indemnity", "limitation of liability", "arbitration", "tax",
		"intellectual property", "change of control", "data protection", "sanctions", "competition law", "schedule",
	)
	score += min(30, sum(3 for marker in markers if marker in lower))
	return max(1, min(100, score))


def _fallback_risk(extracted):
	lower = (extracted or "").lower()
	critical = ("criminal", "injunction", "sanctions breach", "regulatory enforcement")
	high = ("indemnity", "unlimited liability", "data breach", "termination for cause", "litigation")
	if any(marker in lower for marker in critical):
		return "Critical"
	if any(marker in lower for marker in high):
		return "High"
	return "Medium"


def _document_type_hint(extracted):
	lower = (extracted or "").lower()
	for marker, label in (
		("non-disclosure", "NDA"), ("master services agreement", "MSA"), ("share purchase agreement", "Share Purchase Agreement"),
		("statement of claim", "Statement of Claim"), ("affidavit", "Affidavit"), ("privacy policy", "Privacy Policy"),
		("memorandum", "Memorandum"), ("agreement", "Agreement"),
	):
		if marker in lower:
			return label
	return "Unclassified Legal Document"


def _reviewer_for_score(score):
	if score >= 76:
		return "Subject Matter Expert"
	if score >= 51:
		return "Senior Associate"
	return "Junior Associate"


def _effort(service, tasks, units, complexity, reviewer):
	total = flt(service.standard_hours) * tasks * units
	total *= {"Routine": 1.0, "Moderate": 1.15, "Complex": 1.35, "Specialist": 1.6}.get(complexity, 1.0)
	shares = {
		"Junior Associate": (0.85, 0.15, 0), "Senior Associate": (0.6, 0.4, 0),
		"Subject Matter Expert": (0.5, 0.4, 0.1), "Partner": (0.4, 0.35, 0.25), "Mixed Team": (0.55, 0.35, 0.1),
	}.get(reviewer, (0.55, 0.35, 0.1))
	return tuple(round(total * share, 2) for share in shares)


def _delivery_hours(normal_hours, priority):
	return min(max(8, cint(normal_hours)), {"Standard": normal_hours, "72 Hours": 72, "48 Hours": 48, "24 Hours": 24, "Same Day": 8}.get(priority, normal_hours))


def _language_hint(text):
	if not text:
		return "Unknown"
	letters = [char for char in text[:10000] if char.isalpha()]
	if letters and sum(ord(char) < 128 for char in letters) / len(letters) > 0.9:
		return "English"
	return "Needs Detection"


def _explanation(profile):
	factors = [
		f"{profile['document_count']} document(s), {profile['page_count']} effective page(s) ({profile.get('physical_pages', profile['page_count'])} physical), {profile['word_count']:,} extracted words",
		f"Classified as {profile['detected_document_type']} and routed to {profile['recommended_service']}",
		f"{profile['task_count']} task(s) x {profile['billable_units']} billable {profile['billing_measure']} unit(s) x {profile['base_lexpoints']} base LP",
		f"Complexity {profile['complexity_score']}/100 ({profile['complexity_classification']}), risk {profile['risk_level']}",
		f"Priority {profile['priority']}, jurisdiction {profile['jurisdiction']}, reviewer {profile['reviewer_level']}",
		f"Governed Additive Model: {profile['lexpoints']} LP (${profile.get('quoted_price_cad', profile['lexpoints'] * 3):,.2f} CAD)",
	]
	if profile.get("canadian_market_benchmark_cad"):
		factors.append(
			f"Canadian Law Firm Benchmark: ~${profile['canadian_market_benchmark_cad']:,.2f} CAD; Guaranteed Client Savings: {profile.get('client_savings_percent', 0)}% (Floor: {profile.get('floor_lexpoints', 10)} LP, Ceiling Cap: {profile.get('ceiling_lexpoints', 100)} LP)"
		)
	return factors


def profile_json(profile):
	return json.dumps(profile, default=str, sort_keys=True, separators=(",", ":"))
