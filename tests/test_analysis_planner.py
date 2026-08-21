"""Tests for SQL-to-Python analysis plan generation."""

from __future__ import annotations

import json

import pytest

from data_analysis_agent.analysis_planner import (
    PythonAnalysisPlan,
    PythonAnalysisPlanError,
    build_python_analysis_plan_prompt,
    generate_python_analysis_plan,
)
from data_analysis_agent.metric_catalog import format_business_semantics_context
from data_analysis_agent.schema import ColumnSchema, DatabaseSchema, SchemaObject


SCHEMA = DatabaseSchema(
    objects=(
        SchemaObject(
            name="order_items",
            object_type="table",
            grain="one row per order item",
            columns=(
                ColumnSchema("order_id", "VARCHAR", False, False),
                ColumnSchema("price", "DECIMAL(12,2)", False, False),
                ColumnSchema("freight_value", "DECIMAL(12,2)", False, False),
            ),
        ),
        SchemaObject(
            name="order_payments",
            object_type="table",
            grain="one row per payment record",
            columns=(
                ColumnSchema("order_id", "VARCHAR", False, False),
                ColumnSchema("payment_value", "DECIMAL(12,2)", False, False),
            ),
        ),
        SchemaObject(
            name="orders",
            object_type="table",
            grain="one row per order",
            columns=(
                ColumnSchema("order_id", "VARCHAR", False, True),
                ColumnSchema(
                    "order_purchase_timestamp",
                    "TIMESTAMP",
                    False,
                    False,
                ),
            ),
        ),
    )
)


def _success_output(sql: str, columns: list[object]) -> dict[str, object]:
    return {
        "status": "success",
        "sql": sql,
        "python_columns": columns,
    }


def test_correlation_plan_returns_retrieval_sql_and_two_columns() -> None:
    sql = "SELECT price, freight_value FROM order_items"

    result = generate_python_analysis_plan(
        "What is the correlation between item price and freight value?",
        SCHEMA,
        "correlation",
        lambda prompt: json.dumps(_success_output(sql, ["price", "freight_value"])),
    )

    assert result == PythonAnalysisPlan(
        question="What is the correlation between item price and freight value?",
        python_operation="correlation",
        sql=sql,
        python_columns=("price", "freight_value"),
        status="success",
        error=None,
    )


