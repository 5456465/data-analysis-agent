from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import data_analysis_agent.final_answer_service as service_module
from data_analysis_agent.answer_synthesis import AnswerSynthesis
from data_analysis_agent.final_answer_service import (
    FinalAnswerResult,
    answer_question_for_user,
)
from data_analysis_agent.multi_tool_service import (
    ANALYSIS_MAX_ROWS,
    MultiToolQuestionResult,
)
from data_analysis_agent.result_validation import ResultValidation, ValidationIssue
from data_analysis_agent.schema import DatabaseSchema
from data_analysis_agent.sql_executor import DEFAULT_MAX_ROWS, SQLResult
from data_analysis_agent.tool_router import ToolRouteDecision
from data_analysis_agent.validated_question_service import ValidatedQuestionResult


def _multi_tool_result() -> MultiToolQuestionResult:
    return MultiToolQuestionResult(
        question="test question",
        route_decision=ToolRouteDecision(
            question="test question",
            route="sql_only",
            python_operation=None,
            reason="test",
            status="success",
            error=None,
        ),
        status="success",
        sql_answer_result=None,
        analysis_plan=None,
        sql_result=SQLResult(
            executed_sql="SELECT 1 AS value",
            columns=("value",),
            rows=((1,),),
            returned_row_count=1,
            truncated=False,
            status="success",
            error=None,
        ),
        python_result=None,
        error=None,
    )


def _validated_result(
    status: str = "valid",
    issues: tuple[ValidationIssue, ...] = (),
) -> ValidatedQuestionResult:
    return ValidatedQuestionResult(
        result=_multi_tool_result(),
        validation=ResultValidation(status=status, issues=issues),
    )


def test_successful_validated_result_returns_successful_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validated = _validated_result()
    synthesis = AnswerSynthesis("success", "Result: 1", ())
    monkeypatch.setattr(
        service_module,
        "answer_question_with_validation",
        lambda *args, **kwargs: validated,
    )
    monkeypatch.setattr(
        service_module,
        "synthesize_answer",
        lambda result, locale="en": synthesis,
    )

    final = answer_question_for_user("database.duckdb", "question", object())

    assert final.validated_result is validated
    assert final.synthesis is synthesis
    assert final.synthesis.status == "success"


def test_invalid_validation_flows_to_blocked_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validated = _validated_result(
        "invalid",
        (ValidationIssue("failed", "error", "Failed validation."),),
    )
    synthesis = AnswerSynthesis("blocked", "Cannot answer.", ())
    received: list[ValidatedQuestionResult] = []
    monkeypatch.setattr(
        service_module,
        "answer_question_with_validation",
        lambda *args, **kwargs: validated,
    )

    def fake_synthesize(
        result: ValidatedQuestionResult,
        locale: str = "en",
    ) -> AnswerSynthesis:
        assert locale == "en"
        received.append(result)
        return synthesis

    monkeypatch.setattr(service_module, "synthesize_answer", fake_synthesize)

    final = answer_question_for_user("database.duckdb", "question", object())

    assert received == [validated]
    assert final.validated_result is validated
    assert final.synthesis is synthesis
    assert final.synthesis.status == "blocked"


def test_valid_with_warnings_preserves_synthesis_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warning = ValidationIssue("empty_result", "warning", "No rows.")
    validated = _validated_result("valid_with_warnings", (warning,))
    synthesis = AnswerSynthesis("success", "value", ("No rows.",))
    monkeypatch.setattr(
        service_module,
        "answer_question_with_validation",
        lambda *args, **kwargs: validated,
    )
    monkeypatch.setattr(
        service_module,
        "synthesize_answer",
        lambda result, locale="en": synthesis,
    )

    final = answer_question_for_user("database.duckdb", "question", object())

    assert final.synthesis is synthesis
    assert final.synthesis.warnings == ("No rows.",)


def test_validation_service_and_synthesis_are_each_called_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validated = _validated_result()
    validation_calls = 0
    synthesis_calls = 0

    def fake_validation(*args: object, **kwargs: object) -> ValidatedQuestionResult:
        nonlocal validation_calls
        validation_calls += 1
        return validated

    def fake_synthesis(
        result: ValidatedQuestionResult,
        locale: str = "en",
    ) -> AnswerSynthesis:
        nonlocal synthesis_calls
        synthesis_calls += 1
        assert result is validated
        assert locale == "en"
        return AnswerSynthesis("success", "Result: 1", ())

    monkeypatch.setattr(
        service_module,
        "answer_question_with_validation",
        fake_validation,
    )
    monkeypatch.setattr(service_module, "synthesize_answer", fake_synthesis)

    answer_question_for_user("database.duckdb", "question", object())

    assert validation_calls == 1
    assert synthesis_calls == 1


