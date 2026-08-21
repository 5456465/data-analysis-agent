"""Deterministic observability views over completed final-answer results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from data_analysis_agent.final_answer_service import FinalAnswerResult
from data_analysis_agent.multi_tool_service import MultiToolQuestionResult
from data_analysis_agent.python_analysis import (
    CorrelationResult,
    GrowthResult,
    PythonAnalysisResult,
)
from data_analysis_agent.question_service import QuestionAnswerResult
from data_analysis_agent.sql_executor import SQLResult


TraceStatus = Literal["success", "error", "warning", "skipped"]
TraceDetails = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class TraceStep:
    """One immutable stage assembled from existing execution evidence."""

    stage: str
    status: TraceStatus
    summary: str
    details: TraceDetails


@dataclass(frozen=True)
class ExecutionTrace:
    """Stable structured view of one completed question workflow."""

    question: str
    route: str | None
    python_operation: str | None
    steps: tuple[TraceStep, ...]


def build_execution_trace(final_result: FinalAnswerResult) -> ExecutionTrace:
    """Build a trace without executing tools or changing the final result."""

    if not isinstance(final_result, FinalAnswerResult):
        raise TypeError("final_result must be a FinalAnswerResult instance.")

    validated = final_result.validated_result
    result = validated.result
    steps = [_routing_step(result)]

    if result.route_decision.status == "success":
        if result.route_decision.route == "sql_only":
            steps.extend(_sql_only_steps(result))
        elif result.route_decision.route == "sql_then_python":
            steps.extend(_sql_then_python_steps(result))

    steps.append(_validation_step(final_result))
    steps.append(_synthesis_step(final_result))
    return ExecutionTrace(
        question=result.question,
        route=result.route_decision.route,
        python_operation=result.route_decision.python_operation,
        steps=tuple(steps),
    )


def format_execution_trace(trace: ExecutionTrace) -> str:
    """Format an existing trace without adding interpretation."""

    if not isinstance(trace, ExecutionTrace):
        raise TypeError("trace must be an ExecutionTrace instance.")

    blocks = []
    for step in trace.steps:
        lines = [
            f"{step.stage.replace('_', ' ').capitalize()} [{step.status}]",
            f"  summary: {step.summary}",
        ]
        lines.extend(f"  {key}: {value}" for key, value in step.details)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def _routing_step(result: MultiToolQuestionResult) -> TraceStep:
    decision = result.route_decision
    details: list[tuple[str, str]] = []
    if decision.route is not None:
        details.append(("route", decision.route))
    if decision.python_operation is not None:
        details.append(("python_operation", decision.python_operation))
    if decision.error is not None:
        details.extend(
            (
                ("error_code", decision.error.code),
                ("error_message", decision.error.message),
            )
        )
    return TraceStep(
        stage="routing",
        status="success" if decision.status == "success" else "error",
        summary=(
            "Routing completed."
            if decision.status == "success"
            else "Routing failed."
        ),
        details=tuple(details),
    )


def _sql_only_steps(result: MultiToolQuestionResult) -> tuple[TraceStep, ...]:
    answer = result.sql_answer_result
    if answer is None:
        return ()

    steps = [_sql_generation_step(answer)]
    if answer.repair_attempted:
        steps.append(_sql_repair_step(answer))

    sql_result = result.sql_result or answer.execution_result
    if sql_result is not None:
        steps.append(_sql_execution_step(sql_result))
    return tuple(steps)


def _sql_generation_step(answer: QuestionAnswerResult) -> TraceStep:
    generation_failed = answer.status == "generation_error"
    details: list[tuple[str, str]] = []
    if answer.generated_sql is not None:
        details.append(("generated_sql", answer.generated_sql))
    if answer.generation_error is not None:
        details.extend(
            (
                ("error_code", answer.generation_error.code),
                ("error_message", answer.generation_error.message),
            )
        )
    return TraceStep(
        "sql_generation",
        "error" if generation_failed else "success",
        "SQL generation failed." if generation_failed else "SQL generation completed.",
        tuple(details),
    )


def _sql_repair_step(answer: QuestionAnswerResult) -> TraceStep:
    repair_failed = answer.repair_error is not None or answer.repaired_sql is None
    details: list[tuple[str, str]] = [("repair_attempted", "True")]
    if answer.repaired_sql is not None:
        details.append(("repaired_sql", answer.repaired_sql))
    if answer.repair_error is not None:
        details.extend(
            (
                ("error_code", answer.repair_error.code),
                ("error_message", answer.repair_error.message),
            )
        )
    return TraceStep(
        "sql_repair",
        "error" if repair_failed else "success",
        "SQL repair failed." if repair_failed else "SQL repair completed.",
        tuple(details),
    )


def _sql_then_python_steps(
    result: MultiToolQuestionResult,
) -> tuple[TraceStep, ...]:
    steps: list[TraceStep] = []
    plan = result.analysis_plan
    if plan is not None:
        details: list[tuple[str, str]] = [
            ("python_operation", plan.python_operation)
        ]
        if plan.sql is not None:
            details.append(("planner_sql", plan.sql))
        if plan.python_columns:
            details.append(("python_columns", ", ".join(plan.python_columns)))
        if plan.error is not None:
            details.extend(
                (
                    ("error_code", plan.error.code),
                    ("error_message", plan.error.message),
                )
            )
        steps.append(
            TraceStep(
                "planning",
                "success" if plan.status == "success" else "error",
                (
                    "Analysis planning completed."
                    if plan.status == "success"
                    else "Analysis planning failed."
                ),
                tuple(details),
            )
        )

    if result.sql_result is not None:
        steps.append(_sql_execution_step(result.sql_result))
    if result.python_result is not None:
        steps.append(_python_analysis_step(result.python_result))
    return tuple(steps)


def _sql_execution_step(result: SQLResult) -> TraceStep:
    details: list[tuple[str, str]] = [
        ("returned_row_count", str(result.returned_row_count)),
        ("truncated", str(result.truncated)),
        ("columns", ", ".join(result.columns)),
    ]
    if result.error is not None:
        details.extend(
            (
                ("error_code", result.error.code),
                ("error_message", result.error.message),
            )
        )
    return TraceStep(
        "sql_execution",
        "success" if result.status == "success" else "error",
        (
            "SQL execution completed."
            if result.status == "success"
            else "SQL execution failed."
        ),
        tuple(details),
    )


def _python_analysis_step(result: PythonAnalysisResult) -> TraceStep:
    details: list[tuple[str, str]] = [("operation", result.operation)]
    payload = result.result
    if payload is not None:
        details.append(("payload_type", type(payload).__name__))
        if isinstance(payload, GrowthResult):
            details.append(("period_count", str(payload.period_count)))
        elif isinstance(payload, tuple):
            details.append(("description_count", str(len(payload))))
        elif isinstance(payload, CorrelationResult):
            details.append(("paired_count", str(payload.paired_count)))
    if result.error is not None:
        details.extend(
            (
                ("error_code", result.error.code),
                ("error_message", result.error.message),
            )
        )
    return TraceStep(
        "python_analysis",
        "success" if result.status == "success" else "error",
        (
            "Python analysis completed."
            if result.status == "success"
            else "Python analysis failed."
        ),
        tuple(details),
    )


def _validation_step(final_result: FinalAnswerResult) -> TraceStep:
    validation = final_result.validated_result.validation
    status_by_validation = {
        "valid": "success",
        "valid_with_warnings": "warning",
        "invalid": "error",
    }
    details: list[tuple[str, str]] = [
        ("validation_status", validation.status),
        ("issue_count", str(len(validation.issues))),
    ]
    details.extend(
        (
            f"issue_{index}",
            f"{issue.code} | {issue.severity} | {issue.message}",
        )
        for index, issue in enumerate(validation.issues, start=1)
    )
    return TraceStep(
        "validation",
        status_by_validation[validation.status],
        "Result validation completed.",
        tuple(details),
    )


def _synthesis_step(final_result: FinalAnswerResult) -> TraceStep:
    synthesis = final_result.synthesis
    return TraceStep(
        "answer_synthesis",
        "success" if synthesis.status == "success" else "error",
        (
            "Answer synthesis completed."
            if synthesis.status == "success"
            else "Answer synthesis was blocked."
        ),
        (
            ("synthesis_status", synthesis.status),
            ("warning_count", str(len(synthesis.warnings))),
        ),
    )
