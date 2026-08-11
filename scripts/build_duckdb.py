"""Build the minimal typed DuckDB database from the audited Olist CSV files."""

from __future__ import annotations

import argparse
import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import duckdb


DEFAULT_DATA_DIR = Path("data/raw")
DEFAULT_OUTPUT_PATH = Path("data/processed/olist.duckdb")


@dataclass(frozen=True)
class TableSpec:
    """A traceable mapping from one audited CSV file to one DuckDB table."""

    table_name: str
    csv_filename: str
    columns: tuple[str, ...]
    expected_row_count: int
    create_sql: str
    primary_key: tuple[str, ...]


TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec(
        table_name="customers",
        csv_filename="olist_customers_dataset.csv",
        columns=(
            "customer_id",
            "customer_unique_id",
            "customer_zip_code_prefix",
            "customer_city",
            "customer_state",
        ),
        expected_row_count=99_441,
        create_sql="""
            CREATE TABLE customers (
                customer_id VARCHAR PRIMARY KEY,
                customer_unique_id VARCHAR NOT NULL,
                customer_zip_code_prefix VARCHAR,
                customer_city VARCHAR,
                customer_state VARCHAR
            )
        """,
        primary_key=("customer_id",),
    ),
    TableSpec(
        table_name="orders",
        csv_filename="olist_orders_dataset.csv",
        columns=(
            "order_id",
            "customer_id",
            "order_status",
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ),
        expected_row_count=99_441,
        create_sql="""
            CREATE TABLE orders (
                order_id VARCHAR PRIMARY KEY,
                customer_id VARCHAR NOT NULL,
                order_status VARCHAR NOT NULL,
                order_purchase_timestamp TIMESTAMP NOT NULL,
                order_approved_at TIMESTAMP,
                order_delivered_carrier_date TIMESTAMP,
                order_delivered_customer_date TIMESTAMP,
                order_estimated_delivery_date TIMESTAMP
            )
        """,
        primary_key=("order_id",),
    ),
    TableSpec(
        table_name="order_items",
        csv_filename="olist_order_items_dataset.csv",
        columns=(
            "order_id",
            "order_item_id",
            "product_id",
            "seller_id",
            "shipping_limit_date",
            "price",
            "freight_value",
        ),
        expected_row_count=112_650,
        create_sql="""
            CREATE TABLE order_items (
                order_id VARCHAR NOT NULL,
                order_item_id INTEGER NOT NULL,
                product_id VARCHAR NOT NULL,
                seller_id VARCHAR NOT NULL,
                shipping_limit_date TIMESTAMP,
                price DECIMAL(18, 2) NOT NULL CHECK (price >= 0),
                freight_value DECIMAL(18, 2) NOT NULL CHECK (freight_value >= 0),
                PRIMARY KEY (order_id, order_item_id)
            )
        """,
        primary_key=("order_id", "order_item_id"),
    ),
    TableSpec(
        table_name="order_payments",
        csv_filename="olist_order_payments_dataset.csv",
        columns=(
            "order_id",
            "payment_sequential",
            "payment_type",
            "payment_installments",
            "payment_value",
        ),
        expected_row_count=103_886,
        create_sql="""
            CREATE TABLE order_payments (
                order_id VARCHAR NOT NULL,
                payment_sequential INTEGER NOT NULL,
                payment_type VARCHAR,
                payment_installments INTEGER,
                payment_value DECIMAL(18, 2) NOT NULL CHECK (payment_value >= 0),
                PRIMARY KEY (order_id, payment_sequential)
            )
        """,
        primary_key=("order_id", "payment_sequential"),
    ),
    TableSpec(
        table_name="order_reviews",
        csv_filename="olist_order_reviews_dataset.csv",
        columns=(
            "review_id",
            "order_id",
            "review_score",
            "review_comment_title",
            "review_comment_message",
            "review_creation_date",
            "review_answer_timestamp",
        ),
        expected_row_count=99_224,
        create_sql="""
            CREATE TABLE order_reviews (
                review_id VARCHAR NOT NULL,
                order_id VARCHAR NOT NULL,
                review_score INTEGER NOT NULL CHECK (review_score BETWEEN 1 AND 5),
                review_comment_title VARCHAR,
                review_comment_message VARCHAR,
                review_creation_date TIMESTAMP,
                review_answer_timestamp TIMESTAMP,
                PRIMARY KEY (review_id, order_id)
            )
        """,
        primary_key=("review_id", "order_id"),
    ),
    TableSpec(
        table_name="products",
        csv_filename="olist_products_dataset.csv",
        columns=(
            "product_id",
            "product_category_name",
            "product_name_lenght",
            "product_description_lenght",
            "product_photos_qty",
            "product_weight_g",
            "product_length_cm",
            "product_height_cm",
            "product_width_cm",
        ),
        expected_row_count=32_951,
        create_sql="""
            CREATE TABLE products (
                product_id VARCHAR PRIMARY KEY,
                product_category_name VARCHAR,
                product_name_lenght INTEGER,
                product_description_lenght INTEGER,
                product_photos_qty INTEGER,
                product_weight_g INTEGER,
                product_length_cm INTEGER,
                product_height_cm INTEGER,
                product_width_cm INTEGER
            )
        """,
        primary_key=("product_id",),
    ),
    TableSpec(
        table_name="sellers",
        csv_filename="olist_sellers_dataset.csv",
        columns=(
            "seller_id",
            "seller_zip_code_prefix",
            "seller_city",
            "seller_state",
        ),
        expected_row_count=3_095,
        create_sql="""
            CREATE TABLE sellers (
                seller_id VARCHAR PRIMARY KEY,
                seller_zip_code_prefix VARCHAR,
                seller_city VARCHAR,
                seller_state VARCHAR
            )
        """,
        primary_key=("seller_id",),
    ),
    TableSpec(
        table_name="product_category_translation",
        csv_filename="product_category_name_translation.csv",
        columns=("product_category_name", "product_category_name_english"),
        expected_row_count=71,
        create_sql="""
            CREATE TABLE product_category_translation (
                product_category_name VARCHAR PRIMARY KEY,
                product_category_name_english VARCHAR NOT NULL
            )
        """,
        primary_key=("product_category_name",),
    ),
)


