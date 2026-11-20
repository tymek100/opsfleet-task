"""Contact-pattern screening; warehouse PII exclusion is structural in the gateway.

This is intentionally not represented as comprehensive named-entity detection.
"""

import re

CONTACT = re.compile(
    r"[\w.+-]+@[\w.-]+\.[a-z]{2,}"
    r"|\b(?:customer name|my name|email|address|phone|postal code|zip code)\s*(?:is\s+|[:=])[^\n;]+"
    r"|\b\d{1,5}\s+(?:[\w]+\s+){1,5}(?:street|road|avenue|lane|drive|st|rd|ave)\b"
    r"|(?<!\d)-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}"
    r"|(?<!\w)(?:\+\d{1,3}[ -]?)?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}\b",
    re.I,
)
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u200b-\u200d\ufeff]")


def screen(text: str) -> str:
    text = CONTROL.sub("", text)
    if CONTACT.search(text):
        raise ValueError(
            "Please remove personal contact details; use internal customer IDs instead."
        )
    return text
