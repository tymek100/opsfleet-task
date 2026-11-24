"""Contact-pattern screening; warehouse PII exclusion is structural in the gateway.

This is intentionally not represented as comprehensive named-entity detection.
"""

import re
from decimal import Decimal

COORDINATES = re.compile(r"(?<!\d)-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}")

CONTACT = re.compile(
    r"[\w.+-]+@[\w.-]+\.[a-z]{2,}"
    r"|\b(?:customer name|my name|email|address|phone|postal code|zip code)\s*(?:is\s+|[:=])[^\n;]+"
    r"|\b\d{1,5}\s+(?:[\w]+\s+){1,5}(?:street|road|avenue|lane|drive|st|rd|ave)\b"
    r"|"
    + COORDINATES.pattern
    + r"|(?<!\w)(?:\+\d{1,3}[ -]?)?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}\b",
    re.I,
)
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u200b-\u200d\ufeff]")


def screen(
    text: str, *, public_coordinates: frozenset[tuple[Decimal, Decimal]] = frozenset()
) -> str:
    text = CONTROL.sub("", text)
    for match in CONTACT.finditer(text):
        # Only the exact coordinate match can be exempted. Emails, phone numbers,
        # street addresses and contact-labelled text retain the strict boundary.
        value = match.group()
        if COORDINATES.fullmatch(value):
            latitude, longitude = (Decimal(part.strip()) for part in value.split(","))
            if (latitude, longitude) in public_coordinates:
                continue
        raise ValueError(
            "Please remove personal contact details; use internal customer IDs instead."
        )
    return text
