"""Minimal deterministic business semantics for Text-to-SQL generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SemanticKind = Literal["metric", "query_constraint"]


@dataclass(frozen=True)
class BusinessSemanticRule:
    """One canonical metric definition or cross-cutting query constraint."""

    identifier: str
    kind: SemanticKind
    label: str
    definition: str
    grain: str
    instructions: tuple[str, ...]


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


def format_business_semantics_context(
    semantics: tuple[BusinessSemanticRule, ...] = BUSINESS_SEMANTICS_V1,
) -> str:
    """Format business semantics as compact English prompt context."""

    blocks: list[str] = []
    for semantic in sorted(semantics, key=lambda item: item.identifier):
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
