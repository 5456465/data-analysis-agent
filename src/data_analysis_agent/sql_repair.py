"""Single-attempt SQL repair generation without SQL execution."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from data_analysis_agent.observability import observed_stage
from data_analysis_agent.schema import DatabaseSchema
from data_analysis_agent.sql_executor import SQLExecutionError
from data_analysis_agent.sql_generator import (
    ModelOutput,
    TextToSQLModel,
    format_schema_context,
)


SQLRepairStatus = Literal["success", "error"]
SQLRepairErrorCode = Literal[
    "invalid_argument",
    "model_error",
    "invalid_model_output",
    "cannot_repair",
]


@dataclass(frozen=True)
class SQLRepairError:
    """Structured error returned when SQL repair does not succeed."""

    code: SQLRepairErrorCode
    message: str


@dataclass(frozen=True)
class SQLRepairResult:
    """Stable result of generating, but not executing, one repaired SQL query."""

    question: str
    original_sql: str
    repaired_sql: str | None
    status: SQLRepairStatus
    error: SQLRepairError | None


def build_sql_repair_prompt(
    question: str,
    schema: DatabaseSchema,
    original_sql: str,
    execution_error: SQLExecutionError,
) -> str:
    """Build an English prompt for one deterministic SQL repair request."""

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string.")
    if not isinstance(schema, DatabaseSchema):
        raise TypeError("schema must be a DatabaseSchema instance.")
    if not isinstance(original_sql, str) or not original_sql.strip():
        raise ValueError("original_sql must be a non-empty string.")
    if not isinstance(execution_error, SQLExecutionError):
        raise TypeError("execution_error must be a SQLExecutionError instance.")

    schema_context = format_schema_context(schema)
    return f"""You repair DuckDB SQL for the Olist analytics database.

The original SQL failed during read-only execution. Repair only the SQL using the execution error and provided schema.

Rules:
- Use only tables, views, and columns present in the schema context.
- Generate exactly one read-only DuckDB query: SELECT or WITH ... SELECT.
- Do not invent tables or columns.
- Do not read external files or use external resources.
- Repair the SQL only; do not answer or explain the user's question.
- Put only SQL in the sql field; do not use Markdown fences.
- If the SQL cannot be repaired reliably, return a structured error and do not fabricate SQL.

Return exactly one JSON object in one of these forms:
{{"status":"success","sql":"SELECT ..."}}
{{"status":"error","error":"Reason the SQL cannot be repaired reliably."}}

Original question:
{question}

Original SQL:
{original_sql}

Execution error:
{execution_error.code}: {execution_error.message}

Schema context:
{schema_context}
"""


@observed_stage("sql_repair")
def repair_sql(
    question: str,
    schema: DatabaseSchema,
    original_sql: str,
    execution_error: SQLExecutionError,
    model: TextToSQLModel,
) -> SQLRepairResult:
    """Ask the model for one repaired SQL query without executing it."""

    argument_error = _validate_arguments(
        question,
        schema,
        original_sql,
        execution_error,
        model,
    )
    if argument_error is not None:
        return argument_error

    prompt = build_sql_repair_prompt(
        question,
        schema,
        original_sql,
        execution_error,
    )
    try:
        model_output = model(prompt)
    except Exception as exc:
        return _error_result(question, original_sql, "model_error", str(exc))

    try:
        payload = _parse_model_output(model_output)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return _error_result(
            question,
            original_sql,
            "invalid_model_output",
            str(exc),
        )

    status = payload.get("status")
    if status == "success":
        repaired_sql = payload.get("sql")
        if not isinstance(repaired_sql, str) or not repaired_sql.strip():
            return _error_result(
                question,
                original_sql,
                "invalid_model_output",
                "Successful repair output must contain a non-empty sql string.",
            )
        return SQLRepairResult(
            question=question,
            original_sql=original_sql,
            repaired_sql=repaired_sql,
            status="success",
            error=None,
        )

    if status == "error":
        message = payload.get("error")
        if not isinstance(message, str) or not message.strip():
            return _error_result(
                question,
                original_sql,
                "invalid_model_output",
                "Error repair output must contain a non-empty error string.",
            )
        return _error_result(question, original_sql, "cannot_repair", message)

    return _error_result(
        question,
        original_sql,
        "invalid_model_output",
        "Repair output status must be 'success' or 'error'.",
    )


def _validate_arguments(
    question: object,
    schema: object,
    original_sql: object,
    execution_error: object,
    model: object,
) -> SQLRepairResult | None:
    if not isinstance(question, str) or not question.strip():
        return _error_result(
            question,
            original_sql,
            "invalid_argument",
            "question must be a non-empty string.",
        )
    if not isinstance(schema, DatabaseSchema):
        return _error_result(
            question,
            original_sql,
            "invalid_argument",
            "schema must be a DatabaseSchema instance.",
        )
    if not isinstance(original_sql, str) or not original_sql.strip():
        return _error_result(
            question,
            original_sql,
            "invalid_argument",
            "original_sql must be a non-empty string.",
        )
    if not isinstance(execution_error, SQLExecutionError):
        return _error_result(
            question,
            original_sql,
            "invalid_argument",
            "execution_error must be a SQLExecutionError instance.",
        )
    if not callable(model):
        return _error_result(
            question,
            original_sql,
            "invalid_argument",
            "model must be callable.",
        )
    return None


def _parse_model_output(output: ModelOutput) -> dict[str, object]:
    if isinstance(output, str):
        parsed = json.loads(output)
    elif isinstance(output, Mapping):
        parsed = dict(output)
    else:
        raise TypeError("Model output must be a JSON object or JSON object string.")

    if not isinstance(parsed, dict):
        raise ValueError("Model output must decode to a JSON object.")
    return parsed


def _error_result(
    question: object,
    original_sql: object,
    code: SQLRepairErrorCode,
    message: str,
) -> SQLRepairResult:
    return SQLRepairResult(
        question=question if isinstance(question, str) else repr(question),
        original_sql=(
            original_sql if isinstance(original_sql, str) else repr(original_sql)
        ),
        repaired_sql=None,
        status="error",
        error=SQLRepairError(code=code, message=message),
    )
