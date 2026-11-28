from evaluation.prompt_catalog import judge_prompt
from evaluation.settings import EvaluationSettings
from retail_insight.observability.prompts import sync_prompts
from retail_insight.runtime.prompts import analyst_prompt, reviewer_prompt


def test_snapshot_preserves_exact_instructions_without_a_remote_source(settings):
    specs = [analyst_prompt(settings), reviewer_prompt(settings), judge_prompt(EvaluationSettings(), "answer"), judge_prompt(EvaluationSettings(), "trajectory")]
    for spec, ref in zip(specs, sync_prompts(specs), strict=True):
        assert ref["instruction"] == spec.instruction
        assert ref["version_id"] == ref["sha256"] == spec.sha256
