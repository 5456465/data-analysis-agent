"""Minimal English Text-to-SQL generation without SQL execution."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias

from data_analysis_agent.metric_catalog import format_business_semantics_context
from data_analysis_agent.observability import observed_stage
from data_analysis_agent.schema import DatabaseSchema


SQLGenerationStatus = Literal["success", "error"]
SQLGenerationErrorCode = Literal[
    "invalid_argument",
    "model_error",
    "invalid_model_output",
    "cannot_generate",
]

ModelOutput: TypeAlias = str | Mapping[str, object]


class TextToSQLModel(Protocol):
    """Callable boundary implemented by a provider adapter or a test fake."""

    def __call__(self, prompt: str) -> ModelOutput: ...


@dataclass(frozen=True)
class SQLGenerationError:
    """Structured error returned when SQL generation does not succeed."""

    code: SQLGenerationErrorCode
    message: str


@dataclass(frozen=True)
class SQLGenerationResult:
    """Stable result of generating, but not executing, one SQL query."""

    question: str
    sql: str | None
    status: SQLGenerationStatus
    error: SQLGenerationError | None


def format_schema_context(schema: DatabaseSchema) -> str:
    """Format an existing schema as compact, deterministic English context."""

    if not isinstance(schema, DatabaseSchema):
        raise TypeError("schema must be a DatabaseSchema instance.")

    blocks: list[str] = []
    for schema_object in sorted(schema.objects, key=lambda item: item.name):
        lines = [f"{schema_object.object_type.upper()} {schema_object.name}"]
        if schema_object.grain is not None:
            lines.append(f"Grain: {schema_object.grain}")
        lines.append("Columns:")
        lines.extend(
            f"- {column.name}: {column.data_type}"
            for column in schema_object.columns
        )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_text_to_sql_prompt(question: str, schema: DatabaseSchema) -> str:
    """Build the English prompt used for one structured SQL generation call."""

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string.")

    schema_context = format_schema_context(schema)
    business_semantics_context = format_business_semantics_context()
    return f"""You generate DuckDB SQL for the Olist analytics database.

Generate one read-only DuckDB SQL query that answers the user's question using only the provided schema.

Rules:
- Use only tables, views, and columns present in the schema context.
- Generate exactly one query.
- The query must be read-only and must be SELECT or WITH ... SELECT.
- Do not invent tables or columns.
- Do not read external files or use external resources.
- Put only SQL in the sql field; do not put explanations or Markdown fences there.
- If the question cannot be answered reliably from the provided schema and data capability, do not fabricate SQL.

Return exactly one JSON object in one of these forms:
{{"status":"success","sql":"SELECT ..."}}
{{"status":"error","error":"Reason the SQL cannot be generated reliably."}}

Business semantics context:
{business_semantics_context}

Schema context:
{schema_context}

User question:
{question}
"""


@observed_stage("sql_generation")
def generate_sql(
    question: str,
    schema: DatabaseSchema,
    model: TextToSQLModel,
) -> SQLGenerationResult:
    """Generate structured SQL with one model call and no database execution."""

    if not isinstance(question, str) or not question.strip():
        return _error_result(
            question,
            "invalid_argument",
            "question must be a non-empty string.",
        )
    if not isinstance(schema, DatabaseSchema):
        return _error_result(
            question,
            "invalid_argument",
            "schema must be a DatabaseSchema instance.",
        )
    if not callable(model):
        return _error_result(
            question,
            "invalid_argument",
            "model must be callable.",
        )

    prompt = build_text_to_sql_prompt(question, schema)
    try:
        model_output = model(prompt)
    except Exception as exc:
        return _error_result(question, "model_error", str(exc))

    try:
        payload = _parse_model_output(model_output)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return _error_result(question, "invalid_model_output", str(exc))

    status = payload.get("status")
    if status == "success":
        sql = payload.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            return _error_result(
                question,
                "invalid_model_output",
                "Successful model output must contain a non-empty sql string.",
            )
        return SQLGenerationResult(
            question=question,
            sql=sql,
            status="success",
            error=None,
        )

    if status == "error":
        message = payload.get("error")
        if not isinstance(message, str) or not message.strip():
            return _error_result(
                question,
                "invalid_model_output",
                "Error model output must contain a non-empty error string.",
            )
        return _error_result(question, "cannot_generate", message)

    return _error_result(
        question,
        "invalid_model_output",
        "Model output status must be 'success' or 'error'.",
    )


def _parse_model_output(output: object) -> dict[str, object]:
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
    code: SQLGenerationErrorCode,
    message: str,
) -> SQLGenerationResult:
    return SQLGenerationResult(
        question=question if isinstance(question, str) else repr(question),
        sql=None,
        status="error",
        error=SQLGenerationError(code=code, message=message),
    )
