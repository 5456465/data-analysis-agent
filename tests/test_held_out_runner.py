from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import data_analysis_agent.held_out_runner as runner_module
from data_analysis_agent.held_out_evaluator import HeldOutCaseEvaluation
from data_analysis_agent.held_out_runner import (
    format_held_out_report,
    run_held_out_evaluation,
)
from data_analysis_agent.multi_tool_service import MultiToolQuestionResult
from data_analysis_agent.multi_tool_test_questions import MultiToolTestQuestion
from data_analysis_agent.tool_router import ToolRouteDecision


def _question(number: int, *, category: str = "sql_only") -> MultiToolTestQuestion:
    answerable = category in {"sql_only", "calculate_growth"}
    growth = category == "calculate_growth"
    return MultiToolTestQuestion(
        id=f"MTQ-TEST-{number:03d}",
        question=f"User-only question {number}?",
        category=category,
        expected_disposition="answer" if answerable else "reject",
        expected_route=("sql_then_python" if growth else "sql_only")
        if answerable
        else None,
        expected_python_operation="calculate_growth" if growth else None,
        metric_definition=f"SECRET METRIC {number}",
        expected_grain=f"SECRET GRAIN {number}",
        expected_tables=(f"secret_table_{number}",) if answerable else (),
        reference_sql=f"SELECT {number} AS secret_reference_{number}"
        if answerable
        else None,
        python_columns=("month", "value") if growth else (),
        unanswerable_reason=None if answerable else f"SECRET REASON {number}",
        notes=f"SECRET NOTES {number}",
    )


def _actual(question: str, *, route: str = "sql_only") -> MultiToolQuestionResult:
    operation = "calculate_growth" if route == "sql_then_python" else None
    return MultiToolQuestionResult(
        question=question,
        route_decision=ToolRouteDecision(
            question=question,
            route=route,
            python_operation=operation,
            reason="scripted",
            status="success",
            error=None,
        ),
        status="success",
        sql_answer_result=None,
        analysis_plan=None,
        sql_result=None,
        python_result=None,
        error=None,
    )


def _evaluation(
    question: MultiToolTestQuestion,
    actual: MultiToolQuestionResult,
    *,
    passed: bool = True,
) -> HeldOutCaseEvaluation:
    expected_answer = question.expected_disposition == "answer"
    return HeldOutCaseEvaluation(
        question_id=question.id,
        category=question.category,
        expected_disposition=question.expected_disposition,
        actual_disposition="answer" if expected_answer else "reject",
        disposition_correct=True,
        expected_route=question.expected_route,
        actual_route=actual.route_decision.route,
        route_correct=passed if expected_answer else None,
        expected_python_operation=question.expected_python_operation,
        actual_python_operation=actual.route_decision.python_operation,
        operation_correct=passed if expected_answer else None,
        semantic_correct=passed if expected_answer else None,
        passed=passed,
        failure_reason=None if passed else "scripted failure",
    )


def _install_scripted_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    answer_calls: list[str],
    evaluation_calls: list[str],
) -> None:
    def fake_answer(
        database_path: str | Path,
        question: str,
        model: object,
    ) -> MultiToolQuestionResult:
        del database_path, model
        answer_calls.append(question)
        return _actual(question)

    def fake_evaluate(
        question: MultiToolTestQuestion,
        actual: MultiToolQuestionResult,
        database_path: str | Path,
    ) -> HeldOutCaseEvaluation:
        del database_path
        evaluation_calls.append(question.id)
        return _evaluation(question, actual)

    monkeypatch.setattr(runner_module, "answer_question_with_tools", fake_answer)
    monkeypatch.setattr(runner_module, "evaluate_held_out_case", fake_evaluate)


def test_runner_executes_questions_once_in_supplied_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    questions = (_question(1), _question(2), _question(3))
    answer_calls: list[str] = []
    evaluation_calls: list[str] = []
    _install_scripted_dependencies(
        monkeypatch,
        answer_calls=answer_calls,
        evaluation_calls=evaluation_calls,
    )

    result = run_held_out_evaluation("unused.duckdb", object(), questions)

    assert answer_calls == [question.question for question in questions]
    assert evaluation_calls == [question.id for question in questions]
    assert tuple(item.question for item in result.case_results if item is not None) == (
        tuple(question.question for question in questions)
    )
    assert tuple(item.question_id for item in result.evaluations) == tuple(
        question.id for question in questions
    )


