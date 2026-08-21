"""Governed deterministic business semantics for model prompt context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias


SemanticKind = Literal["metric", "query_constraint"]


@dataclass(frozen=True)
class MetricDefinition:
    """Canonical governed meaning of one business metric."""

    identifier: str
    label: str
    definition: str
    grain: str
    population: str
    aggregation: str
    null_semantics: str
    time_semantics: str
    instructions: tuple[str, ...]


@dataclass(frozen=True)
class QueryConstraintDefinition:
    """Cross-cutting constraint on how a requested query returns results."""

    identifier: str
    label: str
    definition: str
    instructions: tuple[str, ...]


@dataclass(frozen=True)
class BusinessSemanticRule:
    """Backward-compatible V1 metric or query-constraint contract."""

    identifier: str
    kind: SemanticKind
    label: str
    definition: str
    grain: str
    instructions: tuple[str, ...]


METRIC_DEFINITIONS_V2: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        identifier="average_review_score",
        label="Average review score",
        definition=(
            "Average of review_score across individual order_reviews review records."
        ),
        grain="one review record",
        population=(
            "Individual order_reviews review records used by the requested query "
            "population."
        ),
        aggregation="AVG(review_score) at review-record grain.",
        null_semantics=(
            "NULL review_score is missing, not numeric zero; SQL AVG-style "
            "semantics may exclude NULL score observations."
        ),
        time_semantics=(
            "The metric has no inherent time grain; apply only the time population "
            "explicitly requested by the question."
        ),
        instructions=(
            "Treat each row in order_reviews as one review record.",
            "Do not aggregate reviews to order grain before averaging unless the "
            "user explicitly requests an order-level metric.",
            "Do not replace review-record averaging with an average of order-level "
            "average review scores.",
        ),
    ),
    MetricDefinition(
        identifier="average_items_per_order",
        label="Average items per order",
        definition=(
            "Total number of matching order-item records divided by the total "
            "number of orders."
        ),
        grain="one order after counting matching order-item records",
        population="All orders, including orders with zero matching order-item records.",
        aggregation=(
            "Total number of order-item records divided by total number of orders."
        ),
        null_semantics=(
            "Absence of matching order-item facts means zero items for that order; "
            "it does not remove the order from the denominator."
        ),
        time_semantics=(
            "When grouped by time, use the order time population requested by the "
            "question and retain eligible zero-item orders."
        ),
        instructions=(
            "Use all rows in orders as the denominator.",
            "Preserve zero-item orders with a LEFT JOIN or a mathematically "
            "equivalent calculation.",
            "Do not divide by only the distinct orders that have matching item facts.",
        ),
    ),
    MetricDefinition(
        identifier="average_delivery_duration_days",
        label="Average delivery duration in days",
        definition=(
            "Average exact elapsed delivery duration in days across eligible orders."
        ),
        grain="one eligible order before final averaging",
        population=(
            "Orders where order_purchase_timestamp IS NOT NULL and "
            "order_delivered_customer_date IS NOT NULL."
        ),
        aggregation=(
            "For each eligible order, calculate DATE_DIFF('second', "
            "order_purchase_timestamp, order_delivered_customer_date) / 86400.0; "
            "then AVG the per-order duration_days values."
        ),
        null_semantics=(
            "If either required timestamp is NULL, the order has no calculable "
            "delivery-duration observation and is excluded; never treat it as zero "
            "days or fill a missing timestamp."
        ),
        time_semantics=(
            "Days means continuous elapsed seconds / 86400.0, not calendar-date "
            "difference, business days, or integer whole days."
        ),
        instructions=(
            "Do not automatically add order_status = 'delivered'; apply that filter "
            "only when the user explicitly requests it.",
            "Do not use DATEDIFF('day', start, end) or another integer calendar-day "
            "boundary count as an equivalent calculation.",
            "Do not ROUND, FLOOR, or cast duration to integer days unless explicitly "
            "requested.",
            "For period analysis, calculate exact duration per eligible order before "
            "aggregating at the requested period grain.",
        ),
    ),
)


QUERY_CONSTRAINTS_V2: tuple[QueryConstraintDefinition, ...] = (
    QueryConstraintDefinition(
        identifier="explicit_top_bottom_n",
        label="Explicit Top-N or Bottom-N ranking",
        definition=(
            "A ranking request with an explicit N returns only the requested N rows."
        ),
        instructions=(
            "Order by the metric or target named in the question.",
            "Use descending order for Top-N and ascending order for Bottom-N.",
            "Keep the requested N with LIMIT or a mathematically equivalent bounded "
            "ranking; do not return the complete ranked list.",
        ),
    ),
)


# Retained as a public V1 compatibility surface. New prompt context uses the
# richer V2 collections above.
BUSINESS_SEMANTICS_V1: tuple[BusinessSemanticRule, ...] = (
    BusinessSemanticRule(
        identifier="average_review_score",
        kind="metric",
        label="Average review score",
        definition=(
            "Average of review_score across individual order_reviews review records."
        ),
        grain="review-record grain",
        instructions=(
            "Treat each row in order_reviews as one review record.",
            "Do not aggregate reviews to order grain before averaging unless the "
            "user explicitly requests order-level aggregation.",
        ),
    ),
    BusinessSemanticRule(
        identifier="average_items_per_order",
        kind="metric",
        label="Average items per order",
        definition=(
            "Total order-item record count divided by all orders, including orders "
            "with zero matching order-item records."
        ),
        grain="order grain after counting order-item records per order",
        instructions=(
            "Use all rows in orders as the denominator.",
            "Preserve zero-item orders with a LEFT JOIN or a mathematically "
            "equivalent calculation.",
        ),
    ),
    BusinessSemanticRule(
        identifier="explicit_top_bottom_n",
        kind="query_constraint",
        label="Explicit Top-N or Bottom-N ranking",
        definition=(
            "A ranking request with an explicit N returns only the requested N rows."
        ),
        grain="one row per ranked entity, bounded to the requested N",
        instructions=(
            "Order by the metric or target named in the question.",
            "Use descending order for Top-N and ascending order for Bottom-N.",
            "Keep the requested N with LIMIT or an equivalent bounded ranking; do "
            "not return the complete ranked list.",
        ),
    ),
)


SemanticDefinition: TypeAlias = (
    MetricDefinition | QueryConstraintDefinition | BusinessSemanticRule
)


def format_semantic_layer_context(
    metrics: tuple[MetricDefinition, ...] = METRIC_DEFINITIONS_V2,
    query_constraints: tuple[
        QueryConstraintDefinition, ...
    ] = QUERY_CONSTRAINTS_V2,
) -> str:
    """Format the governed V2 semantic layer in deterministic identifier order."""

    return _format_semantics((*metrics, *query_constraints))


def format_business_semantics_context(
    semantics: tuple[SemanticDefinition, ...] | None = None,
) -> str:
    """Backward-compatible formatter defaulting to the V2 semantic layer."""

    if semantics is None:
        return format_semantic_layer_context()
    return _format_semantics(semantics)


def _format_semantics(semantics: tuple[SemanticDefinition, ...]) -> str:
    blocks: list[str] = []
    for semantic in sorted(semantics, key=lambda item: item.identifier):
        if isinstance(semantic, MetricDefinition):
            lines = [
                f"METRIC {semantic.identifier}",
                f"Label: {semantic.label}",
                f"Definition: {semantic.definition}",
                f"Grain: {semantic.grain}",
                f"Population: {semantic.population}",
                f"Aggregation: {semantic.aggregation}",
                f"Null semantics: {semantic.null_semantics}",
                f"Time semantics: {semantic.time_semantics}",
                "Instructions:",
            ]
        elif isinstance(semantic, QueryConstraintDefinition):
            lines = [
                f"QUERY CONSTRAINT {semantic.identifier}",
                f"Label: {semantic.label}",
                f"Definition: {semantic.definition}",
                "Instructions:",
            ]
        else:
            lines = [
                f"{semantic.kind.upper()} {semantic.identifier}",
                f"Label: {semantic.label}",
                f"Definition: {semantic.definition}",
                f"Grain: {semantic.grain}",
                "Instructions:",
            ]
        lines.extend(f"- {instruction}" for instruction in semantic.instructions)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
