"""Deterministic HTTP adapter tests without real models or databases."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import data_analysis_agent.analysis_planner as planner_module
import data_analysis_agent.api as api_module
import data_analysis_agent.python_analysis as python_module
import data_analysis_agent.sql_executor as executor_module
import data_analysis_agent.tool_router as router_module
from data_analysis_agent.analysis_planner import PythonAnalysisPlan
from data_analysis_agent.answer_synthesis import AnswerSynthesis
from data_analysis_agent.final_answer_service import FinalAnswerResult
from data_analysis_agent.multi_tool_service import (
    MultiToolQuestionError,
    MultiToolQuestionResult,
)
from data_analysis_agent.python_analysis import (
    GrowthPoint,
    GrowthResult,
    PythonAnalysisResult,
)
from data_analysis_agent.question_service import QuestionAnswerResult
from data_analysis_agent.result_validation import ResultValidation, ValidationIssue
from data_analysis_agent.sql_executor import SQLResult
from data_analysis_agent.tool_router import (
    ToolRouteDecision,
    ToolRoutingError,
)
from data_analysis_agent.validated_question_service import ValidatedQuestionResult


QUESTION = "How many orders are in the dataset?"


def _fake_model(prompt: str) -> dict[str, object]:
    raise AssertionError(f"Unexpected model call: {prompt}")


def _sql_result() -> SQLResult:
    return SQLResult(
        executed_sql="SELECT COUNT(*) AS order_count FROM orders",
        columns=("order_count",),
        rows=((99441,),),
        returned_row_count=1,
        truncated=False,
        status="success",
        error=None,
    )


def _final_result(
    *,
    route: str = "sql_only",
    warnings: tuple[str, ...] = (),
    repaired: bool = False,
) -> FinalAnswerResult:
    sql_result = _sql_result()
    sql_answer = (
        QuestionAnswerResult(
            question=QUESTION,
            generated_sql="SELECT COUNT(*) AS order_count FROM orders",
            status="success",
            execution_result=sql_result,
            generation_error=None,
            execution_error=None,
            repaired_sql=(
                "SELECT COUNT(*) AS order_count FROM orders"
                if repaired
                else None
            ),
            repair_attempted=repaired,
            repair_error=None,
        )
        if route == "sql_only"
        else None
    )
    plan = (
        PythonAnalysisPlan(
            question=QUESTION,
            python_operation="calculate_growth",
            sql="SELECT month, value FROM monthly_values ORDER BY month",
            python_columns=("month", "value"),
            status="success",
            error=None,
        )
        if route == "sql_then_python"
        else None
    )
    python_result = (
        PythonAnalysisResult(
            operation="calculate_growth",
            status="success",
            result=GrowthResult(
                points=(GrowthPoint("2017-01", 10.0, None, None, None),),
                period_count=1,
            ),
            error=None,
        )
        if route == "sql_then_python"
        else None
    )
    result = MultiToolQuestionResult(
        question=QUESTION,
        route_decision=ToolRouteDecision(
            question=QUESTION,
            route=route,
            python_operation=(
                "calculate_growth" if route == "sql_then_python" else None
            ),
            reason="deterministic test route",
            status="success",
            error=None,
        ),
        status="success",
        sql_answer_result=sql_answer,
        analysis_plan=plan,
        sql_result=sql_result,
        python_result=python_result,
        error=None,
    )
    validation = ResultValidation(
        "valid_with_warnings" if warnings else "valid",
        tuple(
            ValidationIssue("test_warning", "warning", warning)
            for warning in warnings
        ),
    )
    return FinalAnswerResult(
        validated_result=ValidatedQuestionResult(result, validation),
        synthesis=AnswerSynthesis("success", "Result: 99441", warnings),
    )


def _blocked_result() -> FinalAnswerResult:
    decision = ToolRouteDecision(
        question=QUESTION,
        route=None,
        python_operation=None,
        reason=None,
        status="error",
        error=ToolRoutingError("unsupported_route", "Unsupported request."),
    )
    result = MultiToolQuestionResult(
        question=QUESTION,
        route_decision=decision,
        status="routing_error",
        sql_answer_result=None,
        analysis_plan=None,
        sql_result=None,
        python_result=None,
        error=MultiToolQuestionError("routing_error", "Unsupported request."),
    )
    validation = ResultValidation(
        "invalid",
        (
            ValidationIssue(
                "unsuccessful_pipeline",
                "error",
                "Pipeline ended at routing_error.",
            ),
        ),
    )
    return FinalAnswerResult(
        validated_result=ValidatedQuestionResult(result, validation),
        synthesis=AnswerSynthesis(
            "blocked",
            "A reliable answer cannot be generated.",
            (),
        ),
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    database_path = tmp_path / "olist.duckdb"
    database_path.touch()
    monkeypatch.setattr(api_module, "DEFAULT_DATABASE_PATH", database_path)
    return TestClient(api_module.app, raise_server_exceptions=False)


def _configure_result(
    monkeypatch: pytest.MonkeyPatch,
    final_result: FinalAnswerResult,
) -> None:
    monkeypatch.setattr(api_module, "create_model", lambda: _fake_model)
    monkeypatch.setattr(
        api_module,
        "answer_question_for_user",
        lambda *args, **kwargs: final_result,
    )


def _unexpected(*args: object, **kwargs: object) -> object:
    raise AssertionError("Core tool must not be called directly by the API adapter.")


def test_health_returns_stable_json_without_agent_calls(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_module, "create_model", _unexpected)
    monkeypatch.setattr(api_module, "answer_question_for_user", _unexpected)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "data-analysis-agent",
    }


def test_analyze_successful_sql_only_response(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_result(monkeypatch, _final_result())

    response = client.post("/analyze", json={"question": QUESTION})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["route"] == "sql_only"
    assert body["validation"] == "valid"
    assert body["analysis_tool"] is None


def test_analyze_successful_sql_then_python_response(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_result(monkeypatch, _final_result(route="sql_then_python"))

    response = client.post("/analyze", json={"question": QUESTION})

    assert response.status_code == 200
    assert response.json()["route"] == "sql_then_python"
    assert response.json()["analysis_tool"] == "calculate_growth"


def test_blocked_agent_result_is_http_200(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_result(monkeypatch, _blocked_result())

    response = client.post("/analyze", json={"question": QUESTION})

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert response.json()["validation"] == "invalid"
    assert response.json()["route"] is None


def test_warnings_are_preserved_unchanged(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings = ("First warning.", "Second warning.")
    _configure_result(monkeypatch, _final_result(warnings=warnings))

    response = client.post("/analyze", json={"question": QUESTION})

    assert response.json()["warnings"] == list(warnings)
    assert response.json()["validation"] == "valid_with_warnings"


def test_normalized_question_is_passed_to_product_entry_once(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(api_module, "create_model", lambda: _fake_model)

    def answer(database_path, question, model):
        calls.append((database_path, question, model))
        return _final_result()

    monkeypatch.setattr(api_module, "answer_question_for_user", answer)

    response = client.post("/analyze", json={"question": f"  {QUESTION}  "})

    assert response.status_code == 200
    assert calls == [(api_module.DEFAULT_DATABASE_PATH, QUESTION, _fake_model)]


def test_api_does_not_call_core_tools_directly(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_result(monkeypatch, _final_result())
    monkeypatch.setattr(router_module, "route_question", _unexpected)
    monkeypatch.setattr(planner_module, "generate_python_analysis_plan", _unexpected)
    monkeypatch.setattr(executor_module, "run_readonly_sql", _unexpected)
    monkeypatch.setattr(python_module, "run_python_analysis", _unexpected)

    response = client.post("/analyze", json={"question": QUESTION})

    assert response.status_code == 200


@pytest.mark.parametrize("question", ["", "   "])
def test_empty_question_returns_422_without_agent_call(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    question: str,
) -> None:
    monkeypatch.setattr(api_module, "create_model", _unexpected)
    monkeypatch.setattr(api_module, "answer_question_for_user", _unexpected)

    response = client.post("/analyze", json={"question": question})

    assert response.status_code == 422


def test_non_string_question_returns_422(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_module, "create_model", _unexpected)
    monkeypatch.setattr(api_module, "answer_question_for_user", _unexpected)

    response = client.post("/analyze", json={"question": 123})

    assert response.status_code == 422


def test_request_rejects_api_key_and_route_override_fields(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_module, "create_model", _unexpected)
    monkeypatch.setattr(api_module, "answer_question_for_user", _unexpected)

    response = client.post(
        "/analyze",
        json={
            "question": QUESTION,
            "api_key": "secret",
            "route": "sql_only",
        },
    )

    assert response.status_code == 422


def test_response_excludes_secrets_prompts_and_held_out_metadata(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_result(monkeypatch, _final_result())

    body = client.post("/analyze", json={"question": QUESTION}).text.lower()

    assert "api_key" not in body
    assert "deepseek_api_key" not in body
    assert "prompt" not in body
    assert "held_out" not in body
    assert "reference_sql" not in body


def test_machine_identifiers_are_not_ui_labels(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_result(monkeypatch, _final_result(route="sql_then_python"))

    body = client.post("/analyze", json={"question": QUESTION}).json()

    assert body["route"] == "sql_then_python"
    assert body["validation"] == "valid"
    assert body["analysis_tool"] == "calculate_growth"
    assert body["route"] != "SQL → Python"


def test_trace_steps_are_mapped_to_json_objects(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_result(monkeypatch, _final_result())

    trace = client.post("/analyze", json={"question": QUESTION}).json()[
        "evidence"
    ]["trace"]

    assert trace[0]["stage"] == "routing"
    assert trace[0]["status"] == "success"
    assert trace[0]["details"]["route"] == "sql_only"
    assert isinstance(trace[0]["details"], dict)


def test_sql_only_evidence_contains_actual_sql_not_planner_sql(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_result(monkeypatch, _final_result(repaired=True))

    evidence = client.post("/analyze", json={"question": QUESTION}).json()[
        "evidence"
    ]

    assert evidence["generated_sql"] == "SELECT COUNT(*) AS order_count FROM orders"
    assert evidence["repaired_sql"] == "SELECT COUNT(*) AS order_count FROM orders"
    assert evidence["planner_sql"] is None
    assert evidence["python_columns"] == []


def test_sql_then_python_evidence_contains_plan_and_columns(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_result(monkeypatch, _final_result(route="sql_then_python"))

    evidence = client.post("/analyze", json={"question": QUESTION}).json()[
        "evidence"
    ]

    assert evidence["generated_sql"] is None
    assert evidence["repaired_sql"] is None
    assert evidence["planner_sql"] == (
        "SELECT month, value FROM monthly_values ORDER BY month"
    )
    assert evidence["python_columns"] == ["month", "value"]


def test_provider_initialization_failure_returns_safe_500(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api_module,
        "create_model",
        lambda: (_ for _ in ()).throw(
            RuntimeError("DEEPSEEK_API_KEY=super-secret traceback")
        ),
    )
    monkeypatch.setattr(api_module, "answer_question_for_user", _unexpected)

    response = client.post("/analyze", json={"question": QUESTION})

    assert response.status_code == 500
    assert response.json() == {"detail": "Analysis service failed."}
    assert "super-secret" not in response.text
    assert "traceback" not in response.text


def test_unexpected_agent_exception_returns_safe_500(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_module, "create_model", lambda: _fake_model)
    monkeypatch.setattr(
        api_module,
        "answer_question_for_user",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("private detail")),
    )

    response = client.post("/analyze", json={"question": QUESTION})

    assert response.status_code == 500
    assert response.json() == {"detail": "Analysis service failed."}
    assert "private detail" not in response.text


def test_missing_database_returns_500_before_provider_creation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(api_module, "DEFAULT_DATABASE_PATH", tmp_path / "missing.db")
    monkeypatch.setattr(api_module, "create_model", _unexpected)
    monkeypatch.setattr(api_module, "answer_question_for_user", _unexpected)

    response = client.post("/analyze", json={"question": QUESTION})

    assert response.status_code == 500
    assert response.json() == {"detail": "Analysis database is unavailable."}


def test_api_module_has_no_eager_model_instance() -> None:
    assert not hasattr(api_module, "MODEL")
    assert api_module.DEFAULT_DATABASE_PATH == Path("data/processed/olist.duckdb")
