"""Minimal LLM client for the narrative report.

DeepSeek exposes an OpenAI-compatible endpoint, so plain `requests` is enough
and the Docker image needs no new dependency. The API key is read from the
environment, sent only in the Authorization header, and never printed, logged
or written into the report metadata.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import requests

from finagent.integrations.feishu import load_env

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


class LLMError(RuntimeError):
    """A failed or unusable LLM call."""


@dataclass
class LLMConfig:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = 90.0
    temperature: float = 0.2
    max_tokens: int = 4096

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def endpoint(self) -> str:
        base = self.base_url.rstrip("/")
        return f"{base}/chat/completions"


def config_from_env(env: Mapping[str, str] | None = None) -> LLMConfig:
    if env is None:
        load_env()
        env = os.environ
    return LLMConfig(
        api_key=env.get("DEEPSEEK_API_KEY", ""),
        base_url=env.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL,
        model=env.get("FINAGENT_LLM_MODEL") or env.get("DEEPSEEK_MODEL") or DEFAULT_MODEL,
    )


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str) -> str: ...


class DeepSeekClient:
    """Chat-completions client; inject `session` in tests."""

    def __init__(self, config: LLMConfig, session: requests.Session | None = None):
        if not config.configured:
            raise LLMError("DEEPSEEK_API_KEY is not configured")
        self.config = config
        self.model = config.model
        self._session = session or requests.Session()

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": False,
        }
        try:
            response = self._session.post(
                self.config.endpoint(),
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.config.timeout,
            )
        except requests.RequestException as exc:
            raise LLMError(f"request failed: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise LLMError(f"LLM returned HTTP {response.status_code}")
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM response did not contain message content") from exc
        text = (content or "").strip()
        if not text:
            raise LLMError("LLM returned an empty response")
        return text
