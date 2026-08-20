"""Minimal interactive CLI for the multi-tool question workflow."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from data_analysis_agent.deepseek_provider import DeepSeekTextToSQLModel
from data_analysis_agent.multi_tool_service import (
    MultiToolQuestionResult,
    answer_question_with_tools,
)
from data_analysis_agent.python_analysis import ColumnDescription, CorrelationResult
from data_analysis_agent.sql_executor import SQLResult
from data_analysis_agent.sql_generator import TextToSQLModel


DEFAULT_DATABASE_PATH = Path("data/processed/olist.duckdb")
EXIT_COMMANDS = frozenset({"exit", "quit"})

InputFunction = Callable[[str], str]
OutputFunction = Callable[[str], None]
ModelFactory = Callable[[], TextToSQLModel]


def _format_rows(result: SQLResult) -> list[str]:
    if not result.rows:
        return ["(no rows)"]
    if len(result.rows) == 1 and len(result.rows[0]) == 1:
        return [str(result.rows[0][0])]

    lines = [" | ".join(result.columns)] if result.columns else []
    lines.extend(
        " | ".join("NULL" if value is None else str(value) for value in row)
        for row in result.rows
    )
    if result.truncated:
        lines.append("(results truncated)")
    return lines


def _print_error(
    result: MultiToolQuestionResult,
    output_fn: OutputFunction,
) -> None:
    output_fn(f"Error stage: {result.status}")
    message = result.error.message if result.error is not None else "Unknown error."
    output_fn(f"Error: {message}")
    if result.status == "truncated_analysis_input":
        output_fn("Python analysis was NOT executed.")


def _print_sql_only(
    result: MultiToolQuestionResult,
    output_fn: OutputFunction,
) -> None:
    output_fn("Route: SQL only")
    answer = result.sql_answer_result
    if answer is None:
        _print_error(result, output_fn)
        return

    if answer.generated_sql is not None:
        output_fn("Generated SQL:")
        output_fn(answer.generated_sql)

    if answer.repaired_sql is not None:
        output_fn("Repaired SQL:")
        output_fn(answer.repaired_sql)

    if result.status == "success" and answer.execution_result is not None:
        output_fn("Result:")
        for line in _format_rows(answer.execution_result):
            output_fn(line)
    else:
        _print_error(result, output_fn)

    output_fn(f"Repair attempted: {'Yes' if answer.repair_attempted else 'No'}")


def _print_descriptions(
    descriptions: tuple[ColumnDescription, ...],
    output_fn: OutputFunction,
) -> None:
    for index, description in enumerate(descriptions):
        if index:
            output_fn("")
        if len(descriptions) == 1:
            output_fn(description.column.replace("_", " ").capitalize())
        else:
            output_fn(f"Column: {description.column}")
        output_fn(f"Count: {description.count}")
        output_fn(f"Mean: {description.mean}")
        output_fn(f"Std: {description.std}")
        output_fn(f"Min: {description.min}")
        output_fn(f"Median: {description.median}")
        output_fn(f"Max: {description.max}")


def _print_python_analysis(
    result: MultiToolQuestionResult,
    output_fn: OutputFunction,
) -> None:
    output_fn("Route: SQL → Python")
    plan = result.analysis_plan
    if plan is not None:
        output_fn(f"Python analysis: {plan.python_operation}")
        if plan.sql is not None:
            output_fn("SQL:")
            output_fn(plan.sql)
        if plan.python_columns:
            output_fn(f"Python columns: {', '.join(plan.python_columns)}")

    if result.status != "success":
        _print_error(result, output_fn)
        return

    python_result = result.python_result
    if python_result is None or python_result.result is None:
        output_fn("Error stage: python_analysis_error")
        output_fn("Error: Python analysis returned no result.")
        return

    payload = python_result.result
    if isinstance(payload, tuple):
        _print_descriptions(payload, output_fn)
    elif isinstance(payload, CorrelationResult):
        output_fn(f"Correlation: {payload.correlation}")
        output_fn(f"Paired rows: {payload.paired_count}")


def _print_answer(
    result: MultiToolQuestionResult,
    output_fn: OutputFunction,
) -> None:
    if result.route_decision.route == "sql_only":
        _print_sql_only(result, output_fn)
    elif result.route_decision.route == "sql_then_python":
        _print_python_analysis(result, output_fn)
    else:
        _print_error(result, output_fn)


def run_cli(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    *,
    input_fn: InputFunction = input,
    output_fn: OutputFunction = print,
    model_factory: ModelFactory = DeepSeekTextToSQLModel,
) -> int:
    """Run the interactive question loop using multi-tool orchestration."""

    path = Path(database_path)
    if not path.is_file():
        output_fn(f"Error: DuckDB database does not exist: {path}")
        return 1

    try:
        model = model_factory()
    except Exception as exc:
        output_fn(f"Error: Unable to initialize DeepSeek Provider: {exc}")
        return 1

    output_fn("Data Analysis Agent")
    output_fn("Type a question, or 'exit' to quit.")
    output_fn("")

    while True:
        try:
            question = input_fn("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0

        if not question:
            continue
        if question.lower() in EXIT_COMMANDS:
            return 0

        try:
            result = answer_question_with_tools(path, question, model)
        except Exception as exc:
            output_fn(f"Error: {exc}")
            continue

        _print_answer(result, output_fn)
        output_fn("")


def main() -> int:
    """Run the CLI with project defaults."""

    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