def test_runner_passes_only_question_text_to_model_facing_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    questions = (_question(1), _question(2, category="capability_unsupported"))
    observed: list[tuple[object, ...]] = []

    def fake_answer(*args: object, **kwargs: object) -> MultiToolQuestionResult:
        observed.append((*args, kwargs))
        return _actual(str(args[1]))

    monkeypatch.setattr(runner_module, "answer_question_with_tools", fake_answer)
    monkeypatch.setattr(
        runner_module,
        "evaluate_held_out_case",
        lambda question, actual, database_path: _evaluation(question, actual),
    )

    model = object()
    run_held_out_evaluation("database.duckdb", model, questions)

    assert len(observed) == 2
    for call, question in zip(observed, questions, strict=True):
        assert call[:3] == ("database.duckdb", question.question, model)
        assert call[3] == {}
        serialized_call = repr(call)
        if question.reference_sql is not None:
            assert question.reference_sql not in serialized_call
        assert question.metric_definition not in serialized_call
        assert question.expected_grain not in serialized_call
        assert question.notes not in serialized_call
        assert repr(question.expected_tables) not in serialized_call
        assert repr(question.expected_route) not in serialized_call


def test_controlled_case_failure_does_not_stop_later_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    questions = (_question(1), _question(2), _question(3))
    answered: list[str] = []
    evaluated: list[str] = []

    def fake_answer(
        database_path: str | Path,
        question: str,
        model: object,
    ) -> MultiToolQuestionResult:
        del database_path, model
        answered.append(question)
        return _actual(question)

    def fake_evaluate(
        question: MultiToolTestQuestion,
        actual: MultiToolQuestionResult,
        database_path: str | Path,
    ) -> HeldOutCaseEvaluation:
        del database_path
        evaluated.append(question.id)
        return _evaluation(question, actual, passed=question.id != questions[1].id)

    monkeypatch.setattr(runner_module, "answer_question_with_tools", fake_answer)
    monkeypatch.setattr(runner_module, "evaluate_held_out_case", fake_evaluate)

    result = run_held_out_evaluation("unused.duckdb", object(), questions)

    assert answered == [question.question for question in questions]
    assert evaluated == [question.id for question in questions]
    assert (result.summary.total, result.summary.passed, result.summary.failed) == (
        3,
        2,
        1,
    )


@pytest.mark.parametrize("exception_stage", ["agent", "evaluation"])
def test_unhandled_case_exception_is_recorded_without_retry_and_run_continues(
    monkeypatch: pytest.MonkeyPatch,
    exception_stage: str,
) -> None:
    questions = (_question(1), _question(2))
    answer_counts = {question.question: 0 for question in questions}
    evaluated: list[str] = []

    def fake_answer(
        database_path: str | Path,
        question: str,
        model: object,
    ) -> MultiToolQuestionResult:
        del database_path, model
        answer_counts[question] += 1
        if exception_stage == "agent" and question == questions[0].question:
            raise RuntimeError("scripted agent failure")
        return _actual(question)

    def fake_evaluate(
        question: MultiToolTestQuestion,
        actual: MultiToolQuestionResult,
        database_path: str | Path,
    ) -> HeldOutCaseEvaluation:
        del database_path
        evaluated.append(question.id)
        if exception_stage == "evaluation" and question.id == questions[0].id:
            raise RuntimeError("scripted evaluation failure")
        return _evaluation(question, actual)

    monkeypatch.setattr(runner_module, "answer_question_with_tools", fake_answer)
    monkeypatch.setattr(runner_module, "evaluate_held_out_case", fake_evaluate)

    result = run_held_out_evaluation("unused.duckdb", object(), questions)

    assert answer_counts == {question.question: 1 for question in questions}
    assert result.summary.total == 2
    assert result.summary.failed == 1
    assert result.run_failures[0].question_id == questions[0].id
    assert result.run_failures[0].stage == exception_stage
    assert result.evaluations[0].actual_disposition == "unknown"
    assert result.evaluations[1].passed is True