def test_all_parameters_are_forwarded_transparently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validated = _validated_result()
    model = object()
    schema = DatabaseSchema(objects=())
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_validation(*args: object, **kwargs: object) -> ValidatedQuestionResult:
        observed.append((args, kwargs))
        return validated

    monkeypatch.setattr(
        service_module,
        "answer_question_with_validation",
        fake_validation,
    )
    monkeypatch.setattr(
        service_module,
        "synthesize_answer",
        lambda result, locale="en": AnswerSynthesis("success", "Result: 1", ()),
    )

    answer_question_for_user(
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


def test_existing_default_limits_are_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[dict[str, object]] = []

    def fake_validation(*args: object, **kwargs: object) -> ValidatedQuestionResult:
        observed.append(kwargs)
        return _validated_result()

    monkeypatch.setattr(
        service_module,
        "answer_question_with_validation",
        fake_validation,
    )
    monkeypatch.setattr(
        service_module,
        "synthesize_answer",
        lambda result, locale="en": AnswerSynthesis("success", "Result: 1", ()),
    )

    answer_question_for_user("database.duckdb", "question", object())

    assert observed == [
        {
            "max_rows": DEFAULT_MAX_ROWS,
            "analysis_max_rows": ANALYSIS_MAX_ROWS,
            "schema": None,
        }
    ]


def test_final_answer_result_is_frozen() -> None:
    final = FinalAnswerResult(
        validated_result=_validated_result(),
        synthesis=AnswerSynthesis("success", "Result: 1", ()),
    )

    with pytest.raises(FrozenInstanceError):
        final.synthesis = AnswerSynthesis("blocked", "Blocked.", ())


def test_wrapper_does_not_modify_input_or_synthesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validated = _validated_result()
    synthesis = AnswerSynthesis("success", "Result: 1", ("warning",))
    validated_before = repr(validated)
    synthesis_before = repr(synthesis)
    monkeypatch.setattr(
        service_module,
        "answer_question_with_validation",
        lambda *args, **kwargs: validated,
    )
    monkeypatch.setattr(
        service_module,
        "synthesize_answer",
        lambda result, locale="en": synthesis,
    )

    final = answer_question_for_user("database.duckdb", "question", object())

    assert final.validated_result is validated
    assert final.synthesis is synthesis
    assert repr(validated) == validated_before
    assert repr(synthesis) == synthesis_before


def test_wrapper_does_not_make_an_additional_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_calls = 0

    def model(prompt: str) -> str:
        nonlocal model_calls
        model_calls += 1
        return prompt

    def fake_validation(
        database_path: str | Path,
        question: str,
        received_model: object,
        **kwargs: object,
    ) -> ValidatedQuestionResult:
        del database_path, question, kwargs
        received_model("validation-service-owned call")
        return _validated_result()

    monkeypatch.setattr(
        service_module,
        "answer_question_with_validation",
        fake_validation,
    )
    monkeypatch.setattr(
        service_module,
        "synthesize_answer",
        lambda result, locale="en": AnswerSynthesis("success", "Result: 1", ()),
    )

    answer_question_for_user("database.duckdb", "question", model)

    assert model_calls == 1


def test_wrapper_does_not_execute_sql_or_python_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("final wrapper must not execute tools")

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
        "answer_question_with_validation",
        lambda *args, **kwargs: _validated_result(),
    )
    monkeypatch.setattr(
        service_module,
        "synthesize_answer",
        lambda result, locale="en": AnswerSynthesis("success", "Result: 1", ()),
    )

    final = answer_question_for_user("database.duckdb", "question", object())

    assert final.synthesis.status == "success"


def test_programming_exception_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_programming_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("programming error")

    monkeypatch.setattr(
        service_module,
        "answer_question_with_validation",
        raise_programming_error,
    )

    with pytest.raises(RuntimeError, match="programming error"):
        answer_question_for_user("database.duckdb", "question", object())


def test_zh_locale_is_passed_only_to_synthesis_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validated = _validated_result()
    validation_calls: list[dict[str, object]] = []
    synthesis_calls: list[tuple[ValidatedQuestionResult, str]] = []

    def validate(*args: object, **kwargs: object) -> ValidatedQuestionResult:
        validation_calls.append(kwargs)
        return validated

    def synthesize(
        result: ValidatedQuestionResult,
        locale: str = "en",
    ) -> AnswerSynthesis:
        synthesis_calls.append((result, locale))
        return AnswerSynthesis("success", "结果：1", ())

    monkeypatch.setattr(service_module, "answer_question_with_validation", validate)
    monkeypatch.setattr(service_module, "synthesize_answer", synthesize)

    final = answer_question_for_user(
        "database.duckdb",
        "问题",
        object(),
        locale="zh-CN",
    )

    assert len(validation_calls) == 1
    assert "locale" not in validation_calls[0]
    assert synthesis_calls == [(validated, "zh-CN")]
    assert final.synthesis.answer == "结果：1"
