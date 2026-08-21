"""Minimal DeepSeek provider adapters for structured and plain-text calls."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from openai import OpenAI

from data_analysis_agent.observability import (
    LLMCallObservation,
    current_observability_stage,
    observability_is_active,
    record_llm_call,
)


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"
PROJECT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


class DeepSeekTextToSQLModel:
    """Call DeepSeek once and return its response content unchanged."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        env_path: str | Path = PROJECT_ENV_PATH,
    ) -> None:
        if client is not None:
            self._client = client
            return

        load_dotenv(dotenv_path=env_path, override=False)
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key or not api_key.strip():
            raise ValueError(
                "DEEPSEEK_API_KEY is required in the environment or project .env file."
            )

        self._client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)

    def __call__(self, prompt: str) -> str:
        timing = _start_provider_timing()
        response = None
        try:
            response = self._client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not isinstance(content, str) or not content:
                raise ValueError("DeepSeek returned empty response content.")
        except Exception:
            _record_provider_call(timing, status="error", response=response)
            raise
        _record_provider_call(timing, status="success", response=response)
        return content


class DeepSeekNaturalLanguageModel:
    """Call DeepSeek once and return plain-text response content unchanged."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        env_path: str | Path = PROJECT_ENV_PATH,
    ) -> None:
        if client is not None:
            self._client = client
            return

        load_dotenv(dotenv_path=env_path, override=False)
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key or not api_key.strip():
            raise ValueError(
                "DEEPSEEK_API_KEY is required in the environment or project .env file."
            )

        self._client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)

    def __call__(self, prompt: str) -> str:
        timing = _start_provider_timing()
        response = None
        try:
            response = self._client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content
            if not isinstance(content, str) or not content.strip():
                raise ValueError("DeepSeek returned empty response content.")
        except Exception:
            _record_provider_call(timing, status="error", response=response)
            raise
        _record_provider_call(timing, status="success", response=response)
        return content


def _start_provider_timing() -> tuple[str, float] | None:
    stage = current_observability_stage()
    if not observability_is_active() or stage is None:
        return None
    return stage, time.perf_counter()


def _record_provider_call(
    timing: tuple[str, float] | None,
    *,
    status: Literal["success", "error"],
    response: object | None = None,
) -> None:
    if timing is None:
        return
    stage, started_at = timing
    usage = getattr(response, "usage", None)
    record_llm_call(
        LLMCallObservation(
            stage=stage,
            model=DEEPSEEK_MODEL,
            latency_ms=max(0.0, (time.perf_counter() - started_at) * 1000.0),
            prompt_tokens=_usage_token(usage, "prompt_tokens"),
            completion_tokens=_usage_token(usage, "completion_tokens"),
            total_tokens=_usage_token(usage, "total_tokens"),
            status=status,
        )
    )


def _usage_token(usage: object | None, field_name: str) -> int | None:
    value = getattr(usage, field_name, None)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None
