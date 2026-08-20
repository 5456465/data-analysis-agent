"""Tests for SQL-only and SQL-then-Python orchestration."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

import data_analysis_agent.multi_tool_service as service_module
from data_analysis_agent.multi_tool_service import (
    ANALYSIS_MAX_ROWS,
    MultiToolQuestionError,
    answer_question_with_tools,
)
from data_analysis_agent.python_analysis import (
    ColumnDescription,
    CorrelationResult,
)
from data_analysis_agent.schema import ColumnSchema, DatabaseSchema, SchemaObject


SCHEMA = DatabaseSchema(
    objects=(
        SchemaObject(
            name="analysis_values",
            object_type="table",
            grain="one row per observation",
            columns=(
                ColumnSchema("price", "DOUBLE", False, False),
                ColumnSchema("freight_value", "DOUBLE", False, False),
                ColumnSchema("label", "VARCHAR", False, False),
            ),
        ),
    )
)


class QueueModel:
    def __init__(self, outputs: list[dict[str, object]]) -> None:
        self._outputs: Iterator[dict[str, object]] = iter(outputs)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> dict[str, object]:
        self.prompts.append(prompt)
        return next(self._outputs)


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    path = tmp_path / "analysis.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE analysis_values (
                price DOUBLE,
                freight_value DOUBLE,
                label VARCHAR
            )
            """
        )
        connection.execute(
            """
            INSERT INTO analysis_values VALUES
                (1.0, 2.0, 'a'),
                (2.0, 4.0, 'b'),
                (3.0, 6.0, 'c'),
                (4.0, 8.0, 'd')
            """
        )
    return path


def _sql_only_route() -> dict[str, object]:
    return {
        "status": "success",
        "route": "sql_only",
        "python_operation": None,
        "reason": "A count is SQL-native.",
    }


def _python_route(operation: str) -> dict[str, object]:
    return {
        "status": "success",
        "route": "sql_then_python",
        "python_operation": operation,
        "reason": f"The question requires {operation}.",
    }


def _analysis_plan(sql: str, columns: list[str]) -> dict[str, object]:
    return {
        "status": "success",
        "sql": sql,
        "python_columns": columns,
    }


def _unexpected_call(*args, **kwargs):
    raise AssertionError("This dependency must not be called on the selected route.")


def test_sql_only_reuses_existing_question_pipeline(
    monkeypatch,
    database_path: Path,
) -> None:
    model = QueueModel(
        [
            _sql_only_route(),
            {
                "status": "success",
                "sql": "SELECT COUNT(*) AS row_count FROM analysis_values",
            },
        ]
    )
    monkeypatch.setattr(
        service_module,
        "generate_python_analysis_plan",
        _unexpected_call,
    )
    monkeypatch.setattr(service_module, "run_python_analysis", _unexpected_call)

    result = answer_question_with_tools(
        database_path,
        "How many rows are there?",
        model,
        max_rows=25,
        schema=SCHEMA,
    )

    assert result.status == "success"
    assert result.route_decision.route == "sql_only"
    assert result.sql_answer_result is not None
    assert result.sql_answer_result.status == "success"
    assert result.sql_answer_result.generated_sql == (
        "SELECT COUNT(*) AS row_count FROM analysis_values"
    )
    assert result.sql_result == result.sql_answer_result.execution_result
    assert result.sql_result is not None
    assert result.sql_result.rows == ((4,),)
    assert result.analysis_plan is None
    assert result.python_result is None


def test_describe_route_executes_plan_sql_then_python(
    monkeypatch,
    database_path: Path,
) -> None:
    model = QueueModel(
        [
            _python_route("describe"),
            _analysis_plan(
                "SELECT price FROM analysis_values ORDER BY price",
                ["price"],
            ),
        ]
    )
    monkeypatch.setattr(service_module, "answer_question", _unexpected_call)

    result = answer_question_with_tools(
        database_path,
        "Give me descriptive statistics for price.",
        model,
        schema=SCHEMA,
    )

    assert result.status == "success"
    assert result.route_decision.route == "sql_then_python"
    assert result.route_decision.python_operation == "describe"
    assert result.sql_answer_result is None
    assert result.analysis_plan is not None
    assert result.analysis_plan.python_columns == ("price",)
    assert result.sql_result is not None
    assert result.sql_result.columns == ("price",)
    assert result.sql_result.rows == ((1.0,), (2.0,), (3.0,), (4.0,))
    assert result.python_result is not None
    assert result.python_result.status == "success"
    assert result.python_result.result == (
        ColumnDescription(
            column="price",
            count=4,
            mean=2.5,
            std=pytest.approx(1.2909944487358056),
            min=1.0,
            median=2.5,
            max=4.0,
        ),
    )


def test_correlation_route_returns_python_correlation(
    database_path: Path,
) -> None:
    model = QueueModel(
        [
            _python_route("correlation"),
            _analysis_plan(
                "SELECT price, freight_value FROM analysis_values",
                ["price", "freight_value"],
            ),
        ]
    )

    result = answer_question_with_tools(
        database_path,
        "What is the correlation between price and freight value?",
        model,
        schema=SCHEMA,
    )

    assert result.status == "success"
    assert result.route_decision.python_operation == "correlation"
    assert result.sql_result is not None
    assert result.sql_result.columns == ("price", "freight_value")
    assert result.python_result is not None
    assert result.python_result.result == CorrelationResult(
        x_column="price",
        y_column="freight_value",
        correlation=pytest.approx(1.0),
        paired_count=4,
    )


