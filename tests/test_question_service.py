"""Tests for the question-to-SQL-to-execution orchestration."""

from __future__ import annotations

from pathlib import Path

import data_analysis_agent.question_service as service_module
from data_analysis_agent.question_service import QuestionAnswerResult, answer_question
from data_analysis_agent.schema import DatabaseSchema
from data_analysis_agent.sql_executor import SQLExecutionError, SQLResult
from data_analysis_agent.sql_generator import SQLGenerationError


SCHEMA = DatabaseSchema(objects=())
QUESTION = "How many orders are in the dataset?"
SQL = "SELECT COUNT(*) AS order_count FROM orders"


def test_generation_and_execution_succeed(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "olist.duckdb"
    inspected_paths: list[str | Path] = []
    execution_calls: list[tuple[str | Path, str, int]] = []
    expected_execution = SQLResult(
        executed_sql=SQL,
        columns=("order_count",),
        rows=((99_441,),),
        returned_row_count=1,
        truncated=False,
        status="success",
        error=None,
    )

    def fake_inspect_schema(path: str | Path) -> DatabaseSchema:
        inspected_paths.append(path)
        return SCHEMA

    def fake_executor(path: str | Path, sql: str, max_rows: int) -> SQLResult:
        execution_calls.append((path, sql, max_rows))
        return expected_execution

    monkeypatch.setattr(service_module, "inspect_schema", fake_inspect_schema)
    monkeypatch.setattr(service_module, "run_readonly_sql", fake_executor)

    result = answer_question(
        database_path,
        QUESTION,
        lambda prompt: {"status": "success", "sql": SQL},
        max_rows=25,
    )

    assert result == QuestionAnswerResult(
        question=QUESTION,
        generated_sql=SQL,
        status="success",
        execution_result=expected_execution,
        generation_error=None,
        execution_error=None,
    )
    assert inspected_paths == [database_path]
    assert execution_calls == [(database_path, SQL, 25)]


def test_generation_failure_is_returned() -> None:
    reason = "The question cannot be answered from the provided schema."

    result = answer_question(
        "unused.duckdb",
        QUESTION,
        lambda prompt: {"status": "error", "error": reason},
        schema=SCHEMA,
    )

    assert result.status == "generation_error"
    assert result.generated_sql is None
    assert result.execution_result is None
    assert result.generation_error == SQLGenerationError(
        code="cannot_generate",
        message=reason,
    )
    assert result.execution_error is None


def test_execution_failure_preserves_sql_and_error(monkeypatch) -> None:
    execution_error = SQLExecutionError(
        code="unknown_table_or_column",
        message='Table with name "missing" does not exist.',
    )
    failed_execution = SQLResult(
        executed_sql=SQL,
        columns=(),
        rows=(),
        returned_row_count=0,
        truncated=False,
        status="error",
        error=execution_error,
    )
    monkeypatch.setattr(
        service_module,
        "run_readonly_sql",
        lambda database_path, sql, max_rows: failed_execution,
    )

    result = answer_question(
        "unused.duckdb",
        QUESTION,
        lambda prompt: {"status": "success", "sql": SQL},
        schema=SCHEMA,
    )

    assert result.status == "execution_error"
    assert result.generated_sql == SQL
    assert result.execution_result == failed_execution
    assert result.generation_error is None
    assert result.execution_error == execution_error


def test_generation_failure_does_not_call_executor(monkeypatch) -> None:
    def unexpected_executor(database_path, sql, max_rows):
        raise AssertionError("executor must not run after generation failure")

    monkeypatch.setattr(service_module, "run_readonly_sql", unexpected_executor)

    result = answer_question(
        "unused.duckdb",
        "   ",
        lambda prompt: {"status": "success", "sql": SQL},
        schema=SCHEMA,
    )

    assert result.status == "generation_error"
    assert result.generation_error == SQLGenerationError(
        code="invalid_argument",
        message="question must be a non-empty string.",
    )
