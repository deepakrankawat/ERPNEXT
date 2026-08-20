from __future__ import annotations

import re
import frappe
from frappe import _


def verify_ai_citations(ai_output_text: str, source_text_corpus: str | list[str]) -> dict:
	"""Verify citations in AI output against accessible source document text (AI-009)."""
	if not ai_output_text:
		return {"verified": True, "total_citations": 0, "unsupported_citations": []}

	if isinstance(source_text_corpus, list):
		corpus_full = " ".join(source_text_corpus).lower()
	else:
		corpus_full = (source_text_corpus or "").lower()

	# Find potential citation patterns e.g. [Section X], [Doc X, Page Y], "quoted text"
	quotes = re.findall(r'"([^"]{10,})"', ai_output_text)
	brackets = re.findall(r"\[(Section [^\]]+|Doc [^\]]+|Page [^\]]+)\]", ai_output_text, re.IGNORECASE)

	unsupported = []
	for quote in quotes:
		if quote.lower() not in corpus_full:
			unsupported.append({"type": "quote", "text": quote, "reason": "Exact quote not found in source corpus"})

	for bracket in brackets:
		if bracket.lower() not in corpus_full:
			unsupported.append({"type": "reference", "text": bracket, "reason": "Reference marker not present in source metadata"})

	is_verified = len(unsupported) == 0

	return {
		"verified": is_verified,
		"total_quotes_checked": len(quotes),
		"total_references_checked": len(brackets),
		"unsupported_citations_count": len(unsupported),
		"unsupported_citations": unsupported,
	}
