"""Tests for deterministic Gold Set result comparison and metrics."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import scripts.evaluate_gold_set as evaluation_module
from data_analysis_agent.gold_questions import GOLD_QUESTIONS
from data_analysis_agent.question_service import QuestionAnswerResult
from data_analysis_agent.sql_executor import SQLResult
from data_analysis_agent.sql_generator import SQLGenerationError
from scripts.evaluate_gold_set import (
    ResultSnapshot,
    evaluate_gold_set,
    evaluate_result,
    results_match,
    summarize,
)


def _sql_result(
    columns: tuple[str, ...],
    rows: tuple[tuple[object, ...], ...],
) -> SQLResult:
    return SQLResult(
        executed_sql="SELECT test_result",
        columns=columns,
        rows=rows,
        returned_row_count=len(rows),
        truncated=False,
        status="success",
        error=None,
    )


def _answer_result(
    execution_result: SQLResult | None,
    *,
    status="success",
    generated_sql="SELECT test_result",
    generation_error=None,
    repair_attempted=False,
) -> QuestionAnswerResult:
    return QuestionAnswerResult(
        question="test question",
        generated_sql=generated_sql,
        status=status,
        execution_result=execution_result,
        generation_error=generation_error,
        execution_error=None,
        repair_attempted=repair_attempted,
    )


def test_results_match_integer_exactly_and_float_with_tolerance() -> None:
    expected_integer = ResultSnapshot(("value",), ((99_441,),))
    assert results_match(ResultSnapshot(("count",), ((99_441,),)), expected_integer)
    assert not results_match(ResultSnapshot(("count",), ((99_442,),)), expected_integer)

    expected_float = ResultSnapshot(("value",), ((Decimal("103.1234"),),))
    assert results_match(ResultSnapshot(("average",), ((103.13,),)), expected_float)
    assert not results_match(ResultSnapshot(("average",), ((103.14,),)), expected_float)


def test_results_match_reference_projection_and_ignore_row_order() -> None:
    expected = ResultSnapshot(
        ("state", "customer_count", "extra_metric"),
        (("SP", 10, Decimal("20.00")), ("RJ", 5, Decimal("8.00"))),
    )
    actual = ResultSnapshot(
        ("region", "count"),
        (("RJ", 5), ("SP", 10)),
    )

    assert results_match(actual, expected)


def test_results_match_equivalent_date_and_datetime_values() -> None:
    expected = ResultSnapshot(
        ("month", "count"),
        ((date(2018, 1, 1), 10),),
    )
    actual = ResultSnapshot(
        ("order_month", "order_count"),
        ((datetime(2018, 1, 1), 10),),
    )

    assert results_match(actual, expected)


def test_evaluate_result_accepts_correct_answer_and_correct_rejection() -> None:
    answerable_question = GOLD_QUESTIONS[0]
    expected = ResultSnapshot(("total_order_count",), ((99_441,),))
    correct_answer = _answer_result(_sql_result(("order_count",), ((99_441,),)))
    answer_record = evaluate_result(
        answerable_question,
        correct_answer,
        expected,
        "total_order_count",
    )

    unanswerable_question = GOLD_QUESTIONS[-1]
    rejection = _answer_result(
        None,
        status="generation_error",
        generated_sql=None,
        generation_error=SQLGenerationError(
            "cannot_generate",
            "The dataset has no refund events.",
        ),
    )
    rejection_record = evaluate_result(
        unanswerable_question,
        rejection,
        None,
        "rejection",
    )

    assert answer_record.passed is True
    assert rejection_record.passed is True
    assert rejection_record.failure_reason is None


def test_evaluate_result_classifies_semantic_failure_and_missing_rejection() -> None:
    wrong_answer = evaluate_result(
        GOLD_QUESTIONS[0],
        _answer_result(_sql_result(("order_count",), ((10,),))),
        ResultSnapshot(("total_order_count",), ((99_441,),)),
        "total_order_count",
    )
    should_reject = evaluate_result(
        GOLD_QUESTIONS[-1],
        _answer_result(_sql_result(("refund_rate",), ((0.0,),))),
        None,
        "rejection",
    )

    assert wrong_answer.failure_reason == "semantic_wrong_answer"
    assert should_reject.failure_reason == "should_have_rejected"


def test_summary_counts_core_metrics() -> None:
    expected = ResultSnapshot(("total_order_count",), ((99_441,),))
    passed_answer = evaluate_result(
        GOLD_QUESTIONS[0],
        _answer_result(_sql_result(("order_count",), ((99_441,),))),
        expected,
        "total_order_count",
    )
    repaired_wrong_answer = evaluate_result(
        GOLD_QUESTIONS[0],
        _answer_result(
            _sql_result(("order_count",), ((10,),)),
            repair_attempted=True,
        ),
        expected,
        "total_order_count",
    )
    correct_rejection = evaluate_result(
        GOLD_QUESTIONS[-1],
        _answer_result(
            None,
            status="generation_error",
            generated_sql=None,
            generation_error=SQLGenerationError("cannot_generate", "unsupported"),
        ),
        None,
        "rejection",
    )

    summary = summarize((passed_answer, repaired_wrong_answer, correct_rejection))

    assert summary.total == 3
    assert summary.answerable == 2
    assert summary.unanswerable == 1
    assert summary.generation_success == 2
    assert summary.execution_success == 2
    assert summary.correct_answers == 1
    assert summary.correct_rejection == 1
    assert summary.repair_attempted == 1
    assert summary.repair_successful == 1
    assert summary.overall_passed == 2
    assert summary.overall_failed == 1
    assert summary.answerable_correctness_rate == 0.5


def test_evaluate_gold_set_uses_existing_answer_and_reference_paths(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "olist.duckdb"
    database_path.touch()
    question = GOLD_QUESTIONS[0]
    model = object()
    answer_calls: list[tuple[Path, str, object]] = []

    def fake_reference_executor(path, sql):
        assert path == database_path
        assert "COUNT(*)" in sql
        return _sql_result(("total_order_count",), ((99_441,),))

    def fake_answer(path, text, received_model):
        answer_calls.append((path, text, received_model))
        return _answer_result(_sql_result(("order_count",), ((99_441,),)))

    monkeypatch.setattr(evaluation_module, "run_readonly_sql", fake_reference_executor)
    monkeypatch.setattr(evaluation_module, "answer_question", fake_answer)

    records = evaluate_gold_set(database_path, model, questions=(question,))

    assert records[0].passed is True
    assert answer_calls == [(database_path, question.question, model)]
