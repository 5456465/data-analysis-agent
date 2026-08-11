"""Integration tests for the minimal core Olist DuckDB build."""

from __future__ import annotations

import subprocess
from pathlib import Path

import duckdb
import pytest

from scripts.baseline_queries import BASELINE_QUERIES
from scripts.build_duckdb import (
    DEFAULT_OUTPUT_PATH,
    TABLE_SPECS,
    build_database,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "raw"
EXPECTED_TABLES = {spec.table_name for spec in TABLE_SPECS}
EXPECTED_VIEWS = {
    "order_item_summary",
    "order_payment_summary",
    "products_with_category_translation",
}


@pytest.fixture(scope="session")
def database_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("olist_duckdb") / "olist.duckdb"
    build_database(DATA_DIR, path)
    return path


@pytest.fixture()
def connection(database_path: Path):
    with duckdb.connect(str(database_path), read_only=True) as database:
        yield database


def test_required_tables_and_views_are_created(connection) -> None:
    rows = connection.execute(
        """
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = 'main'
        """
    ).fetchall()
    tables = {name for name, table_type in rows if table_type == "BASE TABLE"}
    views = {name for name, table_type in rows if table_type == "VIEW"}
    assert tables == EXPECTED_TABLES
    assert views == EXPECTED_VIEWS


def test_table_row_counts_match_the_audited_csv_version(connection) -> None:
    for spec in TABLE_SPECS:
        actual = connection.execute(
            f"SELECT COUNT(*) FROM {spec.table_name}"
        ).fetchone()[0]
        assert actual == spec.expected_row_count


def test_primary_key_assumptions_remain_unique(connection) -> None:
    for spec in TABLE_SPECS:
        key_columns = ", ".join(spec.primary_key)
        duplicate_groups = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT {key_columns}, COUNT(*) AS row_count
                FROM {spec.table_name}
                GROUP BY {key_columns}
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]
        assert duplicate_groups == 0


def test_core_joins_execute_without_orphaning_child_rows(connection) -> None:
    joins = (
        ("orders", "customers", "customer_id"),
        ("order_items", "orders", "order_id"),
        ("order_payments", "orders", "order_id"),
        ("order_reviews", "orders", "order_id"),
        ("order_items", "products", "product_id"),
        ("order_items", "sellers", "seller_id"),
    )
    for child, parent, key in joins:
        missing = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM {child} AS child
            LEFT JOIN {parent} AS parent USING ({key})
            WHERE parent.{key} IS NULL
            """
        ).fetchone()[0]
        assert missing == 0


def test_timestamp_columns_are_typed_and_queryable(connection) -> None:
    types = dict(
        connection.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'orders'
            """
        ).fetchall()
    )
    assert types["order_purchase_timestamp"] == "TIMESTAMP"
    assert types["order_delivered_customer_date"] == "TIMESTAMP"
    date_range = connection.execute(
        """
        SELECT MIN(order_purchase_timestamp), MAX(order_purchase_timestamp)
        FROM orders
        """
    ).fetchone()
    assert date_range[0] < date_range[1]


def test_all_baseline_sql_executes(connection) -> None:
    assert len(BASELINE_QUERIES) == 14
    for query in BASELINE_QUERIES:
        cursor = connection.execute(query.sql)
        assert cursor.description
        assert cursor.fetchall()


def test_order_level_views_prevent_item_payment_amount_amplification(connection) -> None:
    source_totals = connection.execute(
        """
        SELECT
            (SELECT SUM(price) FROM order_items),
            (SELECT SUM(freight_value) FROM order_items),
            (SELECT SUM(payment_value) FROM order_payments)
        """
    ).fetchone()
    safe_totals = connection.execute(
        """
        SELECT
            SUM(COALESCE(items.item_transaction_value, 0)),
            SUM(COALESCE(items.freight_value, 0)),
            SUM(COALESCE(payments.payment_value, 0))
        FROM order_item_summary AS items
        FULL OUTER JOIN order_payment_summary AS payments USING (order_id)
        """
    ).fetchone()
    assert safe_totals == source_totals

    common_source_item_total, naive_item_total = connection.execute(
        """
        SELECT
            (
                SELECT SUM(summary.item_transaction_value)
                FROM order_item_summary AS summary
                JOIN order_payment_summary AS payments USING (order_id)
            ),
            (
                SELECT SUM(items.price)
                FROM order_items AS items
                JOIN order_payments AS payments USING (order_id)
            )
        """
    ).fetchone()
    assert naive_item_total > common_source_item_total


def test_category_translation_preserves_both_language_columns(connection) -> None:
    columns = {
        row[0]
        for row in connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'products_with_category_translation'
            """
        ).fetchall()
    }
    assert "product_category_name" in columns
    assert "product_category_name_english" in columns


def test_default_database_output_is_ignored_and_untracked() -> None:
    relative_path = str(DEFAULT_OUTPUT_PATH)
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", relative_path],
        cwd=PROJECT_ROOT,
        check=False,
    )
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", relative_path],
        cwd=PROJECT_ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert ignored.returncode == 0
    assert tracked.returncode != 0
