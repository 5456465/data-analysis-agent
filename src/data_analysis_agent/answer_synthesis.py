"""Deterministic, evidence-bound formatting of validated Agent results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from data_analysis_agent.python_analysis import (
    ColumnDescription,
    CorrelationResult,
    GrowthResult,
)
from data_analysis_agent.validated_question_service import ValidatedQuestionResult


AnswerSynthesisStatus = Literal["success", "blocked"]


@dataclass(frozen=True)
class AnswerSynthesis:
    """Stable user-facing text derived only from validated evidence."""

    status: AnswerSynthesisStatus
    answer: str
    warnings: tuple[str, ...]


def synthesize_answer(
    validated_result: ValidatedQuestionResult,
) -> AnswerSynthesis:
    """Format existing evidence without execution, repair, or interpretation."""

    if not isinstance(validated_result, ValidatedQuestionResult):
        raise TypeError("validated_result must be a ValidatedQuestionResult instance.")

    warnings = tuple(
        issue.message
        for issue in validated_result.validation.issues
        if issue.severity == "warning"
    )
    if validated_result.validation.status == "invalid":
        return AnswerSynthesis(
            status="blocked",
            answer=_blocked_validation_message(validated_result),
            warnings=warnings,
        )

    result = validated_result.result
    if result.route_decision.route == "sql_only" and result.sql_result is not None:
        return AnswerSynthesis(
            status="success",
            answer=_format_sql_result(result.sql_result.columns, result.sql_result.rows),
            warnings=warnings,
        )

    if (
        result.route_decision.route == "sql_then_python"
        and result.python_result is not None
    ):
        answer = _format_python_payload(result.python_result.result)
        if answer is not None:
            return AnswerSynthesis("success", answer, warnings)

    return AnswerSynthesis(
        status="blocked",
        answer="Unsupported result payload for answer synthesis.",
        warnings=warnings,
    )


def _blocked_validation_message(validated_result: ValidatedQuestionResult) -> str:
    result = validated_result.result
    lines = [
        "Result did not pass validation; a reliable final answer cannot be generated."
    ]
    if result.error is not None:
        lines.append(f"Stage: {result.status}")
        lines.append(f"Error: {result.error.code}: {result.error.message}")
    else:
        first_error = next(
            (
                issue
                for issue in validated_result.validation.issues
                if issue.severity == "error"
            ),
            None,
        )
        if first_error is not None:
            lines.append(
                f"Validation error: {first_error.code}: {first_error.message}"
            )
    return "\n".join(lines)


def _format_sql_result(
    columns: tuple[str, ...],
    rows: tuple[tuple[object, ...], ...],
) -> str:
    if len(columns) == 1 and len(rows) == 1:
        return f"Result: {_format_value(rows[0][0])}"

    lines = [" | ".join(columns)]
    lines.extend(" | ".join(_format_value(value) for value in row) for row in rows)
    return "\n".join(lines)


def _format_python_payload(payload: object) -> str | None:
    if (
        isinstance(payload, tuple)
        and payload
        and all(isinstance(item, ColumnDescription) for item in payload)
    ):
        return _format_descriptions(payload)
    if isinstance(payload, CorrelationResult):
        return (
            f"Correlation: {payload.correlation}\n"
            f"Paired rows: {payload.paired_count}"
        )
    if isinstance(payload, GrowthResult):
        return _format_growth_result(payload)
    return None


def _format_descriptions(descriptions: tuple[ColumnDescription, ...]) -> str:
    blocks = []
    for description in descriptions:
        blocks.append(
            "\n".join(
                (
                    f"Column: {description.column}",
                    f"Count: {description.count}",
                    f"Mean: {description.mean}",
                    f"Sample std: {description.std}",
                    f"Min: {description.min}",
                    f"Median: {description.median}",
                    f"Max: {description.max}",
                )
            )
        )
    return "\n\n".join(blocks)


def _format_growth_result(result: GrowthResult) -> str:
    lines = ["Period | Value | Previous | Absolute Change | Growth Rate"]
    for point in result.points:
        lines.append(
            " | ".join(
                _format_value(value)
                for value in (
                    point.period,
                    point.value,
                    point.previous_value,
                    point.absolute_change,
                    point.growth_rate,
                )
            )
        )
    lines.append(f"Period count: {result.period_count}")
    return "\n".join(lines)


def _format_value(value: object) -> str:
    return "NULL" if value is None else str(value)
