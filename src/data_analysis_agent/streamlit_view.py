"""Pure view helpers for the minimal Streamlit workbench."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from data_analysis_agent.final_answer_service import FinalAnswerResult


DEFAULT_DATABASE_PATH = Path("data/processed/olist.duckdb")


@dataclass(frozen=True)
class AnalysisDetails:
    """Minimal actual SQL and Python-plan evidence for UI rendering."""

    generated_sql: str | None
    repaired_sql: str | None
    planner_sql: str | None
    python_operation: str | None
    python_columns: tuple[str, ...]


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
