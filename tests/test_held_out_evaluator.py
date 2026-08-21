from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime
from pathlib import Path

import duckdb
import pytest

from data_analysis_agent.held_out_evaluator import (
    HeldOutCaseEvaluation,
    evaluate_held_out_case,
    summarize_held_out_evaluations,
)
from data_analysis_agent.multi_tool_service import (
    MultiToolQuestionError,
    MultiToolQuestionResult,
)
from data_analysis_agent.multi_tool_test_questions import MultiToolTestQuestion
from data_analysis_agent.python_analysis import (
    GrowthPoint,
    GrowthResult,
    PythonAnalysisResult,
)
from data_analysis_agent.question_service import QuestionAnswerResult
from data_analysis_agent.sql_executor import SQLExecutionError, SQLResult
from data_analysis_agent.sql_generator import SQLGenerationError
from data_analysis_agent.tool_router import (
    ToolRouteDecision,
    ToolRoutingError,
)


@pytest.fixture()
def database_path(tmp_path: Path) -> Path:
    path = tmp_path / "held-out.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute("CREATE TABLE scalar_values(value DOUBLE)")
        connection.execute("INSERT INTO scalar_values VALUES (42.0)")
        connection.execute("CREATE TABLE ranked_values(label VARCHAR, value DOUBLE)")
        connection.execute(
            "INSERT INTO ranked_values VALUES ('A', 3.0), ('B', 2.0), ('C', 1.0)"
        )
        connection.execute("CREATE TABLE monthly_values(period DATE, value DOUBLE)")
        connection.execute(
            "INSERT INTO monthly_values VALUES "
            "(DATE '2020-01-01', 10.0), "
            "(DATE '2020-02-01', 15.0), "
            "(DATE '2020-04-01', 12.0)"
        )
    return path


def _sql_question(
    *,
    reference_sql: str = "SELECT value FROM scalar_values",
    expected_grain: str = "single value",
) -> MultiToolTestQuestion:
    return MultiToolTestQuestion(
        id="MTQ-TEST-SQL",
        question="Return the test value.",
        category="sql_only",
        expected_disposition="answer",
        expected_route="sql_only",
        expected_python_operation=None,
        metric_definition="Test metric.",
        expected_grain=expected_grain,
        expected_tables=("scalar_values",),
        reference_sql=reference_sql,
    )


def _growth_question() -> MultiToolTestQuestion:
    return MultiToolTestQuestion(
        id="MTQ-TEST-GROWTH",
        question="How did the value change month over month?",
        category="calculate_growth",
        expected_disposition="answer",
        expected_route="sql_then_python",
        expected_python_operation="calculate_growth",
        metric_definition="Monthly test value followed by period-over-period growth.",
        expected_grain="one value per observed month",
        expected_tables=("monthly_values",),
        reference_sql=(
            "SELECT period AS month, value FROM monthly_values ORDER BY period"
        ),
        python_columns=("month", "value"),
    )


def _reject_question(category: str = "capability_unsupported") -> MultiToolTestQuestion:
    return MultiToolTestQuestion(
        id="MTQ-TEST-REJECT",
        question="Predict a future value.",
        category=category,
        expected_disposition="reject",
        expected_route=None,
        expected_python_operation=None,
        metric_definition="Unsupported test request.",
        expected_grain="one predicted value",
        expected_tables=(),
        unanswerable_reason="The current tools cannot make forecasts.",
    )


def _route(
    route: str | None,
    operation: str | None,
    *,
    status: str = "success",
    error: ToolRoutingError | None = None,
) -> ToolRouteDecision:
    return ToolRouteDecision(
        question="test question",
        route=route,
        python_operation=operation,
        reason="test decision" if status == "success" else None,
        status=status,
        error=error,
    )


def _sql_result(
    columns: tuple[str, ...],
    rows: tuple[tuple[object, ...], ...],
    *,
    status: str = "success",
    error: SQLExecutionError | None = None,
    truncated: bool = False,
) -> SQLResult:
    return SQLResult(
        executed_sql="SELECT test",
        columns=columns,
        rows=rows,
        returned_row_count=len(rows),
        truncated=truncated,
        status=status,
        error=error,
    )


