"""Quality checks for the frozen held-out multi-tool question contracts."""

from __future__ import annotations

from collections import Counter
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from data_analysis_agent.gold_questions import GOLD_QUESTIONS
from data_analysis_agent.multi_tool_test_questions import (
    MULTI_TOOL_TEST_QUESTIONS,
    MultiToolTestQuestion,
)
from data_analysis_agent.python_analysis import (
    GrowthResult,
    PythonAnalysisRequest,
    run_python_analysis,
)
from data_analysis_agent.schema import inspect_schema
from data_analysis_agent.sql_executor import run_readonly_sql
from scripts.build_duckdb import build_database


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "raw"
EXPECTED_IDS = tuple(f"MTQ-{number:03d}" for number in range(1, 19))
EXPECTED_CATEGORY_COUNTS = {
    "sql_only": 10,
    "calculate_growth": 4,
    "data_unanswerable": 2,
    "capability_unsupported": 2,
}
FORBIDDEN_PROMPT_EXAMPLES = {
    "How many orders are in the dataset?",
    "Give me descriptive statistics for payment values.",
    "What is the Pearson correlation between item price and freight value?",
    "What was total item transaction value by month?",
    "How did total item transaction value change month over month?",
}


@pytest.fixture(scope="module")
def database_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("multi_tool_test_questions") / "olist.duckdb"
    build_database(DATA_DIR, path)
    return path


def _normalized_question(text: str) -> str:
    return " ".join(text.lower().split())


def test_question_count_ids_and_text_are_deterministic() -> None:
    ids = tuple(question.id for question in MULTI_TOOL_TEST_QUESTIONS)
    questions = tuple(question.question for question in MULTI_TOOL_TEST_QUESTIONS)

    assert isinstance(MULTI_TOOL_TEST_QUESTIONS, tuple)
    assert len(MULTI_TOOL_TEST_QUESTIONS) == 18
    assert ids == EXPECTED_IDS
    assert len(ids) == len(set(ids))
    assert len(questions) == len(set(questions))
    assert all(question.strip() for question in questions)


def test_question_contracts_are_immutable() -> None:
    assert all(
        isinstance(question, MultiToolTestQuestion)
        for question in MULTI_TOOL_TEST_QUESTIONS
    )
    assert all(
        isinstance(question.expected_tables, tuple)
        and isinstance(question.python_columns, tuple)
        for question in MULTI_TOOL_TEST_QUESTIONS
    )

    with pytest.raises(FrozenInstanceError):
        MULTI_TOOL_TEST_QUESTIONS[0].question = "changed"


def test_category_distribution_matches_frozen_contract() -> None:
    counts = Counter(question.category for question in MULTI_TOOL_TEST_QUESTIONS)

    assert counts == EXPECTED_CATEGORY_COUNTS


def test_all_questions_have_complete_human_audited_semantics() -> None:
    for question in MULTI_TOOL_TEST_QUESTIONS:
        assert question.metric_definition.strip()
        assert question.expected_grain.strip()
        assert question.notes.startswith("ALIGNED:")


def test_sql_only_contracts_are_complete() -> None:
    sql_only = tuple(
        question
        for question in MULTI_TOOL_TEST_QUESTIONS
        if question.category == "sql_only"
    )

    assert len(sql_only) == 10
    for question in sql_only:
        assert question.expected_disposition == "answer"
        assert question.expected_route == "sql_only"
        assert question.expected_python_operation is None
        assert question.reference_sql is not None
        assert question.reference_sql.strip()
        assert question.python_columns == ()
        assert question.unanswerable_reason is None


def test_calculate_growth_contracts_are_complete() -> None:
    growth_questions = tuple(
        question
        for question in MULTI_TOOL_TEST_QUESTIONS
        if question.category == "calculate_growth"
    )

    assert len(growth_questions) == 4
    for question in growth_questions:
        assert question.expected_disposition == "answer"
        assert question.expected_route == "sql_then_python"
        assert question.expected_python_operation == "calculate_growth"
        assert question.reference_sql is not None
        assert question.reference_sql.strip()
        assert len(question.python_columns) == 2
        assert len(set(question.python_columns)) == 2
        assert question.unanswerable_reason is None


