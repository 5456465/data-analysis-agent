"""Tests for the question-to-SQL-to-execution orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

import data_analysis_agent.question_service as service_module
from data_analysis_agent.question_service import (
    MAX_SQL_REPAIR_ATTEMPTS,
    QuestionAnswerResult,
    answer_question,
)
from data_analysis_agent.schema import DatabaseSchema
from data_analysis_agent.sql_executor import SQLExecutionError, SQLResult
from data_analysis_agent.sql_generator import SQLGenerationError
from data_analysis_agent.sql_repair import SQLRepairError


SCHEMA = DatabaseSchema(objects=())
QUESTION = "How many orders are in the dataset?"
SQL = "SELECT COUNT(*) AS order_count FROM orders"
REPAIRED_SQL = "SELECT COUNT(*) AS order_count FROM orders;"


def _failed_execution(sql: str, code="unknown_table_or_column") -> SQLResult:
    error = SQLExecutionError(
        code=code,
        message='Table with name "missing" does not exist.',
    )
    return SQLResult(
        executed_sql=sql,
        columns=(),
        rows=(),
        returned_row_count=0,
        truncated=False,
        status="error",
        error=error,
    )


def _successful_execution(sql: str) -> SQLResult:
    return SQLResult(
        executed_sql=sql,
        columns=("order_count",),
        rows=((99_441,),),
        returned_row_count=1,
        truncated=False,
        status="success",
        error=None,
    )


def test_generation_and_execution_succeed(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "olist.duckdb"
    inspected_paths: list[str | Path] = []
    execution_calls: list[tuple[str | Path, str, int]] = []
    expected_execution = _successful_execution(SQL)

    def fake_inspect_schema(path: str | Path) -> DatabaseSchema:
        inspected_paths.append(path)
        return SCHEMA

    def fake_executor(path: str | Path, sql: str, max_rows: int) -> SQLResult:
        execution_calls.append((path, sql, max_rows))
        return expected_execution

    monkeypatch.setattr(service_module, "inspect_schema", fake_inspect_schema)
    monkeypatch.setattr(service_module, "run_readonly_sql", fake_executor)
    monkeypatch.setattr(
        service_module,
        "repair_sql",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("repair must not run after successful execution")
        ),
    )

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
    assert result.repair_attempted is False


def test_execution_failure_is_repaired_and_reexecuted_successfully(monkeypatch) -> None:
    model_prompts: list[str] = []
    model_outputs = iter(
        [
            {"status": "success", "sql": SQL},
            {"status": "success", "sql": REPAIRED_SQL},
        ]
    )
    execution_calls: list[tuple[str, int]] = []

    def model(prompt: str):
        model_prompts.append(prompt)
        return next(model_outputs)

    def fake_executor(database_path, sql: str, max_rows: int) -> SQLResult:
        execution_calls.append((sql, max_rows))
        if len(execution_calls) == 1:
            return _failed_execution(sql)
        return _successful_execution(sql)

    monkeypatch.setattr(service_module, "run_readonly_sql", fake_executor)

    result = answer_question(
        "unused.duckdb",
        QUESTION,
        model,
        max_rows=25,
        schema=SCHEMA,
    )

    assert result.status == "success"
    assert result.generated_sql == SQL
    assert result.repaired_sql == REPAIRED_SQL
    assert result.repair_attempted is True
    assert result.execution_result == _successful_execution(REPAIRED_SQL)
    assert result.generation_error is None
    assert result.repair_error is None
    assert result.execution_error is None
    assert execution_calls == [(SQL, 25), (REPAIRED_SQL, 25)]
    assert len(model_prompts) == 2
    assert "Original SQL:" in model_prompts[1]


def test_repair_generation_failure_stops_before_second_execution(monkeypatch) -> None:
    reason = "The SQL cannot be repaired reliably."
    model_outputs = iter(
        [
            {"status": "success", "sql": SQL},
            {"status": "error", "error": reason},
        ]
    )
    execution_calls: list[str] = []

    def fake_executor(database_path, sql: str, max_rows: int) -> SQLResult:
        execution_calls.append(sql)
        return _failed_execution(sql)

    monkeypatch.setattr(service_module, "run_readonly_sql", fake_executor)

    result = answer_question(
        "unused.duckdb",
        QUESTION,
        lambda prompt: next(model_outputs),
        schema=SCHEMA,
    )

    assert result.status == "repair_error"
    assert result.generated_sql == SQL
    assert result.repaired_sql is None
    assert result.repair_attempted is True
    assert result.repair_error == SQLRepairError(
        code="cannot_repair",
        message=reason,
    )
    assert execution_calls == [SQL]


def test_second_execution_failure_stops_without_third_attempt(monkeypatch) -> None:
    model_prompts: list[str] = []
    model_outputs = iter(
        [
            {"status": "success", "sql": SQL},
            {"status": "success", "sql": REPAIRED_SQL},
        ]
    )
    execution_calls: list[str] = []

    def model(prompt: str):
        model_prompts.append(prompt)
        return next(model_outputs)

    def fake_executor(database_path, sql: str, max_rows: int) -> SQLResult:
        execution_calls.append(sql)
        return _failed_execution(sql)

    monkeypatch.setattr(service_module, "run_readonly_sql", fake_executor)

    result = answer_question(
        "unused.duckdb",
        QUESTION,
        model,
        schema=SCHEMA,
    )

    assert result.status == "execution_error"
    assert result.generated_sql == SQL
    assert result.repaired_sql == REPAIRED_SQL
    assert result.repair_attempted is True
    assert result.execution_result == _failed_execution(REPAIRED_SQL)
    assert result.execution_error == _failed_execution(REPAIRED_SQL).error
    assert result.repair_error is None
    assert execution_calls == [SQL, REPAIRED_SQL]
    assert len(model_prompts) == 2
    assert MAX_SQL_REPAIR_ATTEMPTS == 1


def test_generation_failure_does_not_call_executor(monkeypatch) -> None:
    def unexpected_executor(database_path, sql, max_rows):
        raise AssertionError("executor must not run after generation failure")

    monkeypatch.setattr(service_module, "run_readonly_sql", unexpected_executor)
    monkeypatch.setattr(
        service_module,
        "repair_sql",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("repair must not run after generation failure")
        ),
    )

    result = answer_question(
        "unused.duckdb",
        QUESTION,
        lambda prompt: {
            "status": "error",
            "error": "No reliable SQL can be generated.",
        },
        schema=SCHEMA,
    )

    assert result.status == "generation_error"
    assert result.generation_error == SQLGenerationError(
        code="cannot_generate",
        message="No reliable SQL can be generated.",
    )


def test_invalid_question_does_not_call_model_executor_or_repair(monkeypatch) -> None:
    def unexpected_call(*args, **kwargs):
        raise AssertionError("downstream dependency must not be called")

    monkeypatch.setattr(service_module, "run_readonly_sql", unexpected_call)
    monkeypatch.setattr(service_module, "repair_sql", unexpected_call)

    result = answer_question(
        "unused.duckdb",
        "   ",
        unexpected_call,
        schema=SCHEMA,
    )

    assert result.status == "generation_error"
    assert result.generation_error == SQLGenerationError(
        code="invalid_argument",
        message="question must be a non-empty string.",
    )


def test_initial_model_failure_does_not_call_executor_or_repair(monkeypatch) -> None:
    def unexpected_call(*args, **kwargs):
        raise AssertionError("executor or repair must not be called")

    def failing_model(prompt: str):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(service_module, "run_readonly_sql", unexpected_call)
    monkeypatch.setattr(service_module, "repair_sql", unexpected_call)

    result = answer_question(
        "unused.duckdb",
        QUESTION,
        failing_model,
        schema=SCHEMA,
    )

    assert result.status == "generation_error"
    assert result.generation_error == SQLGenerationError(
        code="model_error",
        message="provider unavailable",
    )


def test_schema_inspection_exception_propagates_without_downstream_calls(
    monkeypatch,
) -> None:
    def failing_inspection(database_path):
        raise FileNotFoundError("database missing")

    def unexpected_call(*args, **kwargs):
        raise AssertionError("generation, execution, and repair must not be called")

    monkeypatch.setattr(service_module, "inspect_schema", failing_inspection)
    monkeypatch.setattr(service_module, "run_readonly_sql", unexpected_call)
    monkeypatch.setattr(service_module, "repair_sql", unexpected_call)

    with pytest.raises(FileNotFoundError, match="database missing"):
        answer_question("missing.duckdb", QUESTION, unexpected_call)


def test_safety_rejection_is_not_repaired(monkeypatch) -> None:
    execution_calls: list[str] = []

    def fake_executor(database_path, sql: str, max_rows: int) -> SQLResult:
        execution_calls.append(sql)
        return _failed_execution(sql, code="unsafe_sql")

    monkeypatch.setattr(service_module, "run_readonly_sql", fake_executor)
    monkeypatch.setattr(
        service_module,
        "repair_sql",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("safety rejection must not enter repair")
        ),
    )

    result = answer_question(
        "unused.duckdb",
        QUESTION,
        lambda prompt: {"status": "success", "sql": SQL},
        schema=SCHEMA,
    )

    assert result.status == "execution_error"
    assert result.repair_attempted is False
    assert result.execution_error is not None
    assert result.execution_error.code == "unsafe_sql"
    assert execution_calls == [SQL]
