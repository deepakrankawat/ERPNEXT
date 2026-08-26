from __future__ import annotations

import io
import json
import math
import os
import re
from datetime import timedelta

import frappe
from frappe.utils import cint, flt, get_datetime, now_datetime


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
	"""Seed version 1 rules without overwriting management calibration."""
	if not frappe.db.exists("DocType", "LPO LexPoint Service Rule"):
		return
	if frappe.db.exists("DocType", "LexPack Settings"):
		frappe.db.set_single_value("LexPack Settings", "auto_approve_ai_pricing", 0)
	settings = frappe.get_single("LPO LexPoint Settings")
	if not settings.formula_version:
		settings.formula_version = "LEXPOINTS-1.0"
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
	remaining = max(0, len(files) - pdf_pages_known)
	if remaining:
		page_count += max(remaining, math.ceil(words / max(1, cint(settings.words_per_page or 500))))
	lower = (extracted or "").lower()
	return {
		"page_count": max(1, page_count),
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


def calculate_estimate(doc, files, extracted: str, ai_profile=None):
	metadata = collect_document_metadata(files, extracted)
	profile = normalize_profile(ai_profile or {}, doc, metadata, extracted)
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
	multipliers = {
		"complexity": flt(complexity.multiplier),
		"priority": _multiplier("Priority", priority),
		"jurisdiction": _multiplier("Jurisdiction", jurisdiction),
		"risk": _multiplier("Risk", risk),
		"reviewer": _multiplier("Reviewer Level", reviewer_level) if cint(settings.apply_reviewer_multiplier) else 1.0,
		"contingency": flt(settings.contingency_buffer or 1.05),
	}
	tasks = max(1, math.ceil(flt(task_count)))
	volume = max(0.01, flt(volume))
	billable_units = max(1, math.ceil(volume / flt(service.base_quantity)))
	base_total = tasks * billable_units * cint(service.base_lexpoints)
	raw = base_total
	for value in multipliers.values():
		raw *= value
	increment = max(1, cint(settings.rounding_increment or 1))
	lexpoints = max(cint(settings.minimum_charge or 10), int(math.ceil(raw / increment) * increment))
	effort = _effort(service, tasks, billable_units, complexity.factor_key, reviewer_level)
	delivery_hours = _delivery_hours(cint(service.default_sla_hours), priority)
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
		"multipliers": multipliers,
		"raw_lexpoints": round(raw, 4),
		"lexpoints": lexpoints,
		"delivery_hours": delivery_hours,
		"normal_sla_hours": cint(service.default_sla_hours),
		"fast_track_sla_hours": min(cint(service.default_sla_hours), 48),
		"express_sla_hours": min(cint(service.default_sla_hours), 24),
		"junior_hours": effort[0],
		"senior_hours": effort[1],
		"partner_hours": effort[2],
		"formula_version": settings.formula_version,
		"factor_breakdown": {
			"formula": "tasks × ceil(volume/base quantity) × base LP × complexity × priority × jurisdiction × risk × reviewer × contingency",
			"tasks": tasks, "volume": volume, "base_quantity": flt(service.base_quantity),
			"billable_units": billable_units, "base_lexpoints": cint(service.base_lexpoints),
			"base_total": base_total, "multipliers": multipliers, "unrounded_lexpoints": round(raw, 4),
			"minimum_charge": cint(settings.minimum_charge), "rounding_increment": increment,
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
	return [
		f"{profile['document_count']} document(s), {profile['page_count']} page(s), {profile['word_count']:,} extracted words",
		f"Classified as {profile['detected_document_type']} and routed to {profile['recommended_service']}",
		f"{profile['task_count']} task(s) × {profile['billable_units']} billable {profile['billing_measure']} unit(s) × {profile['base_lexpoints']} base LP",
		f"Complexity {profile['complexity_score']}/100 ({profile['complexity_classification']}), risk {profile['risk_level']}",
		f"Priority {profile['priority']}, jurisdiction {profile['jurisdiction']}, reviewer {profile['reviewer_level']}",
		f"Formula {profile['formula_version']} produced {profile['raw_lexpoints']:.2f} LP before governed upward rounding to {profile['lexpoints']} LP",
	]


def profile_json(profile):
	return json.dumps(profile, default=str, sort_keys=True, separators=(",", ":"))
