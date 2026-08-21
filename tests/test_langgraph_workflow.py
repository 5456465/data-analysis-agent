"""Deterministic tests for the optional LangGraph orchestration spike."""

from __future__ import annotations

from pathlib import Path

import pytest

import data_analysis_agent.langgraph_workflow as workflow
import data_analysis_agent.multi_tool_service as explicit_workflow
from data_analysis_agent.analysis_planner import (
    PythonAnalysisPlan,
    PythonAnalysisPlanError,
)
from data_analysis_agent.final_answer_service import FinalAnswerResult
from data_analysis_agent.python_analysis import (
    ColumnDescription,
    PythonAnalysisError,
    PythonAnalysisResult,
)
from data_analysis_agent.question_service import QuestionAnswerResult
from data_analysis_agent.schema import DatabaseSchema
from data_analysis_agent.sql_executor import SQLExecutionError, SQLResult
from data_analysis_agent.sql_generator import SQLGenerationError
from data_analysis_agent.sql_repair import SQLRepairError
from data_analysis_agent.tool_router import (
    ToolRouteDecision,
    ToolRoutingError,
)


QUESTION = "Test question"
DATABASE_PATH = Path("test.duckdb")
SCHEMA = DatabaseSchema(objects=())


def _model(prompt: str) -> dict[str, object]:
    raise AssertionError(f"Unexpected model call: {prompt}")


def _route(
    route: str = "sql_only",
    operation: str | None = None,
) -> ToolRouteDecision:
    return ToolRouteDecision(
        question=QUESTION,
        route=route,
        python_operation=operation,
        reason="deterministic test route",
        status="success",
        error=None,
    )


def _routing_error() -> ToolRouteDecision:
    return ToolRouteDecision(
        question=QUESTION,
        route=None,
        python_operation=None,
        reason=None,
        status="error",
        error=ToolRoutingError("unsupported_route", "Unsupported request."),
    )


def _sql_result(
    *,
    status: str = "success",
    truncated: bool = False,
) -> SQLResult:
    return SQLResult(
        executed_sql="SELECT value FROM facts",
        columns=("value",),
        rows=((1.0,), (2.0,)) if status == "success" else (),
        returned_row_count=2 if status == "success" else 0,
        truncated=truncated,
        status=status,
        error=(
            SQLExecutionError("execution_error", "SQL failed.")
            if status == "error"
            else None
        ),
    )


def _sql_answer(
    status: str = "success",
) -> QuestionAnswerResult:
    execution_result = _sql_result(status="error" if status == "execution_error" else "success")
    return QuestionAnswerResult(
        question=QUESTION,
        generated_sql="SELECT value FROM facts",
        status=status,
        execution_result=(
            execution_result if status in {"success", "execution_error", "repair_error"} else None
        ),
        generation_error=(
            SQLGenerationError("cannot_generate", "Cannot generate SQL.")
            if status == "generation_error"
            else None
        ),
        execution_error=(
            SQLExecutionError("execution_error", "SQL failed.")
            if status in {"execution_error", "repair_error"}
            else None
        ),
        repair_attempted=status == "repair_error",
        repair_error=(
            SQLRepairError("cannot_repair", "Cannot repair SQL.")
            if status == "repair_error"
            else None
        ),
    )


def _plan(status: str = "success") -> PythonAnalysisPlan:
    return PythonAnalysisPlan(
        question=QUESTION,
        python_operation="describe",
        sql="SELECT value FROM facts" if status == "success" else None,
        python_columns=("value",) if status == "success" else (),
        status=status,
        error=(
            PythonAnalysisPlanError("invalid_analysis_plan", "Planning failed.")
            if status == "error"
            else None
        ),
    )


def _python_result(status: str = "success") -> PythonAnalysisResult:
    return PythonAnalysisResult(
        operation="describe",
        status=status,
        result=(
            (
                ColumnDescription(
                    column="value",
                    count=2,
                    mean=1.5,
                    std=0.7071067811865476,
                    min=1.0,
                    median=1.5,
                    max=2.0,
                ),
            )
            if status == "success"
            else None
        ),
        error=(
            PythonAnalysisError("insufficient_data", "Python analysis failed.")
            if status == "error"
            else None
        ),
    )


def _unexpected(*args: object, **kwargs: object) -> object:
    raise AssertionError("This dependency must not be called on this graph path.")


def _patch_route(
    monkeypatch: pytest.MonkeyPatch,
    decision: ToolRouteDecision,
) -> None:
    monkeypatch.setattr(workflow, "route_question", lambda question, model: decision)


