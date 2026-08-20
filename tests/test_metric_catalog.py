"""Tests for deterministic Metric Catalog / Business Semantics V1 context."""

from __future__ import annotations

from data_analysis_agent.metric_catalog import (
    BUSINESS_SEMANTICS_V1,
    format_business_semantics_context,
)


def test_business_semantics_v1_has_stable_unique_identifiers() -> None:
    identifiers = tuple(rule.identifier for rule in BUSINESS_SEMANTICS_V1)

    assert identifiers == (
        "average_review_score",
        "average_items_per_order",
        "explicit_top_bottom_n",
    )
    assert len(identifiers) == len(set(identifiers))


def test_business_semantics_context_is_deterministic() -> None:
    reversed_semantics = tuple(reversed(BUSINESS_SEMANTICS_V1))

    context = format_business_semantics_context(BUSINESS_SEMANTICS_V1)

    assert context == format_business_semantics_context(reversed_semantics)
    assert context.index("average_items_per_order") < context.index(
        "average_review_score"
    )
    assert context.index("average_review_score") < context.index(
        "explicit_top_bottom_n"
    )


def test_business_semantics_context_contains_required_grain_rules() -> None:
    context = format_business_semantics_context()

    assert (
        "Average of review_score across individual order_reviews review records"
        in context
    )
    assert "Do not aggregate reviews to order grain before averaging" in context
    assert "Use all rows in orders as the denominator" in context
    assert "including orders with zero matching order-item records" in context
    assert "LEFT JOIN or a mathematically equivalent calculation" in context
    assert "descending order for Top-N and ascending order for Bottom-N" in context
    assert (
        "Keep the requested N with LIMIT or an equivalent bounded ranking" in context
    )
