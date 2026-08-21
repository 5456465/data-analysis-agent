"""Tests for the local read-only stdio MCP server."""

from __future__ import annotations

import ast
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

from data_analysis_agent import mcp_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
DATABASE_PATH = PROJECT_ROOT / "data" / "processed" / "olist.duckdb"
EXPECTED_TOOL_NAMES = {
    "inspect_schema",
    "run_readonly_sql",
    "get_metric_definition",
}


def _run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


async def _list_tools(server: Any) -> list[Any]:
    async with Client(server) as client:
        return (await client.list_tools()).tools


async def _call_tool(
    server: Any,
    name: str,
    arguments: dict[str, object],
) -> Any:
    async with Client(server) as client:
        return await client.call_tool(name, arguments)


def test_server_registers_only_the_three_expected_tools() -> None:
    server = mcp_server.create_mcp_server(DATABASE_PATH)

    tools = _run(_list_tools(server))

    assert {tool.name for tool in tools} == EXPECTED_TOOL_NAMES


def test_tool_input_schemas_expose_only_the_allowed_arguments() -> None:
    server = mcp_server.create_mcp_server(DATABASE_PATH)
    tools = {tool.name: tool for tool in _run(_list_tools(server))}

    assert tools["inspect_schema"].input_schema.get("properties") == {}
    assert tools["inspect_schema"].input_schema.get("required", []) == []
    assert set(tools["run_readonly_sql"].input_schema["properties"]) == {
        "sql"
    }
    assert tools["run_readonly_sql"].input_schema["required"] == ["sql"]
    assert set(
        tools["get_metric_definition"].input_schema["properties"]
    ) == {"identifier"}
    assert tools["get_metric_definition"].input_schema["required"] == [
        "identifier"
    ]

    all_schema_text = repr(
        {name: tool.input_schema for name, tool in tools.items()}
    )
    assert "db_path" not in all_schema_text
    assert "database_path" not in all_schema_text
    assert "max_rows" not in all_schema_text


def test_mcp_tools_delegate_to_the_existing_adapters(
    monkeypatch: Any,
) -> None:
    calls: dict[str, object] = {}
    trusted_path = Path("trusted.duckdb")

    def fake_inspect_schema_tool(database_path: str | Path) -> Any:
        calls["inspect_bound_path"] = Path(database_path)

        def inspect() -> dict[str, object]:
            calls["inspect_called"] = True
            return {"tables": [], "views": []}

        return inspect

    def fake_run_readonly_sql_tool(database_path: str | Path) -> Any:
        calls["sql_bound_path"] = Path(database_path)

        def run(sql: str) -> dict[str, object]:
            calls["sql"] = sql
            return {
                "status": "success",
                "executed_sql": sql,
                "columns": ["value"],
                "rows": [[1]],
                "returned_row_count": 1,
                "truncated": False,
                "error": None,
            }

        return run

    def fake_get_metric_definition_tool(
        identifier: str,
    ) -> dict[str, object]:
        calls["identifier"] = identifier
        return {"status": "success", "metric": {"identifier": identifier}}

    monkeypatch.setattr(
        mcp_server,
        "inspect_schema_tool",
        fake_inspect_schema_tool,
    )
    monkeypatch.setattr(
        mcp_server,
        "run_readonly_sql_tool",
        fake_run_readonly_sql_tool,
    )
    monkeypatch.setattr(
        mcp_server,
        "get_metric_definition_tool",
        fake_get_metric_definition_tool,
    )
    server = mcp_server.create_mcp_server(trusted_path)

    inspect_result = _run(_call_tool(server, "inspect_schema", {}))
    sql_result = _run(
        _call_tool(server, "run_readonly_sql", {"sql": "SELECT 1"})
    )
    metric_result = _run(
        _call_tool(
            server,
            "get_metric_definition",
            {"identifier": "average_review_score"},
        )
    )

    assert calls == {
        "inspect_bound_path": trusted_path,
        "sql_bound_path": trusted_path,
        "inspect_called": True,
        "sql": "SELECT 1",
        "identifier": "average_review_score",
    }
    assert inspect_result.structured_content == {"tables": [], "views": []}
    assert sql_result.structured_content["executed_sql"] == "SELECT 1"
    assert metric_result.structured_content == {
        "status": "success",
        "metric": {"identifier": "average_review_score"},
    }