def _invoke(schema: DatabaseSchema = SCHEMA) -> FinalAnswerResult:
    return workflow.answer_question_with_langgraph(
        DATABASE_PATH,
        QUESTION,
        _model,
        schema=schema,
    )


def test_graph_compiles_with_expected_nodes() -> None:
    graph = workflow.build_agent_graph().get_graph()

    assert {
        "route",
        "sql_only",
        "plan",
        "analysis_sql",
        "python_analysis",
        "finalize_execution",
        "validate",
        "synthesize",
    }.issubset(graph.nodes)


def test_sql_only_success_uses_only_sql_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    _patch_route(monkeypatch, _route())
    monkeypatch.setattr(
        workflow,
        "answer_question",
        lambda *args, **kwargs: events.append("sql_only") or _sql_answer(),
    )
    monkeypatch.setattr(workflow, "generate_python_analysis_plan", _unexpected)
    monkeypatch.setattr(workflow, "run_readonly_sql", _unexpected)
    monkeypatch.setattr(workflow, "run_python_analysis", _unexpected)

    result = _invoke()

    assert result.validated_result.result.status == "success"
    assert result.validated_result.result.route_decision.route == "sql_only"
    assert result.synthesis.status == "success"
    assert events == ["sql_only"]


def test_sql_then_python_success_uses_plan_sql_and_python_nodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    _patch_route(monkeypatch, _route("sql_then_python", "describe"))
    monkeypatch.setattr(workflow, "answer_question", _unexpected)
    monkeypatch.setattr(
        workflow,
        "generate_python_analysis_plan",
        lambda *args: events.append("plan") or _plan(),
    )
    monkeypatch.setattr(
        workflow,
        "run_readonly_sql",
        lambda *args, **kwargs: events.append("sql") or _sql_result(),
    )
    monkeypatch.setattr(
        workflow,
        "run_python_analysis",
        lambda *args, **kwargs: events.append("python") or _python_result(),
    )

    result = _invoke()

    assert result.validated_result.result.status == "success"
    assert result.validated_result.result.route_decision.route == "sql_then_python"
    assert result.synthesis.status == "success"
    assert events == ["plan", "sql", "python"]


def test_conditional_route_does_not_enter_unselected_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_route(monkeypatch, _route("sql_then_python", "describe"))
    monkeypatch.setattr(workflow, "answer_question", _unexpected)
    monkeypatch.setattr(workflow, "generate_python_analysis_plan", lambda *args: _plan())
    monkeypatch.setattr(workflow, "run_readonly_sql", lambda *args, **kwargs: _sql_result())
    monkeypatch.setattr(workflow, "run_python_analysis", lambda *args, **kwargs: _python_result())

    assert _invoke().validated_result.result.analysis_plan == _plan()


def test_routing_error_skips_all_execution_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_route(monkeypatch, _routing_error())
    monkeypatch.setattr(workflow, "answer_question", _unexpected)
    monkeypatch.setattr(workflow, "generate_python_analysis_plan", _unexpected)
    monkeypatch.setattr(workflow, "run_readonly_sql", _unexpected)
    monkeypatch.setattr(workflow, "run_python_analysis", _unexpected)

    result = _invoke()

    assert result.validated_result.result.status == "routing_error"
    assert result.validated_result.validation.status == "invalid"
    assert result.synthesis.status == "blocked"


@pytest.mark.parametrize(
    ("answer_status", "expected_status"),
    (
        ("generation_error", "sql_generation_error"),
        ("repair_error", "sql_repair_error"),
        ("execution_error", "sql_execution_error"),
    ),
)
def test_sql_only_errors_preserve_existing_status_contract(
    monkeypatch: pytest.MonkeyPatch,
    answer_status: str,
    expected_status: str,
) -> None:
    _patch_route(monkeypatch, _route())
    monkeypatch.setattr(workflow, "answer_question", lambda *args, **kwargs: _sql_answer(answer_status))
    monkeypatch.setattr(workflow, "generate_python_analysis_plan", _unexpected)
    monkeypatch.setattr(workflow, "run_readonly_sql", _unexpected)
    monkeypatch.setattr(workflow, "run_python_analysis", _unexpected)

    result = _invoke()

    assert result.validated_result.result.status == expected_status
    assert result.validated_result.result.sql_answer_result == _sql_answer(answer_status)
    assert result.synthesis.status == "blocked"


def test_planning_error_skips_sql_and_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_route(monkeypatch, _route("sql_then_python", "describe"))
    monkeypatch.setattr(workflow, "generate_python_analysis_plan", lambda *args: _plan("error"))
    monkeypatch.setattr(workflow, "run_readonly_sql", _unexpected)
    monkeypatch.setattr(workflow, "run_python_analysis", _unexpected)

    result = _invoke()

    assert result.validated_result.result.status == "planning_error"
    assert result.synthesis.status == "blocked"