def _successful_sql_actual(
    sql_result: SQLResult,
    *,
    route: str = "sql_only",
    operation: str | None = None,
    repaired: bool = False,
) -> MultiToolQuestionResult:
    sql_answer = QuestionAnswerResult(
        question="test question",
        generated_sql="SELECT generated",
        status="success",
        execution_result=sql_result,
        generation_error=None,
        execution_error=None,
        repaired_sql="SELECT repaired" if repaired else None,
        repair_attempted=repaired,
    )
    return MultiToolQuestionResult(
        question="test question",
        route_decision=_route(route, operation),
        status="success",
        sql_answer_result=sql_answer,
        analysis_plan=None,
        sql_result=sql_result,
        python_result=None,
        error=None,
    )


def _successful_growth_actual(
    growth: GrowthResult,
    *,
    operation: str = "calculate_growth",
) -> MultiToolQuestionResult:
    sql_result = _sql_result(
        ("period", "value"),
        (
            (date(2020, 1, 1), 10.0),
            (date(2020, 2, 1), 15.0),
            (date(2020, 4, 1), 12.0),
        ),
    )
    return MultiToolQuestionResult(
        question="test question",
        route_decision=_route("sql_then_python", operation),
        status="success",
        sql_answer_result=None,
        analysis_plan=None,
        sql_result=sql_result,
        python_result=PythonAnalysisResult(
            operation=operation,
            status="success",
            result=growth,
            error=None,
        ),
        error=None,
    )


def _expected_growth() -> GrowthResult:
    return GrowthResult(
        points=(
            GrowthPoint("2020-01", 10.0, None, None, None),
            GrowthPoint("2020-02", 15.0, 10.0, 5.0, 0.5),
            GrowthPoint("2020-04", 12.0, None, None, None),
        ),
        period_count=3,
    )


def test_sql_only_perfect_match_passes(database_path: Path) -> None:
    evaluation = evaluate_held_out_case(
        _sql_question(),
        _successful_sql_actual(_sql_result(("value",), ((42.0,),))),
        database_path,
    )

    assert evaluation.passed is True
    assert evaluation.semantic_correct is True
    assert evaluation.failure_reason is None


def test_sql_only_uses_successful_repaired_execution_result(database_path: Path) -> None:
    actual = _successful_sql_actual(
        _sql_result(("different_alias",), ((42.0,),)),
        repaired=True,
    )
    actual = MultiToolQuestionResult(
        question=actual.question,
        route_decision=actual.route_decision,
        status=actual.status,
        sql_answer_result=actual.sql_answer_result,
        analysis_plan=None,
        sql_result=_sql_result(
            (),
            (),
            status="error",
            error=SQLExecutionError("invalid_sql", "initial failure"),
        ),
        python_result=None,
        error=None,
    )

    evaluation = evaluate_held_out_case(_sql_question(), actual, database_path)

    assert evaluation.passed is True
    assert evaluation.semantic_correct is True


def test_sql_only_alias_difference_does_not_fail(database_path: Path) -> None:
    evaluation = evaluate_held_out_case(
        _sql_question(),
        _successful_sql_actual(_sql_result(("harmless_alias",), ((42.0,),))),
        database_path,
    )

    assert evaluation.semantic_correct is True


def test_numeric_small_tolerance_passes(database_path: Path) -> None:
    evaluation = evaluate_held_out_case(
        _sql_question(),
        _successful_sql_actual(_sql_result(("value",), ((42.005,),))),
        database_path,
    )

    assert evaluation.semantic_correct is True


def test_numeric_meaningful_mismatch_fails(database_path: Path) -> None:
    evaluation = evaluate_held_out_case(
        _sql_question(),
        _successful_sql_actual(_sql_result(("value",), ((43.0,),))),
        database_path,
    )

    assert evaluation.passed is False
    assert evaluation.failure_reason == "value mismatch at row 1 column 1"


