"""Tests for the minimal DeepSeek Text-to-SQL provider adapter."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import data_analysis_agent.deepseek_provider as provider_module
from data_analysis_agent.deepseek_provider import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DeepSeekNaturalLanguageModel,
    DeepSeekTextToSQLModel,
)
from data_analysis_agent.schema import DatabaseSchema
from data_analysis_agent.sql_generator import generate_sql


class FakeCompletions:
    def __init__(self, *, content: str | None = None, error: Exception | None = None):
        self.content = content
        self.error = error
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FakeClient:
    def __init__(self, completions: FakeCompletions):
        self.chat = SimpleNamespace(completions=completions)


def test_provider_passes_prompt_model_and_json_output() -> None:
    content = '{"status":"success","sql":"SELECT COUNT(*) FROM orders"}'
    completions = FakeCompletions(content=content)
    model = DeepSeekTextToSQLModel(client=FakeClient(completions))

    returned_content = model("Generate JSON SQL for the provided schema.")

    assert returned_content == content
    assert completions.calls == [
        {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": "Generate JSON SQL for the provided schema.",
                }
            ],
            "response_format": {"type": "json_object"},
        }
    ]
    assert DEEPSEEK_MODEL == "deepseek-v4-flash"


def test_provider_uses_official_base_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    constructor_arguments: dict[str, str] = {}

    class FakeOpenAI:
        def __init__(self, *, api_key: str, base_url: str):
            constructor_arguments.update(api_key=api_key, base_url=base_url)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-placeholder")
    monkeypatch.setattr(provider_module, "OpenAI", FakeOpenAI)

    DeepSeekTextToSQLModel(env_path=tmp_path / "missing.env")

    assert constructor_arguments["api_key"] == "unit-test-placeholder"
    assert constructor_arguments["base_url"] == DEEPSEEK_BASE_URL
    assert DEEPSEEK_BASE_URL == "https://api.deepseek.com"


def test_missing_api_key_has_clear_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY is required"):
        DeepSeekTextToSQLModel(env_path=tmp_path / "missing.env")


def test_provider_exception_becomes_generation_model_error() -> None:
    completions = FakeCompletions(error=RuntimeError("DeepSeek unavailable"))
    model = DeepSeekTextToSQLModel(client=FakeClient(completions))

    result = generate_sql(
        "How many orders are in the dataset?",
        DatabaseSchema(objects=()),
        model,
    )

    assert result.status == "error"
    assert result.sql is None
    assert result.error is not None
    assert result.error.code == "model_error"
    assert result.error.message == "DeepSeek unavailable"


def test_natural_language_provider_returns_plain_text_without_json_mode() -> None:
    content = "The dataset contains 99441 orders."
    completions = FakeCompletions(content=content)
    model = DeepSeekNaturalLanguageModel(client=FakeClient(completions))

    returned_content = model("Summarize the validated result.")

    assert returned_content == content
    assert completions.calls == [
        {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": "Summarize the validated result.",
                }
            ],
        }
    ]
    assert "response_format" not in completions.calls[0]


def test_natural_language_provider_reuses_key_and_official_base_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    constructor_arguments: dict[str, str] = {}

    class FakeOpenAI:
        def __init__(self, *, api_key: str, base_url: str):
            constructor_arguments.update(api_key=api_key, base_url=base_url)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-placeholder")
    monkeypatch.setattr(provider_module, "OpenAI", FakeOpenAI)

    DeepSeekNaturalLanguageModel(env_path=tmp_path / "missing.env")

    assert constructor_arguments == {
        "api_key": "unit-test-placeholder",
        "base_url": DEEPSEEK_BASE_URL,
    }


@pytest.mark.parametrize("content", [None, "", "   "])
def test_natural_language_provider_rejects_empty_content(
    content: str | None,
) -> None:
    model = DeepSeekNaturalLanguageModel(
        client=FakeClient(FakeCompletions(content=content))
    )

    with pytest.raises(ValueError, match="empty response content"):
        model("Summarize the validated result.")
