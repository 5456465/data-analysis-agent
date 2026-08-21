"""Deterministic numeric analysis over already-structured tabular data."""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal, TypeAlias

from data_analysis_agent.observability import observed_stage


PythonAnalysisStatus = Literal["success", "error"]
PythonAnalysisErrorCode = Literal[
    "invalid_argument",
    "unknown_column",
    "non_numeric_column",
    "insufficient_data",
    "zero_variance",
    "unsupported_operation",
    "invalid_period_column",
]

GrowthPeriod: TypeAlias = str | date | datetime
_YEAR_MONTH_PATTERN = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


@dataclass(frozen=True)
class PythonAnalysisRequest:
    """One explicitly supported analysis operation and its target columns."""

    operation: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class ColumnDescription:
    """Basic descriptive statistics for one numeric column."""

    column: str
    count: int
    mean: float
    std: float
    min: float
    median: float
    max: float


@dataclass(frozen=True)
class CorrelationResult:
    """Pearson correlation calculated from paired non-NULL values."""

    x_column: str
    y_column: str
    correlation: float
    paired_count: int


@dataclass(frozen=True)
class GrowthPoint:
    """One chronologically ordered period-over-period growth observation."""

    period: GrowthPeriod
    value: float
    previous_value: float | None
    absolute_change: float | None
    growth_rate: float | None


@dataclass(frozen=True)
class GrowthResult:
    """Complete ordered growth series, including its first baseline period."""

    points: tuple[GrowthPoint, ...]
    period_count: int


PythonAnalysisPayload: TypeAlias = (
    tuple[ColumnDescription, ...] | CorrelationResult | GrowthResult
)


@dataclass(frozen=True)
class PythonAnalysisError:
    """Structured expected error from a controlled analysis operation."""

    code: PythonAnalysisErrorCode
    message: str


@dataclass(frozen=True)
class PythonAnalysisResult:
    """Stable result for one controlled Python analysis operation."""

    operation: str
    status: PythonAnalysisStatus
    result: PythonAnalysisPayload | None
    error: PythonAnalysisError | None


@observed_stage("python_analysis")
def run_python_analysis(
    columns: Sequence[str],
    rows: Sequence[Sequence[object]],
    request: PythonAnalysisRequest,
) -> PythonAnalysisResult:
    """Run one supported numeric operation without database or code execution."""

    if not isinstance(request, PythonAnalysisRequest):
        return _error_result(
            request,
            "invalid_argument",
            "request must be a PythonAnalysisRequest instance.",
        )
    if not isinstance(request.operation, str) or not request.operation.strip():
        return _error_result(
            request.operation,
            "invalid_argument",
            "operation must be a non-empty string.",
        )
    operation = request.operation
    if operation not in {"describe", "correlation", "calculate_growth"}:
        return _error_result(
            operation,
            "unsupported_operation",
            f"Unsupported Python analysis operation: {operation}",
        )
    if (
        not isinstance(request.columns, tuple)
        or not request.columns
        or any(not isinstance(column, str) or not column for column in request.columns)
        or len(request.columns) != len(set(request.columns))
    ):
        return _error_result(
            operation,
            "invalid_argument",
            "request columns must be a non-empty tuple of unique column names.",
        )

    normalized_table = _normalize_table(columns, rows)
    if isinstance(normalized_table, PythonAnalysisError):
        return PythonAnalysisResult(operation, "error", None, normalized_table)
    column_names, table_rows = normalized_table

    unknown_columns = tuple(
        column for column in request.columns if column not in column_names
    )
    if unknown_columns:
        return _error_result(
            operation,
            "unknown_column",
            f"Unknown column: {unknown_columns[0]}",
        )

    if operation == "describe":
        return _describe(column_names, table_rows, request.columns)
    if operation == "calculate_growth":
        if len(request.columns) != 2:
            return _error_result(
                operation,
                "invalid_argument",
                "calculate_growth requires exactly a period column and a value column.",
            )
        return _calculate_growth(
            column_names,
            table_rows,
            request.columns[0],
            request.columns[1],
        )
    if len(request.columns) != 2:
        return _error_result(
            operation,
            "invalid_argument",
            "correlation requires exactly two distinct columns.",
        )
    return _correlation(
        column_names,
        table_rows,
        request.columns[0],
        request.columns[1],
    )


