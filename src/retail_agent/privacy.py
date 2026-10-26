"""Lightweight English contact-pattern checks, not comprehensive entity recognition.

Database privacy is enforced structurally by the query compiler. These patterns
catch common pasted contact details, not arbitrary names, addresses or obfuscation.
"""

import re

from retail_agent.models import AppError

_PATTERNS = (
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    r"\b\d{1,5}\s+[\w ]{1,40}\s(?:street|road|avenue|lane|drive|boulevard|court|st|rd|ave|blvd|ct)\b",
    r"(?<!\d)-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}",
    r"\b(?:my name|customer(?:'s)? name|email|address)\s*(?:is\s+|[:=]\s*)[^\n;]+",
    r"\b(?:postal code|zip code)\s*[:=]?\s*\w[\w -]{2,10}",
    # Formatting distinguishes these from unlabelled customer IDs, dates and revenue.
    r"(?<![\w\d])(?:\+1[ .-]?)?(?:\(\d{3}\)[ .-]?|\d{3}[ .-])\d{3}[ .-]\d{4}(?!\d)",
    r"\b(?:phone|telephone|mobile)(?:\s+number)?\s*(?:is\s+|[:=]\s*)\+?\d[\d () .-]{6,24}\d\b",
)
PII = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.IGNORECASE)
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u200b-\u200d\ufeff]")


def reject_personal_details(text: str) -> None:
    """Reject recognizable contact patterns in questions and new report titles."""
    if PII.search(CONTROL.sub("", text)):
        raise AppError(
            "Please remove personal details; ask using metrics or an internal user_id.",
            code="privacy_input",
        )


def safe_text(text: str, *, limit: int = 20_000) -> str:
    return PII.sub("[redacted]", CONTROL.sub("", text))[:limit]


def validate_question(text: str) -> str:
    if not text.strip() or len(text) > 4000:
        raise AppError("Please ask a retail analysis question of 1-4,000 characters.")
    reject_personal_details(text)
    return CONTROL.sub("", text)
