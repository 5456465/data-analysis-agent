"""Tests for the minimal interactive multi-tool CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

import data_analysis_agent.__main__ as cli_module
from data_analysis_agent.analysis_planner import PythonAnalysisPlan
from data_analysis_agent.multi_tool_service import (
    MultiToolQuestionError,
    MultiToolQuestionResult,
)
from data_analysis_agent.python_analysis import (
    ColumnDescription,
    CorrelationResult,
    PythonAnalysisResult,
)
from data_analysis_agent.question_service import QuestionAnswerResult
from data_analysis_agent.sql_executor import SQLExecutionError, SQLResult
from data_analysis_agent.sql_generator import SQLGenerationError
from data_analysis_agent.sql_repair import SQLRepairError
from data_analysis_agent.tool_router import ToolRouteDecision, ToolRoutingError


QUESTION = "How many orders are in the dataset?"
GENERATED_SQL = "SELECT COUNT(*) AS order_count FROM orders"
REPAIRED_SQL = "SELECT COUNT(*) AS order_count FROM orders;"
ANALYSIS_SQL = "SELECT payment_value FROM order_payments"


def _database_path(tmp_path: Path) -> Path:
    path = tmp_path / "olist.duckdb"
    path.touch()
    return path


def _input_from(*values: str):
    responses = iter(values)
    return lambda prompt: next(responses)


def _route(
    route: str | None,
    operation: str | None = None,
    *,
    status: str = "success",
    error: ToolRoutingError | None = None,
) -> ToolRouteDecision:
    return ToolRouteDecision(
        question=QUESTION,
        route=route,
        python_operation=operation,
        reason="Test route." if status == "success" else None,
        status=status,
        error=error,
    )


def _sql_execution(
    sql: str = GENERATED_SQL,
    rows: tuple[tuple[object, ...], ...] = ((99_441,),),
) -> SQLResult:
    return SQLResult(
        executed_sql=sql,
        columns=("order_count",),
        rows=rows,
        returned_row_count=len(rows),
        truncated=False,
        status="success",
        error=None,
    )


def _sql_only_result(*, repaired: bool = False) -> MultiToolQuestionResult:
    executed_sql = REPAIRED_SQL if repaired else GENERATED_SQL
    execution = _sql_execution(executed_sql)
    answer = QuestionAnswerResult(
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
    return MultiToolQuestionResult(
        question=QUESTION,
        route_decision=_route("sql_only"),
        status="success",
        sql_answer_result=answer,
        analysis_plan=None,
        sql_result=execution,
        python_result=None,
        error=None,
    )


def _analysis_plan(
    operation: str,
    sql: str,
    columns: tuple[str, ...],
) -> PythonAnalysisPlan:
    return PythonAnalysisPlan(
        question=QUESTION,
        python_operation=operation,
        sql=sql,
        python_columns=columns,
        status="success",
        error=None,
    )


def _python_success_result(
    operation: str,
    sql: str,
    columns: tuple[str, ...],
    python_result: PythonAnalysisResult,
) -> MultiToolQuestionResult:
    sql_result = SQLResult(
        executed_sql=sql,
        columns=columns,
        rows=(),
        returned_row_count=0,
        truncated=False,
        status="success",
        error=None,
    )
    return MultiToolQuestionResult(
        question=QUESTION,
        route_decision=_route("sql_then_python", operation),
        status="success",
        sql_answer_result=None,
        analysis_plan=_analysis_plan(operation, sql, columns),
        sql_result=sql_result,
        python_result=python_result,
        error=None,
    )


def _run_one_result(
    monkeypatch,
    tmp_path: Path,
    result: MultiToolQuestionResult,
) -> str:
    monkeypatch.setattr(
        cli_module,
        "answer_question_with_tools",
        lambda database_path, question, model: result,
    )
    output: list[str] = []
    exit_code = cli_module.run_cli(
        _database_path(tmp_path),
        input_fn=_input_from(QUESTION, "exit"),
        output_fn=output.append,
        model_factory=lambda: object(),
    )
    assert exit_code == 0
    return "\n".join(output)


def test_sql_only_success_preserves_sql_result_and_repair_display(
    monkeypatch,
    tmp_path: Path,
) -> None:
    rendered = _run_one_result(monkeypatch, tmp_path, _sql_only_result())

    assert "Route: SQL only" in rendered
    assert f"Generated SQL:\n{GENERATED_SQL}" in rendered
    assert "Result:\n99441" in rendered
    assert "Repair attempted: No" in rendered


def test_sql_only_repair_success_prints_repaired_sql(
    monkeypatch,
    tmp_path: Path,
) -> None:
    rendered = _run_one_result(
        monkeypatch,
        tmp_path,
        _sql_only_result(repaired=True),
    )

    assert f"Repaired SQL:\n{REPAIRED_SQL}" in rendered
    assert "Repair attempted: Yes" in rendered
    assert "Result:\n99441" in rendered


def test_describe_prints_plan_columns_and_statistics(
    monkeypatch,
    tmp_path: Path,
) -> None:
    python_result = PythonAnalysisResult(
        operation="describe",
        status="success",
        result=(
            ColumnDescription(
                column="payment_value",
                count=103_886,
                mean=154.10038,
                std=217.49406,
                min=0.0,
                median=100.0,
                max=13_664.08,
            ),
        ),
        error=None,
    )
    result = _python_success_result(
        "describe",
        ANALYSIS_SQL,
        ("payment_value",),
        python_result,
    )

    rendered = _run_one_result(monkeypatch, tmp_path, result)

    assert "Route: SQL → Python" in rendered
    assert "Python analysis: describe" in rendered
    assert f"SQL:\n{ANALYSIS_SQL}" in rendered
    assert "Python columns: payment_value" in rendered
    assert "Payment value" in rendered
    assert "Count: 103886" in rendered
    assert "Mean: 154.10038" in rendered
    assert "Std: 217.49406" in rendered
    assert "Min: 0.0" in rendered
    assert "Median: 100.0" in rendered
    assert "Max: 13664.08" in rendered


def test_describe_multiple_columns_prints_separate_blocks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    python_result = PythonAnalysisResult(
        operation="describe",
        status="success",
        result=(
            ColumnDescription("price", 2, 2.0, 1.0, 1.0, 2.0, 3.0),
            ColumnDescription("freight_value", 2, 4.0, 2.0, 2.0, 4.0, 6.0),
        ),
        error=None,
    )
    result = _python_success_result(
        "describe",
        "SELECT price, freight_value FROM order_items",
        ("price", "freight_value"),
        python_result,
    )

    rendered = _run_one_result(monkeypatch, tmp_path, result)

    assert "Column: price" in rendered
    assert "Column: freight_value" in rendered


def test_correlation_prints_columns_value_and_paired_rows(
    monkeypatch,
    tmp_path: Path,
) -> None:
    sql = "SELECT price, freight_value FROM order_items"
    python_result = PythonAnalysisResult(
        operation="correlation",
        status="success",
        result=CorrelationResult(
            x_column="price",
            y_column="freight_value",
            correlation=0.4142043104,
            paired_count=112_650,
        ),
        error=None,
    )
    result = _python_success_result(
        "correlation",
        sql,
        ("price", "freight_value"),
        python_result,
    )

    rendered = _run_one_result(monkeypatch, tmp_path, result)

    assert "Route: SQL → Python" in rendered
    assert "Python analysis: correlation" in rendered
    assert f"SQL:\n{sql}" in rendered
    assert "Python columns: price, freight_value" in rendered
    assert "Correlation: 0.4142043104" in rendered
    assert "Paired rows: 112650" in rendered


@pytest.mark.parametrize(
    "stage",
    [
        "routing_error",
        "planning_error",
        "sql_execution_error",
        "truncated_analysis_input",
        "python_analysis_error",
    ],
)
def test_stage_aware_errors_are_printed(
    stage: str,
    monkeypatch,
    tmp_path: Path,
) -> None:
    route = (
        _route(
            None,
            status="error",
            error=ToolRoutingError("unsupported_route", "Unsupported request."),
        )
        if stage == "routing_error"
        else _route("sql_then_python", "describe")
    )
    result = MultiToolQuestionResult(
        question=QUESTION,
        route_decision=route,
        status=stage,
        sql_answer_result=None,
        analysis_plan=None,
        sql_result=None,
        python_result=None,
        error=MultiToolQuestionError(stage, f"Failure at {stage}."),
    )

    rendered = _run_one_result(monkeypatch, tmp_path, result)

    assert f"Error stage: {stage}" in rendered
    assert f"Error: Failure at {stage}." in rendered
    if stage == "truncated_analysis_input":
        assert "Python analysis was NOT executed." in rendered


@pytest.mark.parametrize("command", ["exit", "quit", "EXIT", "QUIT"])
def test_exit_commands_do_not_answer_questions(
    command: str,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli_module,
        "answer_question_with_tools",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("service must not be called")
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
        return _sql_only_result()

    monkeypatch.setattr(cli_module, "answer_question_with_tools", fake_answer)

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
    ("answer_status", "multi_status", "nested_error"),
    [
        (
            "generation_error",
            "sql_generation_error",
            SQLGenerationError("cannot_generate", "Cannot generate SQL."),
        ),
        (
            "execution_error",
            "sql_execution_error",
            SQLExecutionError("unsafe_sql", "Unsafe SQL."),
        ),
        (
            "repair_error",
            "sql_repair_error",
            SQLRepairError("cannot_repair", "Cannot repair SQL."),
        ),
    ],
)
def test_sql_only_errors_keep_repair_display_and_show_stage(
    answer_status: str,
    multi_status: str,
    nested_error,
    monkeypatch,
    tmp_path: Path,
) -> None:
    answer = QuestionAnswerResult(
        question=QUESTION,
        generated_sql=(
            None if answer_status == "generation_error" else GENERATED_SQL
        ),
        status=answer_status,
        execution_result=None,
        generation_error=(
            nested_error if answer_status == "generation_error" else None
        ),
        execution_error=(
            nested_error if answer_status == "execution_error" else None
        ),
        repair_attempted=answer_status == "repair_error",
        repair_error=nested_error if answer_status == "repair_error" else None,
    )
    result = MultiToolQuestionResult(
        question=QUESTION,
        route_decision=_route("sql_only"),
        status=multi_status,
        sql_answer_result=answer,
        analysis_plan=None,
        sql_result=None,
        python_result=None,
        error=MultiToolQuestionError(multi_status, nested_error.message),
    )

    rendered = _run_one_result(monkeypatch, tmp_path, result)

    assert f"Error stage: {multi_status}" in rendered
    assert f"Error: {nested_error.message}" in rendered
    assert (
        f"Repair attempted: {'Yes' if answer_status == 'repair_error' else 'No'}"
        in rendered
    )
