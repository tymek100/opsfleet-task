"""Minimize source data structurally; text checks are defense in depth, not DLP."""

import re

from retail_agent.models import AppError

_PATTERNS = (
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    r"\b\d{1,5}\s+[\w ]{1,40}\s(?:street|road|avenue|lane|drive|st|rd|ave)\b",
    r"(?<!\d)-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}",
    r"\b(?:my name is|customer name is|email is|address is)\s+[^\n;]+",
    r"\b(?:postal code|zip code)\s*[:=]?\s*\w[\w -]{2,10}",
)
PII = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.IGNORECASE)
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def safe_text(text: str, *, limit: int = 20_000) -> str:
    return CONTROL.sub("", PII.sub("[redacted]", text))[:limit]


def validate_question(text: str) -> str:
    if not text.strip() or len(text) > 4000:
        raise AppError("Please ask a retail analysis question of 1-4,000 characters.")
    if PII.search(text):
        raise AppError("Please remove personal details; ask using metrics or an internal user_id.")
    return CONTROL.sub("", text)
