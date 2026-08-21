from __future__ import annotations

from pathlib import Path

from data_analysis_agent.analysis_planner import PythonAnalysisPlan
from data_analysis_agent.answer_synthesis import AnswerSynthesis
from data_analysis_agent.final_answer_service import FinalAnswerResult
from data_analysis_agent.multi_tool_service import MultiToolQuestionResult
from data_analysis_agent.question_service import QuestionAnswerResult
from data_analysis_agent.result_validation import ResultValidation
from data_analysis_agent.sql_executor import SQLResult
from data_analysis_agent.streamlit_view import (
    DEFAULT_DATABASE_PATH,
    extract_analysis_details,
    synthesis_is_blocked,
    synthesis_warnings,
)
from data_analysis_agent.tool_router import ToolRouteDecision
from data_analysis_agent.validated_question_service import ValidatedQuestionResult


def _sql_result() -> SQLResult:
    return SQLResult(
        executed_sql="SELECT executed",
        columns=("value",),
        rows=((1,),),
        returned_row_count=1,
        truncated=False,
        status="success",
        error=None,
    )


def _final_result(
    *,
    route: str = "sql_only",
    repaired: bool = False,
    blocked: bool = False,
    warnings: tuple[str, ...] = (),
) -> FinalAnswerResult:
    sql_result = _sql_result()
    sql_answer = (
        QuestionAnswerResult(
            question="test question",
            generated_sql="SELECT generated",
            status="success",
            execution_result=sql_result,
            generation_error=None,
            execution_error=None,
            repaired_sql="SELECT repaired" if repaired else None,
            repair_attempted=repaired,
            repair_error=None,
        )
        if route == "sql_only"
        else None
    )
    plan = (
        PythonAnalysisPlan(
            question="test question",
            python_operation="calculate_growth",
            sql="SELECT month, value FROM facts ORDER BY month",
            python_columns=("month", "value"),
            status="success",
            error=None,
        )
        if route == "sql_then_python"
        else None
    )
    result = MultiToolQuestionResult(
        question="REFERENCE SQL MUST NOT APPEAR",
        route_decision=ToolRouteDecision(
            question="test question",
            route=route,
            python_operation="calculate_growth" if plan is not None else None,
            reason="test",
            status="success",
            error=None,
        ),
        status="success",
        sql_answer_result=sql_answer,
        analysis_plan=plan,
        sql_result=sql_result,
        python_result=None,
        error=None,
    )
    return FinalAnswerResult(
        validated_result=ValidatedQuestionResult(
            result=result,
            validation=ResultValidation("valid", ()),
        ),
        synthesis=AnswerSynthesis(
            "blocked" if blocked else "success",
            "Blocked." if blocked else "Result: 1",
            warnings,
        ),
    )


def test_default_database_path_is_project_relative() -> None:
    assert DEFAULT_DATABASE_PATH == Path("data/processed/olist.duckdb")
    assert DEFAULT_DATABASE_PATH.is_absolute() is False


def test_sql_only_details_include_generated_sql() -> None:
    details = extract_analysis_details(_final_result())

    assert details.generated_sql == "SELECT generated"
    assert details.planner_sql is None


def test_sql_only_details_include_repaired_sql_when_present() -> None:
    details = extract_analysis_details(_final_result(repaired=True))

    assert details.repaired_sql == "SELECT repaired"


def test_sql_then_python_details_include_planner_sql() -> None:
    details = extract_analysis_details(_final_result(route="sql_then_python"))

    assert details.planner_sql == "SELECT month, value FROM facts ORDER BY month"
    assert details.generated_sql is None


def test_sql_then_python_details_include_operation_and_columns() -> None:
    details = extract_analysis_details(_final_result(route="sql_then_python"))

    assert details.python_operation == "calculate_growth"
    assert details.python_columns == ("month", "value")


def test_details_do_not_include_reference_or_result_rows() -> None:
    details = extract_analysis_details(_final_result())
    serialized = repr(details)

    assert "REFERENCE SQL" not in serialized
    assert repr(((1,),)) not in serialized


def test_blocked_synthesis_is_identified_without_reinterpretation() -> None:
    assert synthesis_is_blocked(_final_result(blocked=True)) is True
    assert synthesis_is_blocked(_final_result()) is False


def test_synthesis_warnings_are_returned_unchanged() -> None:
    final = _final_result(warnings=("First warning.", "Second warning."))

    assert synthesis_warnings(final) == ("First warning.", "Second warning.")


def test_helpers_do_not_modify_final_result() -> None:
    final = _final_result(repaired=True, warnings=("Warning.",))
    before = repr(final)

    extract_analysis_details(final)
    synthesis_is_blocked(final)
    synthesis_warnings(final)

    assert repr(final) == before
