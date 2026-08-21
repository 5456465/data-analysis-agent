from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date

import pytest

from data_analysis_agent.multi_tool_service import (
    MultiToolQuestionError,
    MultiToolQuestionResult,
)
from data_analysis_agent.python_analysis import (
    ColumnDescription,
    CorrelationResult,
    GrowthPoint,
    GrowthResult,
    PythonAnalysisResult,
)
from data_analysis_agent.result_validation import validate_multi_tool_result
from data_analysis_agent.sql_executor import SQLResult
from data_analysis_agent.tool_router import ToolRouteDecision


def _sql_result(
    columns: tuple[str, ...] = ("value",),
    rows: tuple[tuple[object, ...], ...] = ((42,),),
    *,
    truncated: bool = False,
) -> SQLResult:
    return SQLResult(
        executed_sql="SELECT value",
        columns=columns,
        rows=rows,
        returned_row_count=len(rows),
        truncated=truncated,
        status="success",
        error=None,
    )


def _multi_tool_result(
    *,
    route: str = "sql_only",
    operation: str | None = None,
    sql_result: SQLResult | None = None,
    python_result: PythonAnalysisResult | None = None,
    status: str = "success",
) -> MultiToolQuestionResult:
    return MultiToolQuestionResult(
        question="test question",
        route_decision=ToolRouteDecision(
            question="test question",
            route=route,
            python_operation=operation,
            reason="test",
            status="success",
            error=None,
        ),
        status=status,
        sql_answer_result=None,
        analysis_plan=None,
        sql_result=_sql_result() if sql_result is None and status == "success" else sql_result,
        python_result=python_result,
        error=(
            None
            if status == "success"
            else MultiToolQuestionError("sql_execution_error", "query failed")
        ),
    )


def _growth_result(
    points: tuple[GrowthPoint, ...] | None = None,
    *,
    period_count: int | None = None,
) -> GrowthResult:
    actual_points = points or (
        GrowthPoint("2020-01", 10.0, None, None, None),
        GrowthPoint("2020-02", 15.0, 10.0, 5.0, 0.5),
    )
    return GrowthResult(
        points=actual_points,
        period_count=len(actual_points) if period_count is None else period_count,
    )


def _python_actual(
    operation: str,
    payload: object,
) -> MultiToolQuestionResult:
    return _multi_tool_result(
        route="sql_then_python",
        operation=operation,
        sql_result=_sql_result(("period", "value"), (("2020-01", 10.0),)),
        python_result=PythonAnalysisResult(
            operation=operation,
            status="success",
            result=payload,
            error=None,
        ),
    )


def _issue_codes(result: MultiToolQuestionResult) -> tuple[str, ...]:
    return tuple(
        issue.code for issue in validate_multi_tool_result(result).issues
    )


def test_valid_sql_only_scalar_result() -> None:
    validation = validate_multi_tool_result(_multi_tool_result())

    assert validation.status == "valid"
    assert validation.issues == ()


def test_valid_sql_only_multi_row_result() -> None:
    result = _multi_tool_result(
        sql_result=_sql_result(
            ("state", "count"),
            (("SP", 10), ("RJ", 5)),
        )
    )

    assert validate_multi_tool_result(result).status == "valid"


def test_successful_sql_only_without_sql_result_is_invalid() -> None:
    result = replace(_multi_tool_result(), sql_result=None)

    assert "missing_sql_result" in _issue_codes(result)


def test_empty_sql_result_is_warning() -> None:
    result = _multi_tool_result(sql_result=_sql_result(rows=()))

    validation = validate_multi_tool_result(result)

    assert validation.status == "valid_with_warnings"
    assert _issue_codes(result) == ("empty_result",)
    assert validation.issues[0].severity == "warning"


def test_truncated_sql_result_is_invalid() -> None:
    result = _multi_tool_result(sql_result=_sql_result(truncated=True))

    validation = validate_multi_tool_result(result)

    assert validation.status == "invalid"
    assert "truncated_result" in _issue_codes(result)


def test_duplicate_sql_columns_are_invalid() -> None:
    result = _multi_tool_result(
        sql_result=_sql_result(("value", "value"), ((1, 2),))
    )

    assert "duplicate_columns" in _issue_codes(result)


def test_empty_sql_column_name_is_invalid() -> None:
    result = _multi_tool_result(sql_result=_sql_result(("",), ((1,),)))

    assert "invalid_column_name" in _issue_codes(result)


