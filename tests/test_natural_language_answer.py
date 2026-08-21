"""Tests for one-shot evidence-bound natural-language presentation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from data_analysis_agent.answer_synthesis import AnswerSynthesis
from data_analysis_agent.natural_language_answer import (
    NaturalLanguageAnswer,
    build_natural_language_prompt,
    generate_natural_language_answer,
)


QUESTION = "How many orders are in the dataset?"
SYNTHESIS = AnswerSynthesis("success", "Result: 99441", ())


def test_valid_result_calls_model_once() -> None:
    prompts: list[str] = []

    def model(prompt: str) -> str:
        prompts.append(prompt)
        return "There are 99441 orders."

    result = generate_natural_language_answer(
        QUESTION,
        "valid",
        SYNTHESIS,
        model,
    )

    assert result == NaturalLanguageAnswer(
        "success",
        "There are 99441 orders.",
        None,
    )
    assert len(prompts) == 1


def test_valid_with_warnings_calls_model_once_and_includes_warnings() -> None:
    synthesis = AnswerSynthesis("success", "order_status | order_count", ("Notice.",))
    prompts: list[str] = []

    result = generate_natural_language_answer(
        QUESTION,
        "valid_with_warnings",
        synthesis,
        lambda prompt: prompts.append(prompt) or "Answer.",
    )

    assert result.status == "success"
    assert len(prompts) == 1
    assert "- Notice." in prompts[0]


def test_invalid_validation_skips_model() -> None:
    result = generate_natural_language_answer(
        QUESTION,
        "invalid",
        SYNTHESIS,
        lambda prompt: pytest.fail("model must not be called"),
    )

    assert result == NaturalLanguageAnswer("skipped", None, None)


def test_blocked_synthesis_skips_model() -> None:
    result = generate_natural_language_answer(
        QUESTION,
        "valid",
        AnswerSynthesis("blocked", "Cannot answer.", ()),
        lambda prompt: pytest.fail("model must not be called"),
    )

    assert result == NaturalLanguageAnswer("skipped", None, None)


def test_missing_model_is_skipped() -> None:
    assert generate_natural_language_answer(
        QUESTION,
        "valid",
        SYNTHESIS,
        None,
    ) == NaturalLanguageAnswer("skipped", None, None)


def test_model_exception_falls_back_without_retry() -> None:
    calls = 0

    def model(prompt: str) -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("private provider detail")

    result = generate_natural_language_answer(
        QUESTION,
        "valid",
        SYNTHESIS,
        model,
    )

    assert result == NaturalLanguageAnswer(
        "fallback",
        SYNTHESIS.answer,
        "model_error: RuntimeError",
    )
    assert calls == 1
    assert "private provider detail" not in result.error


@pytest.mark.parametrize("response", ["", "   ", None, {"answer": "text"}])
def test_invalid_model_output_falls_back_to_deterministic_answer(
    response: object,
) -> None:
    result = generate_natural_language_answer(
        QUESTION,
        "valid",
        SYNTHESIS,
        lambda prompt: response,
    )

    assert result == NaturalLanguageAnswer(
        "fallback",
        SYNTHESIS.answer,
        "invalid_model_output",
    )


def test_prompt_contains_question_and_deterministic_validated_answer() -> None:
    prompt = build_natural_language_prompt(
        QUESTION,
        "valid",
        SYNTHESIS,
    )

    assert QUESTION in prompt
    assert SYNTHESIS.answer in prompt
    assert "Validation status:\nvalid" in prompt


def test_prompt_contains_evidence_only_and_no_causal_invention_constraints() -> None:
    prompt = build_natural_language_prompt(
        QUESTION,
        "valid",
        SYNTHESIS,
    )

    assert "Use ONLY the supplied validated evidence." in prompt
    assert "Do not recompute metrics." in prompt
    assert "Do not change numeric values" in prompt
    assert "Do not infer business causes or causal relationships." in prompt


def test_prompt_excludes_secrets_and_evaluation_metadata() -> None:
    prompt = build_natural_language_prompt(
        "Question DEEPSEEK_API_KEY=super-secret",
        "valid",
        SYNTHESIS,
    )

    assert "super-secret" not in prompt
    assert "DEEPSEEK_API_KEY" not in prompt
    assert ".env" not in prompt
    assert "reference_sql" not in prompt
    assert "held_out" not in prompt
    assert "expected_answer" not in prompt


def test_zh_locale_requests_concise_simplified_chinese() -> None:
    prompt = build_natural_language_prompt(
        "数据集中有多少订单？",
        "valid",
        AnswerSynthesis("success", "结果：99441", ()),
        "zh-CN",
    )

    assert "Simplified Chinese" in prompt
    assert "1 to 3 short paragraphs" in prompt


def test_en_locale_requests_concise_english() -> None:
    prompt = build_natural_language_prompt(QUESTION, "valid", SYNTHESIS, "en")

    assert "natural answer in English" in prompt
    assert "1 to 3 short paragraphs" in prompt


def test_natural_language_answer_is_frozen() -> None:
    result = NaturalLanguageAnswer("success", "Answer.", None)

    with pytest.raises(FrozenInstanceError):
        result.answer = "Changed."
