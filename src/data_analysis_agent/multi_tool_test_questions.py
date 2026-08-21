"""Frozen held-out questions for future multi-tool generalization evaluation.

This module contains only human-authored evaluation contracts and reference
SQL. It does not call a model, execute SQL, or implement an evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


MultiToolQuestionCategory = Literal[
    "sql_only",
    "calculate_growth",
    "data_unanswerable",
    "capability_unsupported",
]
ExpectedDisposition = Literal["answer", "reject"]
ExpectedRoute = Literal["sql_only", "sql_then_python"]
ExpectedPythonOperation = Literal["calculate_growth"]


@dataclass(frozen=True)
class MultiToolTestQuestion:
    """One human-audited held-out multi-tool evaluation contract."""

    id: str
    question: str
    category: MultiToolQuestionCategory
    expected_disposition: ExpectedDisposition
    expected_route: ExpectedRoute | None
    expected_python_operation: ExpectedPythonOperation | None
    metric_definition: str
    expected_grain: str
    expected_tables: tuple[str, ...]
    reference_sql: str | None = None
    python_columns: tuple[str, ...] = ()
    unanswerable_reason: str | None = None
    notes: str = ""


MULTI_TOOL_TEST_QUESTIONS: tuple[MultiToolTestQuestion, ...] = (
    MultiToolTestQuestion(
        id="MTQ-001",
        question=(
            "How many orders purchased during calendar year 2017 have the "
            "delivered status?"
        ),
        category="sql_only",
        expected_disposition="answer",
        expected_route="sql_only",
        expected_python_operation=None,
        metric_definition=(
            "Count of order-grain rows with order_status = 'delivered' and a "
            "purchase timestamp in calendar year 2017."
        ),
        expected_grain="single count from filtered order grain",
        expected_tables=("orders",),
        reference_sql="""
            SELECT COUNT(*) AS delivered_order_count
            FROM orders
            WHERE order_status = 'delivered'
              AND order_purchase_timestamp >= TIMESTAMP '2017-01-01'
              AND order_purchase_timestamp < TIMESTAMP '2018-01-01'
        """,
        notes="ALIGNED: the status, time population, and order-grain count are explicit.",
    ),
    MultiToolTestQuestion(
        id="MTQ-002",
        question=(
            "What is the total freight value on order-item records handled by "
            "sellers located in São Paulo state (SP)?"
        ),
        category="sql_only",
        expected_disposition="answer",
        expected_route="sql_only",
        expected_python_operation=None,
        metric_definition=(
            "Sum of order_items.freight_value for item records whose seller has "
            "seller_state = 'SP'."
        ),
        expected_grain="single value aggregated from filtered order-item grain",
        expected_tables=("order_items", "sellers"),
        reference_sql="""
            SELECT ROUND(SUM(items.freight_value), 2) AS total_freight_value
            FROM order_items AS items
            JOIN sellers AS sellers USING (seller_id)
            WHERE sellers.seller_state = 'SP'
        """,
        notes="ALIGNED: freight remains at item fact grain before the filtered sum.",
    ),
    MultiToolTestQuestion(
        id="MTQ-003",
        question=(
            "For every payment type, what is the average payment value per "
            "payment record? List payment types alphabetically."
        ),
        category="sql_only",
        expected_disposition="answer",
        expected_route="sql_only",
        expected_python_operation=None,
        metric_definition=(
            "Average order_payments.payment_value at payment-record grain, grouped "
            "by the source payment_type."
        ),
        expected_grain="one row per payment_type from payment-record grain",
        expected_tables=("order_payments",),
        reference_sql="""
            SELECT
                payment_type,
                ROUND(AVG(payment_value), 4) AS average_payment_value
            FROM order_payments
            GROUP BY payment_type
            ORDER BY payment_type ASC
        """,
        notes="ALIGNED: the average is per payment record, not per order.",
    ),
    MultiToolTestQuestion(
        id="MTQ-004",
        question=(
            "Among all orders purchased during calendar year 2018, what percentage "
            "belong to customers whose state is SP?"
        ),
        category="sql_only",
        expected_disposition="answer",
        expected_route="sql_only",
        expected_python_operation=None,
        metric_definition=(
            "Percentage of 2018 order rows whose linked customer_state is 'SP', "
            "using all 2018 orders as the denominator."
        ),
        expected_grain="single percentage calculated from 2018 order grain",
        expected_tables=("orders", "customers"),
        reference_sql="""
            SELECT ROUND(
                100.0 * COUNT(*) FILTER (WHERE customers.customer_state = 'SP')
                    / COUNT(*),
                4
            ) AS sp_customer_order_percentage
            FROM orders AS orders
            JOIN customers AS customers USING (customer_id)
            WHERE orders.order_purchase_timestamp >= TIMESTAMP '2018-01-01'
              AND orders.order_purchase_timestamp < TIMESTAMP '2019-01-01'
        """,
        notes="ALIGNED: both numerator and denominator are explicit 2018 order rows.",
    ),
    MultiToolTestQuestion(
        id="MTQ-005",
        question=(
            "For each customer state with at least 1,000 review records linked to "
            "delivered orders, report the review-record count and average review "
            "score, ordered alphabetically by state."
        ),
        category="sql_only",
        expected_disposition="answer",
        expected_route="sql_only",
        expected_python_operation=None,
        metric_definition=(
            "Review-record count and average review_score by customer_state for "
            "reviews linked to orders whose status is delivered; retain groups with "
            "at least 1,000 review records."
        ),
        expected_grain="one row per customer_state aggregated from review-record grain",
        expected_tables=("order_reviews", "orders", "customers"),
        reference_sql="""
            SELECT
                customers.customer_state,
                COUNT(*) AS review_record_count,
                ROUND(AVG(reviews.review_score), 4) AS average_review_score
            FROM order_reviews AS reviews
            JOIN orders AS orders USING (order_id)
            JOIN customers AS customers USING (customer_id)
            WHERE orders.order_status = 'delivered'
            GROUP BY customers.customer_state
            HAVING COUNT(*) >= 1000
            ORDER BY customers.customer_state ASC
        """,
        notes="ALIGNED: the threshold and average both use review-record grain.",
    ),
    MultiToolTestQuestion(
        id="MTQ-006",
        question=(
            "Which seven seller city-state pairs handled the most order-item "
            "records? Rank them by item count from highest to lowest."
        ),
        category="sql_only",
        expected_disposition="answer",
        expected_route="sql_only",
        expected_python_operation=None,
        metric_definition=(
            "Count of order-item records by seller_city and seller_state, with a "
            "stable descending Top-7 ranking."
        ),
        expected_grain="one row per seller city-state pair from order-item grain",
        expected_tables=("order_items", "sellers"),
        reference_sql="""
            SELECT
                sellers.seller_city,
                sellers.seller_state,
                COUNT(*) AS item_count
            FROM order_items AS items
            JOIN sellers AS sellers USING (seller_id)
            GROUP BY sellers.seller_city, sellers.seller_state
            ORDER BY
                item_count DESC,
                sellers.seller_state ASC,
                sellers.seller_city ASC
            LIMIT 7
        """,
        notes="ALIGNED: Top 7, item-count grain, and deterministic ties are explicit.",
    ),
    MultiToolTestQuestion(
        id="MTQ-007",
        question=(
            "For each purchase month in 2017, what total payment value was recorded "
            "for payment records linked to those orders? Return the months in "
            "chronological order."
        ),
        category="sql_only",
        expected_disposition="answer",
        expected_route="sql_only",
        expected_python_operation=None,
        metric_definition=(
            "Sum of payment-record payment_value grouped by the linked order's "
            "purchase month during calendar year 2017."
        ),
        expected_grain="one row per 2017 purchase month from payment-record grain",
        expected_tables=("order_payments", "orders"),
        reference_sql="""
            SELECT
                DATE_TRUNC('month', orders.order_purchase_timestamp) AS purchase_month,
                ROUND(SUM(payments.payment_value), 2) AS total_payment_value
            FROM order_payments AS payments
            JOIN orders AS orders USING (order_id)
            WHERE orders.order_purchase_timestamp >= TIMESTAMP '2017-01-01'
              AND orders.order_purchase_timestamp < TIMESTAMP '2018-01-01'
            GROUP BY DATE_TRUNC('month', orders.order_purchase_timestamp)
            ORDER BY purchase_month ASC
        """,
        notes="ALIGNED: this requests monthly totals, not month-over-month growth.",
    ),
    MultiToolTestQuestion(
        id="MTQ-008",
        question=(
            "Among credit-card payment records with a recorded installment count, "
            "report the count, mean, sample standard deviation, median, minimum, "
            "and maximum number of installments."
        ),
        category="sql_only",
        expected_disposition="answer",
        expected_route="sql_only",
        expected_python_operation=None,
        metric_definition=(
            "SQL-native descriptive statistics over payment_installments for "
            "credit_card payment records with non-NULL installment values."
        ),
        expected_grain="single summary row over filtered payment-record grain",
        expected_tables=("order_payments",),
        reference_sql="""
            SELECT
                COUNT(payment_installments) AS installment_record_count,
                ROUND(AVG(payment_installments), 4) AS mean_installments,
                ROUND(STDDEV_SAMP(payment_installments), 4) AS std_installments,
                MEDIAN(payment_installments) AS median_installments,
                MIN(payment_installments) AS min_installments,
                MAX(payment_installments) AS max_installments
            FROM order_payments
            WHERE payment_type = 'credit_card'
              AND payment_installments IS NOT NULL
        """,
        notes="ALIGNED: every requested statistic is SQL-native and explicitly scoped.",
    ),
    MultiToolTestQuestion(
        id="MTQ-009",
        question=(
            "Among products with positive recorded weight, length, height, and "
            "width, what is the Pearson correlation between product weight and "
            "product volume (length × height × width)?"
        ),
        category="sql_only",
        expected_disposition="answer",
        expected_route="sql_only",
        expected_python_operation=None,
        metric_definition=(
            "SQL-native Pearson correlation between product_weight_g and derived "
            "volume in cubic centimeters for products with positive non-NULL inputs."
        ),
        expected_grain="single correlation value over eligible product grain",
        expected_tables=("products",),
        reference_sql="""
            SELECT ROUND(
                CORR(
                    CAST(product_weight_g AS DOUBLE),
                    CAST(product_length_cm AS DOUBLE)
                        * CAST(product_height_cm AS DOUBLE)
                        * CAST(product_width_cm AS DOUBLE)
                ),
                6
            ) AS weight_volume_correlation
            FROM products
            WHERE product_weight_g > 0
              AND product_length_cm > 0
              AND product_height_cm > 0
              AND product_width_cm > 0
        """,
        notes="ALIGNED: the eligible population and derived volume formula are explicit.",
    ),
    MultiToolTestQuestion(
        id="MTQ-010",
        question=(
            "Among delivered orders with both item and payment records, what is the "
            "average order-level difference between total payment value and the "
            "combined item price plus freight value?"
        ),
        category="sql_only",
        expected_disposition="answer",
        expected_route="sql_only",
        expected_python_operation=None,
        metric_definition=(
            "Average at order grain of payment_value minus item_transaction_value "
            "minus freight_value, after item and payment facts are separately "
            "aggregated, for delivered orders present in both summaries."
        ),
        expected_grain="single average over delivered order grain",
        expected_tables=("orders", "order_item_summary", "order_payment_summary"),
        reference_sql="""
            SELECT ROUND(
                AVG(
                    payments.payment_value
                    - items.item_transaction_value
                    - items.freight_value
                ),
                4
            ) AS average_order_value_difference
            FROM orders AS orders
            JOIN order_item_summary AS items USING (order_id)
            JOIN order_payment_summary AS payments USING (order_id)
            WHERE orders.order_status = 'delivered'
        """,
        notes="ALIGNED: both many-side facts are aggregated before the order-level join.",
    ),
    MultiToolTestQuestion(
        id="MTQ-011",
        question=(
            "How did the average item price per order-item record change from one "
            "purchase month to the next?"
        ),
        category="calculate_growth",
        expected_disposition="answer",
        expected_route="sql_then_python",
        expected_python_operation="calculate_growth",
        metric_definition=(
            "Average order_items.price at order-item grain by the linked order's "
            "purchase month, followed by deterministic period-over-period growth."
        ),
        expected_grain="one average item-price observation per purchase month with item facts",
        expected_tables=("order_items", "orders"),
        reference_sql="""
            SELECT
                DATE_TRUNC('month', orders.order_purchase_timestamp) AS purchase_month,
                AVG(items.price) AS average_item_price
            FROM order_items AS items
            JOIN orders AS orders USING (order_id)
            GROUP BY DATE_TRUNC('month', orders.order_purchase_timestamp)
            ORDER BY purchase_month ASC
        """,
        python_columns=("purchase_month", "average_item_price"),
        notes=(
            "ALIGNED: months without item facts have no defined average item price; "
            "SQL owns the monthly average and Python owns adjacent-period growth."
        ),
    ),
    MultiToolTestQuestion(
        id="MTQ-012",
        question=(
            "Among orders with at least one payment record, how did the average "
            "order-level total payment value change from one purchase month to "
            "the next?"
        ),
        category="calculate_growth",
        expected_disposition="answer",
        expected_route="sql_then_python",
        expected_python_operation="calculate_growth",
        metric_definition=(
            "Average order_payment_summary.payment_value at order grain among orders "
            "with payment facts, grouped by purchase month, followed by deterministic "
            "period-over-period growth."
        ),
        expected_grain=(
            "one average order-payment observation per purchase month with "
            "payment-bearing orders"
        ),
        expected_tables=("order_payment_summary", "orders"),
        reference_sql="""
            SELECT
                DATE_TRUNC('month', orders.order_purchase_timestamp) AS purchase_month,
                AVG(payments.payment_value) AS average_order_payment_value
            FROM order_payment_summary AS payments
            JOIN orders AS orders USING (order_id)
            GROUP BY DATE_TRUNC('month', orders.order_purchase_timestamp)
            ORDER BY purchase_month ASC
        """,
        python_columns=("purchase_month", "average_order_payment_value"),
        notes=(
            "ALIGNED: months without payment-bearing orders have no defined order-level "
            "payment average; payment records are aggregated before the monthly average."
        ),
    ),
    MultiToolTestQuestion(
        id="MTQ-013",
        question=(
            "Among orders with both purchase and customer delivery timestamps, how "
            "did the average delivery duration in days change from one purchase "
            "month to the next?"
        ),
        category="calculate_growth",
        expected_disposition="answer",
        expected_route="sql_then_python",
        expected_python_operation="calculate_growth",
        metric_definition=(
            "Average elapsed days from order_purchase_timestamp to "
            "order_delivered_customer_date among orders with both timestamps, grouped "
            "by purchase month, followed by deterministic period-over-period growth."
        ),
        expected_grain=(
            "one average delivery-duration observation per purchase month among "
            "orders with both required timestamps"
        ),
        expected_tables=("orders",),
        reference_sql="""
            SELECT
                DATE_TRUNC('month', orders.order_purchase_timestamp) AS purchase_month,
                AVG(
                    DATE_DIFF(
                        'second',
                        orders.order_purchase_timestamp,
                        orders.order_delivered_customer_date
                    ) / 86400.0
                ) AS average_delivery_days
            FROM orders AS orders
            WHERE orders.order_purchase_timestamp IS NOT NULL
              AND orders.order_delivered_customer_date IS NOT NULL
            GROUP BY DATE_TRUNC('month', orders.order_purchase_timestamp)
            ORDER BY purchase_month ASC
        """,
        python_columns=("purchase_month", "average_delivery_days"),
        notes=(
            "ALIGNED: a month without orders having both timestamps has no defined "
            "delivery-duration average; SQL owns the average and Python owns growth."
        ),
    ),
    MultiToolTestQuestion(
        id="MTQ-014",
        question=(
            "Across review records linked to delivered orders, how did the average "
            "review score change from one purchase month to the next?"
        ),
        category="calculate_growth",
        expected_disposition="answer",
        expected_route="sql_then_python",
        expected_python_operation="calculate_growth",
        metric_definition=(
            "Average review_score at review-record grain for delivered orders by "
            "the linked order's purchase month, followed by deterministic growth."
        ),
        expected_grain="one numeric observation per observed purchase month",
        expected_tables=("order_reviews", "orders"),
        reference_sql="""
            SELECT
                DATE_TRUNC('month', orders.order_purchase_timestamp) AS purchase_month,
                AVG(reviews.review_score) AS average_review_score
            FROM order_reviews AS reviews
            JOIN orders AS orders USING (order_id)
            WHERE orders.order_status = 'delivered'
            GROUP BY DATE_TRUNC('month', orders.order_purchase_timestamp)
            ORDER BY purchase_month ASC
        """,
        python_columns=("purchase_month", "average_review_score"),
        notes="ALIGNED: review-record averaging and the delivered population are explicit.",
    ),
    MultiToolTestQuestion(
        id="MTQ-015",
        question=(
            "How many units of each product were in inventory at the end of 2017?"
        ),
        category="data_unanswerable",
        expected_disposition="reject",
        expected_route=None,
        expected_python_operation=None,
        metric_definition="Ending inventory unit quantity by product at a point in time.",
        expected_grain="one inventory snapshot value per product",
        expected_tables=(),
        unanswerable_reason=(
            "The Olist schema has no inventory ledger, stock quantity, or historical "
            "inventory snapshot facts. Order items cannot establish ending inventory."
        ),
        notes="ALIGNED: the required inventory facts are absent from the schema.",
    ),
    MultiToolTestQuestion(
        id="MTQ-016",
        question=(
            "Which customer acquisition channel generated the highest total "
            "payment value?"
        ),
        category="data_unanswerable",
        expected_disposition="reject",
        expected_route=None,
        expected_python_operation=None,
        metric_definition="Total payment value attributed to customer acquisition channel.",
        expected_grain="one attributed payment total per acquisition channel",
        expected_tables=(),
        unanswerable_reason=(
            "The Olist schema has payment facts but no marketing source, campaign, "
            "referral, or customer acquisition channel attribution fields."
        ),
        notes="ALIGNED: channel attribution facts are absent, so payments cannot be assigned.",
    ),
    MultiToolTestQuestion(
        id="MTQ-017",
        question=(
            "Forecast the total number of orders for each of the next six months."
        ),
        category="capability_unsupported",
        expected_disposition="reject",
        expected_route=None,
        expected_python_operation=None,
        metric_definition="Six-month-ahead monthly order-count forecast.",
        expected_grain="one predicted order count per future month",
        expected_tables=("orders",),
        unanswerable_reason=(
            "Forecasting is outside the current controlled SQL and Python operation "
            "set; the Agent must not fabricate future values."
        ),
        notes="ALIGNED: historical order data exists, but forecasting is unsupported.",
    ),
    MultiToolTestQuestion(
        id="MTQ-018",
        question=(
            "Cluster sellers into behavioral segments using their item volume, "
            "transaction value, and freight patterns."
        ),
        category="capability_unsupported",
        expected_disposition="reject",
        expected_route=None,
        expected_python_operation=None,
        metric_definition="Unsupervised seller segmentation from aggregated behavior.",
        expected_grain="one inferred cluster assignment per seller",
        expected_tables=("sellers", "order_items"),
        unanswerable_reason=(
            "Clustering is outside the current controlled Python operation set; "
            "the Agent does not execute arbitrary modeling code."
        ),
        notes="ALIGNED: source facts exist, but the requested modeling capability does not.",
    ),
)
