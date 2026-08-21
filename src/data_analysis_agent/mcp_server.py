"""Local stdio MCP server exposing the governed read-only integrations."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from data_analysis_agent.integration_tools import (
    get_metric_definition_tool,
    inspect_schema_tool,
    run_readonly_sql_tool,
)


DATABASE_PATH_ENV_VAR = "DATA_ANALYSIS_AGENT_DB_PATH"
DEFAULT_DATABASE_PATH = Path("data/processed/olist.duckdb")
SERVER_NAME = "data-analysis-agent-readonly"

READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    openWorldHint=False,
)


def resolve_database_path(
    environment: Mapping[str, str] | None = None,
    *,
    working_directory: Path | None = None,
) -> Path:
    """Resolve the trusted database path from startup configuration."""

    values = os.environ if environment is None else environment
    configured_path = Path(
        values.get(DATABASE_PATH_ENV_VAR, str(DEFAULT_DATABASE_PATH))
    ).expanduser()
    if configured_path.is_absolute():
        return configured_path.resolve()

    base_directory = Path.cwd() if working_directory is None else working_directory
    return (base_directory / configured_path).resolve()


def create_mcp_server(database_path: str | Path) -> MCPServer:
    """Create one MCP server with adapters bound to a trusted database path."""

    bound_inspect_schema = inspect_schema_tool(database_path)
    bound_run_sql = run_readonly_sql_tool(database_path)
    server = MCPServer(SERVER_NAME)

    @server.tool(annotations=READ_ONLY_ANNOTATIONS)
    def inspect_schema() -> dict[str, Any]:
        """Inspect tables, views, columns, types, and available grain metadata."""

        return bound_inspect_schema()

    @server.tool(annotations=READ_ONLY_ANNOTATIONS)
    def run_readonly_sql(sql: str) -> dict[str, Any]:
        """Execute one read-only SQL query through the existing safe executor."""

        return bound_run_sql(sql)

    @server.tool(annotations=READ_ONLY_ANNOTATIONS)
    def get_metric_definition(identifier: str) -> dict[str, Any]:
        """Retrieve one exact governed metric definition by identifier."""

        return get_metric_definition_tool(identifier)

    return server


mcp = create_mcp_server(resolve_database_path())


def main() -> None:
    """Run the MCP server over the SDK-provided stdio transport."""

    mcp.run()


if __name__ == "__main__":
    main()
