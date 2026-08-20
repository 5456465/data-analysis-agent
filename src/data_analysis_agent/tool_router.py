"""Minimal LLM-based routing between SQL-only and SQL-then-Python paths."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from data_analysis_agent.sql_generator import TextToSQLModel


ToolRoute = Literal["sql_only", "sql_then_python"]
PythonRoutingOperation = Literal["describe", "correlation"]
ToolRoutingStatus = Literal["success", "error"]
ToolRoutingErrorCode = Literal[
    "invalid_argument",
    "invalid_model_output",
    "model_error",
    "unsupported_route",
]


@dataclass(frozen=True)
class ToolRoutingError:
    """Structured error returned when a routing decision cannot be made."""

    code: ToolRoutingErrorCode
    message: str


@dataclass(frozen=True)
class ToolRouteDecision:
    """Stable decision describing which supported execution path to use."""

    question: str
    route: ToolRoute | None
    python_operation: PythonRoutingOperation | None
    reason: str | None
    status: ToolRoutingStatus
    error: ToolRoutingError | None


def build_tool_routing_prompt(question: str) -> str:
    """Build the English prompt for one structured routing decision."""

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string.")

    return f"""You route an English Olist business analysis question to one supported execution path.

Available paths:
- sql_only: Use read-only SQL for lookup, filtering, joins, counts, sums, averages, percentages, grouping, ranking, top-N, and other SQL-native aggregation.
- sql_then_python: First use read-only SQL to produce a small tabular result, then run exactly one controlled Python operation over that result.

The only supported Python operations are:
- describe: descriptive statistics for one or more numeric result columns.
- correlation: Pearson correlation between exactly two numeric result columns.

Routing rules:
- Prefer sql_only by default when SQL can naturally and reliably answer the question.
- Choose sql_then_python only when the question genuinely requires one of the two supported Python operations.
- Python never accesses the database, reads files, or executes arbitrary code. SQL must retrieve and shape its input first.
- Regression, clustering, forecasting, machine learning, anomaly detection, and all other Python operations are unsupported.
- Do not generate SQL, execute a tool, answer the question, or add an execution plan.
- If no supported route can reliably fulfill the request, return a structured error rather than inventing a capability.

Return exactly one JSON object in one of these forms:
{{"status":"success","route":"sql_only","python_operation":null,"reason":"Brief reason."}}
{{"status":"success","route":"sql_then_python","python_operation":"describe","reason":"Brief reason."}}
{{"status":"success","route":"sql_then_python","python_operation":"correlation","reason":"Brief reason."}}
{{"status":"error","error":"Reason no supported route can fulfill the request."}}

User question:
{question}
"""


def route_question(
    question: str,
    model: TextToSQLModel,
) -> ToolRouteDecision:
    """Ask one model call for a route without generating SQL or running tools."""

    if not isinstance(question, str) or not question.strip():
        return _error_decision(
            question,
            "invalid_argument",
            "question must be a non-empty string.",
        )
    if not callable(model):
        return _error_decision(
            question,
            "invalid_argument",
            "model must be callable.",
        )

    prompt = build_tool_routing_prompt(question)
    try:
        model_output = model(prompt)
    except Exception as exc:
        return _error_decision(question, "model_error", str(exc))

    try:
        payload = _parse_model_output(model_output)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return _error_decision(question, "invalid_model_output", str(exc))

    if "sql" in payload:
        return _error_decision(
            question,
            "invalid_model_output",
            "Routing output must not contain SQL.",
        )

    status = payload.get("status")
    if status == "error":
        message = payload.get("error")
        if not isinstance(message, str) or not message.strip():
            return _error_decision(
                question,
                "invalid_model_output",
                "Error model output must contain a non-empty error string.",
            )
        return _error_decision(question, "unsupported_route", message)

    if status != "success":
        return _error_decision(
            question,
            "invalid_model_output",
            "Model output status must be 'success' or 'error'.",
        )

    route = payload.get("route")
    if not isinstance(route, str):
        return _error_decision(
            question,
            "invalid_model_output",
            "Successful model output must contain a route string.",
        )
    if route not in {"sql_only", "sql_then_python"}:
        return _error_decision(
            question,
            "unsupported_route",
            f"Unsupported route: {route!r}",
        )

    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return _error_decision(
            question,
            "invalid_model_output",
            "Successful model output must contain a non-empty reason string.",
        )

    operation = payload.get("python_operation")
    if operation is not None and not isinstance(operation, str):
        return _error_decision(
            question,
            "invalid_model_output",
            "python_operation must be a string or null.",
        )
    if operation is not None and operation not in {"describe", "correlation"}:
        return _error_decision(
            question,
            "unsupported_route",
            f"Unsupported Python operation: {operation!r}",
        )

    if route == "sql_only":
        if operation is not None:
            return _error_decision(
                question,
                "invalid_model_output",
                "sql_only must not include a Python operation.",
            )
        return ToolRouteDecision(
            question=question,
            route="sql_only",
            python_operation=None,
            reason=reason,
            status="success",
            error=None,
        )

    if operation not in {"describe", "correlation"}:
        return _error_decision(
            question,
            "invalid_model_output",
            "sql_then_python requires describe or correlation.",
        )
    return ToolRouteDecision(
        question=question,
        route="sql_then_python",
        python_operation=operation,
        reason=reason,
        status="success",
        error=None,
    )


def _parse_model_output(output: object) -> dict[str, object]:
    if isinstance(output, str):
        parsed = json.loads(output)
    elif isinstance(output, Mapping):
        parsed = dict(output)
    else:
        raise TypeError("Model output must be a JSON object or JSON object string.")

    if not isinstance(parsed, dict):
        raise ValueError("Model output must decode to a JSON object.")
    return parsed


def _error_decision(
    question: object,
    code: ToolRoutingErrorCode,
    message: str,
) -> ToolRouteDecision:
    return ToolRouteDecision(
        question=question if isinstance(question, str) else repr(question),
        route=None,
        python_operation=None,
        reason=None,
        status="error",
        error=ToolRoutingError(code=code, message=message),
    )
