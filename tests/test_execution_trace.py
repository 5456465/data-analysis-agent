from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from data_analysis_agent.analysis_planner import (
    PythonAnalysisPlan,
    PythonAnalysisPlanError,
)
from data_analysis_agent.answer_synthesis import AnswerSynthesis
from data_analysis_agent.execution_trace import (
    ExecutionTrace,
    TraceStep,
    build_execution_trace,
    format_execution_trace,
)
from data_analysis_agent.final_answer_service import FinalAnswerResult
from data_analysis_agent.multi_tool_service import (
    MultiToolQuestionError,
    MultiToolQuestionResult,
)
from data_analysis_agent.python_analysis import (
    GrowthPoint,
    GrowthResult,
    PythonAnalysisError,
    PythonAnalysisResult,
)
from data_analysis_agent.question_service import QuestionAnswerResult
from data_analysis_agent.result_validation import ResultValidation, ValidationIssue
from data_analysis_agent.sql_executor import SQLExecutionError, SQLResult
from data_analysis_agent.sql_generator import SQLGenerationError
from data_analysis_agent.tool_router import (
    ToolRouteDecision,
    ToolRoutingError,
)
from data_analysis_agent.validated_question_service import ValidatedQuestionResult


def _route(
    route: str | None,
    operation: str | None = None,
    *,
    status: str = "success",
    error: ToolRoutingError | None = None,
    reason: str = "test reason",
) -> ToolRouteDecision:
    return ToolRouteDecision(
        question="test question",
        route=route,
        python_operation=operation,
        reason=reason if status == "success" else None,
        status=status,
        error=error,
    )


def _sql_result(
    *,
    status: str = "success",
    rows: tuple[tuple[object, ...], ...] = ((1,),),
    columns: tuple[str, ...] = ("value",),
    error: SQLExecutionError | None = None,
) -> SQLResult:
    return SQLResult(
        executed_sql="SELECT executed",
        columns=columns,
        rows=rows,
        returned_row_count=len(rows),
        truncated=False,
        status=status,
        error=error,
    )


def _sql_answer(
    *,
    status: str = "success",
    sql_result: SQLResult | None = None,
    generated_sql: str | None = "SELECT generated",
    generation_error: SQLGenerationError | None = None,
    repair_attempted: bool = False,
    repaired_sql: str | None = None,
) -> QuestionAnswerResult:
    return QuestionAnswerResult(
        question="test question",
        generated_sql=generated_sql,
        status=status,
        execution_result=sql_result,
        generation_error=generation_error,
        execution_error=sql_result.error if sql_result is not None else None,
        repaired_sql=repaired_sql,
        repair_attempted=repair_attempted,
        repair_error=None,
    )


def _final(
    result: MultiToolQuestionResult,
    *,
    validation_status: str = "valid",
    issues: tuple[ValidationIssue, ...] = (),
    synthesis_status: str = "success",
    synthesis_answer: str = "Result: 1",
    warnings: tuple[str, ...] = (),
) -> FinalAnswerResult:
    return FinalAnswerResult(
        validated_result=ValidatedQuestionResult(
            result=result,
            validation=ResultValidation(validation_status, issues),
        ),
        synthesis=AnswerSynthesis(synthesis_status, synthesis_answer, warnings),
    )


def _sql_only_result(
    *,
    answer: QuestionAnswerResult | None = None,
    sql_result: SQLResult | None = None,
    status: str = "success",
) -> MultiToolQuestionResult:
    actual_sql = sql_result or _sql_result()
    actual_answer = answer or _sql_answer(sql_result=actual_sql)
    return MultiToolQuestionResult(
        question="test question",
        route_decision=_route("sql_only"),
        status=status,
        sql_answer_result=actual_answer,
        analysis_plan=None,
        sql_result=actual_sql if actual_answer.execution_result is not None else None,
        python_result=None,
        error=(
            None
            if status == "success"
            else MultiToolQuestionError("sql_generation_error", "generation failed")
        ),
    )