def _normalize_table(
    columns: object,
    rows: object,
) -> tuple[tuple[str, ...], tuple[tuple[object, ...], ...]] | PythonAnalysisError:
    if (
        not isinstance(columns, Sequence)
        or isinstance(columns, (str, bytes))
        or not columns
        or any(not isinstance(column, str) or not column for column in columns)
        or len(columns) != len(set(columns))
    ):
        return PythonAnalysisError(
            "invalid_argument",
            "columns must be a non-empty sequence of unique column names.",
        )
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return PythonAnalysisError(
            "invalid_argument",
            "rows must be a sequence of row sequences.",
        )

    column_names = tuple(columns)
    normalized_rows: list[tuple[object, ...]] = []
    for row in rows:
        if (
            not isinstance(row, Sequence)
            or isinstance(row, (str, bytes))
            or len(row) != len(column_names)
        ):
            return PythonAnalysisError(
                "invalid_argument",
                "every row must contain exactly one value per column.",
            )
        normalized_rows.append(tuple(row))
    return column_names, tuple(normalized_rows)


def _describe(
    column_names: tuple[str, ...],
    rows: tuple[tuple[object, ...], ...],
    requested_columns: tuple[str, ...],
) -> PythonAnalysisResult:
    descriptions: list[ColumnDescription] = []
    for column in requested_columns:
        values_or_error = _numeric_column_values(column_names, rows, column)
        if isinstance(values_or_error, PythonAnalysisError):
            return PythonAnalysisResult("describe", "error", None, values_or_error)
        values = values_or_error
        if len(values) < 2:
            return _error_result(
                "describe",
                "insufficient_data",
                f"Column {column} requires at least two non-NULL numeric values.",
            )
        descriptions.append(
            ColumnDescription(
                column=column,
                count=len(values),
                mean=statistics.fmean(values),
                std=statistics.stdev(values),
                min=min(values),
                median=statistics.median(values),
                max=max(values),
            )
        )
    return PythonAnalysisResult(
        operation="describe",
        status="success",
        result=tuple(descriptions),
        error=None,
    )


def _correlation(
    column_names: tuple[str, ...],
    rows: tuple[tuple[object, ...], ...],
    x_column: str,
    y_column: str,
) -> PythonAnalysisResult:
    x_index = column_names.index(x_column)
    y_index = column_names.index(y_column)
    x_values: list[float] = []
    y_values: list[float] = []

    for row in rows:
        x_value = row[x_index]
        y_value = row[y_index]
        for column, value in ((x_column, x_value), (y_column, y_value)):
            if value is not None and not _is_finite_number(value):
                return _error_result(
                    "correlation",
                    "non_numeric_column",
                    f"Column {column} contains a non-numeric value.",
                )
        if x_value is None or y_value is None:
            continue
        x_values.append(float(x_value))
        y_values.append(float(y_value))

    if len(x_values) < 2:
        return _error_result(
            "correlation",
            "insufficient_data",
            "correlation requires at least two paired non-NULL numeric rows.",
        )
    if _has_zero_variance(x_values):
        return _error_result(
            "correlation",
            "zero_variance",
            f"Column {x_column} has zero variance in the paired rows.",
        )
    if _has_zero_variance(y_values):
        return _error_result(
            "correlation",
            "zero_variance",
            f"Column {y_column} has zero variance in the paired rows.",
        )

    return PythonAnalysisResult(
        operation="correlation",
        status="success",
        result=CorrelationResult(
            x_column=x_column,
            y_column=y_column,
            correlation=statistics.correlation(x_values, y_values),
            paired_count=len(x_values),
        ),
        error=None,
    )


