"""Tests for minimal English Text-to-SQL generation."""

from __future__ import annotations

import json

from data_analysis_agent.schema import ColumnSchema, DatabaseSchema, SchemaObject
from data_analysis_agent.sql_generator import (
    SQLGenerationError,
    SQLGenerationResult,
    build_text_to_sql_prompt,
    format_schema_context,
    generate_sql,
)


SCHEMA = DatabaseSchema(
    objects=(
        SchemaObject(
            name="orders",
            object_type="table",
            grain="one row per order",
            columns=(
                ColumnSchema("order_id", "VARCHAR", False, True),
                ColumnSchema("order_status", "VARCHAR", False, False),
                ColumnSchema(
                    "order_purchase_timestamp", "TIMESTAMP", True, False
                ),
            ),
        ),
        SchemaObject(
            name="order_payment_summary",
            object_type="view",
            grain="one row per order",
            columns=(
                ColumnSchema("order_id", "VARCHAR", True, False),
                ColumnSchema("payment_value", "DECIMAL(38,2)", True, False),
            ),
        ),
    )
)


def test_normal_question_produces_structured_success_result() -> None:
    sql = "SELECT COUNT(*) AS order_count FROM orders"

    result = generate_sql(
        "How many orders are in the dataset?",
        SCHEMA,
        lambda prompt: {"status": "success", "sql": sql},
    )

    assert result == SQLGenerationResult(
        question="How many orders are in the dataset?",
        sql=sql,
        status="success",
        error=None,
    )


def test_schema_context_is_deterministic_and_contains_types_and_grain() -> None:
    reversed_schema = DatabaseSchema(objects=tuple(reversed(SCHEMA.objects)))

    context = format_schema_context(SCHEMA)

    assert context == format_schema_context(reversed_schema)
    assert "TABLE orders" in context
    assert "VIEW order_payment_summary" in context
    assert "Grain: one row per order" in context
    assert "- order_purchase_timestamp: TIMESTAMP" in context
    assert context.index("VIEW order_payment_summary") < context.index("TABLE orders")


def test_prompt_contains_question_and_real_schema_names_and_columns() -> None:
    question = "What is the average payment value per order?"

    prompt = build_text_to_sql_prompt(question, SCHEMA)

    assert question in prompt
    assert "order_payment_summary" in prompt
    assert "payment_value: DECIMAL(38,2)" in prompt
    assert "only tables, views, and columns present" in prompt
    assert "SELECT or WITH ... SELECT" in prompt


def test_prompt_does_not_include_gold_answers_or_baseline_sql() -> None:
    prompt = build_text_to_sql_prompt(
        "How many orders are in the dataset?",
        SCHEMA,
    )

    assert "99,441" not in prompt
    assert "99441" not in prompt
    assert "BASELINE_QUERIES" not in prompt
    assert "baseline_key" not in prompt
    assert "SELECT COUNT(*) AS total_orders FROM orders" not in prompt


def test_empty_question_is_rejected_without_calling_model() -> None:
    called = False

    def model(prompt: str):
        nonlocal called
        called = True
        return {"status": "success", "sql": "SELECT 1"}

    result = generate_sql("   ", SCHEMA, model)

    assert result.status == "error"
    assert result.error == SQLGenerationError(
        code="invalid_argument",
        message="question must be a non-empty string.",
    )
    assert result.sql is None
    assert called is False


def test_malformed_model_output_becomes_structured_error() -> None:
    result = generate_sql("How many orders are there?", SCHEMA, lambda prompt: "not json")

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_model_output"
    assert result.sql is None


def test_model_exception_becomes_structured_error() -> None:
    def failing_model(prompt: str):
        raise RuntimeError("provider unavailable")

    result = generate_sql("How many orders are there?", SCHEMA, failing_model)

    assert result.status == "error"
    assert result.error == SQLGenerationError(
        code="model_error",
        message="provider unavailable",
    )


def test_generated_sql_is_returned_unchanged_for_later_executor() -> None:
    sql = "\nWITH order_counts AS (\n  SELECT COUNT(*) AS value FROM orders\n)\nSELECT value FROM order_counts;\n"
    output = json.dumps({"status": "success", "sql": sql})

    result = generate_sql("How many orders are there?", SCHEMA, lambda prompt: output)

    assert result.status == "success"
    assert result.sql == sql


def test_model_can_decline_to_generate_unreliable_sql() -> None:
    reason = "The schema has no product cost field."

    result = generate_sql(
        "What is Olist's gross profit margin?",
        SCHEMA,
        lambda prompt: {"status": "error", "error": reason},
    )

    assert result.status == "error"
    assert result.sql is None
    assert result.error == SQLGenerationError(
        code="cannot_generate",
        message=reason,
    )
