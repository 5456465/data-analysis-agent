"""Tests for controlled deterministic Python numeric analysis."""

from __future__ import annotations

import pytest

from data_analysis_agent.python_analysis import (
    ColumnDescription,
    CorrelationResult,
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
