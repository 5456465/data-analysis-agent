"""Deterministic scoring for frozen held-out multi-tool contracts."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from data_analysis_agent.multi_tool_service import MultiToolQuestionResult
from data_analysis_agent.multi_tool_test_questions import MultiToolTestQuestion
from data_analysis_agent.python_analysis import (
    GrowthResult,
    PythonAnalysisRequest,
    run_python_analysis,
)
from data_analysis_agent.sql_executor import SQLResult, run_readonly_sql


NUMERIC_ABS_TOLERANCE = 0.01
NUMERIC_REL_TOLERANCE = 1e-9
REFERENCE_MAX_ROWS = 10_000
_FRAMEWORK_UNSUPPORTED_OUTPUT_PREFIXES = (
    "Unsupported route:",
    "Unsupported Python operation:",
)

ActualDisposition = Literal["answer", "reject", "unknown"]


@dataclass(frozen=True)
class HeldOutCaseEvaluation:
    """Deterministic evaluation of one frozen held-out question."""

    question_id: str
    category: str
    expected_disposition: str
    actual_disposition: ActualDisposition
    disposition_correct: bool
    expected_route: str | None
    actual_route: str | None
    route_correct: bool | None
    expected_python_operation: str | None
    actual_python_operation: str | None
    operation_correct: bool | None
    semantic_correct: bool | None
    passed: bool
    failure_reason: str | None


@dataclass(frozen=True)
class HeldOutEvaluationSummary:
    """Aggregate deterministic metrics for held-out case evaluations."""

    total: int
    passed: int
    failed: int
    disposition_correct: int
    disposition_accuracy: float
    route_evaluated: int
    route_correct: int
    route_accuracy: float
    operation_evaluated: int
    operation_correct: int
    operation_accuracy: float
    semantic_evaluated: int
    semantic_correct: int
    semantic_accuracy: float
    sql_only_passed: int
    sql_only_total: int
    calculate_growth_passed: int
    calculate_growth_total: int
    data_unanswerable_passed: int
    data_unanswerable_total: int
    capability_unsupported_passed: int
    capability_unsupported_total: int


def evaluate_held_out_case(
    question: MultiToolTestQuestion,
    actual: MultiToolQuestionResult,
    database_path: str | Path,
) -> HeldOutCaseEvaluation:
    """Score one already-produced Agent result against its frozen contract."""

    if not isinstance(question, MultiToolTestQuestion):
        raise TypeError("question must be a MultiToolTestQuestion instance.")
    if not isinstance(actual, MultiToolQuestionResult):
        raise TypeError("actual must be a MultiToolQuestionResult instance.")

    actual_disposition = _actual_disposition(actual)
    disposition_correct = actual_disposition == question.expected_disposition
    actual_route = actual.route_decision.route
    actual_operation = actual.route_decision.python_operation

    if question.expected_disposition == "answer":
        route_correct: bool | None = actual_route == question.expected_route
        operation_correct: bool | None = (
            actual_operation == question.expected_python_operation
        )
        semantic_correct, semantic_reason = _evaluate_answer_semantics(
            question,
            actual,
            database_path,
        )
        passed = all(
            (
                disposition_correct,
                route_correct,
                operation_correct,
                semantic_correct,
            )
        )
    else:
        route_correct = None
        operation_correct = None
        semantic_correct = None
        semantic_reason = None
        passed = disposition_correct

    failure_reason = _failure_reason(
        question,
        actual,
        actual_disposition,
        disposition_correct,
        route_correct,
        operation_correct,
        semantic_correct,
        semantic_reason,
    )
    return HeldOutCaseEvaluation(
        question_id=question.id,
        category=question.category,
        expected_disposition=question.expected_disposition,
        actual_disposition=actual_disposition,
        disposition_correct=disposition_correct,
        expected_route=question.expected_route,
        actual_route=actual_route,
        route_correct=route_correct,
        expected_python_operation=question.expected_python_operation,
        actual_python_operation=actual_operation,
        operation_correct=operation_correct,
        semantic_correct=semantic_correct,
        passed=passed,
        failure_reason=failure_reason,
    )


def summarize_held_out_evaluations(
    evaluations: Sequence[HeldOutCaseEvaluation],
) -> HeldOutEvaluationSummary:
    """Summarize an observed sequence without changing case order or contents."""

    records = tuple(evaluations)
    if not all(isinstance(record, HeldOutCaseEvaluation) for record in records):
        raise TypeError("evaluations must contain HeldOutCaseEvaluation instances.")

    total = len(records)
    passed = sum(record.passed for record in records)
    disposition_correct = sum(record.disposition_correct for record in records)
    route_records = tuple(record for record in records if record.route_correct is not None)
    operation_records = tuple(
        record for record in records if record.operation_correct is not None
    )
    semantic_records = tuple(
        record for record in records if record.semantic_correct is not None
    )
    category_totals = Counter(record.category for record in records)
    category_passes = Counter(record.category for record in records if record.passed)

    return HeldOutEvaluationSummary(
        total=total,
        passed=passed,
        failed=total - passed,
        disposition_correct=disposition_correct,
        disposition_accuracy=_accuracy(disposition_correct, total),
        route_evaluated=len(route_records),
        route_correct=sum(record.route_correct is True for record in route_records),
        route_accuracy=_accuracy(
            sum(record.route_correct is True for record in route_records),
            len(route_records),
        ),
        operation_evaluated=len(operation_records),
        operation_correct=sum(
            record.operation_correct is True for record in operation_records
        ),
        operation_accuracy=_accuracy(
            sum(record.operation_correct is True for record in operation_records),
            len(operation_records),
        ),
        semantic_evaluated=len(semantic_records),
        semantic_correct=sum(
            record.semantic_correct is True for record in semantic_records
        ),
        semantic_accuracy=_accuracy(
            sum(record.semantic_correct is True for record in semantic_records),
            len(semantic_records),
        ),
        sql_only_passed=category_passes["sql_only"],
        sql_only_total=category_totals["sql_only"],
        calculate_growth_passed=category_passes["calculate_growth"],
        calculate_growth_total=category_totals["calculate_growth"],
        data_unanswerable_passed=category_passes["data_unanswerable"],
        data_unanswerable_total=category_totals["data_unanswerable"],
        capability_unsupported_passed=category_passes["capability_unsupported"],
        capability_unsupported_total=category_totals["capability_unsupported"],
    )


def _actual_disposition(actual: MultiToolQuestionResult) -> ActualDisposition:
    routing_error = actual.route_decision.error
    if (
        actual.status == "routing_error"
        and routing_error is not None
        and routing_error.code == "unsupported_route"
        and not routing_error.message.startswith(
            _FRAMEWORK_UNSUPPORTED_OUTPUT_PREFIXES
        )
    ):
        return "reject"

    sql_answer = actual.sql_answer_result
    if (
        actual.status == "sql_generation_error"
        and sql_answer is not None
        and sql_answer.status == "generation_error"
        and sql_answer.generation_error is not None
        and sql_answer.generation_error.code == "cannot_generate"
    ):
        return "reject"

    if actual.status == "success":
        return "answer"
    return "unknown"


def _evaluate_answer_semantics(
    question: MultiToolTestQuestion,
    actual: MultiToolQuestionResult,
    database_path: str | Path,
) -> tuple[bool, str | None]:
    if question.reference_sql is None:
        return False, "answerable contract has no reference SQL"
    if actual.status != "success":
        return False, "final answer did not complete successfully"

    expected_sql = run_readonly_sql(
        database_path,
        question.reference_sql,
        max_rows=REFERENCE_MAX_ROWS,
    )
    if expected_sql.status != "success":
        code = expected_sql.error.code if expected_sql.error is not None else "unknown"
        return False, f"reference SQL execution failed: {code}"
    if expected_sql.truncated:
        return False, "reference SQL result was truncated"

    if question.category == "sql_only":
        actual_sql = _final_sql_result(actual)
        if actual_sql is None or actual_sql.status != "success":
            return False, "final SQL result is unavailable"
        if actual_sql.truncated:
            return False, "actual SQL result was truncated"
        month_columns = _month_column_positions(question, expected_sql)
        return _compare_sql_results(actual_sql, expected_sql, month_columns)

    if question.category == "calculate_growth":
        expected_python = run_python_analysis(
            expected_sql.columns,
            expected_sql.rows,
            PythonAnalysisRequest(
                operation="calculate_growth",
                columns=question.python_columns,
            ),
        )
        if expected_python.status != "success" or not isinstance(
            expected_python.result,
            GrowthResult,
        ):
            code = (
                expected_python.error.code
                if expected_python.error is not None
                else "unknown"
            )
            return False, f"reference Python analysis failed: {code}"
        if actual.sql_result is None or actual.sql_result.status != "success":
            return False, "final SQL result is unavailable"
        if actual.sql_result.truncated:
            return False, "actual SQL result was truncated"
        if actual.python_result is None or actual.python_result.status != "success":
            return False, "final Python result is unavailable"
        if not isinstance(actual.python_result.result, GrowthResult):
            return False, "final Python result is not GrowthResult"
        return _compare_growth_results(
            actual.python_result.result,
            expected_python.result,
        )

    return False, f"unsupported answerable category: {question.category}"


def _final_sql_result(actual: MultiToolQuestionResult) -> SQLResult | None:
    sql_answer = actual.sql_answer_result
    if (
        sql_answer is not None
        and sql_answer.status == "success"
        and sql_answer.execution_result is not None
    ):
        return sql_answer.execution_result
    return actual.sql_result


def _month_column_positions(
    question: MultiToolTestQuestion,
    expected: SQLResult,
) -> frozenset[int]:
    if "month" not in question.expected_grain.lower():
        return frozenset()
    return frozenset(
        index
        for index, column in enumerate(expected.columns)
        if "month" in column.lower()
    )


def _compare_sql_results(
    actual: SQLResult,
    expected: SQLResult,
    month_columns: frozenset[int],
) -> tuple[bool, str | None]:
    if len(actual.columns) != len(expected.columns):
        return (
            False,
            f"column count mismatch: expected {len(expected.columns)}, "
            f"got {len(actual.columns)}",
        )
    if len(actual.rows) != len(expected.rows):
        return (
            False,
            f"row count mismatch: expected {len(expected.rows)}, got {len(actual.rows)}",
        )

    expected_width = len(expected.columns)
    for row_index, (actual_row, expected_row) in enumerate(
        zip(actual.rows, expected.rows, strict=True),
        start=1,
    ):
        if len(actual_row) != expected_width or len(expected_row) != expected_width:
            return False, f"column count mismatch at row {row_index}"
        for column_index, (actual_value, expected_value) in enumerate(
            zip(actual_row, expected_row, strict=True),
            start=1,
        ):
            if not _values_match(
                actual_value,
                expected_value,
                month_grain=(column_index - 1) in month_columns,
            ):
                return (
                    False,
                    f"value mismatch at row {row_index} column {column_index}",
                )
    return True, None


def _compare_growth_results(
    actual: GrowthResult,
    expected: GrowthResult,
) -> tuple[bool, str | None]:
    if actual.period_count != expected.period_count:
        return (
            False,
            f"growth period count mismatch: expected {expected.period_count}, "
            f"got {actual.period_count}",
        )
    if len(actual.points) != len(expected.points):
        return (
            False,
            f"growth point count mismatch: expected {len(expected.points)}, "
            f"got {len(actual.points)}",
        )

    fields = ("value", "previous_value", "absolute_change", "growth_rate")
    for index, (actual_point, expected_point) in enumerate(
        zip(actual.points, expected.points, strict=True),
        start=1,
    ):
        if not _values_match(actual_point.period, expected_point.period, month_grain=True):
            return False, f"growth period mismatch at point {index}"
        for field in fields:
            if not _values_match(
                getattr(actual_point, field),
                getattr(expected_point, field),
            ):
                return (
                    False,
                    f"growth point mismatch at period {expected_point.period}: {field}",
                )
    return True, None


def _values_match(
    actual: object,
    expected: object,
    *,
    month_grain: bool = False,
) -> bool:
    if actual is None or expected is None:
        return actual is expected
    if month_grain:
        actual_month = _calendar_month(actual)
        expected_month = _calendar_month(expected)
        if actual_month is not None and expected_month is not None:
            return actual_month == expected_month
    if isinstance(expected, int) and not isinstance(expected, bool):
        return actual == expected
    if _is_number(actual) and _is_number(expected):
        return math.isclose(
            float(actual),
            float(expected),
            rel_tol=NUMERIC_REL_TOLERANCE,
            abs_tol=NUMERIC_ABS_TOLERANCE,
        )
    if isinstance(actual, date) and isinstance(expected, date):
        actual_date = actual.date() if isinstance(actual, datetime) else actual
        expected_date = expected.date() if isinstance(expected, datetime) else expected
        return actual_date == expected_date
    return actual == expected


def _calendar_month(value: object) -> tuple[int, int] | None:
    if isinstance(value, date):
        return value.year, value.month
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    if len(normalized) == 7:
        normalized += "-01"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.year, parsed.month


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _failure_reason(
    question: MultiToolTestQuestion,
    actual: MultiToolQuestionResult,
    actual_disposition: ActualDisposition,
    disposition_correct: bool,
    route_correct: bool | None,
    operation_correct: bool | None,
    semantic_correct: bool | None,
    semantic_reason: str | None,
) -> str | None:
    if not disposition_correct:
        if question.expected_disposition == "reject":
            if actual_disposition == "answer":
                return "expected controlled rejection but received successful answer"
            return "model/infrastructure error is not a semantic rejection"
        return (
            f"disposition mismatch: expected {question.expected_disposition}, "
            f"got {actual_disposition}"
        )
    if route_correct is False:
        return f"route mismatch: expected {question.expected_route}, got {actual.route_decision.route}"
    if operation_correct is False:
        return (
            "operation mismatch: expected "
            f"{question.expected_python_operation}, "
            f"got {actual.route_decision.python_operation}"
        )
    if semantic_correct is False:
        return semantic_reason or "semantic result mismatch"
    return None


def _accuracy(correct: int, evaluated: int) -> float:
    return correct / evaluated if evaluated else 0.0
