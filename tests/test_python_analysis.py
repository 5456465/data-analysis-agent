"""Tests for controlled deterministic Python numeric analysis."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from data_analysis_agent.python_analysis import (
    ColumnDescription,
    CorrelationResult,
    GrowthPoint,
    GrowthResult,
    PythonAnalysisError,
    PythonAnalysisRequest,
    PythonAnalysisResult,
    run_python_analysis,
)


def test_describe_single_numeric_column() -> None:
    result = run_python_analysis(
        columns=("value",),
        rows=((1,), (2,), (3,)),
        request=PythonAnalysisRequest("describe", ("value",)),
    )

    assert result.status == "success"
    assert result.error is None
    assert result.result == (
        ColumnDescription(
            column="value",
            count=3,
            mean=2.0,
            std=1.0,
            min=1.0,
            median=2.0,
            max=3.0,
        ),
    )


def test_describe_multiple_numeric_columns() -> None:
    result = run_python_analysis(
        columns=("x", "y"),
        rows=((1, 2), (2, 4), (3, 8)),
        request=PythonAnalysisRequest("describe", ("x", "y")),
    )

    assert result.status == "success"
    assert isinstance(result.result, tuple)
    assert tuple(item.column for item in result.result) == ("x", "y")
    assert result.result[0].mean == pytest.approx(2.0)
    assert result.result[1].median == pytest.approx(4.0)


def test_describe_ignores_null_values() -> None:
    result = run_python_analysis(
        columns=("value",),
        rows=((1,), (None,), (3,)),
        request=PythonAnalysisRequest("describe", ("value",)),
    )

    assert isinstance(result.result, tuple)
    assert result.result[0].count == 2
    assert result.result[0].mean == pytest.approx(2.0)
    assert result.result[0].std == pytest.approx(2**0.5)


def test_describe_rejects_unknown_column() -> None:
    result = run_python_analysis(
        columns=("value",),
        rows=((1,), (2,)),
        request=PythonAnalysisRequest("describe", ("missing",)),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "unknown_column"


def test_describe_rejects_non_numeric_column() -> None:
    result = run_python_analysis(
        columns=("label",),
        rows=(("one",), ("two",)),
        request=PythonAnalysisRequest("describe", ("label",)),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "non_numeric_column"


@pytest.mark.parametrize("rows", [(), ((1,),)])
def test_describe_rejects_empty_or_insufficient_data(rows) -> None:
    result = run_python_analysis(
        columns=("value",),
        rows=rows,
        request=PythonAnalysisRequest("describe", ("value",)),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "insufficient_data"


def test_correlation_returns_positive_pearson_value() -> None:
    result = run_python_analysis(
        columns=("x", "y"),
        rows=((1, 2), (2, 4), (3, 6)),
        request=PythonAnalysisRequest("correlation", ("x", "y")),
    )

    assert result.status == "success"
    assert isinstance(result.result, CorrelationResult)
    assert result.result.correlation == pytest.approx(1.0)
    assert result.result.paired_count == 3


def test_correlation_returns_negative_pearson_value() -> None:
    result = run_python_analysis(
        columns=("x", "y"),
        rows=((1, 6), (2, 4), (3, 2)),
        request=PythonAnalysisRequest("correlation", ("x", "y")),
    )

    assert isinstance(result.result, CorrelationResult)
    assert result.result.correlation == pytest.approx(-1.0)


def test_correlation_uses_only_paired_non_null_rows() -> None:
    result = run_python_analysis(
        columns=("x", "y"),
        rows=((1, 2), (2, None), (None, 6), (3, 6)),
        request=PythonAnalysisRequest("correlation", ("x", "y")),
    )

    assert isinstance(result.result, CorrelationResult)
    assert result.result.paired_count == 2
    assert result.result.correlation == pytest.approx(1.0)


def test_correlation_rejects_unknown_column() -> None:
    result = run_python_analysis(
        columns=("x", "y"),
        rows=((1, 2), (2, 4)),
        request=PythonAnalysisRequest("correlation", ("x", "missing")),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "unknown_column"


def test_correlation_rejects_non_numeric_column() -> None:
    result = run_python_analysis(
        columns=("x", "label"),
        rows=((1, "one"), (2, "two")),
        request=PythonAnalysisRequest("correlation", ("x", "label")),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "non_numeric_column"


def test_correlation_rejects_insufficient_paired_data() -> None:
    result = run_python_analysis(
        columns=("x", "y"),
        rows=((1, None), (2, 4), (None, 6)),
        request=PythonAnalysisRequest("correlation", ("x", "y")),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "insufficient_data"


def test_correlation_rejects_zero_variance() -> None:
    result = run_python_analysis(
        columns=("x", "y"),
        rows=((1, 2), (1, 4), (1, 6)),
        request=PythonAnalysisRequest("correlation", ("x", "y")),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "zero_variance"


def test_unsupported_operation_returns_structured_error() -> None:
    result = run_python_analysis(
        columns=("value",),
        rows=((1,), (2,)),
        request=PythonAnalysisRequest("regression", ("value",)),
    )

    assert result == PythonAnalysisResult(
        operation="regression",
        status="error",
        result=None,
        error=PythonAnalysisError(
            code="unsupported_operation",
            message="Unsupported Python analysis operation: regression",
        ),
    )


def test_malformed_table_returns_invalid_argument() -> None:
    result = run_python_analysis(
        columns=("x", "y"),
        rows=((1,), (2, 4)),
        request=PythonAnalysisRequest("describe", ("x",)),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_argument"


def test_structured_success_result_schema_is_stable() -> None:
    result = run_python_analysis(
        columns=("x", "y"),
        rows=((1, 2), (2, 4), (3, 6)),
        request=PythonAnalysisRequest("correlation", ("x", "y")),
    )

    assert result == PythonAnalysisResult(
        operation="correlation",
        status="success",
        result=CorrelationResult(
            x_column="x",
            y_column="y",
            correlation=pytest.approx(1.0),
            paired_count=3,
        ),
        error=None,
    )


def test_calculate_growth_returns_complete_ordered_growth_series() -> None:
    result = run_python_analysis(
        columns=("month", "transaction_value"),
        rows=(("2018-01", 100.0), ("2018-02", 120.0), ("2018-03", 90.0)),
        request=PythonAnalysisRequest(
            "calculate_growth",
            ("month", "transaction_value"),
        ),
    )

    assert result.status == "success"
    assert result.error is None
    assert isinstance(result.result, GrowthResult)
    assert result.result.period_count == 3
    assert result.result.points == (
        GrowthPoint("2018-01", 100.0, None, None, None),
        GrowthPoint("2018-02", 120.0, 100.0, 20.0, pytest.approx(0.2)),
        GrowthPoint("2018-03", 90.0, 120.0, -30.0, pytest.approx(-0.25)),
    )


def test_calculate_growth_sorts_unordered_date_rows() -> None:
    result = run_python_analysis(
        columns=("period", "value"),
        rows=(
            (date(2018, 3, 1), 90),
            (date(2018, 1, 1), 100),
            (date(2018, 2, 1), 120),
        ),
        request=PythonAnalysisRequest("calculate_growth", ("period", "value")),
    )

    assert isinstance(result.result, GrowthResult)
    assert tuple(point.period for point in result.result.points) == (
        date(2018, 1, 1),
        date(2018, 2, 1),
        date(2018, 3, 1),
    )


def test_calculate_growth_supports_datetime_periods() -> None:
    result = run_python_analysis(
        columns=("period", "value"),
        rows=(
            (datetime(2018, 2, 1, 12), 110),
            (datetime(2018, 1, 1, 12), 100),
        ),
        request=PythonAnalysisRequest("calculate_growth", ("period", "value")),
    )

    assert result.status == "success"
    assert isinstance(result.result, GrowthResult)
    assert result.result.points[1].growth_rate == pytest.approx(0.1)


def test_calculate_growth_keeps_absolute_change_when_previous_value_is_zero() -> None:
    result = run_python_analysis(
        columns=("period", "value"),
        rows=(("2018-01", 0), ("2018-02", 25)),
        request=PythonAnalysisRequest("calculate_growth", ("period", "value")),
    )

    assert isinstance(result.result, GrowthResult)
    second_point = result.result.points[1]
    assert second_point.previous_value == 0.0
    assert second_point.absolute_change == 25.0
    assert second_point.growth_rate is None


@pytest.mark.parametrize(
    "request_columns",
    [("missing", "value"), ("period", "missing")],
)
def test_calculate_growth_rejects_unknown_columns(request_columns) -> None:
    result = run_python_analysis(
        columns=("period", "value"),
        rows=(("2018-01", 100), ("2018-02", 120)),
        request=PythonAnalysisRequest("calculate_growth", request_columns),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "unknown_column"


def test_calculate_growth_rejects_non_numeric_value() -> None:
    result = run_python_analysis(
        columns=("period", "value"),
        rows=(("2018-01", 100), ("2018-02", "120")),
        request=PythonAnalysisRequest("calculate_growth", ("period", "value")),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "non_numeric_column"


def test_calculate_growth_rejects_null_period() -> None:
    result = run_python_analysis(
        columns=("period", "value"),
        rows=(("2018-01", 100), (None, 120)),
        request=PythonAnalysisRequest("calculate_growth", ("period", "value")),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_period_column"


def test_calculate_growth_rejects_insufficient_period_rows() -> None:
    result = run_python_analysis(
        columns=("period", "value"),
        rows=(("2018-01", 100),),
        request=PythonAnalysisRequest("calculate_growth", ("period", "value")),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "insufficient_data"


@pytest.mark.parametrize(
    "periods",
    [
        (("January 2018", 100), ("February 2018", 120)),
        (("2018-1", 100), ("2018-02", 120)),
        (("0000-01", 100), ("0000-02", 120)),
        (("2018-01", 100), (date(2018, 2, 1), 120)),
        (("2018-01", 100), ("2018-01", 120)),
    ],
)
def test_calculate_growth_rejects_unreliable_period_representation(periods) -> None:
    result = run_python_analysis(
        columns=("period", "value"),
        rows=periods,
        request=PythonAnalysisRequest("calculate_growth", ("period", "value")),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_period_column"


def test_calculate_growth_requires_exactly_two_analysis_columns() -> None:
    result = run_python_analysis(
        columns=("period", "value", "extra"),
        rows=(("2018-01", 100, 1), ("2018-02", 120, 2)),
        request=PythonAnalysisRequest(
            "calculate_growth",
            ("period", "value", "extra"),
        ),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_argument"
