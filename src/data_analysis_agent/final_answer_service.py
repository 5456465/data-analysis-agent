"""Thin integration of validated execution and deterministic answer synthesis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from data_analysis_agent.answer_synthesis import AnswerSynthesis, synthesize_answer
from data_analysis_agent.multi_tool_service import ANALYSIS_MAX_ROWS
from data_analysis_agent.schema import DatabaseSchema
from data_analysis_agent.sql_executor import DEFAULT_MAX_ROWS
from data_analysis_agent.sql_generator import TextToSQLModel
from data_analysis_agent.validated_question_service import (
    ValidatedQuestionResult,
    answer_question_with_validation,
)


@dataclass(frozen=True)
class FinalAnswerResult:
    """One unchanged validated result and its user-facing synthesis."""

    validated_result: ValidatedQuestionResult
    synthesis: AnswerSynthesis


def answer_question_for_user(
    database_path: str | Path,
    question: str,
    model: TextToSQLModel,
    max_rows: int = DEFAULT_MAX_ROWS,
    *,
    analysis_max_rows: int = ANALYSIS_MAX_ROWS,
    schema: DatabaseSchema | None = None,
) -> FinalAnswerResult:
    """Execute and validate once, then synthesize once from that result."""

    validated_result = answer_question_with_validation(
        database_path,
        question,
        model,
        max_rows=max_rows,
        analysis_max_rows=analysis_max_rows,
        schema=schema,
    )
    synthesis = synthesize_answer(validated_result)
    return FinalAnswerResult(
        validated_result=validated_result,
        synthesis=synthesis,
    )
