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
from data_analysis_agent.sql_repair import SQLRepairError, repair_sql


MAX_SQL_REPAIR_ATTEMPTS = 1
REPAIRABLE_SQL_ERROR_CODES = frozenset(
    {"invalid_sql", "unknown_table_or_column", "execution_error"}
)

QuestionAnswerStatus = Literal[
    "success",
    "generation_error",
    "repair_error",
    "execution_error",
]


@dataclass(frozen=True)
class QuestionAnswerResult:
    """Structured result for generation followed by read-only execution."""

    question: str
    generated_sql: str | None
    status: QuestionAnswerStatus
    execution_result: SQLResult | None
    generation_error: SQLGenerationError | None
    execution_error: SQLExecutionError | None
    repaired_sql: str | None = None
    repair_attempted: bool = False
    repair_error: SQLRepairError | None = None


def answer_question(
    database_path: str | Path,
    question: str,
    model: TextToSQLModel,
    max_rows: int = DEFAULT_MAX_ROWS,
    *,
    schema: DatabaseSchema | None = None,
) -> QuestionAnswerResult:
    """Generate and execute SQL, with at most one repair and re-execution."""

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
    if execution_result.status == "success":
        return QuestionAnswerResult(
            question=generation_result.question,
            generated_sql=generated_sql,
            status="success",
            execution_result=execution_result,
            generation_error=None,
            execution_error=None,
        )

    initial_execution_error = execution_result.error
    if (
        initial_execution_error is None
        or initial_execution_error.code not in REPAIRABLE_SQL_ERROR_CODES
    ):
        return QuestionAnswerResult(
            question=generation_result.question,
            generated_sql=generated_sql,
            status="execution_error",
            execution_result=execution_result,
            generation_error=None,
            execution_error=initial_execution_error,
        )

    repair_result = repair_sql(
        generation_result.question,
        database_schema,
        generated_sql,
        initial_execution_error,
        model,
    )
    if repair_result.status == "error":
        return QuestionAnswerResult(
            question=generation_result.question,
            generated_sql=generated_sql,
            status="repair_error",
            execution_result=execution_result,
            generation_error=None,
            execution_error=initial_execution_error,
            repaired_sql=None,
            repair_attempted=True,
            repair_error=repair_result.error,
        )

    repaired_sql = cast(str, repair_result.repaired_sql)
    repaired_execution = run_readonly_sql(database_path, repaired_sql, max_rows)
    if repaired_execution.status == "error":
        return QuestionAnswerResult(
            question=generation_result.question,
            generated_sql=generated_sql,
            status="execution_error",
            execution_result=repaired_execution,
            generation_error=None,
            execution_error=repaired_execution.error,
            repaired_sql=repaired_sql,
            repair_attempted=True,
            repair_error=None,
        )

    return QuestionAnswerResult(
        question=generation_result.question,
        generated_sql=generated_sql,
        status="success",
        execution_result=repaired_execution,
        generation_error=None,
        execution_error=None,
        repaired_sql=repaired_sql,
        repair_attempted=True,
        repair_error=None,
    )