def test_summary_covers_every_case_and_all_categories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    questions = (
        _question(1),
        _question(2, category="calculate_growth"),
        _question(3, category="data_unanswerable"),
        _question(4, category="capability_unsupported"),
    )

    def fake_answer(
        database_path: str | Path,
        question: str,
        model: object,
    ) -> MultiToolQuestionResult:
        del database_path, model
        contract = next(item for item in questions if item.question == question)
        route = contract.expected_route or "sql_only"
        return _actual(question, route=route)

    monkeypatch.setattr(runner_module, "answer_question_with_tools", fake_answer)
    monkeypatch.setattr(
        runner_module,
        "evaluate_held_out_case",
        lambda question, actual, database_path: _evaluation(question, actual),
    )

    summary = run_held_out_evaluation(
        "unused.duckdb",
        object(),
        questions,
    ).summary

    assert (summary.total, summary.passed, summary.failed) == (4, 4, 0)
    assert (summary.sql_only_passed, summary.sql_only_total) == (1, 1)
    assert (summary.calculate_growth_passed, summary.calculate_growth_total) == (1, 1)
    assert (summary.data_unanswerable_passed, summary.data_unanswerable_total) == (1, 1)
    assert (
        summary.capability_unsupported_passed,
        summary.capability_unsupported_total,
    ) == (1, 1)


def test_report_contains_summary_and_case_results_without_frozen_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    questions = (_question(1), _question(2))
    monkeypatch.setattr(
        runner_module,
        "answer_question_with_tools",
        lambda database_path, question, model: _actual(question),
    )
    monkeypatch.setattr(
        runner_module,
        "evaluate_held_out_case",
        lambda question, actual, database_path: _evaluation(
            question,
            actual,
            passed=question.id == questions[0].id,
        ),
    )

    report = format_held_out_report(
        run_held_out_evaluation("unused.duckdb", object(), questions)
    )

    assert "Total: 2" in report
    assert "Passed: 1" in report
    assert "Failed: 1" in report
    assert "Overall pass rate: 50.00%" in report
    assert "Disposition accuracy: 100.00%" in report
    assert "Route accuracy: 50.00%" in report
    assert "Operation accuracy: 50.00%" in report
    assert "Semantic accuracy: 50.00%" in report
    assert "SQL_ONLY: 1 / 2" in report
    assert "Result: PASS" in report
    assert "Result: FAIL" in report
    for question in questions:
        assert f"ID: {question.id}" in report
        assert question.reference_sql not in report
        assert question.metric_definition not in report
        assert question.notes not in report


def test_report_does_not_include_model_secret_or_environment_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question = _question(1)
    answer_calls: list[str] = []
    evaluation_calls: list[str] = []
    _install_scripted_dependencies(
        monkeypatch,
        answer_calls=answer_calls,
        evaluation_calls=evaluation_calls,
    )
    secret_model = {"DEEPSEEK_API_KEY": "super-secret-test-key"}

    report = format_held_out_report(
        run_held_out_evaluation("unused.duckdb", secret_model, (question,))
    )

    assert "DEEPSEEK_API_KEY" not in report
    assert "super-secret-test-key" not in report
    assert ".env" not in report


def test_runner_does_not_mutate_questions_or_actual_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    questions = (_question(1), _question(2))
    actuals = {question.question: _actual(question.question) for question in questions}
    questions_before = repr(questions)
    actuals_before = repr(actuals)

    monkeypatch.setattr(
        runner_module,
        "answer_question_with_tools",
        lambda database_path, question, model: actuals[question],
    )
    monkeypatch.setattr(
        runner_module,
        "evaluate_held_out_case",
        lambda question, actual, database_path: _evaluation(question, actual),
    )

    result = run_held_out_evaluation("unused.duckdb", object(), questions)

    assert repr(questions) == questions_before
    assert repr(actuals) == actuals_before
    with pytest.raises(FrozenInstanceError):
        result.summary = result.summary