def _analysis_result(
    *,
    plan: PythonAnalysisPlan,
    sql_result: SQLResult | None = None,
    python_result: PythonAnalysisResult | None = None,
    status: str = "success",
) -> MultiToolQuestionResult:
    return MultiToolQuestionResult(
        question="test question",
        route_decision=_route("sql_then_python", "calculate_growth"),
        status=status,
        sql_answer_result=None,
        analysis_plan=plan,
        sql_result=sql_result,
        python_result=python_result,
        error=(
            None
            if status == "success"
            else MultiToolQuestionError(
                "planning_error" if plan.status == "error" else "sql_execution_error",
                "analysis failed",
            )
        ),
    )


def _successful_plan() -> PythonAnalysisPlan:
    return PythonAnalysisPlan(
        question="test question",
        python_operation="calculate_growth",
        sql="SELECT month, value FROM facts ORDER BY month",
        python_columns=("month", "value"),
        status="success",
        error=None,
    )


def _growth_payload() -> GrowthResult:
    return GrowthResult(
        points=(
            GrowthPoint("2020-01", 10.0, None, None, None),
            GrowthPoint("2020-02", 15.0, 10.0, 5.0, 0.5),
        ),
        period_count=2,
    )


def _stage_names(trace: ExecutionTrace) -> tuple[str, ...]:
    return tuple(step.stage for step in trace.steps)


def _step(trace: ExecutionTrace, stage: str) -> TraceStep:
    return next(step for step in trace.steps if step.stage == stage)


def test_successful_sql_only_trace() -> None:
    trace = build_execution_trace(_final(_sql_only_result()))

    assert _stage_names(trace) == (
        "routing",
        "sql_generation",
        "sql_execution",
        "validation",
        "answer_synthesis",
    )
    assert all(step.status == "success" for step in trace.steps)


def test_sql_only_successful_repair_adds_repair_step() -> None:
    sql_result = _sql_result()
    answer = _sql_answer(
        sql_result=sql_result,
        repair_attempted=True,
        repaired_sql="SELECT repaired",
    )
    trace = build_execution_trace(
        _final(_sql_only_result(answer=answer, sql_result=sql_result))
    )

    assert _stage_names(trace) == (
        "routing",
        "sql_generation",
        "sql_repair",
        "sql_execution",
        "validation",
        "answer_synthesis",
    )
    assert _step(trace, "sql_repair").status == "success"
    assert ("repaired_sql", "SELECT repaired") in _step(trace, "sql_repair").details


def test_sql_generation_failure_does_not_add_sql_execution() -> None:
    answer = _sql_answer(
        status="generation_error",
        sql_result=None,
        generated_sql=None,
        generation_error=SQLGenerationError("invalid_model_output", "bad JSON"),
    )
    result = _sql_only_result(answer=answer, status="sql_generation_error")

    trace = build_execution_trace(
        _final(result, validation_status="invalid", synthesis_status="blocked")
    )

    assert _stage_names(trace) == (
        "routing",
        "sql_generation",
        "validation",
        "answer_synthesis",
    )
    assert _step(trace, "sql_generation").status == "error"


def test_successful_sql_then_python_trace() -> None:
    python_result = PythonAnalysisResult(
        "calculate_growth", "success", _growth_payload(), None
    )
    result = _analysis_result(
        plan=_successful_plan(),
        sql_result=_sql_result(columns=("month", "value")),
        python_result=python_result,
    )

    trace = build_execution_trace(_final(result))

    assert _stage_names(trace) == (
        "routing",
        "planning",
        "sql_execution",
        "python_analysis",
        "validation",
        "answer_synthesis",
    )


