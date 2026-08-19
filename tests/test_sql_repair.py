"""Tests for single-attempt structured SQL repair generation."""

from __future__ import annotations

from data_analysis_agent.schema import ColumnSchema, DatabaseSchema, SchemaObject
from data_analysis_agent.sql_executor import SQLExecutionError
from data_analysis_agent.sql_repair import (
    SQLRepairError,
    SQLRepairResult,
    build_sql_repair_prompt,
    repair_sql,
)


QUESTION = "How many orders are in the dataset?"
ORIGINAL_SQL = "SELECT COUNT(*) FROM orderz"
REPAIRED_SQL = "SELECT COUNT(*) FROM orders"
SCHEMA = DatabaseSchema(
    objects=(
        SchemaObject(
            name="orders",
            object_type="table",
            grain="one row per order",
            columns=(ColumnSchema("order_id", "VARCHAR", False, True),),
        ),
    )
)
EXECUTION_ERROR = SQLExecutionError(
    code="unknown_table_or_column",
    message='Table with name "orderz" does not exist.',
)


def test_repair_prompt_contains_question_sql_error_schema_and_safety_rules() -> None:
    prompt = build_sql_repair_prompt(
        QUESTION,
        SCHEMA,
        ORIGINAL_SQL,
        EXECUTION_ERROR,
    )

    assert f"Original question:\n{QUESTION}" in prompt
    assert f"Original SQL:\n{ORIGINAL_SQL}" in prompt
    assert "Execution error:\nunknown_table_or_column" in prompt
    assert 'Table with name "orderz" does not exist.' in prompt
    assert "TABLE orders" in prompt
    assert "- order_id: VARCHAR" in prompt
    assert "SELECT or WITH ... SELECT" in prompt
    assert "Do not read external files" in prompt
    assert "do not answer or explain" in prompt
    assert "JSON object" in prompt


def test_repair_success_returns_sql_unchanged() -> None:
    result = repair_sql(
        QUESTION,
        SCHEMA,
        ORIGINAL_SQL,
        EXECUTION_ERROR,
        lambda prompt: {"status": "success", "sql": REPAIRED_SQL},
    )

    assert result == SQLRepairResult(
        question=QUESTION,
        original_sql=ORIGINAL_SQL,
        repaired_sql=REPAIRED_SQL,
        status="success",
        error=None,
    )


def test_model_decline_returns_cannot_repair() -> None:
    result = repair_sql(
        QUESTION,
        SCHEMA,
        ORIGINAL_SQL,
        EXECUTION_ERROR,
        lambda prompt: {"status": "error", "error": "Insufficient schema."},
    )

    assert result.status == "error"
    assert result.repaired_sql is None
    assert result.error == SQLRepairError(
        code="cannot_repair",
        message="Insufficient schema.",
    )


def test_malformed_repair_output_returns_structured_error() -> None:
    result = repair_sql(
        QUESTION,
        SCHEMA,
        ORIGINAL_SQL,
        EXECUTION_ERROR,
        lambda prompt: "not json",
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_model_output"


def test_repair_model_exception_returns_structured_error() -> None:
    def failing_model(prompt: str):
        raise RuntimeError("provider unavailable")

    result = repair_sql(
        QUESTION,
        SCHEMA,
        ORIGINAL_SQL,
        EXECUTION_ERROR,
        failing_model,
    )

    assert result.status == "error"
    assert result.error == SQLRepairError(
        code="model_error",
        message="provider unavailable",
    )
