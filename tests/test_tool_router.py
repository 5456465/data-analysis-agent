"""Tests for minimal LLM-based tool routing decisions."""

from __future__ import annotations

import json

import pytest

from data_analysis_agent.tool_router import (
    ToolRouteDecision,
    ToolRoutingError,
    build_tool_routing_prompt,
    route_question,
)


@pytest.mark.parametrize(
    "question",
    [
        "How many orders are in the dataset?",
        "What is the average payment value per order?",
        "Give me descriptive statistics for payment values.",
        (
            "Give me summary statistics including mean, standard deviation, "
            "median, min, and max for item price."
        ),
        "What is the Pearson correlation between item price and freight value?",
        "What was total item transaction value by month?",
        "Show average payment value by month.",
        "List all customer states ranked by unique customer count.",
        "What percentage of orders contain multiple items?",
    ],
)
def test_sql_native_questions_route_to_sql_only(question: str) -> None:
    result = route_question(
        question,
        lambda prompt: json.dumps(
            {
                "status": "success",
                "route": "sql_only",
                "python_operation": None,
                "reason": "SQL can answer this aggregation directly.",
            }
        ),
    )

    assert result == ToolRouteDecision(
        question=question,
        route="sql_only",
        python_operation=None,
        reason="SQL can answer this aggregation directly.",
        status="success",
        error=None,
    )


def test_structured_sql_then_python_output_contract_remains_supported() -> None:
    result = route_question(
        "Apply a supported Python post-processing operation after SQL retrieval.",
        lambda prompt: {
            "status": "success",
            "route": "sql_then_python",
            "python_operation": "describe",
            "reason": "This request requires supported post-processing.",
        },
    )

    assert result.status == "success"
    assert result.route == "sql_then_python"
    assert result.python_operation == "describe"


@pytest.mark.parametrize(
    "question",
    [
        "How did total item transaction value change month over month?",
        (
            "Which month had the largest month-over-month decline in total "
            "item transaction value?"
        ),
    ],
)
def test_period_over_period_questions_route_to_calculate_growth(
    question: str,
) -> None:
    result = route_question(
        question,
        lambda prompt: {
            "status": "success",
            "route": "sql_then_python",
            "python_operation": "calculate_growth",
            "reason": "The final result requires consecutive-period analysis.",
        },
    )

    assert result.status == "success"
    assert result.route == "sql_then_python"
    assert result.python_operation == "calculate_growth"


def test_prompt_contains_question_and_explicit_tool_boundaries() -> None:
    question = "Describe order payment values."

    prompt = build_tool_routing_prompt(question)

    assert prompt == build_tool_routing_prompt(question)
    assert question in prompt
    assert "Prefer the smallest reliable tool chain" in prompt
    assert "directly, naturally, and efficiently produce the final" in prompt
    assert "Do not route to Python merely because Python supports" in prompt
    assert "Avoid unnecessary transfer of large raw datasets" in prompt
    assert "should use sql_only" in prompt
    assert "describe: descriptive statistics" in prompt
    assert "correlation: Pearson correlation" in prompt
    assert "calculate_growth: period-over-period change" in prompt
    assert "grouped by month or shown as a time trend" in prompt
    assert "Explicit month-over-month or period-over-period" in prompt
    assert "Python never accesses the database" in prompt
    assert "Regression, clustering, forecasting" in prompt
    assert "Do not generate SQL" in prompt


def test_prompt_preserves_chinese_question_verbatim() -> None:
    question = "商品成交金额每个月的环比变化怎么样？"

    assert question in build_tool_routing_prompt(question)


def test_prompt_contains_minimal_policy_examples() -> None:
    prompt = build_tool_routing_prompt("Route this question.")

    assert "How many orders are in the dataset?" in prompt
    assert "What is the average payment value per order?" in prompt
    assert "Give me descriptive statistics for payment values." in prompt
    assert (
        "What is the Pearson correlation between item price and freight value?"
        in prompt
    )
    assert "What was total item transaction value by month?" in prompt
    assert "How did total item transaction value change month over month?" in prompt
    assert "largest month-over-month decline" in prompt
    assert prompt.count("Decision: sql_only with python_operation null.") == 5
    assert (
        prompt.count(
            "Decision: sql_then_python with python_operation calculate_growth."
        )
        == 2
    )


def test_malformed_json_returns_invalid_model_output() -> None:
    result = route_question("How many orders are there?", lambda prompt: "not json")

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_model_output"


def test_malformed_field_type_returns_invalid_model_output() -> None:
    result = route_question(
        "How many orders are there?",
        lambda prompt: {
            "status": "success",
            "route": ["sql_only"],
            "python_operation": None,
            "reason": "SQL can answer this.",
        },
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_model_output"


def test_model_exception_returns_model_error() -> None:
    def failing_model(prompt: str):
        raise RuntimeError("provider unavailable")

    result = route_question("How many orders are there?", failing_model)

    assert result.error == ToolRoutingError(
        code="model_error",
        message="provider unavailable",
    )


def test_unsupported_route_returns_structured_error() -> None:
    result = route_question(
        "Create a forecast.",
        lambda prompt: {
            "status": "success",
            "route": "python_only",
            "python_operation": None,
            "reason": "Use Python.",
        },
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "unsupported_route"


def test_unsupported_python_operation_returns_structured_error() -> None:
    result = route_question(
        "Fit a regression model.",
        lambda prompt: {
            "status": "success",
            "route": "sql_then_python",
            "python_operation": "regression",
            "reason": "Run regression after SQL.",
        },
    )

    assert result.status == "error"
    assert result.error == ToolRoutingError(
        code="unsupported_route",
        message="Unsupported Python operation: 'regression'",
    )


def test_model_can_reject_request_with_no_supported_route() -> None:
    result = route_question(
        "Forecast next year's sales.",
        lambda prompt: {
            "status": "error",
            "error": "Forecasting is not supported by the available tools.",
        },
    )

    assert result.route is None
    assert result.python_operation is None
    assert result.error == ToolRoutingError(
        code="unsupported_route",
        message="Forecasting is not supported by the available tools.",
    )


@pytest.mark.parametrize("question", ["", "   ", None])
def test_invalid_question_is_rejected_without_calling_model(question) -> None:
    called = False

    def model(prompt: str):
        nonlocal called
        called = True
        return {"status": "success", "route": "sql_only", "reason": "SQL."}

    result = route_question(question, model)

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_argument"
    assert called is False


def test_sql_then_python_without_operation_is_invalid_model_output() -> None:
    result = route_question(
        "Describe order payment values.",
        lambda prompt: {
            "status": "success",
            "route": "sql_then_python",
            "python_operation": None,
            "reason": "Use Python after SQL.",
        },
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_model_output"


def test_routing_output_containing_sql_is_rejected() -> None:
    result = route_question(
        "How many orders are there?",
        lambda prompt: {
            "status": "success",
            "route": "sql_only",
            "python_operation": None,
            "reason": "Use SQL.",
            "sql": "SELECT COUNT(*) FROM orders",
        },
    )

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_model_output"
