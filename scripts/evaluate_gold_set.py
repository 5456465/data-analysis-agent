"""Run the existing Gold Set through the production question workflow."""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from itertools import permutations
from pathlib import Path
from typing import Any

from data_analysis_agent.deepseek_provider import DeepSeekTextToSQLModel
from data_analysis_agent.gold_questions import GOLD_QUESTIONS, GoldQuestion
from data_analysis_agent.question_service import QuestionAnswerResult, answer_question
from data_analysis_agent.sql_executor import SQLResult, run_readonly_sql
from data_analysis_agent.sql_generator import TextToSQLModel

if __package__:
    from scripts.baseline_queries import BASELINE_QUERIES
    from scripts.build_duckdb import DEFAULT_OUTPUT_PATH
else:
    from baseline_queries import BASELINE_QUERIES
    from build_duckdb import DEFAULT_OUTPUT_PATH


NUMERIC_ABS_TOLERANCE = 0.01
NUMERIC_REL_TOLERANCE = 1e-9


@dataclass(frozen=True)
class ResultSnapshot:
    """Columns and materialized rows used for deterministic comparison."""

    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]

    @classmethod
    def from_sql_result(cls, result: SQLResult) -> ResultSnapshot:
        return cls(columns=result.columns, rows=result.rows)


@dataclass(frozen=True)
class EvaluationRecord:
    """One Gold Set question and its observed production result."""

    question_id: str
    question: str
    answerable: bool
    generated_sql: str | None
    repair_attempted: bool
    repaired_sql: str | None
    status: str
    actual_result: ResultSnapshot | None
    expected_result: ResultSnapshot | None
    expected_reference: str
    passed: bool
    failure_reason: str | None


@dataclass(frozen=True)
class EvaluationSummary:
    """Minimal aggregate metrics for one complete Gold Set run."""

    total: int
    answerable: int
    unanswerable: int
    generation_success: int
    execution_success: int
    correct_answers: int
    correct_rejection: int
    repair_attempted: int
    repair_successful: int
    overall_passed: int
    overall_failed: int

    @property
    def answerable_correctness_rate(self) -> float:
        return self.correct_answers / self.answerable if self.answerable else 0.0

    @property
    def overall_pass_rate(self) -> float:
        return self.overall_passed / self.total if self.total else 0.0


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _values_match(actual: object, expected: object) -> bool:
    if expected is None or actual is None:
        return actual is expected
    if isinstance(expected, int) and not isinstance(expected, bool):
        return actual == expected
    if _is_number(actual) and _is_number(expected):
        return math.isclose(
            float(actual),
            float(expected),
            rel_tol=NUMERIC_REL_TOLERANCE,
            abs_tol=NUMERIC_ABS_TOLERANCE,
        )
    if isinstance(actual, date) and isinstance(expected, date):
        actual_date = actual.date() if isinstance(actual, datetime) else actual
        expected_date = expected.date() if isinstance(expected, datetime) else expected
        return actual_date == expected_date
    return actual == expected


def _rows_match_unordered(
    actual_rows: tuple[tuple[Any, ...], ...],
    expected_rows: tuple[tuple[Any, ...], ...],
) -> bool:
    if len(actual_rows) != len(expected_rows):
        return False

    unmatched = list(expected_rows)
    for actual_row in actual_rows:
        match_index = next(
            (
                index
                for index, expected_row in enumerate(unmatched)
                if len(actual_row) == len(expected_row)
                and all(
                    _values_match(actual, expected)
                    for actual, expected in zip(actual_row, expected_row, strict=True)
                )
            ),
            None,
        )
        if match_index is None:
            return False
        unmatched.pop(match_index)
    return True


def results_match(actual: ResultSnapshot, expected: ResultSnapshot) -> bool:
    """Compare result values, allowing a relevant projection of reference columns."""

    actual_width = len(actual.columns)
    expected_width = len(expected.columns)
    if actual_width == 0 or actual_width > expected_width:
        return False
    if len(expected.rows) > 1 and actual_width < 2:
        return False

    candidate_projections: list[tuple[int, ...]] = []
    if len(set(actual.columns)) == actual_width and all(
        column in expected.columns for column in actual.columns
    ):
        candidate_projections.append(
            tuple(expected.columns.index(column) for column in actual.columns)
        )
    candidate_projections.extend(permutations(range(expected_width), actual_width))

    for projection in candidate_projections:
        expected_rows = tuple(
            tuple(row[index] for index in projection) for row in expected.rows
        )
        if _rows_match_unordered(actual.rows, expected_rows):
            return True
    return False


def _reference_sql(question: GoldQuestion) -> tuple[str, str]:
    if question.baseline_key is not None:
        baselines = {query.key: query.sql for query in BASELINE_QUERIES}
        return question.baseline_key, baselines[question.baseline_key]
    if question.reference_sql is not None:
        return "reference_sql", question.reference_sql
    raise ValueError(f"Answerable question has no reference SQL: {question.id}")


def _failure_reason(
    question: GoldQuestion,
    result: QuestionAnswerResult,
    expected: ResultSnapshot | None,
) -> tuple[bool, str | None]:
    if not question.answerable:
        if (
            result.status == "generation_error"
            and result.generation_error is not None
            and result.generation_error.code == "cannot_generate"
        ):
            return True, None
        if result.status == "generation_error":
            return False, "generation_error"
        return False, "should_have_rejected"

    if result.status == "generation_error":
        if (
            result.generation_error is not None
            and result.generation_error.code == "cannot_generate"
        ):
            return False, "unexpected_rejection"
        return False, "generation_error"
    if result.status == "repair_error":
        return False, "repair_error"
    if result.status == "execution_error":
        return False, "execution_error"
    if result.execution_result is None or expected is None:
        return False, "execution_error"

    actual = ResultSnapshot.from_sql_result(result.execution_result)
    if results_match(actual, expected):
        return True, None
    return False, "semantic_wrong_answer"