def test_analysis_sql_error_skips_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_route(monkeypatch, _route("sql_then_python", "describe"))
    monkeypatch.setattr(workflow, "generate_python_analysis_plan", lambda *args: _plan())
    monkeypatch.setattr(workflow, "run_readonly_sql", lambda *args, **kwargs: _sql_result(status="error"))
    monkeypatch.setattr(workflow, "run_python_analysis", _unexpected)

    result = _invoke()

    assert result.validated_result.result.status == "sql_execution_error"
    assert result.synthesis.status == "blocked"


def test_truncated_analysis_input_skips_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_route(monkeypatch, _route("sql_then_python", "describe"))
    monkeypatch.setattr(workflow, "generate_python_analysis_plan", lambda *args: _plan())
    monkeypatch.setattr(workflow, "run_readonly_sql", lambda *args, **kwargs: _sql_result(truncated=True))
    monkeypatch.setattr(workflow, "run_python_analysis", _unexpected)

    result = _invoke()

    assert result.validated_result.result.status == "truncated_analysis_input"
    assert result.synthesis.status == "blocked"


def test_python_analysis_error_still_validates_and_synthesizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_route(monkeypatch, _route("sql_then_python", "describe"))
    monkeypatch.setattr(workflow, "generate_python_analysis_plan", lambda *args: _plan())
    monkeypatch.setattr(workflow, "run_readonly_sql", lambda *args, **kwargs: _sql_result())
    monkeypatch.setattr(workflow, "run_python_analysis", lambda *args, **kwargs: _python_result("error"))

    result = _invoke()

    assert result.validated_result.result.status == "python_analysis_error"
    assert result.validated_result.validation.status == "invalid"
    assert result.synthesis.status == "blocked"


def test_validation_and_synthesis_are_each_called_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_route(monkeypatch, _route())
    monkeypatch.setattr(workflow, "answer_question", lambda *args, **kwargs: _sql_answer())
    original_validate = workflow.validate_multi_tool_result
    original_synthesize = workflow.synthesize_answer
    calls = {"validate": 0, "synthesize": 0}

    def validate(result):
        calls["validate"] += 1
        return original_validate(result)

    def synthesize(result):
        calls["synthesize"] += 1
        return original_synthesize(result)

    monkeypatch.setattr(workflow, "validate_multi_tool_result", validate)
    monkeypatch.setattr(workflow, "synthesize_answer", synthesize)

    _invoke()

    assert calls == {"validate": 1, "synthesize": 1}


def test_router_is_called_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def route(question, model):
        nonlocal calls
        calls += 1
        return _route()

    monkeypatch.setattr(workflow, "route_question", route)
    monkeypatch.setattr(workflow, "answer_question", lambda *args, **kwargs: _sql_answer())

    _invoke()

    assert calls == 1


def test_planner_is_called_once_on_python_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    _patch_route(monkeypatch, _route("sql_then_python", "describe"))

    def plan(*args):
        nonlocal calls
        calls += 1
        return _plan()

    monkeypatch.setattr(workflow, "generate_python_analysis_plan", plan)
    monkeypatch.setattr(workflow, "run_readonly_sql", lambda *args, **kwargs: _sql_result())
    monkeypatch.setattr(workflow, "run_python_analysis", lambda *args, **kwargs: _python_result())

    _invoke()

    assert calls == 1


def test_schema_is_inspected_once_when_not_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def inspect(path):
        nonlocal calls
        calls += 1
        assert path == DATABASE_PATH
        return SCHEMA

    monkeypatch.setattr(workflow, "inspect_schema", inspect)
    _patch_route(monkeypatch, _route())
    monkeypatch.setattr(workflow, "answer_question", lambda *args, **kwargs: _sql_answer())

    workflow.answer_question_with_langgraph(DATABASE_PATH, QUESTION, _model)

    assert calls == 1


def test_sql_only_parameters_and_supplied_schema_are_propagated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    _patch_route(monkeypatch, _route())
    monkeypatch.setattr(workflow, "inspect_schema", _unexpected)

    def answer(database_path, question, model, max_rows, *, schema):
        captured.update(
            database_path=database_path,
            question=question,
            model=model,
            max_rows=max_rows,
            schema=schema,
        )
        return _sql_answer()

    monkeypatch.setattr(workflow, "answer_question", answer)

    workflow.answer_question_with_langgraph(
        DATABASE_PATH,
        QUESTION,
        _model,
        max_rows=17,
        schema=SCHEMA,
    )

    assert captured == {
        "database_path": DATABASE_PATH,
        "question": QUESTION,
        "model": _model,
        "max_rows": 17,
        "schema": SCHEMA,
    }


