"""JSON-safe read-only adapters for future external tool integrations."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import fields
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TypeAlias

from data_analysis_agent.metric_catalog import METRIC_DEFINITIONS_V2
from data_analysis_agent.schema import SchemaObject, inspect_schema
from data_analysis_agent.sql_executor import (
    DEFAULT_MAX_ROWS,
    SQLResult,
    run_readonly_sql,
)


JSONScalar: TypeAlias = None | str | int | float | bool
JSONValue: TypeAlias = (
    JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
)
JSONDict: TypeAlias = dict[str, JSONValue]
InspectSchemaTool: TypeAlias = Callable[[], JSONDict]
ReadonlySQLTool: TypeAlias = Callable[[str], JSONDict]

INTEGRATION_MAX_ROWS = DEFAULT_MAX_ROWS


def inspect_schema_tool(database_path: str | Path) -> InspectSchemaTool:
    """Bind a trusted database path and return a zero-argument schema tool."""

    bound_database_path = Path(database_path)

    def bound_inspect_schema_tool() -> JSONDict:
        schema = inspect_schema(bound_database_path)
        return {
            "tables": [
                _schema_object_to_json(item)
                for item in schema.objects
                if item.object_type == "table"
            ],
            "views": [
                _schema_object_to_json(item)
                for item in schema.objects
                if item.object_type == "view"
            ],
        }

    return bound_inspect_schema_tool


def run_readonly_sql_tool(database_path: str | Path) -> ReadonlySQLTool:
    """Bind a trusted database path and return a SQL-only tool callable."""

    bound_database_path = Path(database_path)
    max_rows = INTEGRATION_MAX_ROWS

    def bound_run_readonly_sql_tool(sql: str) -> JSONDict:
        result = run_readonly_sql(
            bound_database_path,
            sql,
            max_rows=max_rows,
        )
        return _sql_result_to_json(result)

    return bound_run_readonly_sql_tool


def get_metric_definition_tool(identifier: str) -> JSONDict:
    """Return one exact governed V2 metric definition or stable not-found data."""

    if not isinstance(identifier, str):
        raise TypeError("identifier must be a string.")

    metric = next(
        (
            definition
            for definition in METRIC_DEFINITIONS_V2
            if definition.identifier == identifier
        ),
        None,
    )
    if metric is None:
        return {
            "status": "not_found",
            "identifier": identifier,
            "error": {
                "code": "not_found",
                "message": f"Unknown metric identifier: {identifier}",
            },
        }

    metric_payload = {
        field.name: _to_json_safe(getattr(metric, field.name))
        for field in fields(metric)
    }
    return {
        "status": "success",
        "metric": metric_payload,
    }


def _schema_object_to_json(schema_object: SchemaObject) -> JSONDict:
    return {
        "name": schema_object.name,
        "object_type": schema_object.object_type,
        "grain": schema_object.grain,
        "columns": [
            {
                "name": column.name,
                "data_type": column.data_type,
                "nullable": column.nullable,
                "primary_key": column.primary_key,
            }
            for column in schema_object.columns
        ],
    }


def _sql_result_to_json(result: SQLResult) -> JSONDict:
    error: JSONValue = None
    if result.error is not None:
        error = {
            "code": result.error.code,
            "message": result.error.message,
        }

    payload: dict[str, object] = {
        "status": result.status,
        "executed_sql": result.executed_sql,
        "columns": result.columns,
        "rows": result.rows,
        "returned_row_count": result.returned_row_count,
        "truncated": result.truncated,
        "error": error,
    }
    converted = _to_json_safe(payload)
    if not isinstance(converted, dict):
        raise TypeError("SQL result conversion must produce a JSON object.")
    return converted


def _to_json_safe(value: object) -> JSONValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings.")
        return {
            key: _to_json_safe(item)
            for key, item in value.items()
        }
    raise TypeError(f"Unsupported JSON value type: {type(value).__name__}")
