"""Deterministic read-only SQL execution for the Olist MVP database."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import duckdb


DEFAULT_MAX_ROWS = 200

SQLStatus = Literal["success", "error"]
SQLErrorCode = Literal[
    "database_missing",
    "invalid_argument",
    "unsafe_sql",
    "multiple_statements",
    "invalid_sql",
    "unknown_table_or_column",
    "execution_error",
]


@dataclass(frozen=True)
class SQLExecutionError:
    """Structured error returned when SQL cannot be executed safely."""

    code: SQLErrorCode
    message: str


@dataclass(frozen=True)
class SQLResult:
    """Stable structured result for one read-only SQL query."""

    executed_sql: str
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    returned_row_count: int
    truncated: bool
    status: SQLStatus
    error: SQLExecutionError | None


def run_readonly_sql(
    database_path: str | Path,
    sql: str,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> SQLResult:
    """Validate and execute one SELECT query against DuckDB in read-only mode.

    At most ``max_rows`` rows are materialized in Python. One additional row is
    fetched only to determine whether the returned result was truncated.
    """

    if not isinstance(max_rows, int) or isinstance(max_rows, bool) or max_rows <= 0:
        return _error_result(
            sql,
            "invalid_argument",
            "max_rows must be a positive integer.",
        )

    path = Path(database_path)
    if not path.is_file():
        return _error_result(
            sql,
            "database_missing",
            f"DuckDB database does not exist: {path}",
        )

    safety_error = _validate_readonly_query(sql)
    if safety_error is not None:
        return _error_result(sql, safety_error.code, safety_error.message)

    try:
        with duckdb.connect(
            str(path),
            read_only=True,
            config={
                "enable_external_access": "false",
                "autoload_known_extensions": "false",
                "autoinstall_known_extensions": "false",
            },
        ) as connection:
            cursor = connection.execute(sql)
            columns = tuple(description[0] for description in cursor.description)
            fetched_rows = cursor.fetchmany(max_rows + 1)
    except duckdb.ParserException as exc:
        return _error_result(sql, "invalid_sql", str(exc))
    except (duckdb.CatalogException, duckdb.BinderException) as exc:
        message = str(exc)
        code: SQLErrorCode = (
            "unknown_table_or_column"
            if _is_unknown_table_or_column(message)
            else "execution_error"
        )
        return _error_result(sql, code, message)
    except duckdb.Error as exc:
        return _error_result(sql, "execution_error", str(exc))

    truncated = len(fetched_rows) > max_rows
    rows = tuple(fetched_rows[:max_rows])
    return SQLResult(
        executed_sql=sql,
        columns=columns,
        rows=rows,
        returned_row_count=len(rows),
        truncated=truncated,
        status="success",
        error=None,
    )


def _validate_readonly_query(sql: str) -> SQLExecutionError | None:
    if not isinstance(sql, str) or not sql.strip():
        return SQLExecutionError("invalid_sql", "SQL must be a non-empty string.")

    first_keyword = _first_keyword(sql)
    if first_keyword not in {"SELECT", "WITH"}:
        return SQLExecutionError(
            "unsafe_sql",
            "Only SELECT or WITH ... SELECT statements are allowed.",
        )

    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.ParserException as exc:
        return SQLExecutionError("invalid_sql", str(exc))

    if len(statements) > 1:
        return SQLExecutionError(
            "multiple_statements",
            "Exactly one SQL statement is allowed.",
        )
    if not statements:
        return SQLExecutionError("invalid_sql", "SQL must contain one statement.")

    statement = statements[0]
    if statement.type != duckdb.StatementType.SELECT:
        return SQLExecutionError(
            "unsafe_sql",
            "Only SELECT or WITH ... SELECT statements are allowed.",
        )
    return None


def _first_keyword(sql: str) -> str | None:
    """Return the first bare keyword after whitespace and SQL comments."""

    index = 0
    length = len(sql)
    while index < length:
        if sql[index].isspace():
            index += 1
            continue
        if sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            index = length if newline == -1 else newline + 1
            continue
        if sql.startswith("/*", index):
            index = _skip_block_comment(sql, index)
            continue
        break

    start = index
    while index < length and (sql[index].isalnum() or sql[index] == "_"):
        index += 1
    if index == start:
        return None
    return sql[start:index].upper()


def _skip_block_comment(sql: str, start: int) -> int:
    depth = 1
    index = start + 2
    while index < len(sql) and depth:
        if sql.startswith("/*", index):
            depth += 1
            index += 2
        elif sql.startswith("*/", index):
            depth -= 1
            index += 2
        else:
            index += 1
    return index


def _is_unknown_table_or_column(message: str) -> bool:
    normalized = message.lower()
    return any(
        marker in normalized
        for marker in (
            "table with name",
            "referenced column",
            "does not have a column named",
        )
    )


def _error_result(
    sql: object,
    code: SQLErrorCode,
    message: str,
) -> SQLResult:
    return SQLResult(
        executed_sql=sql if isinstance(sql, str) else repr(sql),
        columns=(),
        rows=(),
        returned_row_count=0,
        truncated=False,
        status="error",
        error=SQLExecutionError(code=code, message=message),
    )