VIEW_SQL: tuple[str, ...] = (
    """
        CREATE VIEW order_item_summary AS
        SELECT
            order_id,
            COUNT(*)::BIGINT AS item_count,
            CAST(SUM(price) AS DECIMAL(18, 2)) AS item_transaction_value,
            CAST(SUM(freight_value) AS DECIMAL(18, 2)) AS freight_value
        FROM order_items
        GROUP BY order_id
    """,
    """
        CREATE VIEW order_payment_summary AS
        SELECT
            order_id,
            COUNT(*)::BIGINT AS payment_record_count,
            CAST(SUM(payment_value) AS DECIMAL(18, 2)) AS payment_value
        FROM order_payments
        GROUP BY order_id
    """,
    """
        CREATE VIEW products_with_category_translation AS
        SELECT
            products.product_id,
            products.product_category_name,
            product_category_translation.product_category_name_english
        FROM products
        LEFT JOIN product_category_translation
            USING (product_category_name)
    """,
)


def _quote_sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _read_header(path: Path) -> tuple[str, ...]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return tuple(next(csv.reader(handle)))
    except (UnicodeDecodeError, csv.Error, StopIteration) as exc:
        raise ValueError(f"Unable to read a valid UTF-8 CSV header: {path}") from exc


def validate_source_files(data_dir: Path) -> dict[str, Path]:
    """Validate the exact audited filenames and headers used by the build."""

    if not data_dir.is_dir():
        raise FileNotFoundError(f"Data directory does not exist: {data_dir}")

    paths: dict[str, Path] = {}
    for spec in TABLE_SPECS:
        path = data_dir / spec.csv_filename
        if not path.is_file():
            raise FileNotFoundError(f"Required source CSV is missing: {path}")
        actual_columns = _read_header(path)
        if actual_columns != spec.columns:
            raise ValueError(
                f"Unexpected header for {path}: expected {spec.columns}, "
                f"found {actual_columns}"
            )
        paths[spec.table_name] = path
    return paths


def _copy_table(
    connection: duckdb.DuckDBPyConnection, spec: TableSpec, csv_path: Path
) -> int:
    connection.execute(spec.create_sql)
    csv_literal = _quote_sql_string(str(csv_path.resolve()))
    connection.execute(
        f"""
        COPY {spec.table_name}
        FROM {csv_literal}
        (
            FORMAT CSV,
            HEADER TRUE,
            DELIMITER ',',
            QUOTE '"',
            ESCAPE '"',
            NULLSTR '',
            TIMESTAMPFORMAT '%Y-%m-%d %H:%M:%S'
        )
        """
    )
    row_count = connection.execute(
        f"SELECT COUNT(*) FROM {spec.table_name}"
    ).fetchone()[0]
    if row_count != spec.expected_row_count:
        raise ValueError(
            f"Unexpected row count for {spec.table_name}: expected "
            f"{spec.expected_row_count:,}, found {row_count:,}"
        )
    return int(row_count)


def build_database(
    data_dir: Path = DEFAULT_DATA_DIR,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    *,
    overwrite: bool = False,
) -> dict[str, int]:
    """Build and atomically publish the audited core Olist DuckDB database."""

    source_paths = validate_source_files(data_dir)
    if not output_path.parent.is_dir():
        raise FileNotFoundError(
            f"Output directory does not exist: {output_path.parent}"
        )
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"Database already exists: {output_path}. Use --force to rebuild it."
        )

    temporary_path = output_path.with_name(f".{output_path.name}.building")
    if temporary_path.exists():
        temporary_path.unlink()

    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = duckdb.connect(str(temporary_path))
        row_counts: dict[str, int] = {}
        for spec in TABLE_SPECS:
            row_counts[spec.table_name] = _copy_table(
                connection, spec, source_paths[spec.table_name]
            )
        for statement in VIEW_SQL:
            connection.execute(statement)
        connection.execute("CHECKPOINT")
        connection.close()
        connection = None
        os.replace(temporary_path, output_path)
        return row_counts
    except Exception:
        if connection is not None:
            connection.close()
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the typed core Olist DuckDB database from audited CSV files."
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Atomically replace an existing database file.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    row_counts = build_database(
        data_dir=args.data_dir,
        output_path=args.output,
        overwrite=args.force,
    )
    print(f"Built DuckDB database: {args.output}")
    for table_name, row_count in row_counts.items():
        print(f"- {table_name}: {row_count:,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
