"""Human-verifiable English baseline SQL for the core Olist DuckDB database."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

import duckdb

if __package__:
    from scripts.build_duckdb import DEFAULT_OUTPUT_PATH
else:
    from build_duckdb import DEFAULT_OUTPUT_PATH


@dataclass(frozen=True)
class BaselineQuery:
    """A named SQL baseline with an explicit definition and result grain."""

    key: str
    metric_definition: str
    result_grain: str
    sql: str


BASELINE_QUERIES: tuple[BaselineQuery, ...] = (
    BaselineQuery(
        key="total_order_count",
        metric_definition="Count of distinct order-level rows in orders.",
        result_grain="single value",
        sql="SELECT COUNT(*) AS total_order_count FROM orders",
    ),
    BaselineQuery(
        key="order_count_by_status",
        metric_definition="Order count grouped by the source order_status value.",
        result_grain="one row per order_status",
        sql="""
            SELECT order_status, COUNT(*) AS order_count
            FROM orders
            GROUP BY order_status
            ORDER BY order_count DESC, order_status
        """,
    ),
    BaselineQuery(
        key="monthly_order_count",
        metric_definition="Order count by purchase month using order_purchase_timestamp.",
        result_grain="one row per calendar month",
        sql="""
            SELECT
                CAST(DATE_TRUNC('month', order_purchase_timestamp) AS DATE) AS order_month,
                COUNT(*) AS order_count
            FROM orders
            GROUP BY order_month
            ORDER BY order_month
        """,
    ),
    BaselineQuery(
        key="total_item_transaction_value",
        metric_definition=(
            "Sum of order_items.price at order-item grain. Freight and payment "
            "values are excluded; this is not profit or revenue."
        ),
        result_grain="single value",
        sql="""
            SELECT CAST(SUM(price) AS DECIMAL(18, 2)) AS item_transaction_value
            FROM order_items
        """,
    ),
    BaselineQuery(
        key="total_freight_value",
        metric_definition=(
            "Sum of order_items.freight_value at order-item grain. Item price "
            "and payment values are excluded."
        ),
        result_grain="single value",
        sql="""
            SELECT CAST(SUM(freight_value) AS DECIMAL(18, 2)) AS freight_value
            FROM order_items
        """,
    ),
    BaselineQuery(
        key="average_payment_value_per_order",
        metric_definition=(
            "Average of order-level payment totals among orders with at least "
            "one payment record. Payments are aggregated before averaging."
        ),
        result_grain="single value",
        sql="""
            SELECT
                COUNT(*) AS paid_order_count,
                CAST(SUM(payment_value) AS DECIMAL(18, 2)) AS total_payment_value,
                ROUND(AVG(payment_value), 2) AS average_payment_value_per_order
            FROM order_payment_summary
        """,
    ),
    BaselineQuery(
        key="top_product_categories_by_item_transaction_value",
        metric_definition=(
            "Sum of order_items.price by original Portuguese category and its "
            "official English mapping. Freight and payment values are excluded."
        ),
        result_grain="one row per product category; top 10",
        sql="""
            SELECT
                category.product_category_name,
                category.product_category_name_english,
                COUNT(*) AS order_item_count,
                CAST(SUM(items.price) AS DECIMAL(18, 2)) AS item_transaction_value
            FROM order_items AS items
            JOIN products_with_category_translation AS category
                USING (product_id)
            GROUP BY
                category.product_category_name,
                category.product_category_name_english
            ORDER BY item_transaction_value DESC NULLS LAST
            LIMIT 10
        """,
    ),
    BaselineQuery(
        key="customer_distribution_by_state",
        metric_definition=(
            "Count of distinct customer_unique_id values by the source customer_state."
        ),
        result_grain="one row per customer_state",
        sql="""
            SELECT
                customer_state,
                COUNT(DISTINCT customer_unique_id) AS unique_customer_count
            FROM customers
            GROUP BY customer_state
            ORDER BY unique_customer_count DESC, customer_state
        """,
    ),
    BaselineQuery(
        key="seller_distribution_by_state",
        metric_definition="Count of unique seller rows by the source seller_state.",
        result_grain="one row per seller_state",
        sql="""
            SELECT seller_state, COUNT(*) AS seller_count
            FROM sellers
            GROUP BY seller_state
            ORDER BY seller_count DESC, seller_state
        """,
    ),
    BaselineQuery(
        key="average_review_score",
        metric_definition="Average review_score across review records.",
        result_grain="single value",
        sql="""
            SELECT
                COUNT(*) AS review_record_count,
                ROUND(AVG(review_score), 4) AS average_review_score
            FROM order_reviews
        """,
    ),
    BaselineQuery(
        key="delivery_delay_analysis",
        metric_definition=(
            "Delivered orders are delayed when order_delivered_customer_date is "
            "later than order_estimated_delivery_date."
        ),
        result_grain="single summary row over delivered orders",
        sql="""
            SELECT
                COUNT(*) AS delivered_order_count,
                COUNT(*) FILTER (
                    WHERE order_delivered_customer_date > order_estimated_delivery_date
                ) AS delayed_order_count,
                ROUND(
                    100.0 * COUNT(*) FILTER (
                        WHERE order_delivered_customer_date
                            > order_estimated_delivery_date
                    ) / COUNT(*),
                    4
                ) AS delayed_order_percentage,
                ROUND(
                    AVG(
                        DATE_DIFF(
                            'second',
                            order_estimated_delivery_date,
                            order_delivered_customer_date
                        ) / 86400.0
                    ),
                    4
                ) AS average_days_from_estimate
            FROM orders
            WHERE order_delivered_customer_date IS NOT NULL
              AND order_estimated_delivery_date IS NOT NULL
        """,
    ),
    BaselineQuery(
        key="delivery_delay_and_review_score",
        metric_definition=(
            "Review-record average score grouped by whether the related order "
            "was delivered after its estimated delivery timestamp."
        ),
        result_grain="one row per delivery_status at review-record grain",
        sql="""
            WITH review_delivery AS (
                SELECT
                    reviews.review_id,
                    reviews.order_id,
                    reviews.review_score,
                    CASE
                        WHEN orders.order_delivered_customer_date
                            > orders.order_estimated_delivery_date
                        THEN 'delayed'
                        ELSE 'on_time_or_early'
                    END AS delivery_status,
                    DATE_DIFF(
                        'second',
                        orders.order_estimated_delivery_date,
                        orders.order_delivered_customer_date
                    ) / 86400.0 AS days_from_estimate
                FROM order_reviews AS reviews
                JOIN orders USING (order_id)
                WHERE orders.order_delivered_customer_date IS NOT NULL
                  AND orders.order_estimated_delivery_date IS NOT NULL
            )
            SELECT
                delivery_status,
                COUNT(*) AS review_record_count,
                COUNT(DISTINCT order_id) AS order_count,
                ROUND(AVG(review_score), 4) AS average_review_score,
                ROUND(AVG(days_from_estimate), 4) AS average_days_from_estimate
            FROM review_delivery
            GROUP BY delivery_status
            ORDER BY delivery_status
        """,
    ),
    BaselineQuery(
        key="orders_with_multiple_items_percentage",
        metric_definition=(
            "Percentage of all order-level rows with more than one order-item record."
        ),
        result_grain="single value",
        sql="""
            SELECT
                COUNT(*) AS total_order_count,
                COUNT(*) FILTER (WHERE COALESCE(items.item_count, 0) > 1)
                    AS multiple_item_order_count,
                ROUND(
                    100.0 * COUNT(*) FILTER (
                        WHERE COALESCE(items.item_count, 0) > 1
                    ) / COUNT(*),
                    4
                ) AS multiple_item_order_percentage
            FROM orders
            LEFT JOIN order_item_summary AS items USING (order_id)
        """,
    ),
    BaselineQuery(
        key="orders_with_multiple_payment_records_percentage",
        metric_definition=(
            "Percentage of all order-level rows with more than one payment record."
        ),
        result_grain="single value",
        sql="""
            SELECT
                COUNT(*) AS total_order_count,
                COUNT(*) FILTER (
                    WHERE COALESCE(payments.payment_record_count, 0) > 1
                ) AS multiple_payment_order_count,
                ROUND(
                    100.0 * COUNT(*) FILTER (
                        WHERE COALESCE(payments.payment_record_count, 0) > 1
                    ) / COUNT(*),
                    4
                ) AS multiple_payment_order_percentage
            FROM orders
            LEFT JOIN order_payment_summary AS payments USING (order_id)
        """,
    ),
)


def get_query(key: str) -> BaselineQuery:
    for query in BASELINE_QUERIES:
        if query.key == key:
            return query
    raise KeyError(f"Unknown baseline query: {key}")


def _format_value(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def run_queries(
    database_path: Path, query_keys: Sequence[str] | None = None
) -> dict[str, tuple[list[str], list[tuple[Any, ...]]]]:
    """Run selected baselines against the persistent database in read-only mode."""

    if not database_path.is_file():
        raise FileNotFoundError(f"Database does not exist: {database_path}")
    selected = (
        [get_query(key) for key in query_keys] if query_keys else BASELINE_QUERIES
    )
    results: dict[str, tuple[list[str], list[tuple[Any, ...]]]] = {}
    with duckdb.connect(str(database_path), read_only=True) as connection:
        for query in selected:
            cursor = connection.execute(query.sql)
            columns = [description[0] for description in cursor.description]
            results[query.key] = (columns, cursor.fetchall())
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run human-verifiable baseline SQL against the Olist DuckDB."
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--query",
        action="append",
        choices=[query.key for query in BASELINE_QUERIES],
        help="Run only this baseline key; repeat to select multiple queries.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    selected = args.query or [query.key for query in BASELINE_QUERIES]
    results = run_queries(args.database, selected)
    for key in selected:
        query = get_query(key)
        columns, rows = results[key]
        print(f"\n[{key}]")
        print(f"Definition: {query.metric_definition}")
        print(f"Grain: {query.result_grain}")
        print(" | ".join(columns))
        for row in rows:
            print(" | ".join(_format_value(value) for value in row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
