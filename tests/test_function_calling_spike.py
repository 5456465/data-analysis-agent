"""Tests for the isolated Native Function Calling protocol spike."""

from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import data_analysis_agent.function_calling_spike as spike


class FakeCompletions:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        recorded = dict(kwargs)
        messages = kwargs.get("messages")
        if isinstance(messages, list):
            recorded["messages"] = list(messages)
        self.calls.append(recorded)
        if not self._responses:
            raise AssertionError("Unexpected fake Chat Completions request.")
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.completions = FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)


def _tool_call(
    *,
    call_id: str = "call_sql_1",
    call_type: str = "function",
    name: str = spike.TOOL_NAME,
    arguments: object = '{"sql":"SELECT 1 AS value"}',
) -> object:
    return SimpleNamespace(
        id=call_id,
        type=call_type,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _first_response(
    *,
    finish_reason: str = "tool_calls",
    tool_calls: list[object] | None = None,
) -> tuple[object, object]:
    calls = [_tool_call()] if tool_calls is None else tool_calls
    message = SimpleNamespace(
        role="assistant",
        content=None,
        tool_calls=calls,
    )
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=message,
            )
        ]
    )
    return response, message


def _second_response(content: str = "The query returned one row.") -> object:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=content),
            )
        ]
    )


def _successful_sql_result() -> dict[str, object]:
    return {
        "status": "success",
        "executed_sql": "SELECT 1 AS value",
        "columns": ["value"],
        "rows": [[1]],
        "returned_row_count": 1,
        "truncated": False,
        "error": None,
    }


def _install_fake_adapters(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sql_result: dict[str, object] | None = None,
) -> dict[str, list[object]]:
    calls: dict[str, list[object]] = {
        "schema_bind": [],
        "schema_call": [],
        "sql_bind": [],
        "sql_call": [],
    }

    def fake_inspect_schema_tool(database_path: str | Path) -> Any:
        calls["schema_bind"].append(Path(database_path))

        def inspect() -> dict[str, object]:
            calls["schema_call"].append(True)
            return {
                "tables": [
                    {
                        "name": "orders",
                        "columns": [
                            {"name": "order_id", "data_type": "VARCHAR"}
                        ],
                    }
                ],
                "views": [],
            }

        return inspect

    def fake_run_readonly_sql_tool(database_path: str | Path) -> Any:
        calls["sql_bind"].append(Path(database_path))

        def run(sql: str) -> dict[str, object]:
            calls["sql_call"].append(sql)
            return (
                _successful_sql_result()
                if sql_result is None
                else sql_result
            )

        return run

    monkeypatch.setattr(
        spike,
        "inspect_schema_tool",
        fake_inspect_schema_tool,
    )
    monkeypatch.setattr(
        spike,
        "run_readonly_sql_tool",
        fake_run_readonly_sql_tool,
    )
    return calls


def _run_valid_spike(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[spike.FunctionCallingProof, FakeClient, dict[str, list[object]], object]:
    calls = _install_fake_adapters(monkeypatch)
    first_response, assistant_message = _first_response()
    client = FakeClient([first_response, _second_response()])

    proof = spike.run_function_calling_spike(
        "How many rows does this query return?",
        Path("trusted.duckdb"),
        client,
    )
    return proof, client, calls, assistant_message


def _assert_invalid_first_response(
    monkeypatch: pytest.MonkeyPatch,
    first_response: object,
    message: str,
) -> None:
    calls = _install_fake_adapters(monkeypatch)
    client = FakeClient([first_response])

    with pytest.raises(spike.FunctionCallingProtocolError, match=message):
        spike.run_function_calling_spike(
            "Run a safe query.",
            Path("trusted.duckdb"),
            client,
        )

    assert calls["sql_bind"] == []
    assert calls["sql_call"] == []
    assert len(client.completions.calls) == 1


def test_first_request_uses_tools_and_preloaded_schema_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client, calls, _ = _run_valid_spike(monkeypatch)

    first_request = client.completions.calls[0]
    assert first_request["tools"] == spike.FUNCTION_TOOLS
    assert first_request["tool_choice"] == "required"
    assert first_request["extra_body"] == {
        "thinking": {"type": "disabled"}
    }
    assert calls["schema_bind"] == [Path("trusted.duckdb")]
    assert calls["schema_call"] == [True]
    messages = first_request["messages"]
    assert isinstance(messages, list)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert '"name":"orders"' in messages[0]["content"]
    assert messages[1] == {
        "role": "user",
        "content": "How many rows does this query return?",
    }


def test_function_tool_schema_allows_only_required_sql() -> None:
    assert spike.FUNCTION_TOOLS == [spike.RUN_READONLY_SQL_TOOL]
    function = spike.RUN_READONLY_SQL_TOOL["function"]
    assert function["name"] == "run_readonly_sql"
    parameters = function["parameters"]
    assert parameters == {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "The read-only SQL query to execute.",
            }
        },
        "required": ["sql"],
        "additionalProperties": False,
    }
    schema_text = json.dumps(spike.FUNCTION_TOOLS)
    for forbidden_name in (
        "db_path",
        "database_path",
        "max_rows",
        "api_key",
        "model",
        "python",
    ):
        assert forbidden_name not in schema_text.lower()


def test_valid_message_tool_calls_drive_existing_sql_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, calls, _ = _run_valid_spike(monkeypatch)

    assert calls["sql_bind"] == [Path("trusted.duckdb")]
    assert calls["sql_call"] == ["SELECT 1 AS value"]