def test_planning_failure_does_not_add_execution_or_python() -> None:
    plan = PythonAnalysisPlan(
        "test question",
        "calculate_growth",
        None,
        (),
        "error",
        PythonAnalysisPlanError("invalid_model_output", "bad plan"),
    )
    result = _analysis_result(plan=plan, status="planning_error")

    trace = build_execution_trace(
        _final(result, validation_status="invalid", synthesis_status="blocked")
    )

    assert _stage_names(trace) == (
        "routing",
        "planning",
        "validation",
        "answer_synthesis",
    )
    assert _step(trace, "planning").status == "error"


def test_sql_execution_failure_does_not_add_python_analysis() -> None:
    sql_result = _sql_result(
        status="error",
        rows=(),
        columns=(),
        error=SQLExecutionError("execution_error", "query failed"),
    )
    result = _analysis_result(
        plan=_successful_plan(),
        sql_result=sql_result,
        status="sql_execution_error",
    )

    trace = build_execution_trace(
        _final(result, validation_status="invalid", synthesis_status="blocked")
    )

    assert "python_analysis" not in _stage_names(trace)
    assert _step(trace, "sql_execution").status == "error"


def test_python_analysis_failure_is_recorded() -> None:
    python_result = PythonAnalysisResult(
        "calculate_growth",
        "error",
        None,
        PythonAnalysisError("insufficient_data", "not enough rows"),
    )
    result = _analysis_result(
        plan=_successful_plan(),
        sql_result=_sql_result(columns=("month", "value")),
        python_result=python_result,
        status="python_analysis_error",
    )

    trace = build_execution_trace(
        _final(result, validation_status="invalid", synthesis_status="blocked")
    )

    step = _step(trace, "python_analysis")
    assert step.status == "error"
    assert ("error_code", "insufficient_data") in step.details


def test_routing_failure_only_adds_routing_validation_and_synthesis() -> None:
    result = MultiToolQuestionResult(
        question="test question",
        route_decision=_route(
            None,
            status="error",
            error=ToolRoutingError("unsupported_route", "unsupported"),
        ),
        status="routing_error",
        sql_answer_result=None,
        analysis_plan=None,
        sql_result=None,
        python_result=None,
        error=MultiToolQuestionError("routing_error", "unsupported"),
    )

    trace = build_execution_trace(
        _final(result, validation_status="invalid", synthesis_status="blocked")
    )

    assert _stage_names(trace) == (
        "routing",
        "validation",
        "answer_synthesis",
    )
    assert _step(trace, "routing").status == "error"


@pytest.mark.parametrize(
    ("validation_status", "expected_trace_status"),
    [
        ("valid", "success"),
        ("valid_with_warnings", "warning"),
        ("invalid", "error"),
    ],
)
def test_validation_status_mapping(
    validation_status: str,
    expected_trace_status: str,
) -> None:
    issues = (
        ValidationIssue("empty_result", "warning", "No rows."),
    ) if validation_status == "valid_with_warnings" else ()

    trace = build_execution_trace(
        _final(_sql_only_result(), validation_status=validation_status, issues=issues)
    )

    step = _step(trace, "validation")
    assert step.status == expected_trace_status
    assert ("validation_status", validation_status) in step.details
    assert ("issue_count", str(len(issues))) in step.details


def test_blocked_synthesis_maps_to_error() -> None:
    trace = build_execution_trace(
        _final(
            _sql_only_result(),
            validation_status="invalid",
            synthesis_status="blocked",
        )
    )

    assert _step(trace, "answer_synthesis").status == "error"


def test_growth_trace_records_metadata_without_points() -> None:
    payload = _growth_payload()
    result = _analysis_result(
        plan=_successful_plan(),
        sql_result=_sql_result(columns=("month", "value")),
        python_result=PythonAnalysisResult(
            "calculate_growth", "success", payload, None
        ),
    )

    trace = build_execution_trace(_final(result))
    step = _step(trace, "python_analysis")

    assert ("payload_type", "GrowthResult") in step.details
    assert ("period_count", "2") in step.details
    assert repr(payload.points) not in repr(trace)
    assert "2020-01" not in repr(trace)


