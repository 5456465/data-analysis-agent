"""Tests for read-only adapters shared by future tool integrations."""

from __future__ import annotations

import ast
import inspect
import json
from dataclasses import fields
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

import data_analysis_agent.integration_tools as integration_tools
from data_analysis_agent.metric_catalog import METRIC_DEFINITIONS_V2
from data_analysis_agent.schema import (
    ColumnSchema,
    DatabaseSchema,
    SchemaObject,
)
from data_analysis_agent.sql_executor import SQLExecutionError, SQLResult


def test_schema_tool_binds_path_and_calls_existing_inspector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trusted_path = tmp_path / "trusted.duckdb"
    observed_paths: list[Path] = []

    def fake_inspect_schema(database_path: str | Path) -> DatabaseSchema:
        observed_paths.append(Path(database_path))
        return DatabaseSchema(
            objects=(
                SchemaObject(
                    name="orders",
                    object_type="table",
                    grain="one row per order",
                    columns=(
                        ColumnSchema("order_id", "VARCHAR", False, True),
                    ),
                ),
                SchemaObject(
                    name="order_item_summary",
                    object_type="view",
                    grain="one row per order",
                    columns=(
                        ColumnSchema("item_count", "BIGINT", True, False),
                    ),
                ),
            )
        )

    monkeypatch.setattr(integration_tools, "inspect_schema", fake_inspect_schema)

    tool = integration_tools.inspect_schema_tool(trusted_path)
    result = tool()

    assert observed_paths == [trusted_path]
    assert tuple(inspect.signature(tool).parameters) == ()
    assert result == {
        "tables": [
            {
                "name": "orders",
                "object_type": "table",
                "grain": "one row per order",
                "columns": [
                    {
                        "name": "order_id",
                        "data_type": "VARCHAR",
                        "nullable": False,
                        "primary_key": True,
                    }
                ],
            }
        ],
        "views": [
            {
                "name": "order_item_summary",
                "object_type": "view",
                "grain": "one row per order",
                "columns": [
                    {
                        "name": "item_count",
                        "data_type": "BIGINT",
                        "nullable": True,
                        "primary_key": False,
                    }
                ],
            }
        ],
    }
    json.dumps(result, allow_nan=False)


def test_schema_tool_arguments_cannot_override_database_path(tmp_path: Path) -> None:
    tool = integration_tools.inspect_schema_tool(tmp_path / "trusted.duckdb")

    with pytest.raises(TypeError):
        tool(database_path=tmp_path / "other.duckdb")  # type: ignore[call-arg]


def test_sql_tool_binds_path_and_fixed_row_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trusted_path = tmp_path / "trusted.duckdb"
    observed_calls: list[tuple[Path, str, int]] = []

    def fake_run_readonly_sql(
        database_path: str | Path,
        sql: str,
        max_rows: int,
    ) -> SQLResult:
        observed_calls.append((Path(database_path), sql, max_rows))
        return SQLResult(
            executed_sql=sql,
            columns=("value",),
            rows=((1,),),
            returned_row_count=1,
            truncated=False,
            status="success",
            error=None,
        )

    monkeypatch.setattr(
        integration_tools,
        "run_readonly_sql",
        fake_run_readonly_sql,
    )

    tool = integration_tools.run_readonly_sql_tool(trusted_path)
    result = tool("SELECT 1 AS value")

    assert tuple(inspect.signature(tool).parameters) == ("sql",)
    assert observed_calls == [
        (
            trusted_path,
            "SELECT 1 AS value",
            integration_tools.INTEGRATION_MAX_ROWS,
        )
    ]
    assert result["status"] == "success"


def test_sql_tool_arguments_cannot_override_path_or_row_limit(
    tmp_path: Path,
) -> None:
    tool = integration_tools.run_readonly_sql_tool(tmp_path / "trusted.duckdb")

    with pytest.raises(TypeError):
        tool(  # type: ignore[call-arg]
            sql="SELECT 1",
            database_path=tmp_path / "other.duckdb",
        )
    with pytest.raises(TypeError):
        tool(sql="SELECT 1", max_rows=10_000)  # type: ignore[call-arg]