def test_finish_reason_other_than_tool_calls_fails_before_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, _ = _first_response(finish_reason="stop")
    _assert_invalid_first_response(
        monkeypatch,
        response,
        "finish_reason must be 'tool_calls'",
    )


def test_zero_tool_calls_fails_before_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, _ = _first_response(tool_calls=[])
    _assert_invalid_first_response(
        monkeypatch,
        response,
        "exactly one tool call",
    )


def test_multiple_tool_calls_fail_before_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, _ = _first_response(tool_calls=[_tool_call(), _tool_call()])
    _assert_invalid_first_response(
        monkeypatch,
        response,
        "exactly one tool call",
    )


def test_non_function_tool_call_fails_before_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, _ = _first_response(
        tool_calls=[_tool_call(call_type="custom")]
    )
    _assert_invalid_first_response(
        monkeypatch,
        response,
        "type must be 'function'",
    )


def test_wrong_tool_name_fails_before_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, _ = _first_response(tool_calls=[_tool_call(name="other_tool")])
    _assert_invalid_first_response(
        monkeypatch,
        response,
        "Tool name must be exactly",
    )


def test_invalid_json_arguments_fail_before_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, _ = _first_response(
        tool_calls=[_tool_call(arguments="not-json")]
    )
    _assert_invalid_first_response(
        monkeypatch,
        response,
        "must be valid JSON",
    )


@pytest.mark.parametrize("raw_arguments", ["[]", '"SELECT 1"', "null"])
def test_non_object_arguments_fail_before_sql(
    monkeypatch: pytest.MonkeyPatch,
    raw_arguments: str,
) -> None:
    response, _ = _first_response(
        tool_calls=[_tool_call(arguments=raw_arguments)]
    )
    _assert_invalid_first_response(
        monkeypatch,
        response,
        "must be a JSON object",
    )


def test_missing_sql_fails_before_sql_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, _ = _first_response(tool_calls=[_tool_call(arguments="{}")])
    _assert_invalid_first_response(
        monkeypatch,
        response,
        "must contain only the 'sql' field",
    )


@pytest.mark.parametrize(
    "raw_arguments",
    ['{"sql":1}', '{"sql":null}', '{"sql":""}', '{"sql":"   "}'],
)
def test_non_string_or_empty_sql_fails_before_sql(
    monkeypatch: pytest.MonkeyPatch,
    raw_arguments: str,
) -> None:
    response, _ = _first_response(
        tool_calls=[_tool_call(arguments=raw_arguments)]
    )
    _assert_invalid_first_response(
        monkeypatch,
        response,
        "must be a non-empty string",
    )


def test_arbitrary_extra_argument_fails_before_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, _ = _first_response(
        tool_calls=[
            _tool_call(arguments='{"sql":"SELECT 1","extra":true}')
        ]
    )
    _assert_invalid_first_response(
        monkeypatch,
        response,
        "must contain only the 'sql' field",
    )


@pytest.mark.parametrize("injected_name", ["db_path", "database_path", "max_rows"])
def test_path_and_row_limit_injection_fail_before_sql(
    monkeypatch: pytest.MonkeyPatch,
    injected_name: str,
) -> None:
    arguments = json.dumps({"sql": "SELECT 1", injected_name: "attacker"})
    response, _ = _first_response(
        tool_calls=[_tool_call(arguments=arguments)]
    )
    _assert_invalid_first_response(
        monkeypatch,
        response,
        "must contain only the 'sql' field",
    )


def test_second_request_preserves_assistant_tool_call_and_adds_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client, _, assistant_message = _run_valid_spike(monkeypatch)

    second_request = client.completions.calls[1]
    messages = second_request["messages"]
    assert isinstance(messages, list)
    assert len(messages) == 4
    assert messages[2] is assistant_message
    assert messages[2].tool_calls[0].id == "call_sql_1"
    assert messages[3]["role"] == "tool"
    assert messages[3]["tool_call_id"] == "call_sql_1"
    assert json.loads(messages[3]["content"]) == _successful_sql_result()
    assert second_request["tool_choice"] == "none"
    assert second_request["extra_body"] == {
        "thinking": {"type": "disabled"}
    }


def test_proof_result_records_the_protocol_and_sql_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof, _, _, _ = _run_valid_spike(monkeypatch)

    assert proof.finish_reason == "tool_calls"
    assert proof.tool_call_id == "call_sql_1"
    assert proof.tool_name == "run_readonly_sql"
    assert proof.raw_arguments == '{"sql":"SELECT 1 AS value"}'
    assert proof.validated_arguments == {"sql": "SELECT 1 AS value"}
    assert proof.sql_status == "success"
    assert proof.returned_row_count == 1
    assert proof.truncated is False
    assert proof.final_text == "The query returned one row."
    json.dumps(proof.to_json_dict(), allow_nan=False)

    with pytest.raises(FrozenInstanceError):
        proof.final_text = "changed"  # type: ignore[misc]


def test_spike_has_no_arbitrary_execution_or_direct_network_capability() -> None:
    source_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "data_analysis_agent"
        / "function_calling_spike.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "data_analysis_agent.integration_tools" in imported_modules
    assert imported_modules.isdisjoint(
        {"httpx", "requests", "socket", "subprocess", "urllib"}
    )
    assert called_names.isdisjoint(
        {"__import__", "compile", "eval", "exec", "open"}
    )