def evaluate_result(
    question: GoldQuestion,
    result: QuestionAnswerResult,
    expected_result: ResultSnapshot | None,
    expected_reference: str,
) -> EvaluationRecord:
    """Evaluate one already-observed production answer against its reference."""

    passed, failure_reason = _failure_reason(question, result, expected_result)
    actual_result = (
        ResultSnapshot.from_sql_result(result.execution_result)
        if result.execution_result is not None
        else None
    )
    return EvaluationRecord(
        question_id=question.id,
        question=question.question,
        answerable=question.answerable,
        generated_sql=result.generated_sql,
        repair_attempted=result.repair_attempted,
        repaired_sql=result.repaired_sql,
        status=result.status,
        actual_result=actual_result,
        expected_result=expected_result,
        expected_reference=expected_reference,
        passed=passed,
        failure_reason=failure_reason,
    )


def evaluate_gold_set(
    database_path: str | Path,
    model: TextToSQLModel,
    questions: Sequence[GoldQuestion] = GOLD_QUESTIONS,
    *,
    on_record: Callable[[EvaluationRecord], None] | None = None,
) -> tuple[EvaluationRecord, ...]:
    """Run questions sequentially through ``answer_question`` and evaluate them."""

    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError(f"Database does not exist: {path}")

    references: dict[str, tuple[str, ResultSnapshot]] = {}
    for question in questions:
        if not question.answerable:
            continue
        reference_name, sql = _reference_sql(question)
        reference_result = run_readonly_sql(path, sql)
        if reference_result.status != "success" or reference_result.truncated:
            raise RuntimeError(
                f"Reference query failed or was truncated for {question.id}: "
                f"{reference_result.error}"
            )
        references[question.id] = (
            reference_name,
            ResultSnapshot.from_sql_result(reference_result),
        )

    records: list[EvaluationRecord] = []
    for question in questions:
        result = answer_question(path, question.question, model)
        if question.answerable:
            expected_reference, expected_result = references[question.id]
        else:
            expected_reference = f"rejection: {question.unanswerable_reason}"
            expected_result = None
        record = evaluate_result(
            question,
            result,
            expected_result,
            expected_reference,
        )
        records.append(record)
        if on_record is not None:
            on_record(record)
    return tuple(records)


def summarize(records: Sequence[EvaluationRecord]) -> EvaluationSummary:
    """Calculate the minimal aggregate metrics requested for the Gold Set."""

    answerable = sum(record.answerable for record in records)
    correct_answers = sum(record.answerable and record.passed for record in records)
    correct_rejection = sum(
        not record.answerable and record.passed for record in records
    )
    overall_passed = sum(record.passed for record in records)
    return EvaluationSummary(
        total=len(records),
        answerable=answerable,
        unanswerable=len(records) - answerable,
        generation_success=sum(record.generated_sql is not None for record in records),
        execution_success=sum(record.status == "success" for record in records),
        correct_answers=correct_answers,
        correct_rejection=correct_rejection,
        repair_attempted=sum(record.repair_attempted for record in records),
        repair_successful=sum(
            record.repair_attempted and record.status == "success"
            for record in records
        ),
        overall_passed=overall_passed,
        overall_failed=len(records) - overall_passed,
    )


def print_record(record: EvaluationRecord) -> None:
    """Print one safe evaluation record without prompts or credentials."""

    print(f"\n[{record.question_id}] {'PASS' if record.passed else 'FAIL'}")
    print(f"Question: {record.question}")
    print(f"Answerable: {'Yes' if record.answerable else 'No'}")
    print(f"Generated SQL: {record.generated_sql or '-'}")
    print(f"Repair attempted: {'Yes' if record.repair_attempted else 'No'}")
    print(f"Repaired SQL: {record.repaired_sql or '-'}")
    print(f"Status: {record.status}")
    print(f"Actual result: {record.actual_result}")
    print(
        f"Expected/reference result ({record.expected_reference}): "
        f"{record.expected_result}"
    )
    print(f"Passed: {'Yes' if record.passed else 'No'}")
    print(f"Failure reason: {record.failure_reason or '-'}")
    sys.stdout.flush()


def print_summary(summary: EvaluationSummary) -> None:
    """Print the compact aggregate evaluation metrics."""

    print("\n=== Gold Set Summary ===")
    print(f"Gold Set total: {summary.total}")
    print(f"Answerable: {summary.answerable}")
    print(f"Unanswerable: {summary.unanswerable}")
    print(f"Generation success: {summary.generation_success}")
    print(f"Execution success: {summary.execution_success}")
    print(f"Correct answers: {summary.correct_answers}")
    print(f"Correct rejection: {summary.correct_rejection}")
    print(f"Repair attempted: {summary.repair_attempted}")
    print(f"Repair successful: {summary.repair_successful}")
    print(f"Overall passed: {summary.overall_passed}")
    print(f"Overall failed: {summary.overall_failed}")
    print(
        "Answerable correctness rate: "
        f"{summary.answerable_correctness_rate:.2%}"
    )
    print(f"Overall Gold Set pass rate: {summary.overall_pass_rate:.2%}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate the production Agent against the existing Gold Set."
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        model = DeepSeekTextToSQLModel()
        records = evaluate_gold_set(
            args.database,
            model,
            on_record=print_record,
        )
    except Exception as exc:
        print(f"Evaluation error: {exc}")
        return 1
    print_summary(summarize(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