def test_sql_result_is_json_safe_for_supported_duckdb_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sql_result = SQLResult(
        executed_sql="SELECT values",
        columns=("amount", "order_date", "created_at"),
        rows=(
            (
                Decimal("123.4500"),
                date(2024, 1, 2),
                datetime(2024, 1, 2, 3, 4, 5),
            ),
        ),
        returned_row_count=1,
        truncated=False,
        status="success",
        error=None,
    )
    monkeypatch.setattr(
        integration_tools,
        "run_readonly_sql",
        lambda database_path, sql, max_rows: sql_result,
    )

    result = integration_tools.run_readonly_sql_tool(
        tmp_path / "trusted.duckdb"
    )("SELECT values")

    assert result == {
        "status": "success",
        "executed_sql": "SELECT values",
        "columns": ["amount", "order_date", "created_at"],
        "rows": [["123.4500", "2024-01-02", "2024-01-02T03:04:05"]],
        "returned_row_count": 1,
        "truncated": False,
        "error": None,
    }
    json.dumps(result, allow_nan=False)


def test_sql_error_contract_preserves_executor_safety_semantics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sql_result = SQLResult(
        executed_sql="DROP TABLE orders",
        columns=(),
        rows=(),
        returned_row_count=0,
        truncated=False,
        status="error",
        error=SQLExecutionError(
            "unsafe_sql",
            "Only SELECT or WITH ... SELECT statements are allowed.",
        ),
    )
    monkeypatch.setattr(
        integration_tools,
        "run_readonly_sql",
        lambda database_path, sql, max_rows: sql_result,
    )

    result = integration_tools.run_readonly_sql_tool(
        tmp_path / "trusted.duckdb"
    )("DROP TABLE orders")

    assert result["status"] == "error"
    assert result["error"] == {
        "code": "unsafe_sql",
        "message": "Only SELECT or WITH ... SELECT statements are allowed.",
    }


def test_metric_identifier_uses_exact_v2_definition() -> None:
    identifier = "average_delivery_duration_days"
    metric = next(
        item for item in METRIC_DEFINITIONS_V2 if item.identifier == identifier
    )

    result = integration_tools.get_metric_definition_tool(identifier)

    expected_metric = {
        field.name: (
            list(value)
            if isinstance((value := getattr(metric, field.name)), tuple)
            else value
        )
        for field in fields(metric)
    }
    assert result == {"status": "success", "metric": expected_metric}
    assert integration_tools.get_metric_definition_tool(
        identifier.upper()
    )["status"] == "not_found"
    assert integration_tools.get_metric_definition_tool(
        f" {identifier}"
    )["status"] == "not_found"
    json.dumps(result, allow_nan=False)


def test_unknown_metric_returns_stable_not_found() -> None:
    result = integration_tools.get_metric_definition_tool("unknown_metric")

    assert result == {
        "status": "not_found",
        "identifier": "unknown_metric",
        "error": {
            "code": "not_found",
            "message": "Unknown metric identifier: unknown_metric",
        },
    }


def test_metric_output_does_not_modify_or_share_mutable_catalog_state() -> None:
    catalog_before = METRIC_DEFINITIONS_V2
    metric_before = METRIC_DEFINITIONS_V2[0]
    instructions_before = metric_before.instructions

    result = integration_tools.get_metric_definition_tool(metric_before.identifier)
    metric_payload = result["metric"]
    assert isinstance(metric_payload, dict)
    output_instructions = metric_payload["instructions"]
    assert isinstance(output_instructions, list)
    output_instructions.append("adapter-only mutation")

    assert METRIC_DEFINITIONS_V2 is catalog_before
    assert METRIC_DEFINITIONS_V2[0] is metric_before
    assert metric_before.instructions is instructions_before
    assert "adapter-only mutation" not in metric_before.instructions


def test_adapter_has_no_arbitrary_execution_shell_or_network_capability() -> None:
    source = inspect.getsource(integration_tools)
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    called_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_roots.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called_names.add(node.func.id)

    assert imported_roots.isdisjoint(
        {"httpx", "os", "requests", "socket", "subprocess", "urllib"}
    )
    assert called_names.isdisjoint(
        {"__import__", "compile", "eval", "exec", "open"}
    )