def test_sql_trace_records_metadata_without_rows() -> None:
    sql_result = _sql_result(rows=(("ROW SECRET ONE",), ("ROW SECRET TWO",)))
    trace = build_execution_trace(
        _final(_sql_only_result(sql_result=sql_result))
    )
    step = _step(trace, "sql_execution")

    assert ("returned_row_count", "2") in step.details
    assert ("columns", "value") in step.details
    assert "ROW SECRET" not in repr(trace)


def test_generated_sql_is_recorded() -> None:
    answer = _sql_answer(sql_result=_sql_result(), generated_sql="SELECT visible_sql")
    trace = build_execution_trace(_final(_sql_only_result(answer=answer)))

    assert ("generated_sql", "SELECT visible_sql") in _step(
        trace, "sql_generation"
    ).details


def test_planner_sql_and_columns_are_recorded() -> None:
    result = _analysis_result(
        plan=_successful_plan(),
        sql_result=_sql_result(columns=("month", "value")),
        python_result=PythonAnalysisResult(
            "calculate_growth", "success", _growth_payload(), None
        ),
    )

    details = _step(build_execution_trace(_final(result)), "planning").details

    assert (
        "planner_sql",
        "SELECT month, value FROM facts ORDER BY month",
    ) in details
    assert ("python_columns", "month, value") in details


def test_trace_does_not_include_prompt_answer_rows_or_credentials() -> None:
    secret = "DEEPSEEK_API_KEY=super-secret-key"
    sql_result = _sql_result(rows=((secret,),))
    answer = _sql_answer(sql_result=sql_result, generated_sql="SELECT safe_sql")
    result = _sql_only_result(answer=answer, sql_result=sql_result)
    result = MultiToolQuestionResult(
        question=result.question,
        route_decision=_route("sql_only", reason=f"FULL PROMPT {secret}"),
        status=result.status,
        sql_answer_result=result.sql_answer_result,
        analysis_plan=None,
        sql_result=result.sql_result,
        python_result=None,
        error=None,
    )

    trace = build_execution_trace(
        _final(result, synthesis_answer=f"answer contains {secret}")
    )
    serialized = repr(trace)

    assert "FULL PROMPT" not in serialized
    assert "DEEPSEEK_API_KEY" not in serialized
    assert "super-secret-key" not in serialized
    assert "answer contains" not in serialized


def test_build_trace_does_not_modify_final_result() -> None:
    final = _final(_sql_only_result())
    before = repr(final)

    build_execution_trace(final)

    assert repr(final) == before


def test_trace_contracts_are_frozen() -> None:
    step = TraceStep("routing", "success", "done", ())
    trace = ExecutionTrace("question", "sql_only", None, (step,))

    with pytest.raises(FrozenInstanceError):
        step.status = "error"
    with pytest.raises(FrozenInstanceError):
        trace.steps = ()


def test_formatter_is_deterministic() -> None:
    trace = build_execution_trace(_final(_sql_only_result()))

    first = format_execution_trace(trace)
    second = format_execution_trace(trace)

    assert first == second
    assert first.startswith("Routing [success]\n")
    assert "Sql generation [success]" in first
    assert "Validation [success]" in first


def test_trace_builder_does_not_execute_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("trace builder must not execute tools")

    monkeypatch.setattr(
        "data_analysis_agent.sql_executor.run_readonly_sql",
        fail_if_called,
    )
    monkeypatch.setattr(
        "data_analysis_agent.python_analysis.run_python_analysis",
        fail_if_called,
    )
    monkeypatch.setattr(
        "data_analysis_agent.deepseek_provider.DeepSeekTextToSQLModel",
        fail_if_called,
    )

    trace = build_execution_trace(_final(_sql_only_result()))

    assert _stage_names(trace)[0] == "routing"
