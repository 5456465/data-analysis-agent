"""Tests for deterministic DuckDB schema inspection."""

from __future__ import annotations

from pathlib import Path

import pytest

from data_analysis_agent.schema import DatabaseSchema, inspect_schema
from scripts.build_duckdb import build_database


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "raw"
EXPECTED_TABLES = {
    "customers",
    "order_items",
    "order_payments",
    "order_reviews",
    "orders",
    "product_category_translation",
    "products",
    "sellers",
}
EXPECTED_VIEWS = {
    "order_item_summary",
    "order_payment_summary",
    "products_with_category_translation",
}


@pytest.fixture(scope="module")
def schema(tmp_path_factory: pytest.TempPathFactory) -> DatabaseSchema:
    database_path = tmp_path_factory.mktemp("schema_inspection") / "olist.duckdb"
    build_database(DATA_DIR, database_path)
    return inspect_schema(database_path)


def _objects_by_name(schema: DatabaseSchema):
    return {obj.name: obj for obj in schema.objects}


def _columns_by_name(schema: DatabaseSchema, object_name: str):
    obj = _objects_by_name(schema)[object_name]
    return {column.name: column for column in obj.columns}


def test_inspect_schema_discovers_core_tables_and_views(schema) -> None:
    tables = {obj.name for obj in schema.objects if obj.object_type == "table"}
    views = {obj.name for obj in schema.objects if obj.object_type == "view"}

    assert tables == EXPECTED_TABLES
    assert views == EXPECTED_VIEWS


def test_inspect_schema_reads_columns_types_and_constraints(schema) -> None:
    order_columns = _columns_by_name(schema, "orders")
    item_columns = _columns_by_name(schema, "order_items")
    summary_columns = _columns_by_name(schema, "order_item_summary")

    assert order_columns["order_id"].data_type == "VARCHAR"
    assert order_columns["order_id"].nullable is False
    assert order_columns["order_id"].primary_key is True
    assert order_columns["order_purchase_timestamp"].data_type == "TIMESTAMP"
    assert item_columns["price"].data_type == "DECIMAL(18,2)"
    assert summary_columns["item_count"].data_type == "BIGINT"
    assert summary_columns["order_id"].primary_key is False


def test_inspect_schema_adds_only_known_grain_metadata(schema) -> None:
    objects = _objects_by_name(schema)

    assert objects["orders"].grain == "one row per order"
    assert objects["order_items"].grain == "one row per order item"
    assert objects["order_payments"].grain == "one row per payment record"
    assert objects["order_item_summary"].grain == "one row per order"
    assert objects["order_payment_summary"].grain == "one row per order"
    assert objects["products"].grain is None


def test_inspect_schema_reports_missing_database(tmp_path) -> None:
    missing_path = tmp_path / "missing.duckdb"

    with pytest.raises(
        FileNotFoundError,
        match=r"DuckDB database does not exist: .*missing\.duckdb",
    ):
        inspect_schema(missing_path)


def test_inspect_schema_output_is_stable(tmp_path) -> None:
    database_path = tmp_path / "olist.duckdb"
    build_database(DATA_DIR, database_path)

    first = inspect_schema(database_path)
    second = inspect_schema(database_path)

    assert first == second
    assert [obj.name for obj in first.objects] == sorted(
        obj.name for obj in first.objects
    )
    assert isinstance(first.objects, tuple)
    assert all(isinstance(obj.columns, tuple) for obj in first.objects)
