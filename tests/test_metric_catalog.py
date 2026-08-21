"""Tests for the governed deterministic Semantic Layer V2 context."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from data_analysis_agent.analysis_planner import build_python_analysis_plan_prompt
from data_analysis_agent.metric_catalog import (
    BUSINESS_SEMANTICS_V1,
    METRIC_DEFINITIONS_V2,
    QUERY_CONSTRAINTS_V2,
    MetricDefinition,
    QueryConstraintDefinition,
    format_business_semantics_context,
    format_semantic_layer_context,
)
from data_analysis_agent.schema import ColumnSchema, DatabaseSchema, SchemaObject
from data_analysis_agent.sql_generator import build_text_to_sql_prompt


SCHEMA = DatabaseSchema(
    objects=(
        SchemaObject(
            name="orders",
            object_type="table",
            grain="one row per order",
            columns=(
                ColumnSchema("order_id", "VARCHAR", False, True),
                ColumnSchema("order_status", "VARCHAR", False, False),
                ColumnSchema("order_purchase_timestamp", "TIMESTAMP", True, False),
                ColumnSchema(
                    "order_delivered_customer_date", "TIMESTAMP", True, False
                ),
            ),
        ),
    )
)


def _metric(identifier: str) -> MetricDefinition:
    return next(
        metric for metric in METRIC_DEFINITIONS_V2 if metric.identifier == identifier
    )


def test_v2_metrics_have_stable_unique_identifiers() -> None:
    identifiers = tuple(metric.identifier for metric in METRIC_DEFINITIONS_V2)

    assert identifiers == (
        "average_review_score",
        "average_items_per_order",
        "average_delivery_duration_days",
    )
    assert len(identifiers) == len(set(identifiers))


def test_metric_definition_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        _metric("average_review_score").label = "Changed"


def test_query_constraint_definition_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        QUERY_CONSTRAINTS_V2[0].label = "Changed"


def test_metric_and_query_constraint_use_distinct_contracts() -> None:
    assert isinstance(METRIC_DEFINITIONS_V2[0], MetricDefinition)
    assert isinstance(QUERY_CONSTRAINTS_V2[0], QueryConstraintDefinition)
    assert not isinstance(METRIC_DEFINITIONS_V2[0], QueryConstraintDefinition)


def test_semantic_layer_formatter_is_deterministic() -> None:
    assert format_semantic_layer_context() == format_semantic_layer_context()


def test_formatter_is_independent_of_collection_order() -> None:
    context = format_semantic_layer_context()

    assert context == format_semantic_layer_context(
        tuple(reversed(METRIC_DEFINITIONS_V2)),
        tuple(reversed(QUERY_CONSTRAINTS_V2)),
    )


def test_average_review_score_uses_review_record_grain() -> None:
    metric = _metric("average_review_score")

    assert metric.grain == "one review record"
    assert "AVG(review_score) at review-record grain" in metric.aggregation
    assert "individual order_reviews review records" in metric.definition


def test_average_review_score_rejects_implicit_order_level_aggregation() -> None:
    instructions = " ".join(_metric("average_review_score").instructions)

    assert "Do not aggregate reviews to order grain" in instructions
    assert "average of order-level average review scores" in instructions


def test_average_items_per_order_denominator_is_all_orders() -> None:
    metric = _metric("average_items_per_order")

    assert metric.population.startswith("All orders")
    assert "divided by total number of orders" in metric.aggregation
    assert "Use all rows in orders as the denominator" in " ".join(
        metric.instructions
    )


def test_average_items_per_order_includes_zero_item_orders() -> None:
    metric = _metric("average_items_per_order")

    assert "zero matching order-item records" in metric.population
    assert "means zero items" in metric.null_semantics
    assert "does not remove the order from the denominator" in metric.null_semantics


def test_average_items_per_order_expresses_left_join_or_equivalent_semantics() -> None:
    instructions = " ".join(_metric("average_items_per_order").instructions)

    assert "LEFT JOIN or a mathematically equivalent calculation" in instructions
    assert "only the distinct orders that have matching item facts" in instructions


def test_delivery_duration_requires_both_non_null_timestamps() -> None:
    population = _metric("average_delivery_duration_days").population

    assert "order_purchase_timestamp IS NOT NULL" in population
    assert "order_delivered_customer_date IS NOT NULL" in population


def test_delivery_duration_uses_exact_seconds_divided_by_86400() -> None:
    metric = _metric("average_delivery_duration_days")

    assert "DATE_DIFF('second'" in metric.aggregation
    assert "/ 86400.0" in metric.aggregation
    assert "AVG the per-order duration_days values" in metric.aggregation
    assert "continuous elapsed seconds / 86400.0" in metric.time_semantics


def test_delivery_duration_rejects_integer_calendar_day_difference() -> None:
    instructions = " ".join(
        _metric("average_delivery_duration_days").instructions
    )

    assert "Do not use DATEDIFF('day', start, end)" in instructions
    assert "integer calendar-day boundary count" in instructions
    assert "Do not ROUND, FLOOR, or cast duration to integer days" in instructions


def test_delivery_duration_missing_timestamps_are_not_zero() -> None:
    null_semantics = _metric("average_delivery_duration_days").null_semantics

    assert "excluded" in null_semantics
    assert "never treat it as zero days" in null_semantics
    assert "fill a missing timestamp" in null_semantics


def test_delivery_duration_does_not_implicitly_filter_delivered_status() -> None:
    instructions = " ".join(
        _metric("average_delivery_duration_days").instructions
    )

    assert "Do not automatically add order_status = 'delivered'" in instructions
    assert "only when the user explicitly requests it" in instructions


def test_explicit_top_bottom_n_semantics_are_preserved() -> None:
    constraint = QUERY_CONSTRAINTS_V2[0]
    instructions = " ".join(constraint.instructions)

    assert constraint.identifier == "explicit_top_bottom_n"
    assert "only the requested N rows" in constraint.definition
    assert "descending order for Top-N and ascending order for Bottom-N" in instructions
    assert "LIMIT or a mathematically equivalent bounded ranking" in instructions


def test_backward_compatible_formatter_defaults_to_v2_context() -> None:
    assert format_business_semantics_context() == format_semantic_layer_context()
    assert "average_delivery_duration_days" in format_business_semantics_context()


def test_backward_compatible_formatter_accepts_v1_collection() -> None:
    context = format_business_semantics_context(BUSINESS_SEMANTICS_V1)

    assert "average_review_score" in context
    assert "explicit_top_bottom_n" in context


def test_sql_generator_prompt_contains_delivery_duration_v2_context() -> None:
    prompt = build_text_to_sql_prompt(
        "What is the average delivery duration in days?",
        SCHEMA,
    )

    assert "METRIC average_delivery_duration_days" in prompt
    assert "DATE_DIFF('second'" in prompt
    assert "/ 86400.0" in prompt
    assert "Do not use DATEDIFF('day', start, end)" in prompt


def test_analysis_planner_prompt_contains_delivery_duration_v2_context() -> None:
    prompt = build_python_analysis_plan_prompt(
        "How did average delivery duration change month over month?",
        SCHEMA,
        "calculate_growth",
    )

    assert "METRIC average_delivery_duration_days" in prompt
    assert "DATE_DIFF('second'" in prompt
    assert "Do not automatically add order_status = 'delivered'" in prompt


def test_formatter_excludes_secrets_and_runtime_information() -> None:
    context = format_semantic_layer_context().lower()

    assert "api key" not in context
    assert "deepseek" not in context
    assert "prompt secret" not in context
    assert "runtime" not in context