def test_correlation_plan_rejects_sql_corr_function() -> None:
    result = generate_python_analysis_plan(
        "What is the correlation between item price and freight value?",
        SCHEMA,
        "correlation",
        lambda prompt: _success_output(
            "SELECT CORR(price, freight_value) AS correlation FROM order_items",
            ["price", "freight_value"],
        ),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_analysis_plan"
    assert "corr" in result.error.message


@pytest.mark.parametrize(
    "columns",
    [["price"], ["price", "freight_value", "order_id"]],
)
def test_correlation_plan_requires_exactly_two_columns(columns: list[str]) -> None:
    result = generate_python_analysis_plan(
        "What is the correlation between item price and freight value?",
        SCHEMA,
        "correlation",
        lambda prompt: _success_output(
            "SELECT price, freight_value FROM order_items",
            columns,
        ),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_analysis_plan"


def test_describe_plan_accepts_one_raw_numeric_column() -> None:
    sql = "SELECT payment_value FROM order_payments"

    result = generate_python_analysis_plan(
        "Give me descriptive statistics for payment value.",
        SCHEMA,
        "describe",
        lambda prompt: _success_output(sql, ["payment_value"]),
    )

    assert result.status == "success"
    assert result.sql == sql
    assert result.python_columns == ("payment_value",)


def test_describe_plan_accepts_multiple_raw_numeric_columns() -> None:
    result = generate_python_analysis_plan(
        "Describe item price and freight value.",
        SCHEMA,
        "describe",
        lambda prompt: _success_output(
            "SELECT price, freight_value FROM order_items",
            ["price", "freight_value"],
        ),
    )

    assert result.status == "success"
    assert result.python_columns == ("price", "freight_value")


def test_describe_plan_rejects_empty_python_columns() -> None:
    result = generate_python_analysis_plan(
        "Describe payment values.",
        SCHEMA,
        "describe",
        lambda prompt: _success_output(
            "SELECT payment_value FROM order_payments",
            [],
        ),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_analysis_plan"


def test_describe_plan_rejects_sql_summary_functions() -> None:
    result = generate_python_analysis_plan(
        "Describe payment values.",
        SCHEMA,
        "describe",
        lambda prompt: _success_output(
            "SELECT AVG(payment_value) AS payment_value FROM order_payments",
            ["payment_value"],
        ),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_analysis_plan"
    assert "avg" in result.error.message


def test_calculate_growth_plan_returns_ordered_period_value_series() -> None:
    sql = """
        SELECT
            DATE_TRUNC('month', o.order_purchase_timestamp) AS month,
            SUM(oi.price) AS total_item_transaction_value
        FROM orders AS o
        JOIN order_items AS oi ON o.order_id = oi.order_id
        GROUP BY month
        ORDER BY month
    """

    result = generate_python_analysis_plan(
        "How did total item transaction value change month over month?",
        SCHEMA,
        "calculate_growth",
        lambda prompt: _success_output(
            sql,
            ["month", "total_item_transaction_value"],
        ),
    )

    assert result.status == "success"
    assert result.sql == sql
    assert result.python_columns == ("month", "total_item_transaction_value")


@pytest.mark.parametrize("aggregate", ["SUM(price)", "AVG(price)", "COUNT(*)"])
def test_calculate_growth_plan_allows_sql_metric_aggregation(
    aggregate: str,
) -> None:
    sql = f"""
        SELECT
            DATE_TRUNC('month', o.order_purchase_timestamp) AS month,
            {aggregate} AS metric_value
        FROM orders AS o
        JOIN order_items AS oi ON o.order_id = oi.order_id
        GROUP BY month
        ORDER BY month
    """

    result = generate_python_analysis_plan(
        "How did the metric change month over month?",
        SCHEMA,
        "calculate_growth",
        lambda prompt: _success_output(sql, ["month", "metric_value"]),
    )

    assert result.status == "success"


def test_calculate_growth_plan_rejects_lag() -> None:
    sql = """
        SELECT
            month,
            metric_value - LAG(metric_value) OVER (ORDER BY month) AS metric_value
        FROM monthly_values
        ORDER BY month
    """

    result = generate_python_analysis_plan(
        "How did the metric change month over month?",
        SCHEMA,
        "calculate_growth",
        lambda prompt: _success_output(sql, ["month", "metric_value"]),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_analysis_plan"
    assert "lag" in result.error.message


@pytest.mark.parametrize(
    "derived_column",
    ["growth", "growth_rate", "percentage_change"],
)
def test_calculate_growth_plan_rejects_precomputed_growth_column(
    derived_column: str,
) -> None:
    sql = f"""
        SELECT
            month,
            metric_value AS {derived_column}
        FROM monthly_values
        ORDER BY month
    """

    result = generate_python_analysis_plan(
        "How did the metric change month over month?",
        SCHEMA,
        "calculate_growth",
        lambda prompt: _success_output(sql, ["month", derived_column]),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_analysis_plan"
    assert derived_column in result.error.message


def test_calculate_growth_plan_rejects_current_previous_arithmetic() -> None:
    sql = """
        SELECT
            current.month,
            current.metric_value - previous.metric_value AS metric_value
        FROM monthly_values AS current
        JOIN monthly_values AS previous
          ON current.month = previous.month + INTERVAL '1 month'
        ORDER BY current.month
    """

    result = generate_python_analysis_plan(
        "How did the metric change month over month?",
        SCHEMA,
        "calculate_growth",
        lambda prompt: _success_output(sql, ["month", "metric_value"]),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_analysis_plan"
    assert "current-versus-previous arithmetic" in result.error.message


@pytest.mark.parametrize(
    "columns",
    [["month"], ["month", "metric_value", "order_count"]],
)
def test_calculate_growth_plan_requires_exactly_two_columns(
    columns: list[str],
) -> None:
    result = generate_python_analysis_plan(
        "How did the metric change month over month?",
        SCHEMA,
        "calculate_growth",
        lambda prompt: _success_output(
            "SELECT month, metric_value FROM monthly_values ORDER BY month",
            columns,
        ),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_analysis_plan"


def test_calculate_growth_plan_requires_ordered_sql() -> None:
    result = generate_python_analysis_plan(
        "How did the metric change month over month?",
        SCHEMA,
        "calculate_growth",
        lambda prompt: _success_output(
            "SELECT month, metric_value FROM monthly_values",
            ["month", "metric_value"],
        ),
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_analysis_plan"
    assert "ORDER BY" in result.error.message


def test_malformed_json_returns_invalid_model_output() -> None:
    result = generate_python_analysis_plan(
        "Describe payment values.",
        SCHEMA,
        "describe",
        lambda prompt: "not json",
    )

    assert result.error is not None
    assert result.error.code == "invalid_model_output"


def test_missing_sql_returns_invalid_model_output() -> None:
    result = generate_python_analysis_plan(
        "Describe payment values.",
        SCHEMA,
        "describe",
        lambda prompt: {
            "status": "success",
            "python_columns": ["payment_value"],
        },
    )

    assert result.error is not None
    assert result.error.code == "invalid_model_output"


def test_missing_python_columns_returns_invalid_model_output() -> None:
    result = generate_python_analysis_plan(
        "Describe payment values.",
        SCHEMA,
        "describe",
        lambda prompt: {
            "status": "success",
            "sql": "SELECT payment_value FROM order_payments",
        },
    )

    assert result.error is not None
    assert result.error.code == "invalid_model_output"


def test_invalid_python_column_value_type_returns_invalid_model_output() -> None:
    result = generate_python_analysis_plan(
        "Describe payment values.",
        SCHEMA,
        "describe",
        lambda prompt: _success_output(
            "SELECT payment_value FROM order_payments",
            ["payment_value", 7],
        ),
    )

    assert result.error is not None
    assert result.error.code == "invalid_model_output"


def test_model_exception_returns_model_error() -> None:
    def failing_model(prompt: str):
        raise RuntimeError("provider unavailable")

    result = generate_python_analysis_plan(
        "Describe payment values.",
        SCHEMA,
        "describe",
        failing_model,
    )

    assert result.error == PythonAnalysisPlanError(
        code="model_error",
        message="provider unavailable",
    )


def test_unsupported_operation_is_rejected_without_calling_model() -> None:
    called = False

    def model(prompt: str):
        nonlocal called
        called = True
        return _success_output("SELECT price FROM order_items", ["price"])

    result = generate_python_analysis_plan(
        "Fit a regression model for item price.",
        SCHEMA,
        "regression",
        model,
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "unsupported_operation"
    assert called is False


def test_model_can_decline_to_generate_reliable_plan() -> None:
    result = generate_python_analysis_plan(
        "Describe product cost.",
        SCHEMA,
        "describe",
        lambda prompt: {
            "status": "error",
            "error": "The schema has no product cost field.",
        },
    )

    assert result.status == "error"
    assert result.error == PythonAnalysisPlanError(
        code="invalid_analysis_plan",
        message="The schema has no product cost field.",
    )


@pytest.mark.parametrize("question", ["", "   ", None])
def test_invalid_question_is_rejected_without_model_call(question) -> None:
    called = False

    def model(prompt: str):
        nonlocal called
        called = True
        return _success_output("SELECT price FROM order_items", ["price"])

    result = generate_python_analysis_plan(
        question,
        SCHEMA,
        "describe",
        model,
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_argument"
    assert called is False


@pytest.mark.parametrize(
    "operation",
    ["correlation", "describe", "calculate_growth"],
)
def test_prompt_contains_grounding_and_sql_python_contract(operation: str) -> None:
    question = "Analyze item price and freight value."

    prompt = build_python_analysis_plan_prompt(question, SCHEMA, operation)

    assert question in prompt
    assert f"Requested Python operation: {operation}" in prompt
    assert "TABLE order_items" in prompt
    assert "price: DECIMAL(12,2)" in prompt
    assert format_business_semantics_context() in prompt
    assert "SQL step only retrieves, joins, filters, projects" in prompt
    assert "Python performs the final analysis" in prompt
    assert "exactly one read-only SELECT or WITH ... SELECT" in prompt


def test_prompt_preserves_chinese_question_verbatim() -> None:
    question = "商品成交金额每个月的环比变化怎么样？"

    prompt = build_python_analysis_plan_prompt(
        question,
        SCHEMA,
        "calculate_growth",
    )

    assert question in prompt


def test_calculate_growth_prompt_defines_sql_python_boundary() -> None:
    prompt = build_python_analysis_plan_prompt(
        "How did total item transaction value change month over month?",
        SCHEMA,
        "calculate_growth",
    )

    assert "one chronologically ordered row per requested period" in prompt
    assert "period-value series" in prompt
    assert "first Python column is the period column" in prompt
    assert "second Python column is the aggregated numeric metric" in prompt
    assert "SUM, AVG, COUNT" in prompt
    assert "GROUP BY the period" in prompt
    assert "preserve the business metric's actual fact population" in prompt
    assert "Missing fact rows must not automatically become numeric zero" in prompt
    assert "Do not manufacture zero-valued periods with LEFT JOIN plus COALESCE" in prompt
    assert "business semantics explicitly require zero filling" in prompt
    assert "numeric metric column should represent valid metric observations" in prompt
    assert "A NULL metric observation means missing, not numeric zero" in prompt
    assert "prefer filtering that missing metric observation" in prompt
    assert "No specific JOIN type is required" in prompt
    assert "WHERE, HAVING, or fact-table-driven aggregation" in prompt
    assert "must not use LAG, LEAD" in prompt
    assert "Python calculate_growth owns previous_value" in prompt