def test_row_count_mismatch_fails(database_path: Path) -> None:
    question = _sql_question(
        reference_sql="SELECT label, value FROM ranked_values ORDER BY value DESC"
    )
    actual = _successful_sql_actual(
        _sql_result(("label", "value"), (("A", 3.0), ("B", 2.0)))
    )

    evaluation = evaluate_held_out_case(question, actual, database_path)

    assert evaluation.semantic_correct is False
    assert evaluation.failure_reason == "row count mismatch: expected 3, got 2"


def test_column_count_mismatch_fails(database_path: Path) -> None:
    evaluation = evaluate_held_out_case(
        _sql_question(),
        _successful_sql_actual(_sql_result(("value", "extra"), ((42.0, 1),))),
        database_path,
    )

    assert evaluation.semantic_correct is False
    assert evaluation.failure_reason == "column count mismatch: expected 1, got 2"


def test_ordered_multi_row_mismatch_fails(database_path: Path) -> None:
    question = _sql_question(
        reference_sql="SELECT label, value FROM ranked_values ORDER BY value DESC"
    )
    actual = _successful_sql_actual(
        _sql_result(
            ("label", "value"),
            (("C", 1.0), ("B", 2.0), ("A", 3.0)),
        )
    )

    evaluation = evaluate_held_out_case(question, actual, database_path)

    assert evaluation.semantic_correct is False
    assert evaluation.failure_reason == "value mismatch at row 1 column 1"


def test_monthly_equivalent_representations_pass(database_path: Path) -> None:
    question = _sql_question(
        reference_sql="SELECT period AS purchase_month, value FROM monthly_values ORDER BY period",
        expected_grain="one row per purchase month",
    )
    actual = _successful_sql_actual(
        _sql_result(
            ("month_alias", "value_alias"),
            (
                ("2020-01", 10.0),
                ("2020-02-01", 15.0),
                (datetime(2020, 4, 1), 12.0),
            ),
        )
    )

    evaluation = evaluate_held_out_case(question, actual, database_path)

    assert evaluation.semantic_correct is True


def test_month_normalization_does_not_apply_to_ordinary_strings(
    database_path: Path,
) -> None:
    question = _sql_question(
        reference_sql="SELECT '2020-01-01' AS label",
        expected_grain="single string label",
    )
    actual = _successful_sql_actual(_sql_result(("label",), (("2020-01",),)))

    evaluation = evaluate_held_out_case(question, actual, database_path)

    assert evaluation.semantic_correct is False


def test_route_mismatch_fails_even_when_values_match(database_path: Path) -> None:
    actual = _successful_sql_actual(
        _sql_result(("value",), ((42.0,),)),
        route="sql_then_python",
        operation="calculate_growth",
    )

    evaluation = evaluate_held_out_case(_sql_question(), actual, database_path)

    assert evaluation.semantic_correct is True
    assert evaluation.route_correct is False
    assert evaluation.passed is False
    assert evaluation.failure_reason == (
        "route mismatch: expected sql_only, got sql_then_python"
    )


def test_growth_correct_route_operation_and_result_pass(database_path: Path) -> None:
    evaluation = evaluate_held_out_case(
        _growth_question(),
        _successful_growth_actual(_expected_growth()),
        database_path,
    )

    assert evaluation.passed is True
    assert evaluation.semantic_correct is True


def test_growth_wrong_operation_fails(database_path: Path) -> None:
    evaluation = evaluate_held_out_case(
        _growth_question(),
        _successful_growth_actual(_expected_growth(), operation="correlation"),
        database_path,
    )

    assert evaluation.operation_correct is False
    assert evaluation.passed is False
    assert evaluation.failure_reason == (
        "operation mismatch: expected calculate_growth, got correlation"
    )


def test_growth_none_fields_and_month_representations_compare_correctly(
    database_path: Path,
) -> None:
    actual_growth = GrowthResult(
        points=(
            GrowthPoint(date(2020, 1, 1), 10.0, None, None, None),
            GrowthPoint(datetime(2020, 2, 1), 15.0, 10.0, 5.0, 0.5),
            GrowthPoint("2020-04-01", 12.0, None, None, None),
        ),
        period_count=3,
    )

    evaluation = evaluate_held_out_case(
        _growth_question(),
        _successful_growth_actual(actual_growth),
        database_path,
    )

    assert evaluation.semantic_correct is True