def test_caller_arguments_cannot_change_bound_path_or_row_limit(
    monkeypatch: Any,
) -> None:
    calls: dict[str, object] = {}
    trusted_path = Path("trusted.duckdb")

    def fake_run_readonly_sql_tool(database_path: str | Path) -> Any:
        calls["bound_path"] = Path(database_path)

        def run(sql: str) -> dict[str, object]:
            calls["sql"] = sql
            return {"status": "success"}

        return run

    monkeypatch.setattr(
        mcp_server,
        "run_readonly_sql_tool",
        fake_run_readonly_sql_tool,
    )
    server = mcp_server.create_mcp_server(trusted_path)

    result = _run(
        _call_tool(
            server,
            "run_readonly_sql",
            {
                "sql": "SELECT 1",
                "db_path": "attacker.duckdb",
                "database_path": "attacker-2.duckdb",
                "max_rows": 1_000_000,
            },
        )
    )

    assert result.structured_content == {"status": "success"}
    assert calls == {
        "bound_path": trusted_path,
        "sql": "SELECT 1",
    }


def test_unknown_metric_preserves_stable_not_found_result() -> None:
    server = mcp_server.create_mcp_server(DATABASE_PATH)

    result = _run(
        _call_tool(
            server,
            "get_metric_definition",
            {"identifier": "not_a_metric"},
        )
    )

    assert result.structured_content == {
        "status": "not_found",
        "identifier": "not_a_metric",
        "error": {
            "code": "not_found",
            "message": "Unknown metric identifier: not_a_metric",
        },
    }


def test_database_path_is_resolved_only_from_startup_configuration(
    tmp_path: Path,
) -> None:
    default_path = mcp_server.resolve_database_path(
        {},
        working_directory=tmp_path,
    )
    configured_path = mcp_server.resolve_database_path(
        {mcp_server.DATABASE_PATH_ENV_VAR: "runtime/custom.duckdb"},
        working_directory=tmp_path,
    )

    assert default_path == (tmp_path / mcp_server.DEFAULT_DATABASE_PATH).resolve()
    assert configured_path == (tmp_path / "runtime/custom.duckdb").resolve()


def test_mcp_layer_contains_no_executor_catalog_or_external_capabilities() -> None:
    source_path = SOURCE_ROOT / "data_analysis_agent" / "mcp_server.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    assert "data_analysis_agent.integration_tools" in imported_modules
    assert "data_analysis_agent.sql_executor" not in imported_modules
    assert "data_analysis_agent.metric_catalog" not in imported_modules
    assert imported_modules.isdisjoint(
        {"subprocess", "socket", "requests", "httpx", "openai"}
    )


def test_real_stdio_protocol_initialize_list_and_call() -> None:
    server_parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "data_analysis_agent.mcp_server"],
        cwd=PROJECT_ROOT,
        env={
            "PYTHONPATH": str(SOURCE_ROOT),
            mcp_server.DATABASE_PATH_ENV_VAR: str(DATABASE_PATH),
        },
    )

    async def smoke_test() -> None:
        with open(os.devnull, "w", encoding="utf-8") as error_log:
            async with Client(
                stdio_client(server_parameters, errlog=error_log),
                read_timeout_seconds=10,
            ) as client:
                tools = (await client.list_tools()).tools
                assert {tool.name for tool in tools} == EXPECTED_TOOL_NAMES
                result = await client.call_tool(
                    "get_metric_definition",
                    {"identifier": "average_review_score"},
                )
                assert result.is_error is False
                assert result.structured_content is not None
                assert result.structured_content["status"] == "success"
                assert result.structured_content["metric"]["identifier"] == (
                    "average_review_score"
                )

    _run(smoke_test())