def test_routing_failure_stops_before_any_branch(
    monkeypatch,
    database_path: Path,
) -> None:
    model = QueueModel(
        [
            {
                "status": "error",
                "error": "Forecasting is not supported.",
            }
        ]
    )
    monkeypatch.setattr(service_module, "answer_question", _unexpected_call)
    monkeypatch.setattr(
        service_module,
        "generate_python_analysis_plan",
        _unexpected_call,
    )

    result = answer_question_with_tools(
        database_path,
        "Forecast next year's sales.",
        model,
        schema=SCHEMA,
    )

    assert result.status == "routing_error"
    assert result.error == MultiToolQuestionError(
        code="routing_error",
        message="Forecasting is not supported.",
    )
    assert result.sql_answer_result is None
    assert result.analysis_plan is None
    assert result.sql_result is None
    assert result.python_result is None


def test_planning_failure_stops_before_sql_execution(
    monkeypatch,
    database_path: Path,
) -> None:
    model = QueueModel(
        [
            _python_route("describe"),
            {
                "status": "error",
                "error": "No numeric source column is available.",
            },
        ]
    )
    monkeypatch.setattr(service_module, "run_readonly_sql", _unexpected_call)
    monkeypatch.setattr(service_module, "run_python_analysis", _unexpected_call)

    result = answer_question_with_tools(
        database_path,
        "Describe an unavailable value.",
        model,
        schema=SCHEMA,
    )

    assert result.status == "planning_error"
    assert result.analysis_plan is not None
    assert result.analysis_plan.status == "error"
    assert result.sql_result is None
    assert result.python_result is None


def test_analysis_sql_execution_failure_is_not_repaired(
    monkeypatch,
    database_path: Path,
) -> None:
    model = QueueModel(
        [
            _python_route("describe"),
            _analysis_plan("SELECT missing_value FROM analysis_values", ["missing_value"]),
        ]
    )
    monkeypatch.setattr(service_module, "run_python_analysis", _unexpected_call)

    result = answer_question_with_tools(
        database_path,
        "Describe the missing value.",
        model,
        schema=SCHEMA,
    )

    assert result.status == "sql_execution_error"
    assert result.sql_result is not None
    assert result.sql_result.status == "error"
    assert result.sql_result.error is not None
    assert result.sql_result.error.code == "unknown_table_or_column"
    assert len(model.prompts) == 2


def test_truncated_analysis_input_never_runs_python(
    monkeypatch,
    database_path: Path,
) -> None:
    model = QueueModel(
        [
            _python_route("describe"),
            _analysis_plan("SELECT price FROM analysis_values", ["price"]),
        ]
    )
    monkeypatch.setattr(service_module, "run_python_analysis", _unexpected_call)

    result = answer_question_with_tools(
        database_path,
        "Describe all prices.",
        model,
        analysis_max_rows=2,
        schema=SCHEMA,
    )

    assert result.status == "truncated_analysis_input"
    assert result.sql_result is not None
    assert result.sql_result.returned_row_count == 2
    assert result.sql_result.truncated is True
    assert result.python_result is None
    assert result.error is not None
    assert "statistics over truncated data would be misleading" in result.error.message


def test_python_analysis_failure_is_structured(
    database_path: Path,
) -> None:
    model = QueueModel(
        [
            _python_route("describe"),
            _analysis_plan("SELECT label FROM analysis_values", ["label"]),
        ]
    )

    result = answer_question_with_tools(
        database_path,
        "Describe the labels.",
        model,
        schema=SCHEMA,
    )

    assert result.status == "python_analysis_error"
    assert result.python_result is not None
    assert result.python_result.error is not None
    assert result.python_result.error.code == "non_numeric_column"


def test_missing_planned_python_column_is_structured(
    database_path: Path,
) -> None:
    model = QueueModel(
        [
            _python_route("describe"),
            _analysis_plan("SELECT price FROM analysis_values", ["missing"]),
        ]
    )

    result = answer_question_with_tools(
        database_path,
        "Describe price.",
        model,
        schema=SCHEMA,
    )

    assert result.status == "python_analysis_error"
    assert result.python_result is not None
    assert result.python_result.error is not None
    assert result.python_result.error.code == "unknown_column"


def test_analysis_sql_still_passes_through_readonly_safety(
    monkeypatch,
    database_path: Path,
) -> None:
    model = QueueModel(
        [
            _python_route("describe"),
            _analysis_plan("DELETE FROM analysis_values", ["price"]),
        ]
    )
    monkeypatch.setattr(service_module, "run_python_analysis", _unexpected_call)

    result = answer_question_with_tools(
        database_path,
        "Describe price.",
        model,
        schema=SCHEMA,
    )

    assert result.status == "sql_execution_error"
    assert result.sql_result is not None
    assert result.sql_result.error is not None
    assert result.sql_result.error.code == "unsafe_sql"
    assert result.python_result is None


def test_analysis_row_cap_is_explicit() -> None:
    assert ANALYSIS_MAX_ROWS == 150_000