def test_growth_value_mismatch_fails(database_path: Path) -> None:
    growth = _expected_growth()
    mismatched = GrowthResult(
        points=(
            growth.points[0],
            GrowthPoint("2020-02", 16.0, 10.0, 6.0, 0.6),
            growth.points[2],
        ),
        period_count=3,
    )

    evaluation = evaluate_held_out_case(
        _growth_question(),
        _successful_growth_actual(mismatched),
        database_path,
    )

    assert evaluation.semantic_correct is False
    assert evaluation.failure_reason == "growth point mismatch at period 2020-02-01: value"


def test_growth_period_count_mismatch_fails(database_path: Path) -> None:
    growth = _expected_growth()
    mismatched = GrowthResult(points=growth.points, period_count=2)

    evaluation = evaluate_held_out_case(
        _growth_question(),
        _successful_growth_actual(mismatched),
        database_path,
    )

    assert evaluation.semantic_correct is False
    assert evaluation.failure_reason == (
        "growth period count mismatch: expected 3, got 2"
    )


def test_controlled_routing_rejection_passes(database_path: Path) -> None:
    actual = MultiToolQuestionResult(
        question="test question",
        route_decision=_route(
            None,
            None,
            status="error",
            error=ToolRoutingError("unsupported_route", "unsupported"),
        ),
        status="routing_error",
        sql_answer_result=None,
        analysis_plan=None,
        sql_result=None,
        python_result=None,
        error=MultiToolQuestionError("routing_error", "unsupported"),
    )

    evaluation = evaluate_held_out_case(_reject_question(), actual, database_path)

    assert evaluation.actual_disposition == "reject"
    assert evaluation.passed is True


def test_unsupported_route_value_is_not_a_controlled_rejection(
    database_path: Path,
) -> None:
    actual = MultiToolQuestionResult(
        question="test question",
        route_decision=_route(
            None,
            None,
            status="error",
            error=ToolRoutingError(
                "unsupported_route",
                "Unsupported route: 'magic_route'",
            ),
        ),
        status="routing_error",
        sql_answer_result=None,
        analysis_plan=None,
        sql_result=None,
        python_result=None,
        error=MultiToolQuestionError("routing_error", "unsupported route value"),
    )

    evaluation = evaluate_held_out_case(_reject_question(), actual, database_path)

    assert evaluation.actual_disposition == "unknown"
    assert evaluation.passed is False
    assert evaluation.failure_reason == (
        "model/infrastructure error is not a semantic rejection"
    )


def test_unsupported_python_operation_is_not_a_controlled_rejection(
    database_path: Path,
) -> None:
    actual = MultiToolQuestionResult(
        question="test question",
        route_decision=_route(
            None,
            None,
            status="error",
            error=ToolRoutingError(
                "unsupported_route",
                "Unsupported Python operation: 'forecast'",
            ),
        ),
        status="routing_error",
        sql_answer_result=None,
        analysis_plan=None,
        sql_result=None,
        python_result=None,
        error=MultiToolQuestionError(
            "routing_error",
            "unsupported Python operation",
        ),
    )

    evaluation = evaluate_held_out_case(_reject_question(), actual, database_path)

    assert evaluation.actual_disposition == "unknown"
    assert evaluation.passed is False
    assert evaluation.failure_reason == (
        "model/infrastructure error is not a semantic rejection"
    )


def test_controlled_sql_generation_rejection_passes(database_path: Path) -> None:
    sql_answer = QuestionAnswerResult(
        question="test question",
        generated_sql=None,
        status="generation_error",
        execution_result=None,
        generation_error=SQLGenerationError("cannot_generate", "missing data"),
        execution_error=None,
    )
    actual = MultiToolQuestionResult(
        question="test question",
        route_decision=_route("sql_only", None),
        status="sql_generation_error",
        sql_answer_result=sql_answer,
        analysis_plan=None,
        sql_result=None,
        python_result=None,
        error=MultiToolQuestionError("sql_generation_error", "missing data"),
    )

    evaluation = evaluate_held_out_case(
        _reject_question("data_unanswerable"),
        actual,
        database_path,
    )

    assert evaluation.actual_disposition == "reject"
    assert evaluation.passed is True


