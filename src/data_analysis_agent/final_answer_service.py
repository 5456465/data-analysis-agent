"""Thin integration of validated execution and optional answer presentation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from data_analysis_agent.answer_synthesis import (
    AnswerSynthesis,
    Locale,
    synthesize_answer,
)
from data_analysis_agent.multi_tool_service import ANALYSIS_MAX_ROWS
from data_analysis_agent.natural_language_answer import (
    NaturalLanguageAnswer,
    NaturalLanguageModel,
    generate_natural_language_answer,
)
from data_analysis_agent.schema import DatabaseSchema
from data_analysis_agent.sql_executor import DEFAULT_MAX_ROWS
from data_analysis_agent.sql_generator import TextToSQLModel
from data_analysis_agent.validated_question_service import (
    ValidatedQuestionResult,
    answer_question_with_validation,
)


@dataclass(frozen=True)
class FinalAnswerResult:
    """Validated evidence, deterministic synthesis, and optional narrative."""

    validated_result: ValidatedQuestionResult
    synthesis: AnswerSynthesis
    natural_language_answer: NaturalLanguageAnswer | None = None


def answer_question_for_user(
    database_path: str | Path,
    question: str,
    model: TextToSQLModel,
    max_rows: int = DEFAULT_MAX_ROWS,
    *,
    analysis_max_rows: int = ANALYSIS_MAX_ROWS,
    schema: DatabaseSchema | None = None,
    locale: Locale = "en",
    natural_language_model: NaturalLanguageModel | None = None,
) -> FinalAnswerResult:
    """Execute and validate once, then optionally add one narrative."""

    validated_result = answer_question_with_validation(
        database_path,
        question,
        model,
        max_rows=max_rows,
        analysis_max_rows=analysis_max_rows,
        schema=schema,
    )
    synthesis = synthesize_answer(validated_result, locale=locale)
    natural_language_answer = (
        generate_natural_language_answer(
            question,
            validated_result.validation.status,
            synthesis,
            natural_language_model,
            locale,
        )
        if natural_language_model is not None
        else None
    )
    return FinalAnswerResult(
        validated_result=validated_result,
        synthesis=synthesis,
        natural_language_answer=natural_language_answer,
    )
