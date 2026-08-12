"""Tests for deterministic read-only SQL execution."""

from __future__ import annotations

from pathlib import Path

import pytest

import data_analysis_agent.sql_executor as sql_executor_module
from data_analysis_agent import SQLResult, run_readonly_sql
from scripts.build_duckdb import build_database


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "raw"


@pytest.fixture(scope="module")
def database_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("sql_executor") / "olist.duckdb"
    build_database(DATA_DIR, path)
    return path


def test_executes_count_query(database_path: Path) -> None:
    result = run_readonly_sql(database_path, "SELECT COUNT(*) AS count FROM orders")

    assert result == SQLResult(
        executed_sql="SELECT COUNT(*) AS count FROM orders",
        columns=("count",),
        rows=((99_441,),),
        returned_row_count=1,
        truncated=False,
        status="success",
        error=None,
    )


def test_executes_regular_select(database_path: Path) -> None:
    sql = "SELECT order_id, order_status FROM orders ORDER BY order_id LIMIT 3"
    result = run_readonly_sql(database_path, sql)

    assert result.status == "success"
    assert result.columns == ("order_id", "order_status")
    assert result.returned_row_count == 3
    assert result.truncated is False


def test_executes_with_select(database_path: Path) -> None:
    sql = "WITH statuses AS (SELECT order_status FROM orders) SELECT COUNT(*) FROM statuses"
    result = run_readonly_sql(database_path, sql)

    assert result.status == "success"
    assert result.rows == ((99_441,),)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "UPDATE orders SET order_status = 'canceled'",
        "INSERT INTO orders SELECT * FROM orders",
        "DROP TABLE orders",
        "CREATE TABLE copy_of_orders AS SELECT * FROM orders",
        "ALTER TABLE orders ADD COLUMN unsafe INTEGER",
        "TRUNCATE TABLE orders",
        "COPY orders TO '/tmp/orders.csv'",
        "ATTACH 'other.duckdb' AS other",
        "DETACH other",
        "INSTALL httpfs",
        "LOAD httpfs",
        "CALL checkpoint()",
        "EXPORT DATABASE '/tmp/olist_export'",
        "IMPORT DATABASE '/tmp/olist_export'",
        "VACUUM",
        "SET threads = 1",
        "PRAGMA version",
    ],
)
def test_rejects_unsafe_statement(database_path: Path, sql: str) -> None:
    result = run_readonly_sql(database_path, sql)

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "unsafe_sql"
    assert result.rows == ()


def test_rejects_multiple_statements(database_path: Path) -> None:
    result = run_readonly_sql(database_path, "SELECT 1; SELECT 2")

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "multiple_statements"


def test_comments_and_string_literals_do_not_trigger_false_rejection(
    database_path: Path,
) -> None:
    sql = "-- DELETE is text only\nSELECT 'DROP TABLE orders' AS statement_text"
    result = run_readonly_sql(database_path, sql)

    assert result.status == "success"
    assert result.rows == (("DROP TABLE orders",),)


def test_limits_materialized_rows_and_marks_truncation(database_path: Path) -> None:
    result = run_readonly_sql(
        database_path,
        "SELECT order_id, order_item_id FROM order_items ORDER BY order_id, order_item_id",
        max_rows=5,
    )

    assert result.status == "success"
    assert result.returned_row_count == 5
    assert len(result.rows) == 5
    assert result.truncated is True


def test_exact_row_limit_is_not_marked_truncated(database_path: Path) -> None:
    result = run_readonly_sql(database_path, "SELECT * FROM orders LIMIT 5", max_rows=5)

    assert result.returned_row_count == 5
    assert result.truncated is False


def test_fetches_only_max_rows_plus_one_without_fetchall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "placeholder.duckdb"
    database_path.touch()

    class FakeCursor:
        description = (("value",),)

        def fetchmany(self, size: int):
            assert size == 4
            return [(1,), (2,), (3,), (4,)]

        def fetchall(self):
            raise AssertionError("fetchall must not be used by the executor")

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def execute(self, sql: str):
            assert sql == "SELECT value FROM large_table"
            return FakeCursor()

    def fake_connect(path: str, *, read_only: bool, config: dict[str, str]):
        assert path == str(database_path)
        assert read_only is True
        assert config["enable_external_access"] == "false"
        return FakeConnection()

    monkeypatch.setattr(sql_executor_module.duckdb, "connect", fake_connect)

    result = run_readonly_sql(
        database_path,
        "SELECT value FROM large_table",
        max_rows=3,
    )

    assert result.rows == ((1,), (2,), (3,))
    assert result.returned_row_count == 3
    assert result.truncated is True


def test_reports_invalid_max_rows(database_path: Path) -> None:
    result = run_readonly_sql(database_path, "SELECT 1", max_rows=0)

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_argument"


def test_reports_missing_database(tmp_path: Path) -> None:
    result = run_readonly_sql(tmp_path / "missing.duckdb", "SELECT 1")

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "database_missing"


def test_reports_invalid_sql(database_path: Path) -> None:
    result = run_readonly_sql(database_path, "SELECT COUNT(* FROM orders")

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "invalid_sql"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM table_that_does_not_exist",
        "SELECT column_that_does_not_exist FROM orders",
    ],
)
def test_reports_unknown_table_or_column(database_path: Path, sql: str) -> None:
    result = run_readonly_sql(database_path, sql)

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "unknown_table_or_column"


def test_external_file_access_is_disabled(database_path: Path) -> None:
    result = run_readonly_sql(database_path, "SELECT * FROM read_csv('/etc/passwd')")

    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "execution_error"
    assert "file system operations are disabled" in result.error.message.lower()
