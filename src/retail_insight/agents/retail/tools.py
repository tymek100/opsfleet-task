"""Explicit registration of the analyst's model-callable capabilities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from retail_insight.review.completion import CompletionTools
from retail_insight.tools.analytics import DataTools
from retail_insight.tools.knowledge import KnowledgeTools
from retail_insight.tools.reports import ReportTools
from retail_insight.tools.skills import SkillTools

if TYPE_CHECKING:
    from retail_insight.runtime.turn import Turn


def build_tools(turn: Turn) -> list:
    """Bind domain tools to one shared question state and accounting boundary."""
    data = DataTools(turn)
    knowledge = KnowledgeTools(turn)
    reports = ReportTools(turn)
    completion = CompletionTools(turn)
    skills = SkillTools(turn)
    return [
        data.describe_data,
        skills.load_skill,
        skills.load_skill_resource,
        knowledge.list_golden,
        knowledge.read_golden,
        data.query_data,
        data.read_result,
        data.analyze_results,
        data.query_state_summary,
        reports.search_reports,
        reports.read_report,
        reports.read_answer,
        reports.stage_report_save,
        reports.preview_report_deletion,
        reports.cancel_report_deletion,
        completion.finish_answer,
    ]
