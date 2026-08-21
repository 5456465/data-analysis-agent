"""Optional LangGraph orchestration over the existing deterministic services."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from data_analysis_agent.analysis_planner import (
    PythonAnalysisPlan,
    generate_python_analysis_plan,
)
from data_analysis_agent.answer_synthesis import AnswerSynthesis, synthesize_answer
from data_analysis_agent.final_answer_service import FinalAnswerResult
from data_analysis_agent.multi_tool_service import (
    ANALYSIS_MAX_ROWS,
    MultiToolQuestionError,
    MultiToolQuestionResult,
    _error_result,
    _sql_answer_error,
)
from data_analysis_agent.python_analysis import (
    PythonAnalysisRequest,
    PythonAnalysisResult,
    run_python_analysis,
)
from data_analysis_agent.question_service import QuestionAnswerResult, answer_question
from data_analysis_agent.result_validation import (
    ResultValidation,
    validate_multi_tool_result,
)
from data_analysis_agent.schema import DatabaseSchema, inspect_schema
from data_analysis_agent.sql_executor import (
    DEFAULT_MAX_ROWS,
    SQLResult,
    run_readonly_sql,
)
from data_analysis_agent.sql_generator import TextToSQLModel
from data_analysis_agent.tool_router import ToolRouteDecision, route_question
from data_analysis_agent.validated_question_service import ValidatedQuestionResult


class AgentGraphState(TypedDict, total=False):
    """Inputs and existing structured results carried between graph nodes."""

    question: str
    database_path: str | Path
    model: TextToSQLModel
    max_rows: int
    analysis_max_rows: int
    schema: DatabaseSchema
    route_decision: ToolRouteDecision
    sql_answer_result: QuestionAnswerResult
    analysis_plan: PythonAnalysisPlan
    sql_result: SQLResult
    python_result: PythonAnalysisResult
    multi_tool_result: MultiToolQuestionResult
    validation: ResultValidation
    validated_result: ValidatedQuestionResult
    synthesis: AnswerSynthesis


class CompiledAgentGraph(Protocol):
    """Minimal compiled-graph interface used by the public entry point."""

    def invoke(self, input: AgentGraphState) -> AgentGraphState: ...


def build_agent_graph() -> CompiledAgentGraph:
    """Compile the optional state graph without persistence or retry features."""

    graph = StateGraph(AgentGraphState)
    graph.add_node("route", _route_node)
    graph.add_node("sql_only", _sql_only_node)
    graph.add_node("plan", _plan_node)
    graph.add_node("analysis_sql", _analysis_sql_node)
    graph.add_node("python_analysis", _python_analysis_node)
    graph.add_node("finalize_execution", _finalize_execution_node)
    graph.add_node("validate", _validate_node)
    graph.add_node("synthesize", _synthesize_node)

    graph.add_edge(START, "route")
    graph.add_conditional_edges(
        "route",
        _route_branch,
        {
            "sql_only": "sql_only",
            "sql_then_python": "plan",
            "finalize_execution": "finalize_execution",
        },
    )
    graph.add_edge("sql_only", "finalize_execution")
    graph.add_conditional_edges(
        "plan",
        _plan_branch,
        {
            "analysis_sql": "analysis_sql",
            "finalize_execution": "finalize_execution",
        },
    )
    graph.add_conditional_edges(
        "analysis_sql",
        _analysis_sql_branch,
        {
            "python_analysis": "python_analysis",
            "finalize_execution": "finalize_execution",
        },
    )
    graph.add_edge("python_analysis", "finalize_execution")
    graph.add_edge("finalize_execution", "validate")
    graph.add_edge("validate", "synthesize")
    graph.add_edge("synthesize", END)
    return cast(CompiledAgentGraph, graph.compile())


def answer_question_with_langgraph(
    database_path: str | Path,
    question: str,
    model: TextToSQLModel,
    max_rows: int = DEFAULT_MAX_ROWS,
    *,
    analysis_max_rows: int = ANALYSIS_MAX_ROWS,
    schema: DatabaseSchema | None = None,
) -> FinalAnswerResult:
    """Run the existing services through the optional LangGraph workflow."""

    database_schema = schema if schema is not None else inspect_schema(database_path)
    final_state = build_agent_graph().invoke(
        AgentGraphState(
            question=question,
            database_path=database_path,
            model=model,
            max_rows=max_rows,
            analysis_max_rows=analysis_max_rows,
            schema=database_schema,
        )
    )
    return FinalAnswerResult(
        validated_result=final_state["validated_result"],
        synthesis=final_state["synthesis"],
    )


def _route_node(state: AgentGraphState) -> AgentGraphState:
    return {
        "route_decision": route_question(state["question"], state["model"]),
    }


def _route_branch(
    state: AgentGraphState,
) -> Literal["sql_only", "sql_then_python", "finalize_execution"]:
    decision = state["route_decision"]
    if decision.status == "error":
        return "finalize_execution"
    return cast(Literal["sql_only", "sql_then_python"], decision.route)


def _sql_only_node(state: AgentGraphState) -> AgentGraphState:
    answer = answer_question(
        state["database_path"],
        state["question"],
        state["model"],
        max_rows=state["max_rows"],
        schema=state["schema"],
    )
    update: AgentGraphState = {"sql_answer_result": answer}
    if answer.execution_result is not None:
        update["sql_result"] = answer.execution_result
    return update


def _plan_node(state: AgentGraphState) -> AgentGraphState:
    operation = cast(str, state["route_decision"].python_operation)
    return {
        "analysis_plan": generate_python_analysis_plan(
            state["question"],
            state["schema"],
            operation,
            state["model"],
        )
    }


def _plan_branch(
    state: AgentGraphState,
) -> Literal["analysis_sql", "finalize_execution"]:
    if state["analysis_plan"].status == "error":
        return "finalize_execution"
    return "analysis_sql"


def _analysis_sql_node(state: AgentGraphState) -> AgentGraphState:
    sql = cast(str, state["analysis_plan"].sql)
    return {
        "sql_result": run_readonly_sql(
            state["database_path"],
            sql,
            max_rows=state["analysis_max_rows"],
        )
    }


def _analysis_sql_branch(
    state: AgentGraphState,
) -> Literal["python_analysis", "finalize_execution"]:
    sql_result = state["sql_result"]
    if sql_result.status == "error" or sql_result.truncated:
        return "finalize_execution"
    return "python_analysis"


def _python_analysis_node(state: AgentGraphState) -> AgentGraphState:
    plan = state["analysis_plan"]
    sql_result = state["sql_result"]
    request = PythonAnalysisRequest(
        operation=plan.python_operation,
        columns=plan.python_columns,
    )
    return {
        "python_result": run_python_analysis(
            columns=sql_result.columns,
            rows=sql_result.rows,
            request=request,
        )
    }


def _finalize_execution_node(state: AgentGraphState) -> AgentGraphState:
    decision = state["route_decision"]
    if decision.status == "error":
        message = (
            decision.error.message
            if decision.error is not None
            else "Tool routing failed without a structured error."
        )
        result = _error_result(
            decision.question,
            decision,
            "routing_error",
            message,
        )
    elif decision.route == "sql_only":
        result = _finalize_sql_only(state, decision)
    else:
        result = _finalize_sql_then_python(state, decision)
    return {"multi_tool_result": result}


def _finalize_sql_only(
    state: AgentGraphState,
    decision: ToolRouteDecision,
) -> MultiToolQuestionResult:
    answer = state["sql_answer_result"]
    if answer.status == "success":
        return MultiToolQuestionResult(
            question=answer.question,
            route_decision=decision,
            status="success",
            sql_answer_result=answer,
            analysis_plan=None,
            sql_result=answer.execution_result,
            python_result=None,
            error=None,
        )

    error_code, message = _sql_answer_error(answer)
    return MultiToolQuestionResult(
        question=answer.question,
        route_decision=decision,
        status=error_code,
        sql_answer_result=answer,
        analysis_plan=None,
        sql_result=answer.execution_result,
        python_result=None,
        error=MultiToolQuestionError(error_code, message),
    )


def _finalize_sql_then_python(
    state: AgentGraphState,
    decision: ToolRouteDecision,
) -> MultiToolQuestionResult:
    plan = state["analysis_plan"]
    if plan.status == "error":
        message = (
            plan.error.message
            if plan.error is not None
            else "Python analysis planning failed without a structured error."
        )
        return _error_result(
            plan.question,
            decision,
            "planning_error",
            message,
            analysis_plan=plan,
        )

    sql_result = state["sql_result"]
    if sql_result.status == "error":
        message = (
            sql_result.error.message
            if sql_result.error is not None
            else "Analysis SQL execution failed without a structured error."
        )
        return _error_result(
            plan.question,
            decision,
            "sql_execution_error",
            message,
            analysis_plan=plan,
            sql_result=sql_result,
        )
    if sql_result.truncated:
        return _error_result(
            plan.question,
            decision,
            "truncated_analysis_input",
            "SQL result exceeded the allowed row limit, so Python analysis was "
            "not executed because statistics over truncated data would be misleading.",
            analysis_plan=plan,
            sql_result=sql_result,
        )

    python_result = state["python_result"]
    if python_result.status == "error":
        message = (
            python_result.error.message
            if python_result.error is not None
            else "Python analysis failed without a structured error."
        )
        return _error_result(
            plan.question,
            decision,
            "python_analysis_error",
            message,
            analysis_plan=plan,
            sql_result=sql_result,
            python_result=python_result,
        )

    return MultiToolQuestionResult(
        question=plan.question,
        route_decision=decision,
        status="success",
        sql_answer_result=None,
        analysis_plan=plan,
        sql_result=sql_result,
        python_result=python_result,
        error=None,
    )


def _validate_node(state: AgentGraphState) -> AgentGraphState:
    validation = validate_multi_tool_result(state["multi_tool_result"])
    return {"validation": validation}


def _synthesize_node(state: AgentGraphState) -> AgentGraphState:
    validated_result = ValidatedQuestionResult(
        result=state["multi_tool_result"],
        validation=state["validation"],
    )
    return {
        "validated_result": validated_result,
        "synthesis": synthesize_answer(validated_result),
    }
