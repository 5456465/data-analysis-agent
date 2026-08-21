from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import data_analysis_agent.validated_question_service as service_module
from data_analysis_agent.multi_tool_service import (
    ANALYSIS_MAX_ROWS,
    MultiToolQuestionError,
    MultiToolQuestionResult,
)
from data_analysis_agent.result_validation import ResultValidation, ValidationIssue
from data_analysis_agent.schema import DatabaseSchema
from data_analysis_agent.sql_executor import DEFAULT_MAX_ROWS, SQLResult
from data_analysis_agent.tool_router import ToolRouteDecision
from data_analysis_agent.validated_question_service import (
    ValidatedQuestionResult,
    answer_question_with_validation,
)


def _result(
    *,
    route: str = "sql_only",
    operation: str | None = None,
    status: str = "success",
) -> MultiToolQuestionResult:
    sql_result = (
        SQLResult(
            executed_sql="SELECT 1 AS value",
            columns=("value",),
            rows=((1,),),
            returned_row_count=1,
            truncated=False,
            status="success",
            error=None,
        )
        if status == "success"
        else None
    )
    return MultiToolQuestionResult(
        question="test question",
        route_decision=ToolRouteDecision(
            question="test question",
            route=route,
            python_operation=operation,
            reason="test",
            status="success",
            error=None,
        ),
        status=status,
        sql_answer_result=None,
        analysis_plan=None,
        sql_result=sql_result,
        python_result=None,
        error=(
            None
            if status == "success"
            else MultiToolQuestionError("routing_error", "unsupported request")
        ),
    )


def test_successful_sql_only_executes_and_validates_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual = _result()
    validation = ResultValidation("valid", ())
    execution_calls = 0
    validation_calls = 0

    def fake_answer(*args: object, **kwargs: object) -> MultiToolQuestionResult:
        nonlocal execution_calls
        execution_calls += 1
        return actual

    def fake_validate(result: MultiToolQuestionResult) -> ResultValidation:
        nonlocal validation_calls
        validation_calls += 1
        assert result is actual
        return validation

    monkeypatch.setattr(service_module, "answer_question_with_tools", fake_answer)
    monkeypatch.setattr(service_module, "validate_multi_tool_result", fake_validate)

    wrapped = answer_question_with_validation("database.duckdb", "question", object())

    assert execution_calls == 1
    assert validation_calls == 1
    assert wrapped.result is actual
    assert wrapped.validation is validation


def test_successful_sql_then_python_preserves_result_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual = _result(route="sql_then_python", operation="calculate_growth")
    validation = ResultValidation("valid", ())
    monkeypatch.setattr(
        service_module,
        "answer_question_with_tools",
        lambda *args, **kwargs: actual,
    )
    monkeypatch.setattr(
        service_module,
        "validate_multi_tool_result",
        lambda result: validation,
    )

    wrapped = answer_question_with_validation("database.duckdb", "question", object())

    assert wrapped.result is actual
    assert wrapped.validation is validation


def test_structured_agent_failure_is_still_validated_and_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual = _result(status="routing_error")
    validation = ResultValidation(
        "invalid",
        (ValidationIssue("unsuccessful_pipeline", "error", "routing failed"),),
    )
    validated: list[MultiToolQuestionResult] = []
    monkeypatch.setattr(
        service_module,
        "answer_question_with_tools",
        lambda *args, **kwargs: actual,
    )

    def fake_validate(result: MultiToolQuestionResult) -> ResultValidation:
        validated.append(result)
        return validation

    monkeypatch.setattr(service_module, "validate_multi_tool_result", fake_validate)

    wrapped = answer_question_with_validation("database.duckdb", "question", object())

    assert validated == [actual]
    assert wrapped.result is actual
    assert wrapped.validation is validation


def test_warning_validation_is_not_modified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual = _result()
    validation = ResultValidation(
        "valid_with_warnings",
        (ValidationIssue("empty_result", "warning", "No rows."),),
    )
    monkeypatch.setattr(
        service_module,
        "answer_question_with_tools",
        lambda *args, **kwargs: actual,
    )
    monkeypatch.setattr(
        service_module,
        "validate_multi_tool_result",
        lambda result: validation,
    )

    wrapped = answer_question_with_validation("database.duckdb", "question", object())

    assert wrapped.validation is validation
    assert wrapped.validation.status == "valid_with_warnings"


