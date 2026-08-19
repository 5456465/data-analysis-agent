"""Thin orchestration from an English question to read-only SQL results."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from data_analysis_agent.schema import DatabaseSchema, inspect_schema
from data_analysis_agent.sql_executor import (
    DEFAULT_MAX_ROWS,
    SQLExecutionError,
    SQLResult,
    run_readonly_sql,
)
from data_analysis_agent.sql_generator import (
    SQLGenerationError,
    TextToSQLModel,
    generate_sql,
)


QuestionAnswerStatus = Literal["success", "generation_error", "execution_error"]


@dataclass(frozen=True)
class QuestionAnswerResult:
    """Structured result for generation followed by read-only execution."""

    question: str
    generated_sql: str | None
    status: QuestionAnswerStatus
    execution_result: SQLResult | None
    generation_error: SQLGenerationError | None
    execution_error: SQLExecutionError | None


def answer_question(
    database_path: str | Path,
    question: str,
    model: TextToSQLModel,
    max_rows: int = DEFAULT_MAX_ROWS,
    *,
    schema: DatabaseSchema | None = None,
) -> QuestionAnswerResult:
    """Generate SQL once, execute it once in read-only mode, and return both stages."""

    database_schema = schema if schema is not None else inspect_schema(database_path)
    generation_result = generate_sql(question, database_schema, model)
    if generation_result.status == "error":
        return QuestionAnswerResult(
            question=generation_result.question,
            generated_sql=generation_result.sql,
            status="generation_error",
            execution_result=None,
            generation_error=generation_result.error,
            execution_error=None,
        )

    generated_sql = cast(str, generation_result.sql)
    execution_result = run_readonly_sql(database_path, generated_sql, max_rows)
    if execution_result.status == "error":
        return QuestionAnswerResult(
            question=generation_result.question,
            generated_sql=generated_sql,
            status="execution_error",
            execution_result=execution_result,
            generation_error=None,
            execution_error=execution_result.error,
        )

    return QuestionAnswerResult(
        question=generation_result.question,
        generated_sql=generated_sql,
        status="success",
        execution_result=execution_result,
        generation_error=None,
        execution_error=None,
    )
