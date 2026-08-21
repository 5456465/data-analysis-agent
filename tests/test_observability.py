"""Tests for request-scoped latency and provider-usage observations."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import duckdb
import pytest

import data_analysis_agent.observability as observability_module
from data_analysis_agent.answer_synthesis import AnswerSynthesis
from data_analysis_agent.final_answer_service import answer_question_for_user
from data_analysis_agent.natural_language_answer import (
    generate_natural_language_answer,
)
from data_analysis_agent.observability import (
    LLMCallObservation,
    RequestObservability,
    StageObservation,
    finalize_observability,
    observe_stage,
    record_llm_call,
    start_observability_request,
)
from data_analysis_agent.schema import DatabaseSchema


def _finalize(collector) -> RequestObservability:
    return finalize_observability(
        collector,
        route="sql_only",
        final_status="success",
        validation_status="valid",
    )


@pytest.mark.parametrize(
    ("value", "field_name", "replacement"),
    [
        (StageObservation("routing", 1.0), "stage", "planning"),
        (
            LLMCallObservation(
                "routing",
                "model",
                1.0,
                2,
                3,
                5,
                "success",
            ),
            "model",
            "changed",
        ),
    ],
)
def test_observation_records_are_frozen(
    value: object,
    field_name: str,
    replacement: object,
) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(value, field_name, replacement)


def test_request_observability_is_frozen() -> None:
    with start_observability_request() as collector:
        result = _finalize(collector)

    with pytest.raises(FrozenInstanceError):
        result.final_status = "changed"


def test_request_id_is_non_empty_and_unique_per_request() -> None:
    with start_observability_request() as first_collector:
        first = _finalize(first_collector)
    with start_observability_request() as second_collector:
        second = _finalize(second_collector)

    assert first.request_id
    assert second.request_id
    assert first.request_id != second.request_id


def test_stage_and_total_latency_use_controllable_monotonic_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter((1.0, 2.0, 2.25, 4.0))
    monkeypatch.setattr(
        observability_module.time,
        "perf_counter",
        lambda: next(clock),
    )

    with start_observability_request() as collector:
        with observe_stage("routing"):
            pass
        result = _finalize(collector)

    assert result.stages == (StageObservation("routing", 250.0),)
    assert result.total_latency_ms == 3000.0
    assert result.stages[0].latency_ms >= 0
    assert result.total_latency_ms >= 0


def test_inactive_collector_is_no_op() -> None:
    with observe_stage("routing"):
        pass
    record_llm_call(
        LLMCallObservation("routing", "model", 1.0, 1, 1, 2, "success")
    )

    with start_observability_request() as collector:
        result = _finalize(collector)

    assert result.stages == ()
    assert result.llm_calls == ()


def test_request_isolation_and_stage_order_are_deterministic() -> None:
    with start_observability_request() as first_collector:
        with observe_stage("routing"):
            pass
        with observe_stage("sql_generation"):
            pass
        first = _finalize(first_collector)

    with start_observability_request() as second_collector:
        with observe_stage("planning"):
            pass
        second = _finalize(second_collector)

    assert tuple(stage.stage for stage in first.stages) == (
        "routing",
        "sql_generation",
    )
    assert tuple(stage.stage for stage in second.stages) == ("planning",)
    assert second.request_id != first.request_id


def test_no_llm_calls_produce_unavailable_token_totals() -> None:
    with start_observability_request() as collector:
        result = _finalize(collector)

    assert result.total_prompt_tokens is None
    assert result.total_completion_tokens is None
    assert result.total_tokens is None


def test_skipped_narrative_creates_no_stage_or_llm_call() -> None:
    with start_observability_request() as collector:
        narrative = generate_natural_language_answer(
            "Question",
            "invalid",
            AnswerSynthesis("blocked", "Blocked.", ()),
            lambda prompt: pytest.fail("skipped narrative must not call model"),
        )
        result = _finalize(collector)

    assert narrative.status == "skipped"
    assert result.stages == ()
    assert result.llm_calls == ()


def test_complete_usage_is_aggregated_across_calls() -> None:
    with start_observability_request() as collector:
        record_llm_call(
            LLMCallObservation("routing", "model", 1.0, 10, 2, 12, "success")
        )
        record_llm_call(
            LLMCallObservation(
                "sql_generation",
                "model",
                2.0,
                20,
                3,
                23,
                "success",
            )
        )
        result = _finalize(collector)

    assert result.total_prompt_tokens == 30
    assert result.total_completion_tokens == 5
    assert result.total_tokens == 35


def test_partial_usage_makes_corresponding_aggregates_unavailable() -> None:
    with start_observability_request() as collector:
        record_llm_call(
            LLMCallObservation("routing", "model", 1.0, 10, 2, 12, "success")
        )
        record_llm_call(
            LLMCallObservation(
                "sql_generation",
                "model",
                2.0,
                None,
                None,
                None,
                "success",
            )
        )
        result = _finalize(collector)

    assert result.total_prompt_tokens is None
    assert result.total_completion_tokens is None
    assert result.total_tokens is None


def test_public_contract_cannot_store_prompt_response_or_secret() -> None:
    field_names = {
        field.name
        for contract in (RequestObservability, StageObservation, LLMCallObservation)
        for field in fields(contract)
    }

    assert "prompt" not in field_names
    assert "response" not in field_names
    assert "raw_response" not in field_names
    assert "api_key" not in field_names


def _create_database(tmp_path) -> str:
    database_path = tmp_path / "observability.duckdb"
    with duckdb.connect(str(database_path)):
        pass
    return str(database_path)


def test_sql_only_pipeline_records_only_executed_stages(tmp_path) -> None:
    database_path = _create_database(tmp_path)

    def model(prompt: str):
        if prompt.startswith("You route"):
            return {
                "status": "success",
                "route": "sql_only",
                "python_operation": None,
                "reason": "SQL is sufficient.",
            }
        return {"status": "success", "sql": "SELECT 1 AS value"}

    final = answer_question_for_user(
        database_path,
        "Return one value.",
        model,
        schema=DatabaseSchema(objects=()),
    )

    assert final.observability is not None
    assert tuple(stage.stage for stage in final.observability.stages) == (
        "routing",
        "sql_generation",
        "sql_execution",
        "validation",
        "answer_synthesis",
    )
    assert "sql_repair" not in {
        stage.stage for stage in final.observability.stages
    }
    assert final.observability.route == "sql_only"
    assert final.observability.final_status == "success"
    assert final.observability.validation_status == "valid"


def test_sql_then_python_pipeline_records_planning_and_python(tmp_path) -> None:
    database_path = _create_database(tmp_path)

    def model(prompt: str):
        if prompt.startswith("You route"):
            return {
                "status": "success",
                "route": "sql_then_python",
                "python_operation": "correlation",
                "reason": "Use controlled Python analysis.",
            }
        return {
            "status": "success",
            "sql": "SELECT x, y FROM (VALUES (1, 2), (2, 4)) AS t(x, y)",
            "python_columns": ["x", "y"],
        }

    final = answer_question_for_user(
        database_path,
        "Calculate a controlled correlation.",
        model,
        schema=DatabaseSchema(objects=()),
    )

    assert final.observability is not None
    assert tuple(stage.stage for stage in final.observability.stages) == (
        "routing",
        "planning",
        "sql_execution",
        "python_analysis",
        "validation",
        "answer_synthesis",
    )


def test_repair_pipeline_records_repair_and_both_sql_attempts(tmp_path) -> None:
    database_path = _create_database(tmp_path)

    def model(prompt: str):
        if prompt.startswith("You route"):
            return {
                "status": "success",
                "route": "sql_only",
                "python_operation": None,
                "reason": "SQL is sufficient.",
            }
        if prompt.startswith("You generate"):
            return {"status": "success", "sql": "SELECT missing FROM missing"}
        return {"status": "success", "sql": "SELECT 1 AS value"}

    final = answer_question_for_user(
        database_path,
        "Return one value.",
        model,
        schema=DatabaseSchema(objects=()),
    )

    assert final.observability is not None
    assert tuple(stage.stage for stage in final.observability.stages) == (
        "routing",
        "sql_generation",
        "sql_execution",
        "sql_repair",
        "sql_execution",
        "validation",
        "answer_synthesis",
    )


def test_narrative_stage_exists_only_when_model_is_called(tmp_path) -> None:
    database_path = _create_database(tmp_path)

    def model(prompt: str):
        if prompt.startswith("You route"):
            return {
                "status": "success",
                "route": "sql_only",
                "python_operation": None,
                "reason": "SQL is sufficient.",
            }
        return {"status": "success", "sql": "SELECT 1 AS value"}

    without_narrative = answer_question_for_user(
        database_path,
        "Return one value.",
        model,
        schema=DatabaseSchema(objects=()),
    )
    with_narrative = answer_question_for_user(
        database_path,
        "Return one value.",
        model,
        schema=DatabaseSchema(objects=()),
        natural_language_model=lambda prompt: "The result is 1.",
    )

    assert without_narrative.observability is not None
    assert with_narrative.observability is not None
    assert "natural_language_synthesis" not in {
        stage.stage for stage in without_narrative.observability.stages
    }
    assert "natural_language_synthesis" in {
        stage.stage for stage in with_narrative.observability.stages
    }


def test_structured_routing_failure_records_no_unexecuted_stages(tmp_path) -> None:
    final = answer_question_for_user(
        _create_database(tmp_path),
        "Unsupported request.",
        lambda prompt: {"status": "error", "error": "Unsupported."},
        schema=DatabaseSchema(objects=()),
    )

    assert final.observability is not None
    assert tuple(stage.stage for stage in final.observability.stages) == (
        "routing",
        "validation",
        "answer_synthesis",
    )
    assert final.observability.final_status == "routing_error"
    assert final.observability.validation_status == "invalid"
