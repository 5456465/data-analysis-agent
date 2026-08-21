"""Pure view helpers for the minimal Streamlit workbench."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from data_analysis_agent.final_answer_service import FinalAnswerResult
from data_analysis_agent.python_analysis import GrowthPeriod, GrowthResult


DEFAULT_DATABASE_PATH = Path("data/processed/olist.duckdb")
EXAMPLE_QUESTIONS = (
    "How many orders were canceled in 2017?",
    "What are the top 5 product categories by total item transaction value?",
    "How did total item transaction value change month over month?",
)


@dataclass(frozen=True)
class StatusSummary:
    """Existing pipeline status labels prepared for compact UI display."""

    route: str
    validation: str
    tool: str


@dataclass(frozen=True)
class GrowthChartData:
    """Ordered period/value evidence copied from an existing GrowthResult."""

    periods: tuple[GrowthPeriod, ...]
    values: tuple[float, ...]


@dataclass(frozen=True)
class AnalysisDetails:
    """Minimal actual SQL and Python-plan evidence for UI rendering."""

    generated_sql: str | None
    repaired_sql: str | None
    planner_sql: str | None
    python_operation: str | None
    python_columns: tuple[str, ...]


def build_status_summary(final_result: FinalAnswerResult) -> StatusSummary:
    """Map existing route, validation, and operation values to UI labels."""

    if not isinstance(final_result, FinalAnswerResult):
        raise TypeError("final_result must be a FinalAnswerResult instance.")

    result = final_result.validated_result.result
    route = result.route_decision.route
    route_label = {
        "sql_only": "SQL only",
        "sql_then_python": "SQL → Python",
        None: "N/A",
    }.get(route, str(route))
    validation = final_result.validated_result.validation.status
    validation_label = {
        "valid": "Valid",
        "valid_with_warnings": "Warning",
        "invalid": "Invalid",
    }[validation]
    return StatusSummary(
        route=route_label,
        validation=validation_label,
        tool=result.route_decision.python_operation or "SQL",
    )


def extract_growth_chart_data(
    final_result: FinalAnswerResult,
) -> GrowthChartData | None:
    """Return unmodified ordered period/value evidence for a growth chart."""

    if not isinstance(final_result, FinalAnswerResult):
        raise TypeError("final_result must be a FinalAnswerResult instance.")

    python_result = final_result.validated_result.result.python_result
    payload = python_result.result if python_result is not None else None
    if not isinstance(payload, GrowthResult) or not payload.points:
        return None
    return GrowthChartData(
        periods=tuple(point.period for point in payload.points),
        values=tuple(point.value for point in payload.points),
    )


def extract_analysis_details(final_result: FinalAnswerResult) -> AnalysisDetails:
    """Extract actual execution evidence without copying result rows."""

    if not isinstance(final_result, FinalAnswerResult):
        raise TypeError("final_result must be a FinalAnswerResult instance.")

    result = final_result.validated_result.result
    sql_answer = result.sql_answer_result
    plan = result.analysis_plan
    return AnalysisDetails(
        generated_sql=(
            sql_answer.generated_sql if sql_answer is not None else None
        ),
        repaired_sql=(
            sql_answer.repaired_sql if sql_answer is not None else None
        ),
        planner_sql=plan.sql if plan is not None else None,
        python_operation=plan.python_operation if plan is not None else None,
        python_columns=plan.python_columns if plan is not None else (),
    )


def synthesis_is_blocked(final_result: FinalAnswerResult) -> bool:
    """Return the existing synthesis disposition without reinterpretation."""

    return final_result.synthesis.status == "blocked"


def synthesis_warnings(final_result: FinalAnswerResult) -> tuple[str, ...]:
    """Return synthesis warnings unchanged for UI display."""

    return final_result.synthesis.warnings
