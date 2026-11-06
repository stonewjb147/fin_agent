"""The HTTP client is small, but its contract (payload, errors, no key leak) matters."""

from __future__ import annotations

import os

import pytest

from finagent.agent.llm import DeepSeekClient, LLMConfig, LLMError, config_from_env
from finagent.integrations.feishu import load_env


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def _config(**overrides) -> LLMConfig:
    base = {"api_key": "sk-test", "base_url": "https://example.test/v1"}
    base.update(overrides)
    return LLMConfig(**base)


def test_client_posts_openai_compatible_payload_without_logging_the_key():
    session = FakeSession(
        FakeResponse(body={"choices": [{"message": {"content": "  报告正文  "}}]})
    )
    client = DeepSeekClient(_config(model="deepseek-chat"), session=session)

    text = client.complete("system", "user")

    assert text == "报告正文"
    url, kwargs = session.calls[0]
    assert url == "https://example.test/v1/chat/completions"
    assert kwargs["json"]["model"] == "deepseek-chat"
    assert kwargs["json"]["messages"][0] == {"role": "system", "content": "system"}
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
    assert "sk-test" not in repr(kwargs["json"])


def test_non_200_is_an_llm_error():
    client = DeepSeekClient(_config(), session=FakeSession(FakeResponse(status_code=401)))

    with pytest.raises(LLMError, match="HTTP 401"):
        client.complete("s", "u")


def test_malformed_or_empty_response_is_an_llm_error():
    malformed = DeepSeekClient(_config(), session=FakeSession(FakeResponse(body={"x": 1})))
    with pytest.raises(LLMError, match="message content"):
        malformed.complete("s", "u")

    empty = DeepSeekClient(
        _config(), session=FakeSession(FakeResponse(body={"choices": [{"message": {"content": ""}}]}))
    )
    with pytest.raises(LLMError, match="empty"):
        empty.complete("s", "u")


def test_client_requires_a_key():
    with pytest.raises(LLMError, match="DEEPSEEK_API_KEY"):
        DeepSeekClient(LLMConfig(api_key=""))


def test_load_env_uses_the_last_duplicate_but_never_overrides_process_env(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("DUP_KEY=first\nDUP_KEY=second\n", encoding="utf-8")
    monkeypatch.delenv("DUP_KEY", raising=False)

    load_env(path)
    assert os.environ["DUP_KEY"] == "second"

    monkeypatch.setenv("DUP_KEY", "already-set")
    load_env(path)
    assert os.environ["DUP_KEY"] == "already-set"


def test_config_from_env_reads_only_known_names():
    cfg = config_from_env(
        {
            "DEEPSEEK_API_KEY": "sk-test",
            "DEEPSEEK_BASE_URL": "https://example.test",
            "FINAGENT_LLM_MODEL": "deepseek-reasoner",
        }
    )
    assert cfg.configured
    assert cfg.model == "deepseek-reasoner"
    assert cfg.endpoint() == "https://example.test/chat/completions"
