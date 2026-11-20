"""Validate scalar tool results and render values from evidence, not model arithmetic."""

import math
import re
from datetime import date, datetime
from decimal import Decimal

from retail_agent.models import AppError, QueryEvidence, Scalar
from retail_agent.privacy import safe_text

REFERENCE = re.compile(r"\{\{(E[0-9]+)\.r([0-9]+)\.([A-Za-z_][A-Za-z0-9_]*)(\|percent)?\}\}")
CITATION = re.compile(r"\[(E[0-9]+)\]")
CITATION_GROUP = re.compile(r"\[(E[0-9]+(?:\s*[,;]\s*E[0-9]+)+)\]")


def normalize_rows(
    rows: list[dict[str, object]], columns: tuple[str, ...]
) -> list[dict[str, Scalar]]:
    if len(rows) > 100:
        raise AppError(
            "Result exceeds 100 rows. Aggregate or request an explicit smaller ranking.",
            code="result_limit",
        )
    result: list[dict[str, Scalar]] = []
    for row in rows:
        if set(row) != set(columns):
            raise AppError("Unexpected query output was blocked.", code="result_schema")
        clean: dict[str, Scalar] = {}
        for key, value in row.items():
            if isinstance(value, (date, datetime)):
                value = value.isoformat()
            elif isinstance(value, Decimal):
                value = float(value)
            if (
                value is None
                or isinstance(value, (bool, int))
                or (isinstance(value, float) and math.isfinite(value))
            ):
                clean[key] = value
            elif isinstance(value, str):
                clean[key] = safe_text(value, limit=500)
            else:
                raise AppError(
                    "Unsupported or non-finite result value was blocked.", code="result_type"
                )
        result.append(clean)
    return result


def render_grounded_text(text: str, sources: dict[str, QueryEvidence]) -> str:
    if not text.strip() or len(text) > 16000:
        raise AppError("Provide a nonempty answer of at most 16000 characters.")
    # Common grouped citations are equivalent to individual citations. Canonicalize
    # them before digit validation and before saved-report citation rebasing.
    text = CITATION_GROUP.sub(
        lambda match: " ".join(f"[{key}]" for key in re.findall(r"E[0-9]+", match[1])), text
    )
    # Dates and quarter labels are context, not business measurements. All other
    # digits in prose must use evidence references so fabricated totals fail.
    remaining = REFERENCE.sub("", text)
    remaining = CITATION.sub("", remaining)
    # List ordinals and exact source labels (e.g. a product named "3-Pack")
    # are formatting/identifiers, not unsupported numerical measurements.
    remaining = re.sub(r"(?m)^\s{0,3}\d{1,3}[.)]\s+", "", remaining)
    labels = {
        value
        for item in sources.values()
        for row in item.rows
        for value in row.values()
        if isinstance(value, str) and re.search(r"[A-Za-z]", value) and re.search(r"\d", value)
    }
    for label in sorted(labels, key=len, reverse=True):
        remaining = re.sub(r"(?<!\w)" + re.escape(label) + r"(?!\w)", "", remaining)
    remaining = re.sub(r"\b\d{4}-\d{2}-\d{2}\b|\bQ[1-4]\b|\b20\d{2}\b", "", remaining)
    if re.search(r"\d", remaining):
        ungrounded = ", ".join(dict.fromkeys(re.findall(r"\d+(?:[.,]\d+)*%?", remaining)))[:120]
        raise AppError(
            f"Unreferenced numeric text: {ungrounded}. Use {{{{E1.r0.column}}}} for numerical claims, or {{{{E1.r0.share|percent}}}} for ratios. Tables are appended automatically; do not repeat their rows.",
            code="answer_grounding",
        )
    for evidence_id in CITATION.findall(text):
        if evidence_id not in sources:
            raise AppError("Answer cites unavailable evidence.", code="answer_grounding")

    def replace(match: re.Match[str]) -> str:
        evidence_id, index, column, percent = match.groups()
        evidence = sources.get(evidence_id)
        if (
            evidence is None
            or int(index) >= len(evidence.rows)
            or column not in evidence.rows[int(index)]
        ):
            raise AppError(
                "Answer references an unavailable evidence cell.", code="answer_grounding"
            )
        value = evidence.rows[int(index)][column]
        if value is None:
            return "undefined"
        if percent:
            if not isinstance(value, (float, int)) or isinstance(value, bool):
                raise AppError("Percent formatting requires a numeric evidence value.")
            return f"{value * 100:,.2f}%"
        if isinstance(value, float):
            return f"{value:,.6g}"
        return str(value)

    rendered = REFERENCE.sub(replace, text)
    if "{{" in rendered or "}}" in rendered:
        raise AppError("Malformed evidence reference.", code="answer_grounding")
    return safe_text(rendered, limit=24000)


def evidence_table(item: QueryEvidence) -> str:
    if not item.rows:
        return f"[{item.id}] No matching rows; no values inferred."
    columns = list(item.rows[0])

    def cell(value: Scalar) -> str:
        return ("undefined" if value is None else str(value)).replace("|", "\\|").replace("\n", " ")

    lines = [f"[{item.id}]", " | ".join(columns), " | ".join("---" for _ in columns)]
    lines.extend(" | ".join(cell(row[column]) for column in columns) for row in item.rows)
    return "\n".join(lines)
