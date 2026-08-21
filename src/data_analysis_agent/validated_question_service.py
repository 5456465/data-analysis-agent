"""Thin integration of multi-tool execution and deterministic validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from data_analysis_agent.multi_tool_service import (
    ANALYSIS_MAX_ROWS,
    MultiToolQuestionResult,
    answer_question_with_tools,
)
from data_analysis_agent.result_validation import (
    ResultValidation,
    validate_multi_tool_result,
)
from data_analysis_agent.schema import DatabaseSchema
from data_analysis_agent.sql_executor import DEFAULT_MAX_ROWS
from data_analysis_agent.sql_generator import TextToSQLModel


@dataclass(frozen=True)
class ValidatedQuestionResult:
    """One unchanged multi-tool result and its read-only validation."""

    result: MultiToolQuestionResult
    validation: ResultValidation


def answer_question_with_validation(
    database_path: str | Path,
    question: str,
    model: TextToSQLModel,
    max_rows: int = DEFAULT_MAX_ROWS,
    *,
    analysis_max_rows: int = ANALYSIS_MAX_ROWS,
    schema: DatabaseSchema | None = None,
) -> ValidatedQuestionResult:
    """Execute the existing workflow once, then validate its result once."""

    result = answer_question_with_tools(
        database_path,
        question,
        model,
        max_rows=max_rows,
        analysis_max_rows=analysis_max_rows,
        schema=schema,
    )
    validation = validate_multi_tool_result(result)
    return ValidatedQuestionResult(result=result, validation=validation)
