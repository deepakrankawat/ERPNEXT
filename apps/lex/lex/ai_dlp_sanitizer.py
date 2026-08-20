from __future__ import annotations

import re


# Regular expressions for PII and sensitive data minimization (AI-004)
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_REGEX = re.compile(r"\+?\d{1,4}?[-.\s]?\(?\d{1,3}?\)?[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}")
SSN_REGEX = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CREDIT_CARD_REGEX = re.compile(r"\b(?:\d[ -]*?){13,16}\b")


def sanitize_text_for_ai(text: str, redaction_flags: dict | None = None) -> tuple[str, dict]:
	"""Minimize and redact sensitive personal information before sending to external LLM boundary (AI-004)."""
	if not text:
		return "", {"redacted_items_count": 0}

	redacted_count = 0
	sanitized = text

	# Redact SSN
	sanitized, n = SSN_REGEX.subn("[REDACTED_SSN]", sanitized)
	redacted_count += n

	# Redact Credit Cards
	sanitized, n = CREDIT_CARD_REGEX.subn("[REDACTED_CARD]", sanitized)
	redacted_count += n

	# Redact Emails if flagged
	if not redaction_flags or redaction_flags.get("redact_email", True):
		sanitized, n = EMAIL_REGEX.subn("[REDACTED_EMAIL]", sanitized)
		redacted_count += n

	# Redact Phone Numbers if flagged
	if not redaction_flags or redaction_flags.get("redact_phone", True):
		sanitized, n = PHONE_REGEX.subn("[REDACTED_PHONE]", sanitized)
		redacted_count += n

	return sanitized, {"redacted_items_count": redacted_count, "was_modified": redacted_count > 0}