def test_successful_answer_when_rejection_expected_fails(database_path: Path) -> None:
    actual = _successful_sql_actual(_sql_result(("value",), ((42.0,),)))

    evaluation = evaluate_held_out_case(_reject_question(), actual, database_path)

    assert evaluation.actual_disposition == "answer"
    assert evaluation.passed is False
    assert evaluation.failure_reason == (
        "expected controlled rejection but received successful answer"
    )


@pytest.mark.parametrize("error_code", ["invalid_model_output", "model_error"])
def test_model_error_is_not_a_controlled_rejection(
    database_path: Path,
    error_code: str,
) -> None:
    actual = MultiToolQuestionResult(
        question="test question",
        route_decision=_route(
            None,
            None,
            status="error",
            error=ToolRoutingError(error_code, "provider unavailable"),
        ),
        status="routing_error",
        sql_answer_result=None,
        analysis_plan=None,
        sql_result=None,
        python_result=None,
        error=MultiToolQuestionError("routing_error", "provider unavailable"),
    )

    evaluation = evaluate_held_out_case(_reject_question(), actual, database_path)

    assert evaluation.actual_disposition == "unknown"
    assert evaluation.passed is False
    assert evaluation.failure_reason == (
        "model/infrastructure error is not a semantic rejection"
    )


def test_summary_counts_denominators_and_accuracies() -> None:
    evaluations = (
        HeldOutCaseEvaluation(
            "one", "sql_only", "answer", "answer", True,
            "sql_only", "sql_only", True, None, None, True, True, True, None,
        ),
        HeldOutCaseEvaluation(
            "two", "calculate_growth", "answer", "answer", True,
            "sql_then_python", "sql_then_python", True,
            "calculate_growth", "correlation", False, True, False,
            "operation mismatch",
        ),
        HeldOutCaseEvaluation(
            "three", "data_unanswerable", "reject", "reject", True,
            None, None, None, None, None, None, None, True, None,
        ),
        HeldOutCaseEvaluation(
            "four", "capability_unsupported", "reject", "unknown", False,
            None, None, None, None, None, None, None, False,
            "infrastructure error",
        ),
    )

    summary = summarize_held_out_evaluations(evaluations)

    assert (summary.total, summary.passed, summary.failed) == (4, 2, 2)
    assert (summary.disposition_correct, summary.disposition_accuracy) == (3, 0.75)
    assert (summary.route_evaluated, summary.route_correct, summary.route_accuracy) == (
        2,
        2,
        1.0,
    )
    assert (
        summary.operation_evaluated,
        summary.operation_correct,
        summary.operation_accuracy,
    ) == (2, 1, 0.5)
    assert (
        summary.semantic_evaluated,
        summary.semantic_correct,
        summary.semantic_accuracy,
    ) == (2, 2, 1.0)
    assert (summary.sql_only_passed, summary.sql_only_total) == (1, 1)
    assert (summary.calculate_growth_passed, summary.calculate_growth_total) == (0, 1)
    assert (summary.data_unanswerable_passed, summary.data_unanswerable_total) == (1, 1)
    assert (
        summary.capability_unsupported_passed,
        summary.capability_unsupported_total,
    ) == (0, 1)


def test_evaluator_does_not_mutate_frozen_inputs(database_path: Path) -> None:
    question = _sql_question()
    actual = _successful_sql_actual(_sql_result(("value",), ((42.0,),)))
    question_before = repr(question)
    actual_before = repr(actual)

    evaluation = evaluate_held_out_case(question, actual, database_path)

    assert repr(question) == question_before
    assert repr(actual) == actual_before
    with pytest.raises(FrozenInstanceError):
        evaluation.passed = False
