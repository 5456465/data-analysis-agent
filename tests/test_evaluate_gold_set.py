"""Tests for deterministic Gold Set result comparison and metrics."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import scripts.evaluate_gold_set as evaluation_module
from data_analysis_agent.gold_questions import (
    GOLD_QUESTIONS,
    LabelAlias,
    RankingComparison,
    TemporalComparison,
)
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


def test_order_sensitive_results_require_the_same_row_order() -> None:
    expected = ResultSnapshot(
        ("state", "customer_count"),
        (("SP", 100), ("RJ", 80)),
    )
    same_order = ResultSnapshot(
        ("region", "count"),
        (("SP", 100), ("RJ", 80)),
    )
    reversed_order = ResultSnapshot(
        ("region", "count"),
        (("RJ", 80), ("SP", 100)),
    )

    assert results_match(same_order, expected, order_sensitive=True)
    assert not results_match(reversed_order, expected, order_sensitive=True)
    assert results_match(reversed_order, expected, order_sensitive=False)


def test_results_with_different_row_counts_do_not_match() -> None:
    expected = ResultSnapshot(
        ("state", "customer_count"),
        (("SP", 100), ("RJ", 80)),
    )
    actual = ResultSnapshot(("state", "customer_count"), (("SP", 100),))

    assert not results_match(actual, expected)
    assert not results_match(actual, expected, order_sensitive=True)


def test_order_sensitive_top_k_rejects_extra_rows() -> None:
    expected_rows = tuple((f"category_{index}", 100 - index) for index in range(10))
    actual_rows = expected_rows + (("category_10", 90),)
    expected = ResultSnapshot(("category", "value"), expected_rows)
    actual = ResultSnapshot(("category", "value"), actual_rows)

    assert not results_match(actual, expected, order_sensitive=True)


def test_order_sensitive_results_preserve_numeric_tolerance() -> None:
    expected = ResultSnapshot(
        ("state", "value"),
        (("SP", Decimal("100.004")), ("RJ", Decimal("80.004"))),
    )
    actual = ResultSnapshot(
        ("state", "value"),
        (("SP", 100.00), ("RJ", 80.00)),
    )

    assert results_match(actual, expected, order_sensitive=True)


def test_gold_questions_declare_order_sensitive_contract_explicitly() -> None:
    order_sensitive_ids = {
        question.id for question in GOLD_QUESTIONS if question.order_sensitive
    }

    assert order_sensitive_ids == {"GQ-002", "GQ-005", "GQ-006", "GQ-009"}


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


def test_month_grain_accepts_equivalent_representations_only() -> None:
    contract = (TemporalComparison("order_month", "month"),)
    expected = ResultSnapshot(
        ("order_month", "order_count"),
        ((date(2016, 9, 1), 4),),
    )

    assert results_match(
        ResultSnapshot(("month", "count"), (("2016-09", 4),)),
        expected,
        temporal_comparisons=contract,
    )
    assert results_match(
        ResultSnapshot(
            ("month", "count"),
            (("2016-09-01 00:00:00", 4),),
        ),
        expected,
        temporal_comparisons=contract,
    )
    assert not results_match(
        ResultSnapshot(("month", "count"), (("2016-10", 4),)),
        expected,
        temporal_comparisons=contract,
    )


def test_month_normalization_does_not_affect_ordinary_strings() -> None:
    actual = ResultSnapshot(("delivery_status",), (("after_estimate",),))
    expected = ResultSnapshot(("delivery_status",), (("delayed",),))

    assert not results_match(actual, expected)


def test_tie_aware_ranking_allows_only_tied_group_reordering() -> None:
    ranking = RankingComparison("seller_count", "descending")
    expected = ResultSnapshot(
        ("seller_state", "seller_count"),
        (("SP", 100), ("RJ", 50), ("MS", 5), ("RN", 5)),
    )
    tied_rows_reordered = ResultSnapshot(
        ("state", "count"),
        (("SP", 100), ("RJ", 50), ("RN", 5), ("MS", 5)),
    )
    primary_ranking_broken = ResultSnapshot(
        ("state", "count"),
        (("SP", 100), ("RN", 5), ("RJ", 50), ("MS", 5)),
    )

    assert results_match(tied_rows_reordered, expected, ranking=ranking)
    assert not results_match(primary_ranking_broken, expected, ranking=ranking)


def test_tie_aware_ranking_rejects_missing_or_extra_rows() -> None:
    ranking = RankingComparison("seller_count", "descending")
    expected = ResultSnapshot(
        ("seller_state", "seller_count"),
        (("SP", 100), ("RJ", 50), ("MS", 5), ("RN", 5)),
    )
    missing = ResultSnapshot(
        ("state", "count"),
        (("SP", 100), ("RJ", 50), ("MS", 5)),
    )
    extra = ResultSnapshot(
        ("state", "count"),
        (("SP", 100), ("RJ", 50), ("MS", 5), ("RN", 5), ("AC", 1)),
    )

    assert not results_match(missing, expected, ranking=ranking)
    assert not results_match(extra, expected, ranking=ranking)


def test_declared_label_aliases_require_matching_numeric_values() -> None:
    aliases = (
        LabelAlias("delivery_status", "delayed", ("after_estimate",)),
        LabelAlias(
            "delivery_status",
            "on_time_or_early",
            ("on_or_before_estimate",),
        ),
    )
    expected = ResultSnapshot(
        ("delivery_status", "average_review_score"),
        (("delayed", 2.5665), ("on_time_or_early", 4.2936)),
    )
    equivalent = ResultSnapshot(
        ("timing", "score"),
        (("after_estimate", 2.56655), ("on_or_before_estimate", 4.29358)),
    )
    unknown_label = ResultSnapshot(
        ("timing", "score"),
        (("late_delivery", 2.56655), ("on_or_before_estimate", 4.29358)),
    )
    wrong_value = ResultSnapshot(
        ("timing", "score"),
        (("after_estimate", 3.0), ("on_or_before_estimate", 4.29358)),
    )

    assert results_match(equivalent, expected, label_aliases=aliases)
    assert not results_match(unknown_label, expected, label_aliases=aliases)
    assert not results_match(wrong_value, expected, label_aliases=aliases)


def test_gold_metadata_covers_observed_evaluator_equivalences() -> None:
    questions = {question.id: question for question in GOLD_QUESTIONS}

    monthly_record = evaluate_result(
        questions["GQ-004"],
        _answer_result(
            _sql_result(("month", "order_count"), (("2016-09", 4),))
        ),
        ResultSnapshot(
            ("order_month", "order_count"),
            ((date(2016, 9, 1), 4),),
        ),
        "monthly_order_count",
    )
    seller_record = evaluate_result(
        questions["GQ-006"],
        _answer_result(
            _sql_result(
                ("seller_state", "seller_count"),
                (("SP", 100), ("RN", 5), ("MS", 5)),
            )
        ),
        ResultSnapshot(
            ("seller_state", "seller_count"),
            (("SP", 100), ("MS", 5), ("RN", 5)),
        ),
        "seller_distribution_by_state",
    )
    review_record = evaluate_result(
        questions["GQ-010"],
        _answer_result(
            _sql_result(
                ("delivery_timing", "average_review_score"),
                (
                    ("after_estimate", 2.56655),
                    ("on_or_before_estimate", 4.29358),
                ),
            )
        ),
        ResultSnapshot(
            ("delivery_status", "average_review_score"),
            (("delayed", 2.5665), ("on_time_or_early", 4.2936)),
        ),
        "delivery_delay_and_review_score",
    )

    assert monthly_record.passed is True
    assert seller_record.passed is True
    assert review_record.passed is True


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


def test_evaluate_result_uses_question_order_sensitive_contract() -> None:
    question = next(question for question in GOLD_QUESTIONS if question.id == "GQ-005")
    expected = ResultSnapshot(
        ("customer_state", "unique_customer_count"),
        (("SP", 100), ("RJ", 80)),
    )
    reversed_result = _answer_result(
        _sql_result(
            ("customer_state", "unique_customer_count"),
            (("RJ", 80), ("SP", 100)),
        )
    )

    record = evaluate_result(
        question,
        reversed_result,
        expected,
        "customer_distribution_by_state",
    )

    assert record.passed is False
    assert record.failure_reason == "semantic_wrong_answer"


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
