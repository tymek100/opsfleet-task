"""Curated retail conversation dataset rows."""

from evaluation.reporting.foundry import ensure_rows

PROJECT_NAME = "retail-evaluation"
DATASET_NAME = "Retail agent - 20 conversations"


def dataset_rows(scenarios, references=None):
    return [
        {
            "input": {
                "case_id": case.id,
                "identity": case.identity,
                "question": case.prompt,
                "follow_up": case.follow_up,
            },
            "output": {
                "acceptance_criteria": case.checks,
                "reference_status": "Independently computed facts and behavioral criteria; model answers are not reference truth."
                if references
                else "Behavioral criteria; observed answers are not reference truth.",
                **(
                    {"turns": references["cases"][case.id], "provenance": references["provenance"]}
                    if references
                    else {}
                ),
            },
            "metadata": {
                "case_id": case.id,
                "intent": case.intent,
                "provenance": "assistant-authored, not production traffic",
                "oracle_topics": case.oracle_topics,
            },
        }
        for case in scenarios
    ]


def ensure_dataset(client, scenarios, references=None):
    return ensure_rows(client, DATASET_NAME, dataset_rows(scenarios, references))
