"""Minimal interactive CLI for the existing question-answer workflow."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from data_analysis_agent.deepseek_provider import DeepSeekTextToSQLModel
from data_analysis_agent.question_service import QuestionAnswerResult, answer_question
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


def _print_answer(result: QuestionAnswerResult, output_fn: OutputFunction) -> None:
    if result.generated_sql is not None:
        output_fn("Generated SQL:")
        output_fn(result.generated_sql)

    if result.repaired_sql is not None:
        output_fn("Repaired SQL:")
        output_fn(result.repaired_sql)

    if result.status == "success" and result.execution_result is not None:
        output_fn("Result:")
        for line in _format_rows(result.execution_result):
            output_fn(line)
    else:
        error = (
            result.generation_error
            or result.repair_error
            or result.execution_error
        )
        if error is None:
            output_fn(f"Error ({result.status}).")
        else:
            output_fn(f"Error ({result.status}): {error.code}: {error.message}")

    output_fn(f"Repair attempted: {'Yes' if result.repair_attempted else 'No'}")


def run_cli(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    *,
    input_fn: InputFunction = input,
    output_fn: OutputFunction = print,
    model_factory: ModelFactory = DeepSeekTextToSQLModel,
) -> int:
    """Run the interactive question loop using the existing orchestration."""

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
            result = answer_question(path, question, model)
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
