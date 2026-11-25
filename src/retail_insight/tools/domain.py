"""Reusable warehouse adapter and capabilities shared by domain specialists."""

from retail_insight.review.maps_completion import MapsCompletionTools
from retail_insight.tools.analytics import DataTools
from retail_insight.tools.knowledge import KnowledgeTools
from retail_insight.tools.reports import ReportTools
from retail_insight.tools.skills import SkillTools


def common_tools(turn):
    data, knowledge, reports = DataTools(turn), KnowledgeTools(turn), ReportTools(turn)
    skills, completion = SkillTools(turn), MapsCompletionTools(turn)
    return [
        skills.load_skill,
        skills.load_skill_resource,
        knowledge.list_golden,
        knowledge.read_golden,
        data.read_result,
        data.analyze_results,
        reports.read_answer,
        reports.search_reports,
        reports.read_report,
        reports.stage_report_save,
        completion.finish_answer,
    ]


class DomainTools:
    def __init__(self, turn):
        self.turn = turn

    async def query_data(self, sql: str, purpose: str, parameters_json: str = "{}") -> dict:
        """Execute read-only BigQuery SQL over authorized relations from describe_data."""
        return await DataTools(self.turn).query_data(sql, purpose, parameters_json)
