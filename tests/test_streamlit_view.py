from __future__ import annotations

from pathlib import Path

from data_analysis_agent.analysis_planner import PythonAnalysisPlan
from data_analysis_agent.answer_synthesis import AnswerSynthesis
from data_analysis_agent.final_answer_service import FinalAnswerResult
from data_analysis_agent.execution_trace import ExecutionTrace, TraceStep
from data_analysis_agent.multi_tool_service import MultiToolQuestionResult
from data_analysis_agent.natural_language_answer import NaturalLanguageAnswer
from data_analysis_agent.python_analysis import (
    CorrelationResult,
    GrowthPoint,
    GrowthResult,
    PythonAnalysisResult,
)
from data_analysis_agent.question_service import QuestionAnswerResult
from data_analysis_agent.result_validation import ResultValidation, ValidationIssue
from data_analysis_agent.sql_executor import SQLResult
from data_analysis_agent.streamlit_view import (
    DEFAULT_DATABASE_PATH,
    EXAMPLE_QUESTIONS,
    build_status_summary,
    extract_analysis_details,
    extract_growth_chart_data,
    format_execution_trace_for_display,
    primary_answer_text,
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
    validation_status: str = "valid",
    operation: str = "calculate_growth",
    python_payload: object | None = None,
    natural_language_answer: NaturalLanguageAnswer | None = None,
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
            python_operation=operation,
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
            python_operation=operation if plan is not None else None,
            reason="test",
            status="success",
            error=None,
        ),
        status="success",
        sql_answer_result=sql_answer,
        analysis_plan=plan,
        sql_result=sql_result,
        python_result=(
            PythonAnalysisResult(
                operation=operation,
                status="success",
                result=python_payload,
                error=None,
            )
            if python_payload is not None
            else None
        ),
        error=None,
    )
    return FinalAnswerResult(
        validated_result=ValidatedQuestionResult(
            result=result,
            validation=ResultValidation(
                validation_status,
                (
                    ValidationIssue("test", "warning", "Test warning.")
                    if validation_status == "valid_with_warnings"
                    else ValidationIssue("test", "error", "Test error.")
                ,)
                if validation_status != "valid"
                else (),
            ),
        ),
        synthesis=AnswerSynthesis(
            "blocked" if blocked else "success",
            "Blocked." if blocked else "Result: 1",
            warnings,
        ),
        natural_language_answer=natural_language_answer,
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


def test_primary_answer_prefers_successful_natural_language_answer() -> None:
    final = _final_result(
        natural_language_answer=NaturalLanguageAnswer(
            "success",
            "共有 1 条结果。",
            None,
        )
    )

    assert primary_answer_text(final) == "共有 1 条结果。"
    assert final.synthesis.answer == "Result: 1"


def test_primary_answer_uses_deterministic_fallback_after_model_failure() -> None:
    final = _final_result(
        natural_language_answer=NaturalLanguageAnswer(
            "fallback",
            "Result: 1",
            "model_error: RuntimeError",
        )
    )

    assert primary_answer_text(final) == "Result: 1"


def test_primary_answer_defaults_to_deterministic_synthesis() -> None:
    assert primary_answer_text(_final_result()) == "Result: 1"


def test_blocked_result_keeps_deterministic_blocked_message() -> None:
    final = _final_result(blocked=True, validation_status="invalid")

    assert synthesis_is_blocked(final) is True
    assert primary_answer_text(final) == "Blocked."


def test_helpers_do_not_modify_final_result() -> None:
    final = _final_result(repaired=True, warnings=("Warning.",))
    before = repr(final)

    extract_analysis_details(final)
    synthesis_is_blocked(final)
    synthesis_warnings(final)
    primary_answer_text(final)
    build_status_summary(final)
    extract_growth_chart_data(final)

    assert repr(final) == before


def test_sql_only_status_summary_uses_sql_labels() -> None:
    summary = build_status_summary(_final_result())

    assert summary.route == "仅 SQL"
    assert summary.tool == "SQL"


def test_sql_then_python_status_summary_uses_operation() -> None:
    summary = build_status_summary(_final_result(route="sql_then_python"))

    assert summary.route == "SQL → Python"
    assert summary.tool == "环比计算"


def test_valid_status_maps_to_valid() -> None:
    assert build_status_summary(_final_result()).validation == "通过"


def test_valid_with_warnings_status_maps_to_warning() -> None:
    final = _final_result(validation_status="valid_with_warnings")

    assert build_status_summary(final).validation == "有警告"


def test_invalid_status_maps_to_invalid() -> None:
    final = _final_result(validation_status="invalid", blocked=True)

    assert build_status_summary(final).validation == "未通过"


def test_python_operations_map_to_chinese_display_labels() -> None:
    assert build_status_summary(
        _final_result(route="sql_then_python", operation="describe")
    ).tool == "描述性统计"
    assert build_status_summary(
        _final_result(route="sql_then_python", operation="correlation")
    ).tool == "相关性分析"


def test_trace_display_localizes_stage_and_status_only() -> None:
    trace = ExecutionTrace(
        question="test question",
        route="sql_then_python",
        python_operation="calculate_growth",
        steps=(
            TraceStep(
                stage="routing",
                status="success",
                summary="Routing completed.",
                details=(("route", "sql_then_python"),),
            ),
            TraceStep(
                stage="python_analysis",
                status="warning",
                summary="Python analysis completed with a warning.",
                details=(("python_operation", "calculate_growth"),),
            ),
        ),
    )
    before = repr(trace)

    display = format_execution_trace_for_display(trace)

    assert "路由判断 [成功]" in display
    assert "Python 分析 [警告]" in display
    assert "route: sql_then_python" in display
    assert "python_operation: calculate_growth" in display
    assert repr(trace) == before


def test_missing_route_maps_to_na() -> None:
    final = _final_result()
    result = final.validated_result.result
    missing_route = ToolRouteDecision(
        question=result.route_decision.question,
        route=None,
        python_operation=None,
        reason=None,
        status="error",
        error=result.route_decision.error,
    )
    final = FinalAnswerResult(
        validated_result=ValidatedQuestionResult(
            result=MultiToolQuestionResult(
                question=result.question,
                route_decision=missing_route,
                status=result.status,
                sql_answer_result=result.sql_answer_result,
                analysis_plan=result.analysis_plan,
                sql_result=result.sql_result,
                python_result=result.python_result,
                error=result.error,
            ),
            validation=final.validated_result.validation,
        ),
        synthesis=final.synthesis,
    )

    assert build_status_summary(final).route == "N/A"


def _growth_result(*points: GrowthPoint) -> GrowthResult:
    return GrowthResult(points=points, period_count=len(points))


def test_growth_chart_extracts_periods_and_values() -> None:
    payload = _growth_result(
        GrowthPoint("2017-01", 10.0, None, None, None),
        GrowthPoint("2017-02", 12.5, 10.0, 2.5, 0.25),
    )

    chart = extract_growth_chart_data(
        _final_result(route="sql_then_python", python_payload=payload)
    )

    assert chart is not None
    assert chart.periods == ("2017-01", "2017-02")
    assert chart.values == (10.0, 12.5)


def test_growth_chart_preserves_point_order() -> None:
    payload = _growth_result(
        GrowthPoint("2017-03", 30.0, 20.0, 10.0, 0.5),
        GrowthPoint("2017-01", 10.0, None, None, None),
    )

    chart = extract_growth_chart_data(
        _final_result(route="sql_then_python", python_payload=payload)
    )

    assert chart is not None
    assert chart.periods == ("2017-03", "2017-01")
    assert chart.values == (30.0, 10.0)


def test_growth_chart_does_not_include_growth_fields() -> None:
    payload = _growth_result(
        GrowthPoint("2017-02", 12.5, 10.0, 2.5, 0.25),
    )

    chart = extract_growth_chart_data(
        _final_result(route="sql_then_python", python_payload=payload)
    )

    assert chart is not None
    assert not hasattr(chart, "growth_rate")
    assert repr(chart) == "GrowthChartData(periods=('2017-02',), values=(12.5,))"


def test_non_growth_payload_has_no_chart_data() -> None:
    payload = CorrelationResult("price", "freight", 0.4, 10)

    assert (
        extract_growth_chart_data(
            _final_result(route="sql_then_python", python_payload=payload)
        )
        is None
    )


def test_empty_growth_payload_has_no_chart_data() -> None:
    payload = _growth_result()

    assert (
        extract_growth_chart_data(
            _final_result(route="sql_then_python", python_payload=payload)
        )
        is None
    )


def test_example_question_count_is_fixed_at_three() -> None:
    assert len(EXAMPLE_QUESTIONS) == 3


def test_examples_cover_simple_sql_ranking_and_growth() -> None:
    assert EXAMPLE_QUESTIONS == (
        "2017 年取消了多少订单？",
        "商品成交金额最高的前 5 个商品类别是什么？",
        "商品成交金额每个月的环比变化怎么样？",
    )


def test_examples_are_inert_text_values() -> None:
    assert all(isinstance(question, str) for question in EXAMPLE_QUESTIONS)
    assert all(question.strip() for question in EXAMPLE_QUESTIONS)
