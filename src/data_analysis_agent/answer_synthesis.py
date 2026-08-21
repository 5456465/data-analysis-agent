"""Deterministic, evidence-bound formatting of validated Agent results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from data_analysis_agent.observability import observed_stage
from data_analysis_agent.python_analysis import (
    ColumnDescription,
    CorrelationResult,
    GrowthResult,
)
from data_analysis_agent.validated_question_service import ValidatedQuestionResult


AnswerSynthesisStatus = Literal["success", "blocked"]
Locale = Literal["en", "zh-CN"]


@dataclass(frozen=True)
class AnswerSynthesis:
    """Stable user-facing text derived only from validated evidence."""

    status: AnswerSynthesisStatus
    answer: str
    warnings: tuple[str, ...]


@observed_stage("answer_synthesis")
def synthesize_answer(
    validated_result: ValidatedQuestionResult,
    locale: Locale = "en",
) -> AnswerSynthesis:
    """Format existing evidence without execution, repair, or interpretation."""

    if not isinstance(validated_result, ValidatedQuestionResult):
        raise TypeError("validated_result must be a ValidatedQuestionResult instance.")
    if locale not in {"en", "zh-CN"}:
        raise ValueError("locale must be 'en' or 'zh-CN'.")

    warnings = tuple(
        _warning_message(issue.code, issue.message, locale)
        for issue in validated_result.validation.issues
        if issue.severity == "warning"
    )
    if validated_result.validation.status == "invalid":
        return AnswerSynthesis(
            status="blocked",
            answer=_blocked_validation_message(validated_result, locale),
            warnings=warnings,
        )

    result = validated_result.result
    if result.route_decision.route == "sql_only" and result.sql_result is not None:
        return AnswerSynthesis(
            status="success",
            answer=_format_sql_result(
                result.sql_result.columns,
                result.sql_result.rows,
                locale,
            ),
            warnings=warnings,
        )

    if (
        result.route_decision.route == "sql_then_python"
        and result.python_result is not None
    ):
        answer = _format_python_payload(result.python_result.result, locale)
        if answer is not None:
            return AnswerSynthesis("success", answer, warnings)

    return AnswerSynthesis(
        status="blocked",
        answer=(
            "暂不支持该结果类型的答案展示。"
            if locale == "zh-CN"
            else "Unsupported result payload for answer synthesis."
        ),
        warnings=warnings,
    )


def _blocked_validation_message(
    validated_result: ValidatedQuestionResult,
    locale: Locale,
) -> str:
    result = validated_result.result
    lines = [
        (
            "结果未通过有效性校验，暂时无法生成可靠答案。"
            if locale == "zh-CN"
            else "Result did not pass validation; a reliable final answer cannot be generated."
        )
    ]
    if result.error is not None:
        if locale == "zh-CN":
            lines.append(f"阶段：{result.status}")
            lines.append(f"错误：{result.error.code}: {result.error.message}")
        else:
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
            prefix = "校验错误：" if locale == "zh-CN" else "Validation error: "
            lines.append(f"{prefix}{first_error.code}: {first_error.message}")
    return "\n".join(lines)


def _format_sql_result(
    columns: tuple[str, ...],
    rows: tuple[tuple[object, ...], ...],
    locale: Locale,
) -> str:
    if len(columns) == 1 and len(rows) == 1:
        prefix = "结果：" if locale == "zh-CN" else "Result: "
        return f"{prefix}{_format_value(rows[0][0])}"

    lines = [" | ".join(columns)]
    lines.extend(" | ".join(_format_value(value) for value in row) for row in rows)
    return "\n".join(lines)


def _format_python_payload(payload: object, locale: Locale) -> str | None:
    if (
        isinstance(payload, tuple)
        and payload
        and all(isinstance(item, ColumnDescription) for item in payload)
    ):
        return _format_descriptions(payload, locale)
    if isinstance(payload, CorrelationResult):
        if locale == "zh-CN":
            return (
                f"皮尔逊相关系数：{payload.correlation}\n"
                f"配对样本数：{payload.paired_count}"
            )
        return (
            f"Correlation: {payload.correlation}\n"
            f"Paired rows: {payload.paired_count}"
        )
    if isinstance(payload, GrowthResult):
        return _format_growth_result(payload, locale)
    return None


def _format_descriptions(
    descriptions: tuple[ColumnDescription, ...],
    locale: Locale,
) -> str:
    blocks = []
    for description in descriptions:
        if locale == "zh-CN":
            lines = (
                f"列：{description.column}",
                f"样本数：{description.count}",
                f"均值：{description.mean}",
                f"样本标准差：{description.std}",
                f"最小值：{description.min}",
                f"中位数：{description.median}",
                f"最大值：{description.max}",
            )
        else:
            lines = (
                f"Column: {description.column}",
                f"Count: {description.count}",
                f"Mean: {description.mean}",
                f"Sample std: {description.std}",
                f"Min: {description.min}",
                f"Median: {description.median}",
                f"Max: {description.max}",
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _format_growth_result(result: GrowthResult, locale: Locale) -> str:
    lines = [
        (
            "时间 | 当前值 | 上期值 | 绝对变化 | 环比变化率"
            if locale == "zh-CN"
            else "Period | Value | Previous | Absolute Change | Growth Rate"
        )
    ]
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
    count_label = "时间点数量：" if locale == "zh-CN" else "Period count: "
    lines.append(f"{count_label}{result.period_count}")
    return "\n".join(lines)


def _warning_message(code: str, message: str, locale: Locale) -> str:
    if locale == "zh-CN" and code == "empty_result":
        return "查询结果为空。"
    return message


def _format_value(value: object) -> str:
    return "NULL" if value is None else str(value)
