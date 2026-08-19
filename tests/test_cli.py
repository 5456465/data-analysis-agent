"""Tests for the minimal interactive CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

import data_analysis_agent.__main__ as cli_module
from data_analysis_agent.question_service import QuestionAnswerResult
from data_analysis_agent.sql_executor import SQLExecutionError, SQLResult
from data_analysis_agent.sql_generator import SQLGenerationError
from data_analysis_agent.sql_repair import SQLRepairError


QUESTION = "How many orders are in the dataset?"
GENERATED_SQL = "SELECT COUNT(*) AS order_count FROM orders"
REPAIRED_SQL = "SELECT COUNT(*) AS order_count FROM orders;"


def _database_path(tmp_path: Path) -> Path:
    path = tmp_path / "olist.duckdb"
    path.touch()
    return path


def _input_from(*values: str):
    responses = iter(values)
    return lambda prompt: next(responses)


def _success_result(*, repaired: bool = False) -> QuestionAnswerResult:
    executed_sql = REPAIRED_SQL if repaired else GENERATED_SQL
    execution = SQLResult(
        executed_sql=executed_sql,
        columns=("order_count",),
        rows=((99_441,),),
        returned_row_count=1,
        truncated=False,
        status="success",
        error=None,
    )
    return QuestionAnswerResult(
        question=QUESTION,
        generated_sql=GENERATED_SQL,
        status="success",
        execution_result=execution,
        generation_error=None,
        execution_error=None,
        repaired_sql=REPAIRED_SQL if repaired else None,
        repair_attempted=repaired,
        repair_error=None,
    )


def test_success_prints_sql_result_and_no_repair(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli_module,
        "answer_question",
        lambda database_path, question, model: _success_result(),
    )
    output: list[str] = []

    exit_code = cli_module.run_cli(
        _database_path(tmp_path),
        input_fn=_input_from(QUESTION, "exit"),
        output_fn=output.append,
        model_factory=lambda: object(),
    )

    rendered = "\n".join(output)
    assert exit_code == 0
    assert f"Generated SQL:\n{GENERATED_SQL}" in rendered
    assert "Result:\n99441" in rendered
    assert "Repair attempted: No" in rendered


def test_repair_success_prints_repaired_sql(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli_module,
        "answer_question",
        lambda database_path, question, model: _success_result(repaired=True),
    )
    output: list[str] = []

    cli_module.run_cli(
        _database_path(tmp_path),
        input_fn=_input_from(QUESTION, "quit"),
        output_fn=output.append,
        model_factory=lambda: object(),
    )

    rendered = "\n".join(output)
    assert f"Repaired SQL:\n{REPAIRED_SQL}" in rendered
    assert "Repair attempted: Yes" in rendered
    assert "Result:\n99441" in rendered


@pytest.mark.parametrize("command", ["exit", "quit", "EXIT", "QUIT"])
def test_exit_commands_do_not_answer_questions(
    command: str,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli_module,
        "answer_question",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("answer_question must not be called")
        ),
    )

    exit_code = cli_module.run_cli(
        _database_path(tmp_path),
        input_fn=_input_from(command),
        output_fn=lambda message: None,
        model_factory=lambda: object(),
    )

    assert exit_code == 0


def test_empty_input_does_not_answer_question(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_answer(database_path, question, model):
        calls.append(question)
        return _success_result()

    monkeypatch.setattr(cli_module, "answer_question", fake_answer)

    cli_module.run_cli(
        _database_path(tmp_path),
        input_fn=_input_from("", "   ", "exit"),
        output_fn=lambda message: None,
        model_factory=lambda: object(),
    )

    assert calls == []


def test_missing_database_prints_error_and_exits(tmp_path: Path) -> None:
    output: list[str] = []

    exit_code = cli_module.run_cli(
        tmp_path / "missing.duckdb",
        input_fn=_input_from("exit"),
        output_fn=output.append,
        model_factory=lambda: (_ for _ in ()).throw(
            AssertionError("provider must not initialize")
        ),
    )

    assert exit_code == 1
    assert "DuckDB database does not exist" in "\n".join(output)


def test_provider_initialization_failure_prints_error_and_exits(
    tmp_path: Path,
) -> None:
    output: list[str] = []

    exit_code = cli_module.run_cli(
        _database_path(tmp_path),
        input_fn=_input_from("exit"),
        output_fn=output.append,
        model_factory=lambda: (_ for _ in ()).throw(
            ValueError("API key is required")
        ),
    )

    assert exit_code == 1
    assert "Unable to initialize DeepSeek Provider" in "\n".join(output)


@pytest.mark.parametrize(
    ("status", "error", "expected"),
    [
        (
            "generation_error",
            SQLGenerationError("cannot_generate", "Cannot generate SQL."),
            "Error (generation_error): cannot_generate: Cannot generate SQL.",
        ),
        (
            "execution_error",
            SQLExecutionError("unsafe_sql", "Unsafe SQL."),
            "Error (execution_error): unsafe_sql: Unsafe SQL.",
        ),
        (
            "repair_error",
            SQLRepairError("cannot_repair", "Cannot repair SQL."),
            "Error (repair_error): cannot_repair: Cannot repair SQL.",
        ),
    ],
)
def test_structured_errors_are_printed(
    status,
    error,
    expected: str,
    monkeypatch,
    tmp_path: Path,
) -> None:
    result = QuestionAnswerResult(
        question=QUESTION,
        generated_sql=None if status == "generation_error" else GENERATED_SQL,
        status=status,
        execution_result=None,
        generation_error=error if status == "generation_error" else None,
        execution_error=error if status == "execution_error" else None,
        repair_attempted=status == "repair_error",
        repair_error=error if status == "repair_error" else None,
    )
    monkeypatch.setattr(
        cli_module,
        "answer_question",
        lambda database_path, question, model: result,
    )
    output: list[str] = []

    cli_module.run_cli(
        _database_path(tmp_path),
        input_fn=_input_from(QUESTION, "exit"),
        output_fn=output.append,
        model_factory=lambda: object(),
    )

    assert expected in "\n".join(output)
