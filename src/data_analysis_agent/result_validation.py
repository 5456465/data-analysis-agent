"""Deterministic structural validation of completed multi-tool results."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from data_analysis_agent.multi_tool_service import MultiToolQuestionResult
from data_analysis_agent.python_analysis import (
    ColumnDescription,
    CorrelationResult,
    GrowthResult,
    PythonAnalysisResult,
)
from data_analysis_agent.sql_executor import SQLResult


ValidationSeverity = Literal["warning", "error"]
ValidationStatus = Literal["valid", "valid_with_warnings", "invalid"]
_YEAR_MONTH_PATTERN = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


@dataclass(frozen=True)
class ValidationIssue:
    """One deterministic warning or error found in a completed result."""

    code: str
    severity: ValidationSeverity
    message: str


@dataclass(frozen=True)
class ResultValidation:
    """Structural validation outcome for one multi-tool result."""

    status: ValidationStatus
    issues: tuple[ValidationIssue, ...]


def validate_multi_tool_result(result: MultiToolQuestionResult) -> ResultValidation:
    """Validate a completed result without executing, repairing, or mutating it."""

    if not isinstance(result, MultiToolQuestionResult):
        raise TypeError("result must be a MultiToolQuestionResult instance.")

    if result.status != "success":
        detail = (
            f"{result.error.code}: {result.error.message}"
            if result.error is not None
            else "no structured error was provided"
        )
        return _validation(
            [
                ValidationIssue(
                    code="unsuccessful_pipeline",
                    severity="error",
                    message=f"Pipeline ended at {result.status}: {detail}",
                )
            ]
        )

    issues: list[ValidationIssue] = []
    route = result.route_decision.route
    if route == "sql_only":
        if result.sql_result is None:
            issues.append(
                ValidationIssue(
                    "missing_sql_result",
                    "error",
                    "Successful SQL_ONLY result must include a final SQLResult.",
                )
            )
        else:
            issues.extend(_validate_sql_result(result.sql_result))
        return _validation(issues)

    if route == "sql_then_python":
        if result.sql_result is None:
            issues.append(
                ValidationIssue(
                    "missing_sql_result",
                    "error",
                    "Successful SQL_THEN_PYTHON result must include a SQLResult.",
                )
            )
        else:
            issues.extend(_validate_sql_result(result.sql_result))

        if result.python_result is None:
            issues.append(
                ValidationIssue(
                    "missing_python_result",
                    "error",
                    "Successful SQL_THEN_PYTHON result must include a PythonAnalysisResult.",
                )
            )
        else:
            issues.extend(
                _validate_python_result(
                    result.route_decision.python_operation,
                    result.python_result,
                )
            )
        return _validation(issues)

    issues.append(
        ValidationIssue(
            "unsupported_success_route",
            "error",
            f"Successful result has no supported route: {route!r}.",
        )
    )
    return _validation(issues)


def _validate_sql_result(result: SQLResult) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if result.status != "success":
        detail = (
            f"{result.error.code}: {result.error.message}"
            if result.error is not None
            else "no structured error was provided"
        )
        issues.append(
            ValidationIssue(
                "unsuccessful_sql_result",
                "error",
                f"Final SQLResult is not successful: {detail}",
            )
        )

    if not result.columns:
        issues.append(
            ValidationIssue(
                "missing_columns",
                "error",
                "SQLResult must contain at least one column.",
            )
        )
    else:
        if any(not isinstance(column, str) or not column.strip() for column in result.columns):
            issues.append(
                ValidationIssue(
                    "invalid_column_name",
                    "error",
                    "SQLResult column names must be non-empty strings.",
                )
            )
        if any(
            column in result.columns[:index]
            for index, column in enumerate(result.columns)
        ):
            issues.append(
                ValidationIssue(
                    "duplicate_columns",
                    "error",
                    "SQLResult column names must be unique.",
                )
            )

    expected_width = len(result.columns)
    for row_index, row in enumerate(result.rows, start=1):
        if len(row) != expected_width:
            issues.append(
                ValidationIssue(
                    "row_width_mismatch",
                    "error",
                    f"SQLResult row {row_index} has width {len(row)}; expected {expected_width}.",
                )
            )
            continue
        for column_index, value in enumerate(row, start=1):
            if _is_numeric(value) and not _is_finite_number(value):
                issues.append(
                    ValidationIssue(
                        "non_finite_sql_value",
                        "error",
                        "SQLResult contains a non-finite numeric value at "
                        f"row {row_index}, column {column_index}.",
                    )
                )

    if result.truncated:
        issues.append(
            ValidationIssue(
                "truncated_result",
                "error",
                "SQLResult is truncated and is not safe to present as complete.",
            )
        )
    if not result.rows:
        issues.append(
            ValidationIssue(
                "empty_result",
                "warning",
                "SQLResult contains no rows.",
            )
        )
    return issues


def _validate_python_result(
    expected_operation: str | None,
    result: PythonAnalysisResult,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if result.status != "success":
        detail = (
            f"{result.error.code}: {result.error.message}"
            if result.error is not None
            else "no structured error was provided"
        )
        issues.append(
            ValidationIssue(
                "unsuccessful_python_result",
                "error",
                f"Final PythonAnalysisResult is not successful: {detail}",
            )
        )

    if expected_operation != result.operation:
        issues.append(
            ValidationIssue(
                "python_operation_mismatch",
                "error",
                f"Route selected {expected_operation!r}, but Python result used {result.operation!r}.",
            )
        )

    payload = result.result
    if payload is None:
        issues.append(
            ValidationIssue(
                "missing_python_payload",
                "error",
                "Successful Python analysis must contain a result payload.",
            )
        )
        return issues

    payload_matches = False
    if expected_operation == "describe":
        payload_matches = isinstance(payload, tuple) and all(
            isinstance(item, ColumnDescription) for item in payload
        )
    elif expected_operation == "correlation":
        payload_matches = isinstance(payload, CorrelationResult)
    elif expected_operation == "calculate_growth":
        payload_matches = isinstance(payload, GrowthResult)

    if not payload_matches:
        issues.append(
            ValidationIssue(
                "python_payload_mismatch",
                "error",
                f"Python payload is incompatible with operation {expected_operation!r}.",
            )
        )
        return issues

    if isinstance(payload, GrowthResult):
        issues.extend(_validate_growth_result(payload))
    return issues


def _validate_growth_result(result: GrowthResult) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if result.period_count < 0:
        issues.append(
            ValidationIssue(
                "invalid_growth_period_count",
                "error",
                "GrowthResult period_count must be non-negative.",
            )
        )
    if result.period_count != len(result.points):
        issues.append(
            ValidationIssue(
                "growth_period_count_mismatch",
                "error",
                "GrowthResult period_count must equal the number of points.",
            )
        )

    period_keys: list[tuple[str, tuple[int, ...]]] = []
    for point_index, point in enumerate(result.points, start=1):
        period_key = _period_sort_key(point.period)
        if period_key is None:
            issues.append(
                ValidationIssue(
                    "invalid_growth_period",
                    "error",
                    f"Growth point {point_index} has a missing or unsupported period.",
                )
            )
        else:
            period_keys.append(period_key)

        for field_name in (
            "value",
            "previous_value",
            "absolute_change",
            "growth_rate",
        ):
            value = getattr(point, field_name)
            if value is not None and not _is_finite_number(value):
                issues.append(
                    ValidationIssue(
                        "non_finite_growth_value",
                        "error",
                        f"Growth point {point_index} field {field_name} must be finite numeric.",
                    )
                )

    if len(period_keys) == len(result.points) and any(
        current_kind != previous_kind or current_key <= previous_key
        for (previous_kind, previous_key), (current_kind, current_key) in zip(
            period_keys,
            period_keys[1:],
        )
    ):
        issues.append(
            ValidationIssue(
                "unordered_growth_periods",
                "error",
                "GrowthResult periods must be strictly increasing and non-duplicate.",
            )
        )
    return issues


def _period_sort_key(value: object) -> tuple[str, tuple[int, ...]] | None:
    if isinstance(value, datetime):
        if value.utcoffset() is not None:
            normalized = value.astimezone(timezone.utc).replace(tzinfo=None)
            kind = "aware_datetime"
        else:
            normalized = value
            kind = "datetime"
        return kind, (
            normalized.year,
            normalized.month,
            normalized.day,
            normalized.hour,
            normalized.minute,
            normalized.second,
            normalized.microsecond,
        )
    if isinstance(value, date):
        return "date", (value.year, value.month, value.day)
    if isinstance(value, str):
        match = _YEAR_MONTH_PATTERN.fullmatch(value)
        if match is not None and int(match.group(1)) > 0:
            return "year_month", (int(match.group(1)), int(match.group(2)))
    return None


def _is_numeric(value: object) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _is_finite_number(value: object) -> bool:
    if not _is_numeric(value):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _validation(issues: list[ValidationIssue]) -> ResultValidation:
    frozen_issues = tuple(issues)
    if any(issue.severity == "error" for issue in frozen_issues):
        status: ValidationStatus = "invalid"
    elif frozen_issues:
        status = "valid_with_warnings"
    else:
        status = "valid"
    return ResultValidation(status=status, issues=frozen_issues)
