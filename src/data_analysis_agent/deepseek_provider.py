"""Minimal DeepSeek provider adapter for Text-to-SQL generation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


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
        response = self._client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content:
            raise ValueError("DeepSeek returned empty response content.")
        return content