def test_sql_row_width_mismatch_is_invalid() -> None:
    result = _multi_tool_result(
        sql_result=_sql_result(("first", "second"), ((1,),))
    )

    assert "row_width_mismatch" in _issue_codes(result)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_sql_numeric_is_invalid(value: float) -> None:
    result = _multi_tool_result(sql_result=_sql_result(rows=((value,),)))

    assert "non_finite_sql_value" in _issue_codes(result)


def test_unsuccessful_multi_tool_result_is_invalid() -> None:
    result = _multi_tool_result(
        status="sql_execution_error",
        sql_result=None,
    )

    validation = validate_multi_tool_result(result)

    assert validation.status == "invalid"
    assert validation.issues[0].code == "unsuccessful_pipeline"
    assert "sql_execution_error" in validation.issues[0].message


def test_valid_describe_payload() -> None:
    payload = (
        ColumnDescription("value", 2, 1.5, 0.5, 1.0, 1.5, 2.0),
    )

    assert validate_multi_tool_result(_python_actual("describe", payload)).status == "valid"


def test_valid_correlation_payload() -> None:
    payload = CorrelationResult("x", "y", 0.5, 3)

    assert (
        validate_multi_tool_result(_python_actual("correlation", payload)).status
        == "valid"
    )


def test_valid_calculate_growth_result() -> None:
    validation = validate_multi_tool_result(
        _python_actual("calculate_growth", _growth_result())
    )

    assert validation.status == "valid"


def test_successful_python_result_without_payload_is_invalid() -> None:
    result = _multi_tool_result(
        route="sql_then_python",
        operation="calculate_growth",
        sql_result=_sql_result(),
        python_result=PythonAnalysisResult(
            operation="calculate_growth",
            status="success",
            result=None,
            error=None,
        ),
    )

    assert "missing_python_payload" in _issue_codes(result)


def test_growth_period_count_mismatch_is_invalid() -> None:
    result = _python_actual(
        "calculate_growth",
        _growth_result(period_count=1),
    )

    assert "growth_period_count_mismatch" in _issue_codes(result)


def test_growth_non_finite_numeric_is_invalid() -> None:
    points = (
        GrowthPoint("2020-01", 10.0, None, None, None),
        GrowthPoint("2020-02", float("nan"), 10.0, float("inf"), 0.5),
    )
    result = _python_actual("calculate_growth", _growth_result(points))

    validation = validate_multi_tool_result(result)

    assert validation.status == "invalid"
    assert _issue_codes(result).count("non_finite_growth_value") == 2


@pytest.mark.parametrize(
    "periods",
    [
        ("2020-02", "2020-01"),
        (date(2020, 1, 1), date(2020, 1, 1)),
    ],
)
def test_growth_unordered_or_duplicate_periods_are_invalid(
    periods: tuple[object, object],
) -> None:
    points = (
        GrowthPoint(periods[0], 10.0, None, None, None),
        GrowthPoint(periods[1], 11.0, 10.0, 1.0, 0.1),
    )
    result = _python_actual("calculate_growth", _growth_result(points))

    assert "unordered_growth_periods" in _issue_codes(result)


def test_calculate_growth_with_wrong_payload_is_invalid() -> None:
    result = _python_actual(
        "calculate_growth",
        CorrelationResult("x", "y", 0.5, 3),
    )

    assert "python_payload_mismatch" in _issue_codes(result)


def test_python_operation_mismatch_is_invalid() -> None:
    result = _multi_tool_result(
        route="sql_then_python",
        operation="calculate_growth",
        sql_result=_sql_result(),
        python_result=PythonAnalysisResult(
            operation="correlation",
            status="success",
            result=CorrelationResult("x", "y", 0.5, 3),
            error=None,
        ),
    )

    assert "python_operation_mismatch" in _issue_codes(result)


def test_validation_does_not_mutate_original_result() -> None:
    result = _python_actual("calculate_growth", _growth_result())
    before = repr(result)

    validation = validate_multi_tool_result(result)

    assert repr(result) == before
    with pytest.raises(FrozenInstanceError):
        validation.status = "invalid"


def test_validation_does_not_call_database_or_analysis_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("external execution must not be called")

    monkeypatch.setattr(
        "data_analysis_agent.sql_executor.run_readonly_sql",
        fail_if_called,
    )
    monkeypatch.setattr(
        "data_analysis_agent.python_analysis.run_python_analysis",
        fail_if_called,
    )

    validation = validate_multi_tool_result(_multi_tool_result())

    assert validation.status == "valid"
