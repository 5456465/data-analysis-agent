"""Tests for the deterministic English gold question set."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from data_analysis_agent import GOLD_QUESTIONS, GoldQuestion, inspect_schema
from data_analysis_agent.sql_executor import run_readonly_sql
from scripts.baseline_queries import BASELINE_QUERIES, get_query
from scripts.build_duckdb import build_database


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "raw"
EXPECTED_IDS = tuple(f"GQ-{number:03d}" for number in range(1, 17))
GRAIN_SENSITIVE_BASELINES = {
    "average_payment_value_per_order",
    "orders_with_multiple_items_percentage",
    "orders_with_multiple_payment_records_percentage",
}


@pytest.fixture(scope="module")
def database_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("gold_questions") / "olist.duckdb"
    build_database(DATA_DIR, path)
    return path


def test_gold_question_ids_and_text_are_unique_and_non_empty() -> None:
    ids = tuple(question.id for question in GOLD_QUESTIONS)
    texts = tuple(question.question for question in GOLD_QUESTIONS)

    assert ids == EXPECTED_IDS
    assert len(ids) == len(set(ids))
    assert len(texts) == len(set(texts))
    assert all(text.strip() for text in texts)
    assert all(question.metric_definition.strip() for question in GOLD_QUESTIONS)
    assert all(question.expected_grain.strip() for question in GOLD_QUESTIONS)


def test_gold_question_collection_is_deterministic_and_immutable() -> None:
    assert isinstance(GOLD_QUESTIONS, tuple)
    assert all(isinstance(question.expected_tables, tuple) for question in GOLD_QUESTIONS)

    with pytest.raises(FrozenInstanceError):
        GOLD_QUESTIONS[0].question = "changed"


def test_answerable_questions_reference_exactly_one_sql_source() -> None:
    for question in GOLD_QUESTIONS:
        has_baseline = question.baseline_key is not None
        has_reference_sql = question.reference_sql is not None
        if question.answerable:
            assert has_baseline ^ has_reference_sql
            assert question.unanswerable_reason is None
        else:
            assert not has_baseline
            assert not has_reference_sql
            assert question.unanswerable_reason is not None
            assert question.unanswerable_reason.strip()


def test_baseline_keys_exist() -> None:
    baseline_keys = {query.key for query in BASELINE_QUERIES}

    assert {
        question.baseline_key
        for question in GOLD_QUESTIONS
        if question.baseline_key is not None
    } <= baseline_keys


def test_expected_tables_exist_in_duckdb_schema(database_path: Path) -> None:
    schema_objects = {obj.name for obj in inspect_schema(database_path).objects}

    for question in GOLD_QUESTIONS:
        assert set(question.expected_tables) <= schema_objects


def test_all_answerable_queries_execute_successfully(database_path: Path) -> None:
    baselines = {query.key: query.sql for query in BASELINE_QUERIES}

    for question in GOLD_QUESTIONS:
        if not question.answerable:
            continue
        sql = (
            baselines[question.baseline_key]
            if question.baseline_key is not None
            else question.reference_sql
        )
        assert sql is not None
        result = run_readonly_sql(database_path, sql)
        assert result.status == "success", (question.id, result.error)
        assert result.returned_row_count > 0
        assert result.truncated is False


def test_contains_required_unanswerable_questions() -> None:
    unanswerable = {
        question.question: question
        for question in GOLD_QUESTIONS
        if not question.answerable
    }

    assert len(unanswerable) >= 2
    assert "What is Olist's gross profit margin?" in unanswerable
    assert "What is the refund rate?" in unanswerable


def test_contains_required_grain_sensitive_questions() -> None:
    grain_questions = {
        question.baseline_key: question
        for question in GOLD_QUESTIONS
        if question.category == "grain_sensitive"
    }

    assert set(grain_questions) == GRAIN_SENSITIVE_BASELINES
    assert "payment-record grain" in grain_questions[
        "average_payment_value_per_order"
    ].expected_grain
    assert "order-item grain" in grain_questions[
        "orders_with_multiple_items_percentage"
    ].expected_grain
    assert "payment-record grain" in grain_questions[
        "orders_with_multiple_payment_records_percentage"
    ].expected_grain
    assert all("order grain" in question.expected_grain for question in grain_questions.values())


def test_order_status_question_declares_descending_ranking_contract() -> None:
    question = next(question for question in GOLD_QUESTIONS if question.id == "GQ-002")
    normalized = question.question.lower()

    assert question.order_sensitive is True
    assert "all order statuses" in normalized
    assert "highest to lowest" in normalized
    assert "order count" in normalized


def test_top_category_baseline_has_deterministic_top_ten_ordering(
    database_path: Path,
) -> None:
    baseline = get_query("top_product_categories_by_item_transaction_value")
    normalized_sql = " ".join(baseline.sql.split())

    assert (
        "ORDER BY item_transaction_value DESC NULLS LAST, "
        "category.product_category_name ASC NULLS LAST"
    ) in normalized_sql
    assert "LIMIT 10" in normalized_sql

    result = run_readonly_sql(database_path, baseline.sql)

    assert result.status == "success"
    assert result.returned_row_count == 10
    ranking = tuple((row[3], row[0]) for row in result.rows)
    assert ranking == tuple(
        sorted(
            ranking,
            key=lambda item: (-item[0], item[1] is None, item[1] or ""),
        )
    )