def test_python_route_parameters_are_propagated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    _patch_route(monkeypatch, _route("sql_then_python", "describe"))

    def plan(question, schema, operation, model):
        captured.update(
            question=question,
            schema=schema,
            operation=operation,
            model=model,
        )
        return _plan()

    def execute(database_path, sql, *, max_rows):
        captured.update(
            database_path=database_path,
            sql=sql,
            analysis_max_rows=max_rows,
        )
        return _sql_result()

    def analyze(*, columns, rows, request):
        captured.update(columns=columns, rows=rows, request=request)
        return _python_result()

    monkeypatch.setattr(workflow, "generate_python_analysis_plan", plan)
    monkeypatch.setattr(workflow, "run_readonly_sql", execute)
    monkeypatch.setattr(workflow, "run_python_analysis", analyze)

    workflow.answer_question_with_langgraph(
        DATABASE_PATH,
        QUESTION,
        _model,
        analysis_max_rows=321,
        schema=SCHEMA,
    )

    assert captured["question"] == QUESTION
    assert captured["schema"] is SCHEMA
    assert captured["operation"] == "describe"
    assert captured["model"] is _model
    assert captured["database_path"] == DATABASE_PATH
    assert captured["sql"] == "SELECT value FROM facts"
    assert captured["analysis_max_rows"] == 321
    assert captured["columns"] == ("value",)
    assert captured["rows"] == ((1.0,), (2.0,))
    assert captured["request"].operation == "describe"
    assert captured["request"].columns == ("value",)


def test_graph_invoke_does_not_mutate_input_state_or_structured_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = _route()
    answer = _sql_answer()
    _patch_route(monkeypatch, decision)
    monkeypatch.setattr(workflow, "answer_question", lambda *args, **kwargs: answer)
    state = workflow.AgentGraphState(
        question=QUESTION,
        database_path=DATABASE_PATH,
        model=_model,
        max_rows=20,
        analysis_max_rows=30,
        schema=SCHEMA,
    )
    state_before = dict(state)
    decision_before = repr(decision)
    answer_before = repr(answer)

    workflow.build_agent_graph().invoke(state)

    assert state == state_before
    assert repr(decision) == decision_before
    assert repr(answer) == answer_before


def test_graph_state_excludes_secrets_prompts_and_evaluation_metadata() -> None:
    fields = set(workflow.AgentGraphState.__annotations__)

    assert "api_key" not in fields
    assert "prompt" not in fields
    assert "held_out_reference" not in fields
    assert "evaluation_metadata" not in fields


def test_sql_only_contract_matches_explicit_orchestration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = _route()
    answer = _sql_answer()
    monkeypatch.setattr(workflow, "route_question", lambda *args: decision)
    monkeypatch.setattr(workflow, "answer_question", lambda *args, **kwargs: answer)
    monkeypatch.setattr(explicit_workflow, "route_question", lambda *args: decision)
    monkeypatch.setattr(explicit_workflow, "answer_question", lambda *args, **kwargs: answer)

    explicit = explicit_workflow.answer_question_with_tools(
        DATABASE_PATH,
        QUESTION,
        _model,
        schema=SCHEMA,
    )
    graph_result = _invoke().validated_result.result

    assert graph_result == explicit


def test_sql_then_python_contract_matches_explicit_orchestration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = _route("sql_then_python", "describe")
    plan = _plan()
    sql_result = _sql_result()
    python_result = _python_result()
    monkeypatch.setattr(workflow, "route_question", lambda *args: decision)
    monkeypatch.setattr(workflow, "generate_python_analysis_plan", lambda *args: plan)
    monkeypatch.setattr(workflow, "run_readonly_sql", lambda *args, **kwargs: sql_result)
    monkeypatch.setattr(workflow, "run_python_analysis", lambda *args, **kwargs: python_result)
    monkeypatch.setattr(explicit_workflow, "route_question", lambda *args: decision)
    monkeypatch.setattr(explicit_workflow, "generate_python_analysis_plan", lambda *args: plan)
    monkeypatch.setattr(explicit_workflow, "run_readonly_sql", lambda *args, **kwargs: sql_result)
    monkeypatch.setattr(explicit_workflow, "run_python_analysis", lambda *args, **kwargs: python_result)

    explicit = explicit_workflow.answer_question_with_tools(
        DATABASE_PATH,
        QUESTION,
        _model,
        schema=SCHEMA,
    )
    graph_result = _invoke().validated_result.result

    assert graph_result == explicit
