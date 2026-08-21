"""Thin one-pass orchestration for frozen held-out multi-tool evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from data_analysis_agent.held_out_evaluator import (
    HeldOutCaseEvaluation,
    HeldOutEvaluationSummary,
    evaluate_held_out_case,
    summarize_held_out_evaluations,
)
from data_analysis_agent.multi_tool_service import (
    MultiToolQuestionResult,
    answer_question_with_tools,
)
from data_analysis_agent.multi_tool_test_questions import (
    MULTI_TOOL_TEST_QUESTIONS,
    MultiToolTestQuestion,
)
from data_analysis_agent.sql_generator import TextToSQLModel


@dataclass(frozen=True)
class HeldOutRunFailure:
    """One unexpected runner-level exception recorded without retrying."""

    question_id: str
    stage: Literal["agent", "evaluation"]
    error_type: str
    message: str


@dataclass(frozen=True)
class HeldOutRunResult:
    """Complete deterministic output from one held-out evaluation run."""

    case_results: tuple[MultiToolQuestionResult | None, ...]
    evaluations: tuple[HeldOutCaseEvaluation, ...]
    summary: HeldOutEvaluationSummary
    run_failures: tuple[HeldOutRunFailure, ...]


def run_held_out_evaluation(
    database_path: str | Path,
    model: TextToSQLModel,
    questions: Sequence[MultiToolTestQuestion] = MULTI_TOOL_TEST_QUESTIONS,
) -> HeldOutRunResult:
    """Run each supplied held-out question once, in its supplied order."""

    question_contracts = tuple(questions)
    if not all(
        isinstance(question, MultiToolTestQuestion)
        for question in question_contracts
    ):
        raise TypeError("questions must contain MultiToolTestQuestion instances.")

    case_results: list[MultiToolQuestionResult | None] = []
    evaluations: list[HeldOutCaseEvaluation] = []
    run_failures: list[HeldOutRunFailure] = []

    for question in question_contracts:
        try:
            actual = answer_question_with_tools(
                database_path,
                question.question,
                model,
            )
        except Exception as exc:
            case_results.append(None)
            run_failures.append(_run_failure(question.id, "agent", exc))
            evaluations.append(_exception_evaluation(question, "agent", exc))
            continue

        case_results.append(actual)
        try:
            evaluation = evaluate_held_out_case(
                question,
                actual,
                database_path,
            )
        except Exception as exc:
            run_failures.append(_run_failure(question.id, "evaluation", exc))
            evaluation = _exception_evaluation(question, "evaluation", exc)
        evaluations.append(evaluation)

    frozen_evaluations = tuple(evaluations)
    return HeldOutRunResult(
        case_results=tuple(case_results),
        evaluations=frozen_evaluations,
        summary=summarize_held_out_evaluations(frozen_evaluations),
        run_failures=tuple(run_failures),
    )


def format_held_out_report(result: HeldOutRunResult) -> str:
    """Format summary and case scores without exposing frozen references."""

    if not isinstance(result, HeldOutRunResult):
        raise TypeError("result must be a HeldOutRunResult instance.")

    summary = result.summary
    lines = [
        "Held-out Evaluation Summary",
        f"Total: {summary.total}",
        f"Passed: {summary.passed}",
        f"Failed: {summary.failed}",
        f"Overall pass rate: {_percentage(summary.passed, summary.total)}",
        f"Disposition accuracy: {_format_accuracy(summary.disposition_accuracy)}",
        f"Route accuracy: {_format_accuracy(summary.route_accuracy)}",
        f"Operation accuracy: {_format_accuracy(summary.operation_accuracy)}",
        f"Semantic accuracy: {_format_accuracy(summary.semantic_accuracy)}",
        f"SQL_ONLY: {summary.sql_only_passed} / {summary.sql_only_total}",
        (
            "calculate_growth: "
            f"{summary.calculate_growth_passed} / "
            f"{summary.calculate_growth_total}"
        ),
        (
            "data_unanswerable: "
            f"{summary.data_unanswerable_passed} / "
            f"{summary.data_unanswerable_total}"
        ),
        (
            "capability_unsupported: "
            f"{summary.capability_unsupported_passed} / "
            f"{summary.capability_unsupported_total}"
        ),
        "",
        "Cases",
    ]

    for evaluation in result.evaluations:
        lines.extend(
            (
                f"ID: {evaluation.question_id}",
                f"Category: {evaluation.category}",
                f"Result: {'PASS' if evaluation.passed else 'FAIL'}",
                f"Actual disposition: {evaluation.actual_disposition}",
                (
                    "Route: "
                    f"{evaluation.expected_route} -> {evaluation.actual_route}"
                ),
                (
                    "Operation: "
                    f"{evaluation.expected_python_operation} -> "
                    f"{evaluation.actual_python_operation}"
                ),
                f"Semantic correct: {evaluation.semantic_correct}",
                f"Failure reason: {evaluation.failure_reason}",
                "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def _run_failure(
    question_id: str,
    stage: Literal["agent", "evaluation"],
    exc: Exception,
) -> HeldOutRunFailure:
    return HeldOutRunFailure(
        question_id=question_id,
        stage=stage,
        error_type=type(exc).__name__,
        message=str(exc),
    )


def _exception_evaluation(
    question: MultiToolTestQuestion,
    stage: Literal["agent", "evaluation"],
    exc: Exception,
) -> HeldOutCaseEvaluation:
    answerable = question.expected_disposition == "answer"
    return HeldOutCaseEvaluation(
        question_id=question.id,
        category=question.category,
        expected_disposition=question.expected_disposition,
        actual_disposition="unknown",
        disposition_correct=False,
        expected_route=question.expected_route,
        actual_route=None,
        route_correct=False if answerable else None,
        expected_python_operation=question.expected_python_operation,
        actual_python_operation=None,
        operation_correct=False if answerable else None,
        semantic_correct=False if answerable else None,
        passed=False,
        failure_reason=f"unhandled {stage} exception: {type(exc).__name__}",
    )


def _format_accuracy(value: float) -> str:
    return f"{100.0 * value:.2f}%"


def _percentage(numerator: int, denominator: int) -> str:
    return _format_accuracy(numerator / denominator if denominator else 0.0)
