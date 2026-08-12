"""Deterministic DuckDB schema inspection for the Olist MVP database."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import duckdb


ObjectType = Literal["table", "view"]


@dataclass(frozen=True)
class ColumnSchema:
    """Catalog metadata for one DuckDB column."""

    name: str
    data_type: str
    nullable: bool
    primary_key: bool


@dataclass(frozen=True)
class SchemaObject:
    """A table or view and its ordered columns."""

    name: str
    object_type: ObjectType
    columns: tuple[ColumnSchema, ...]
    grain: str | None = None


@dataclass(frozen=True)
class DatabaseSchema:
    """Stable structured schema returned by :func:`inspect_schema`."""

    objects: tuple[SchemaObject, ...]


GRAIN_BY_OBJECT: dict[str, str] = {
    "orders": "one row per order",
    "order_items": "one row per order item",
    "order_payments": "one row per payment record",
    "order_item_summary": "one row per order",
    "order_payment_summary": "one row per order",
}


_OBJECT_TYPE_BY_CATALOG_VALUE: dict[str, ObjectType] = {
    "BASE TABLE": "table",
    "VIEW": "view",
}


def inspect_schema(database_path: str | Path) -> DatabaseSchema:
    """Read table, view, column, type, nullability, and primary-key metadata.

    The database is opened in read-only mode. Object order is alphabetical and
    column order follows DuckDB's catalog ordinal position.
    """

    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError(f"DuckDB database does not exist: {path}")

    with duckdb.connect(str(path), read_only=True) as connection:
        primary_key_columns = _read_primary_key_columns(connection)
        rows = connection.execute(
            """
            SELECT
                tables.table_name,
                tables.table_type,
                columns.column_name,
                columns.data_type,
                columns.is_nullable
            FROM information_schema.tables AS tables
            JOIN information_schema.columns AS columns
              ON tables.table_catalog = columns.table_catalog
             AND tables.table_schema = columns.table_schema
             AND tables.table_name = columns.table_name
            WHERE tables.table_schema = 'main'
              AND tables.table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY tables.table_name, columns.ordinal_position
            """
        ).fetchall()

    objects: list[SchemaObject] = []
    current_name: str | None = None
    current_type: ObjectType | None = None
    current_columns: list[ColumnSchema] = []

    for object_name, catalog_type, column_name, data_type, is_nullable in rows:
        object_type = _OBJECT_TYPE_BY_CATALOG_VALUE[catalog_type]
        if current_name is not None and object_name != current_name:
            objects.append(
                _build_schema_object(current_name, current_type, current_columns)
            )
            current_columns = []
        current_name = object_name
        current_type = object_type
        current_columns.append(
            ColumnSchema(
                name=column_name,
                data_type=data_type,
                nullable=is_nullable == "YES",
                primary_key=(object_name, column_name) in primary_key_columns,
            )
        )

    if current_name is not None:
        objects.append(
            _build_schema_object(current_name, current_type, current_columns)
        )

    return DatabaseSchema(objects=tuple(objects))


def _read_primary_key_columns(
    connection: duckdb.DuckDBPyConnection,
) -> set[tuple[str, str]]:
    rows = connection.execute(
        """
        SELECT constraints.table_name, keys.column_name
        FROM information_schema.table_constraints AS constraints
        JOIN information_schema.key_column_usage AS keys
          ON constraints.constraint_catalog = keys.constraint_catalog
         AND constraints.constraint_schema = keys.constraint_schema
         AND constraints.constraint_name = keys.constraint_name
        WHERE constraints.table_schema = 'main'
          AND constraints.constraint_type = 'PRIMARY KEY'
        """
    ).fetchall()
    return {(table_name, column_name) for table_name, column_name in rows}


def _build_schema_object(
    name: str,
    object_type: ObjectType | None,
    columns: list[ColumnSchema],
) -> SchemaObject:
    if object_type is None:
        raise RuntimeError(f"Missing object type for schema object: {name}")
    return SchemaObject(
        name=name,
        object_type=object_type,
        columns=tuple(columns),
        grain=GRAIN_BY_OBJECT.get(name),
    )
