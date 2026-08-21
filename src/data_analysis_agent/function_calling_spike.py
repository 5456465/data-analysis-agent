"""Independent Native Function Calling protocol spike for read-only SQL."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from data_analysis_agent.deepseek_provider import DEEPSEEK_MODEL
from data_analysis_agent.integration_tools import (
    JSONDict,
    inspect_schema_tool,
    run_readonly_sql_tool,
)


TOOL_NAME = "run_readonly_sql"
RUN_READONLY_SQL_TOOL = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Execute one read-only SQL query against the bound analytics "
            "database using the existing safe SQL executor."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "The read-only SQL query to execute.",
                }
            },
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
}
FUNCTION_TOOLS = [RUN_READONLY_SQL_TOOL]
THINKING_DISABLED = {"thinking": {"type": "disabled"}}


class FunctionCallingProtocolError(ValueError):
    """Raised when a model response violates the spike's strict protocol."""


@dataclass(frozen=True)
class FunctionCallingProof:
    """Small immutable record of one completed Function Calling exchange."""

    finish_reason: str
    tool_call_id: str
    tool_name: str
    raw_arguments: str
    validated_arguments: dict[str, str]
    sql_status: str
    returned_row_count: int
    truncated: bool
    final_text: str

    def to_json_dict(self) -> JSONDict:
        """Return a detached JSON-safe representation of the proof."""

        return asdict(self)  # type: ignore[return-value]


def run_function_calling_spike(
    question: str,
    database_path: str | Path,
    client: Any,
    *,
    model: str = DEEPSEEK_MODEL,
) -> FunctionCallingProof:
    """Run one isolated two-turn Chat Completions Function Calling proof."""

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string.")

    schema_context = inspect_schema_tool(database_path)()
    messages: list[Any] = [
        {
            "role": "system",
            "content": (
                "You are running an isolated Function Calling protocol spike. "
                "Use the run_readonly_sql tool exactly once to answer the user. "
                "The database schema is:\n"
                + json.dumps(
                    schema_context,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                )
            ),
        },
        {"role": "user", "content": question},
    ]

    first_response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=FUNCTION_TOOLS,
        tool_choice="required",
        extra_body=THINKING_DISABLED,
    )
    choice, assistant_message = _first_choice(first_response)
    finish_reason = getattr(choice, "finish_reason", None)
    if finish_reason != "tool_calls":
        raise FunctionCallingProtocolError(
            "First response finish_reason must be 'tool_calls'."
        )

    tool_call = _single_function_tool_call(assistant_message)
    tool_call_id = getattr(tool_call, "id", None)
    if not isinstance(tool_call_id, str) or not tool_call_id:
        raise FunctionCallingProtocolError(
            "Tool call id must be a non-empty string."
        )

    function = getattr(tool_call, "function", None)
    tool_name = getattr(function, "name", None)
    if tool_name != TOOL_NAME:
        raise FunctionCallingProtocolError(
            f"Tool name must be exactly '{TOOL_NAME}'."
        )

    raw_arguments = getattr(function, "arguments", None)
    validated_arguments = _validate_arguments(raw_arguments)
    sql_result = run_readonly_sql_tool(database_path)(
        validated_arguments["sql"]
    )
    tool_content = json.dumps(
        sql_result,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )

    messages.append(assistant_message)
    messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": tool_content,
        }
    )
    second_response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=FUNCTION_TOOLS,
        tool_choice="none",
        extra_body=THINKING_DISABLED,
    )
    _, final_message = _first_choice(second_response)
    final_text = getattr(final_message, "content", None)
    if not isinstance(final_text, str) or not final_text.strip():
        raise FunctionCallingProtocolError(
            "Second response must contain non-empty final text."
        )

    return FunctionCallingProof(
        finish_reason=finish_reason,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        raw_arguments=raw_arguments,
        validated_arguments=dict(validated_arguments),
        sql_status=_required_result_field(sql_result, "status", str),
        returned_row_count=_required_result_field(
            sql_result,
            "returned_row_count",
            int,
        ),
        truncated=_required_result_field(sql_result, "truncated", bool),
        final_text=final_text,
    )


def _first_choice(response: object) -> tuple[object, object]:
    choices = getattr(response, "choices", None)
    if not isinstance(choices, list) or len(choices) != 1:
        raise FunctionCallingProtocolError(
            "Chat Completions response must contain exactly one choice."
        )
    choice = choices[0]
    message = getattr(choice, "message", None)
    if message is None:
        raise FunctionCallingProtocolError(
            "Chat Completions choice must contain a message."
        )
    return choice, message


def _single_function_tool_call(message: object) -> object:
    tool_calls = getattr(message, "tool_calls", None)
    if not isinstance(tool_calls, list) or len(tool_calls) != 1:
        raise FunctionCallingProtocolError(
            "First response must contain exactly one tool call."
        )
    tool_call = tool_calls[0]
    if getattr(tool_call, "type", None) != "function":
        raise FunctionCallingProtocolError(
            "Tool call type must be 'function'."
        )
    return tool_call


def _validate_arguments(raw_arguments: object) -> dict[str, str]:
    if not isinstance(raw_arguments, str):
        raise FunctionCallingProtocolError(
            "Tool arguments must be a JSON string."
        )
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as error:
        raise FunctionCallingProtocolError(
            "Tool arguments must be valid JSON."
        ) from error

    if not isinstance(arguments, dict):
        raise FunctionCallingProtocolError(
            "Tool arguments must be a JSON object."
        )
    if set(arguments) != {"sql"}:
        raise FunctionCallingProtocolError(
            "Tool arguments must contain only the 'sql' field."
        )
    sql = arguments["sql"]
    if not isinstance(sql, str) or not sql.strip():
        raise FunctionCallingProtocolError(
            "Tool argument 'sql' must be a non-empty string."
        )
    return {"sql": sql}


def _required_result_field(
    result: JSONDict,
    field_name: str,
    expected_type: type[Any],
) -> Any:
    value = result.get(field_name)
    if not isinstance(value, expected_type):
        raise TypeError(
            f"SQL adapter result field '{field_name}' has an invalid type."
        )
    return value
