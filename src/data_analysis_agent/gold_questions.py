"""Deterministic English gold questions for future Text-to-SQL evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


GoldCategory = Literal[
    "basic",
    "aggregation",
    "multi_table",
    "delivery_analysis",
    "grain_sensitive",
    "unanswerable",
]
TemporalGranularity = Literal["month"]
RankingDirection = Literal["ascending", "descending"]


@dataclass(frozen=True)
class TemporalComparison:
    """Temporal equivalence declared for one reference result column."""

    column: str
    granularity: TemporalGranularity


@dataclass(frozen=True)
class RankingComparison:
    """Primary ranking semantics for an ordered multi-row result."""

    metric_column: str
    direction: RankingDirection
    ties_may_reorder: bool = True


@dataclass(frozen=True)
class LabelAlias:
    """Finite equivalent labels for one reference result column."""

    column: str
    canonical: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class GoldQuestion:
    """One human-reviewed evaluation question and its semantic expectations."""

    id: str
    question: str
    category: GoldCategory
    answerable: bool
    metric_definition: str
    expected_grain: str
    expected_tables: tuple[str, ...]
    baseline_key: str | None = None
    reference_sql: str | None = None
    unanswerable_reason: str | None = None
    order_sensitive: bool = False
    temporal_comparisons: tuple[TemporalComparison, ...] = ()
    ranking: RankingComparison | None = None
    label_aliases: tuple[LabelAlias, ...] = ()


GOLD_QUESTIONS: tuple[GoldQuestion, ...] = (
    GoldQuestion(
        id="GQ-001",
        question="How many orders are in the dataset?",
        category="basic",
        answerable=True,
        metric_definition="Count of order-level rows in orders.",
        expected_grain="single value calculated from order grain",
        expected_tables=("orders",),
        baseline_key="total_order_count",
    ),
    GoldQuestion(
        id="GQ-002",
        question=(
            "List all order statuses with their order counts, ranked from highest "
            "to lowest by order count."
        ),
        category="basic",
        answerable=True,
        metric_definition="Order count grouped by the source order_status value.",
        expected_grain="one row per order_status, calculated from order grain",
        expected_tables=("orders",),
        baseline_key="order_count_by_status",
        order_sensitive=True,
        ranking=RankingComparison("order_count", "descending"),
    ),
    GoldQuestion(
        id="GQ-003",
        question="What is the average review score?",
        category="basic",
        answerable=True,
        metric_definition="Average review_score across review records.",
        expected_grain="single value calculated from review-record grain",
        expected_tables=("order_reviews",),
        baseline_key="average_review_score",
    ),
    GoldQuestion(
        id="GQ-004",
        question="How many orders were placed each month?",
        category="aggregation",
        answerable=True,
        metric_definition=(
            "Order count by calendar month derived from order_purchase_timestamp."
        ),
        expected_grain="one row per calendar month, calculated from order grain",
        expected_tables=("orders",),
        baseline_key="monthly_order_count",
        temporal_comparisons=(TemporalComparison("order_month", "month"),),
    ),
    GoldQuestion(
        id="GQ-005",
        question=(
            "List all customer states ranked by unique customer count, from "
            "highest to lowest."
        ),
        category="aggregation",
        answerable=True,
        metric_definition=(
            "Count of distinct customer_unique_id values by customer_state."
        ),
        expected_grain="one row per customer_state at unique-customer grain",
        expected_tables=("customers",),
        baseline_key="customer_distribution_by_state",
        order_sensitive=True,
        ranking=RankingComparison("unique_customer_count", "descending"),
    ),
    GoldQuestion(
        id="GQ-006",
        question=(
            "List all seller states ranked by seller count, from highest to lowest."
        ),
        category="aggregation",
        answerable=True,
        metric_definition="Count of unique seller rows by seller_state.",
        expected_grain="one row per seller_state at seller grain",
        expected_tables=("sellers",),
        baseline_key="seller_distribution_by_state",
        order_sensitive=True,
        ranking=RankingComparison("seller_count", "descending"),
    ),
    GoldQuestion(
        id="GQ-007",
        question="What is the total item transaction value?",
        category="aggregation",
        answerable=True,
        metric_definition=(
            "Sum of order_items.price; freight and payments are excluded, and "
            "the value is not profit or gross margin."
        ),
        expected_grain="single value aggregated from order-item grain",
        expected_tables=("order_items",),
        baseline_key="total_item_transaction_value",
    ),
    GoldQuestion(
        id="GQ-008",
        question="What is the total freight value?",
        category="aggregation",
        answerable=True,
        metric_definition=(
            "Sum of order_items.freight_value; item price and payment values are "
            "excluded."
        ),
        expected_grain="single value aggregated from order-item grain",
        expected_tables=("order_items",),
        baseline_key="total_freight_value",
    ),
    GoldQuestion(
        id="GQ-009",
        question=(
            "What are the top 10 product categories by total item transaction "
            "value, ranked from highest to lowest?"
        ),
        category="multi_table",
        answerable=True,
        metric_definition=(
            "Sum of order_items.price by original Portuguese product category "
            "and its official English mapping."
        ),
        expected_grain="one row per product category, aggregated from order-item grain",
        expected_tables=("order_items", "products_with_category_translation"),
        baseline_key="top_product_categories_by_item_transaction_value",
        order_sensitive=True,
        ranking=RankingComparison("item_transaction_value", "descending"),
    ),
    GoldQuestion(
        id="GQ-010",
        question=(
            "Among review records linked to orders with both actual and estimated "
            "delivery timestamps, what is the average review score for deliveries "
            "after the estimate versus deliveries on or before the estimate?"
        ),
        category="multi_table",
        answerable=True,
        metric_definition=(
            "Average review_score by whether delivery occurred after the "
            "estimated delivery timestamp."
        ),
        expected_grain=(
            "one row per delivery status, calculated at review-record grain"
        ),
        expected_tables=("order_reviews", "orders"),
        baseline_key="delivery_delay_and_review_score",
        label_aliases=(
            LabelAlias("delivery_status", "delayed", ("after_estimate",)),
            LabelAlias(
                "delivery_status",
                "on_time_or_early",
                ("on_or_before_estimate",),
            ),
        ),
    ),
    GoldQuestion(
        id="GQ-011",
        question=(
            "Among orders with both actual and estimated delivery timestamps, what "
            "percentage have an actual delivery timestamp later than the estimated "
            "delivery timestamp?"
        ),
        category="delivery_analysis",
        answerable=True,
        metric_definition=(
            "Percentage of delivered orders whose customer delivery timestamp "
            "is later than the estimated delivery timestamp."
        ),
        expected_grain="single summary value calculated from delivered-order grain",
        expected_tables=("orders",),
        baseline_key="delivery_delay_analysis",
    ),
    GoldQuestion(
        id="GQ-012",
        question=(
            "Among orders with at least one payment record, what is the average "
            "total payment value per order?"
        ),
        category="grain_sensitive",
        answerable=True,
        metric_definition=(
            "Average of order-level payment totals among orders with at least "
            "one payment record; payment records are aggregated before averaging."
        ),
        expected_grain=(
            "single value at order grain after payment-record grain is aggregated"
        ),
        expected_tables=("order_payment_summary",),
        baseline_key="average_payment_value_per_order",
    ),
    GoldQuestion(
        id="GQ-013",
        question="What percentage of orders contain multiple items?",
        category="grain_sensitive",
        answerable=True,
        metric_definition=(
            "Percentage of all orders with more than one order-item record."
        ),
        expected_grain=(
            "single value at order grain after order-item grain is counted per order"
        ),
        expected_tables=("orders", "order_item_summary"),
        baseline_key="orders_with_multiple_items_percentage",
    ),
    GoldQuestion(
        id="GQ-014",
        question="What percentage of orders have multiple payment records?",
        category="grain_sensitive",
        answerable=True,
        metric_definition=(
            "Percentage of all orders with more than one payment record."
        ),
        expected_grain=(
            "single value at order grain after payment-record grain is counted per order"
        ),
        expected_tables=("orders", "order_payment_summary"),
        baseline_key="orders_with_multiple_payment_records_percentage",
    ),
    GoldQuestion(
        id="GQ-015",
        question="What is Olist's gross profit margin?",
        category="unanswerable",
        answerable=False,
        metric_definition=(
            "Gross profit divided by an explicitly defined sales denominator."
        ),
        expected_grain="not available from the current dataset",
        expected_tables=(),
        unanswerable_reason=(
            "The dataset has no product cost or cost-of-goods-sold field, so "
            "gross profit and gross profit margin cannot be calculated reliably."
        ),
    ),
    GoldQuestion(
        id="GQ-016",
        question="What is the refund rate?",
        category="unanswerable",
        answerable=False,
        metric_definition=(
            "Refunded orders divided by an explicitly defined eligible order population."
        ),
        expected_grain="not available from the current dataset",
        expected_tables=(),
        unanswerable_reason=(
            "The dataset does not include a complete refund-event or refunded-amount "
            "table, so a reliable refund numerator is unavailable."
        ),
    ),
)