def _calculate_growth(
    column_names: tuple[str, ...],
    rows: tuple[tuple[object, ...], ...],
    period_column: str,
    value_column: str,
) -> PythonAnalysisResult:
    period_index = column_names.index(period_column)
    value_index = column_names.index(value_column)
    normalized_rows: list[tuple[tuple[int, ...], GrowthPeriod, float]] = []
    period_kind: str | None = None

    for row in rows:
        period = row[period_index]
        normalized_period = _normalize_period(period)
        if normalized_period is None:
            return _error_result(
                "calculate_growth",
                "invalid_period_column",
                f"Column {period_column} contains an unsupported or NULL period value.",
            )
        current_kind, sort_key, output_period = normalized_period

        value = row[value_index]
        if value is None:
            continue
        if not _is_finite_number(value):
            return _error_result(
                "calculate_growth",
                "non_numeric_column",
                f"Column {value_column} contains a non-numeric value.",
            )

        if period_kind is None:
            period_kind = current_kind
        elif current_kind != period_kind:
            return _error_result(
                "calculate_growth",
                "invalid_period_column",
                f"Column {period_column} mixes incompatible period representations.",
            )
        normalized_rows.append((sort_key, output_period, float(value)))

    if len(normalized_rows) < 2:
        return _error_result(
            "calculate_growth",
            "insufficient_data",
            "calculate_growth requires at least two valid numeric observations.",
        )

    normalized_rows.sort(key=lambda item: item[0])
    if any(
        current[0] == previous[0]
        for previous, current in zip(normalized_rows, normalized_rows[1:])
    ):
        return _error_result(
            "calculate_growth",
            "invalid_period_column",
            f"Column {period_column} contains duplicate periods.",
        )

    points: list[GrowthPoint] = []
    uses_calendar_month_continuity = period_kind == "year_month" or (
        period_kind in {"date", "datetime", "aware_datetime"}
        and all(
            isinstance(period, (date, datetime)) and period.day == 1
            for _, period, _ in normalized_rows
        )
    )
    previous_value: float | None = None
    previous_sort_key: tuple[int, ...] | None = None
    for sort_key, period, value in normalized_rows:
        has_comparable_previous = previous_sort_key is not None
        if (
            has_comparable_previous
            and uses_calendar_month_continuity
            and not _is_next_calendar_month(previous_sort_key, sort_key)
        ):
            has_comparable_previous = False

        if not has_comparable_previous:
            point_previous_value = None
            absolute_change = None
            growth_rate = None
        else:
            point_previous_value = previous_value
            assert point_previous_value is not None
            absolute_change = value - point_previous_value
            growth_rate = (
                None
                if point_previous_value == 0
                else absolute_change / point_previous_value
            )
        points.append(
            GrowthPoint(
                period=period,
                value=value,
                previous_value=point_previous_value,
                absolute_change=absolute_change,
                growth_rate=growth_rate,
            )
        )
        previous_value = value
        previous_sort_key = sort_key

    return PythonAnalysisResult(
        operation="calculate_growth",
        status="success",
        result=GrowthResult(points=tuple(points), period_count=len(points)),
        error=None,
    )


def _normalize_period(
    value: object,
) -> tuple[str, tuple[int, ...], GrowthPeriod] | None:
    if isinstance(value, datetime):
        offset = value.utcoffset()
        if offset is not None:
            normalized = value.astimezone(timezone.utc).replace(tzinfo=None)
            kind = "aware_datetime"
        else:
            normalized = value
            kind = "datetime"
        return (
            kind,
            (
                normalized.year,
                normalized.month,
                normalized.day,
                normalized.hour,
                normalized.minute,
                normalized.second,
                normalized.microsecond,
            ),
            value,
        )
    if isinstance(value, date):
        return "date", (value.year, value.month, value.day), value
    if isinstance(value, str):
        match = _YEAR_MONTH_PATTERN.fullmatch(value)
        if match is None:
            return None
        year = int(match.group(1))
        month = int(match.group(2))
        if year == 0:
            return None
        return "year_month", (year, month), value
    return None


def _is_next_calendar_month(
    previous: tuple[int, ...],
    current: tuple[int, ...],
) -> bool:
    previous_year, previous_month = previous[:2]
    expected = (
        (previous_year + 1, 1)
        if previous_month == 12
        else (previous_year, previous_month + 1)
    )
    return current[:2] == expected


def _numeric_column_values(
    column_names: tuple[str, ...],
    rows: tuple[tuple[object, ...], ...],
    column: str,
) -> tuple[float, ...] | PythonAnalysisError:
    index = column_names.index(column)
    values: list[float] = []
    for row in rows:
        value = row[index]
        if value is None:
            continue
        if not _is_finite_number(value):
            return PythonAnalysisError(
                "non_numeric_column",
                f"Column {column} contains a non-numeric value.",
            )
        values.append(float(value))
    return tuple(values)


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float, Decimal))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _has_zero_variance(values: Sequence[float]) -> bool:
    return all(value == values[0] for value in values[1:])


def _error_result(
    operation: object,
    code: PythonAnalysisErrorCode,
    message: str,
) -> PythonAnalysisResult:
    if isinstance(operation, PythonAnalysisRequest):
        operation_name = (
            operation.operation
            if isinstance(operation.operation, str)
            else repr(operation.operation)
        )
    else:
        operation_name = operation if isinstance(operation, str) else repr(operation)
    return PythonAnalysisResult(
        operation=operation_name,
        status="error",
        result=None,
        error=PythonAnalysisError(code=code, message=message),
    )