def test_invalid_validation_does_not_trigger_retry_or_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual = _result()
    validation = ResultValidation(
        "invalid",
        (ValidationIssue("truncated_result", "error", "Truncated."),),
    )
    execution_calls = 0
    validation_calls = 0

    def fake_answer(*args: object, **kwargs: object) -> MultiToolQuestionResult:
        nonlocal execution_calls
        execution_calls += 1
        return actual

    def fake_validate(result: MultiToolQuestionResult) -> ResultValidation:
        nonlocal validation_calls
        validation_calls += 1
        return validation

    monkeypatch.setattr(service_module, "answer_question_with_tools", fake_answer)
    monkeypatch.setattr(service_module, "validate_multi_tool_result", fake_validate)

    wrapped = answer_question_with_validation("database.duckdb", "question", object())

    assert execution_calls == 1
    assert validation_calls == 1
    assert wrapped.validation.status == "invalid"


def test_all_existing_parameters_are_forwarded_transparently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual = _result()
    model = object()
    schema = DatabaseSchema(objects=())
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_answer(*args: object, **kwargs: object) -> MultiToolQuestionResult:
        observed.append((args, kwargs))
        return actual

    monkeypatch.setattr(service_module, "answer_question_with_tools", fake_answer)
    monkeypatch.setattr(
        service_module,
        "validate_multi_tool_result",
        lambda result: ResultValidation("valid", ()),
    )

    answer_question_with_validation(
        Path("custom.duckdb"),
        "custom question",
        model,
        max_rows=321,
        analysis_max_rows=654,
        schema=schema,
    )

    assert observed == [
        (
            (Path("custom.duckdb"), "custom question", model),
            {"max_rows": 321, "analysis_max_rows": 654, "schema": schema},
        )
    ]


def test_wrapper_uses_existing_default_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_kwargs: list[dict[str, object]] = []

    def fake_answer(*args: object, **kwargs: object) -> MultiToolQuestionResult:
        observed_kwargs.append(kwargs)
        return _result()

    monkeypatch.setattr(service_module, "answer_question_with_tools", fake_answer)
    monkeypatch.setattr(
        service_module,
        "validate_multi_tool_result",
        lambda result: ResultValidation("valid", ()),
    )

    answer_question_with_validation("database.duckdb", "question", object())

    assert observed_kwargs == [
        {
            "max_rows": DEFAULT_MAX_ROWS,
            "analysis_max_rows": ANALYSIS_MAX_ROWS,
            "schema": None,
        }
    ]


def test_wrapper_does_not_make_an_additional_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_calls = 0

    def model(prompt: str) -> str:
        nonlocal model_calls
        model_calls += 1
        return prompt

    def fake_answer(
        database_path: str | Path,
        question: str,
        received_model: object,
        **kwargs: object,
    ) -> MultiToolQuestionResult:
        del database_path, question, kwargs
        received_model("service-owned model call")
        return _result()

    monkeypatch.setattr(service_module, "answer_question_with_tools", fake_answer)
    monkeypatch.setattr(
        service_module,
        "validate_multi_tool_result",
        lambda result: ResultValidation("valid", ()),
    )

    answer_question_with_validation("database.duckdb", "question", model)

    assert model_calls == 1


def test_wrapper_does_not_mutate_multi_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual = _result()
    before = repr(actual)
    monkeypatch.setattr(
        service_module,
        "answer_question_with_tools",
        lambda *args, **kwargs: actual,
    )
    monkeypatch.setattr(
        service_module,
        "validate_multi_tool_result",
        lambda result: ResultValidation("valid", ()),
    )

    wrapped = answer_question_with_validation("database.duckdb", "question", object())

    assert wrapped.result is actual
    assert repr(actual) == before


def test_validated_question_result_is_frozen() -> None:
    wrapped = ValidatedQuestionResult(
        result=_result(),
        validation=ResultValidation("valid", ()),
    )

    with pytest.raises(FrozenInstanceError):
        wrapped.validation = ResultValidation("invalid", ())


def test_wrapper_does_not_execute_sql_or_python_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("wrapper must not execute tools directly")

    monkeypatch.setattr(
        "data_analysis_agent.sql_executor.run_readonly_sql",
        fail_if_called,
    )
    monkeypatch.setattr(
        "data_analysis_agent.python_analysis.run_python_analysis",
        fail_if_called,
    )
    monkeypatch.setattr(
        service_module,
        "answer_question_with_tools",
        lambda *args, **kwargs: _result(),
    )
    monkeypatch.setattr(
        service_module,
        "validate_multi_tool_result",
        lambda result: ResultValidation("valid", ()),
    )

    wrapped = answer_question_with_validation("database.duckdb", "question", object())

    assert wrapped.validation.status == "valid"
