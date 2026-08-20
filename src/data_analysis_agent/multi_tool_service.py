"""Backward-compatible orchestration across SQL and controlled Python tools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from data_analysis_agent.analysis_planner import (
    PythonAnalysisPlan,
    generate_python_analysis_plan,
)
from data_analysis_agent.python_analysis import (
    PythonAnalysisRequest,
    PythonAnalysisResult,
    run_python_analysis,
)
from data_analysis_agent.question_service import QuestionAnswerResult, answer_question
from data_analysis_agent.schema import DatabaseSchema, inspect_schema
from data_analysis_agent.sql_executor import (
    DEFAULT_MAX_ROWS,
    SQLResult,
    run_readonly_sql,
)
from data_analysis_agent.sql_generator import TextToSQLModel
from data_analysis_agent.tool_router import ToolRouteDecision, route_question


ANALYSIS_MAX_ROWS = 150_000

MultiToolStatus = Literal[
    "success",
    "routing_error",
    "planning_error",
    "sql_generation_error",
    "sql_repair_error",
    "sql_execution_error",
    "truncated_analysis_input",
    "python_analysis_error",
]
MultiToolErrorCode = Literal[
    "routing_error",
    "planning_error",
    "sql_generation_error",
    "sql_repair_error",
    "sql_execution_error",
    "truncated_analysis_input",
    "python_analysis_error",
]


@dataclass(frozen=True)
class MultiToolQuestionError:
    """Stage-aware error from multi-tool orchestration."""

    code: MultiToolErrorCode
    message: str


@dataclass(frozen=True)
class MultiToolQuestionResult:
    """Unified structured result for either supported tool route."""

    question: str
    route_decision: ToolRouteDecision
    status: MultiToolStatus
    sql_answer_result: QuestionAnswerResult | None
    analysis_plan: PythonAnalysisPlan | None
    sql_result: SQLResult | None
    python_result: PythonAnalysisResult | None
    error: MultiToolQuestionError | None


def answer_question_with_tools(
    database_path: str | Path,
    question: str,
    model: TextToSQLModel,
    max_rows: int = DEFAULT_MAX_ROWS,
    *,
    analysis_max_rows: int = ANALYSIS_MAX_ROWS,
    schema: DatabaseSchema | None = None,
) -> MultiToolQuestionResult:
    """Route and execute one SQL-only or SQL-then-Python question."""

    database_schema = schema if schema is not None else inspect_schema(database_path)
    route_decision = route_question(question, model)
    if route_decision.status == "error":
        message = (
            route_decision.error.message
            if route_decision.error is not None
            else "Tool routing failed without a structured error."
        )
        return _error_result(
            route_decision.question,
            route_decision,
            "routing_error",
            message,
        )

    if route_decision.route == "sql_only":
        sql_answer = answer_question(
            database_path,
            question,
            model,
            max_rows=max_rows,
            schema=database_schema,
        )
        if sql_answer.status == "success":
            return MultiToolQuestionResult(
                question=sql_answer.question,
                route_decision=route_decision,
                status="success",
                sql_answer_result=sql_answer,
                analysis_plan=None,
                sql_result=sql_answer.execution_result,
                python_result=None,
                error=None,
            )

        error_code, message = _sql_answer_error(sql_answer)
        return MultiToolQuestionResult(
            question=sql_answer.question,
            route_decision=route_decision,
            status=error_code,
            sql_answer_result=sql_answer,
            analysis_plan=None,
            sql_result=sql_answer.execution_result,
            python_result=None,
            error=MultiToolQuestionError(error_code, message),
        )

    python_operation = cast(str, route_decision.python_operation)
    analysis_plan = generate_python_analysis_plan(
        question,
        database_schema,
        python_operation,
        model,
    )
    if analysis_plan.status == "error":
        message = (
            analysis_plan.error.message
            if analysis_plan.error is not None
            else "Python analysis planning failed without a structured error."
        )
        return _error_result(
            analysis_plan.question,
            route_decision,
            "planning_error",
            message,
            analysis_plan=analysis_plan,
        )

    sql = cast(str, analysis_plan.sql)
    sql_result = run_readonly_sql(
        database_path,
        sql,
        max_rows=analysis_max_rows,
    )
    if sql_result.status == "error":
        message = (
            sql_result.error.message
            if sql_result.error is not None
            else "Analysis SQL execution failed without a structured error."
        )
        return _error_result(
            analysis_plan.question,
            route_decision,
            "sql_execution_error",
            message,
            analysis_plan=analysis_plan,
            sql_result=sql_result,
        )

    if sql_result.truncated:
        return _error_result(
            analysis_plan.question,
            route_decision,
            "truncated_analysis_input",
            "SQL result exceeded the allowed row limit, so Python analysis was "
            "not executed because statistics over truncated data would be misleading.",
            analysis_plan=analysis_plan,
            sql_result=sql_result,
        )

    request = PythonAnalysisRequest(
        operation=analysis_plan.python_operation,
        columns=analysis_plan.python_columns,
    )
    python_result = run_python_analysis(
        columns=sql_result.columns,
        rows=sql_result.rows,
        request=request,
    )
    if python_result.status == "error":
        message = (
            python_result.error.message
            if python_result.error is not None
            else "Python analysis failed without a structured error."
        )
        return _error_result(
            analysis_plan.question,
            route_decision,
            "python_analysis_error",
            message,
            analysis_plan=analysis_plan,
            sql_result=sql_result,
            python_result=python_result,
        )

    return MultiToolQuestionResult(
        question=analysis_plan.question,
        route_decision=route_decision,
        status="success",
        sql_answer_result=None,
        analysis_plan=analysis_plan,
        sql_result=sql_result,
        python_result=python_result,
        error=None,
    )


def _sql_answer_error(
    result: QuestionAnswerResult,
) -> tuple[
    Literal[
        "sql_generation_error",
        "sql_repair_error",
        "sql_execution_error",
    ],
    str,
]:
    if result.status == "generation_error":
        message = (
            result.generation_error.message
            if result.generation_error is not None
            else "SQL generation failed without a structured error."
        )
        return "sql_generation_error", message
    if result.status == "repair_error":
        message = (
            result.repair_error.message
            if result.repair_error is not None
            else "SQL repair failed without a structured error."
        )
        return "sql_repair_error", message
    message = (
        result.execution_error.message
        if result.execution_error is not None
        else "SQL execution failed without a structured error."
    )
    return "sql_execution_error", message


def _error_result(
    question: str,
    route_decision: ToolRouteDecision,
    code: MultiToolErrorCode,
    message: str,
    *,
    analysis_plan: PythonAnalysisPlan | None = None,
    sql_result: SQLResult | None = None,
    python_result: PythonAnalysisResult | None = None,
) -> MultiToolQuestionResult:
    return MultiToolQuestionResult(
        question=question,
        route_decision=route_decision,
        status=code,
        sql_answer_result=None,
        analysis_plan=analysis_plan,
        sql_result=sql_result,
        python_result=python_result,
        error=MultiToolQuestionError(code=code, message=message),
    )