def test_reject_contracts_have_reasons_and_no_fabricated_sql() -> None:
    rejected = tuple(
        question
        for question in MULTI_TOOL_TEST_QUESTIONS
        if question.expected_disposition == "reject"
    )

    assert len(rejected) == 4
    assert Counter(question.category for question in rejected) == {
        "data_unanswerable": 2,
        "capability_unsupported": 2,
    }
    for question in rejected:
        assert question.expected_route is None
        assert question.expected_python_operation is None
        assert question.reference_sql is None
        assert question.python_columns == ()
        assert question.unanswerable_reason is not None
        assert question.unanswerable_reason.strip()


def test_expected_schema_objects_exist_for_answerable_questions(
    database_path: Path,
) -> None:
    schema_objects = {obj.name for obj in inspect_schema(database_path).objects}

    for question in MULTI_TOOL_TEST_QUESTIONS:
        if question.expected_disposition == "answer":
            assert question.expected_tables
            assert set(question.expected_tables) <= schema_objects


def test_all_reference_sql_is_safe_and_executes_without_truncation(
    database_path: Path,
) -> None:
    for question in MULTI_TOOL_TEST_QUESTIONS:
        if question.reference_sql is None:
            continue

        result = run_readonly_sql(
            database_path,
            question.reference_sql,
            max_rows=1_000,
        )

        assert result.status == "success", (question.id, result.error)
        assert result.returned_row_count > 0, question.id
        assert result.truncated is False, question.id


def test_growth_reference_sql_only_prepares_period_value_series() -> None:
    forbidden_terms = (
        "lag(",
        "lead(",
        "previous_value",
        "absolute_change",
        "growth_rate",
        "percentage_change",
        "percent_change",
    )

    for question in MULTI_TOOL_TEST_QUESTIONS:
        if question.category != "calculate_growth":
            continue
        assert question.reference_sql is not None
        normalized_sql = " ".join(question.reference_sql.lower().split())
        assert "order by" in normalized_sql
        assert not any(term in normalized_sql for term in forbidden_terms)


def test_growth_references_run_through_frozen_python_tool(
    database_path: Path,
) -> None:
    for question in MULTI_TOOL_TEST_QUESTIONS:
        if question.category != "calculate_growth":
            continue
        assert question.reference_sql is not None
        sql_result = run_readonly_sql(
            database_path,
            question.reference_sql,
            max_rows=1_000,
        )

        assert sql_result.status == "success", (question.id, sql_result.error)
        assert sql_result.truncated is False
        assert sql_result.columns == question.python_columns
        assert all(row[0] is not None and row[1] is not None for row in sql_result.rows)

        analysis_result = run_python_analysis(
            columns=sql_result.columns,
            rows=sql_result.rows,
            request=PythonAnalysisRequest(
                operation="calculate_growth",
                columns=question.python_columns,
            ),
        )

        assert analysis_result.status == "success", (
            question.id,
            analysis_result.error,
        )
        assert isinstance(analysis_result.result, GrowthResult)
        assert analysis_result.result.period_count == sql_result.returned_row_count


def test_top_n_reference_has_deterministic_order_and_exact_row_count(
    database_path: Path,
) -> None:
    question = next(
        question
        for question in MULTI_TOOL_TEST_QUESTIONS
        if question.id == "MTQ-006"
    )
    assert question.reference_sql is not None
    normalized_sql = " ".join(question.reference_sql.split())

    assert "item_count DESC" in normalized_sql
    assert "sellers.seller_state ASC" in normalized_sql
    assert "sellers.seller_city ASC" in normalized_sql
    assert "LIMIT 7" in normalized_sql

    result = run_readonly_sql(database_path, question.reference_sql)

    assert result.status == "success"
    assert result.returned_row_count == 7
    ranking = tuple((row[2], row[1], row[0]) for row in result.rows)
    assert ranking == tuple(
        sorted(ranking, key=lambda item: (-item[0], item[1], item[2]))
    )


def test_questions_do_not_duplicate_gold_or_frozen_prompt_examples() -> None:
    old_questions = {
        _normalized_question(question.question) for question in GOLD_QUESTIONS
    }
    forbidden_questions = {
        _normalized_question(question) for question in FORBIDDEN_PROMPT_EXAMPLES
    }
    new_questions = {
        _normalized_question(question.question)
        for question in MULTI_TOOL_TEST_QUESTIONS
    }

    assert new_questions.isdisjoint(old_questions)
    assert new_questions.isdisjoint(forbidden_questions)
