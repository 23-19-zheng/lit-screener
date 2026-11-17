from types import SimpleNamespace

import pytest

from litreview import llm


class APIError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class FakeCompletions:
    def __init__(self, errors):
        self.errors, self.calls = list(errors), 0

    def create(self, **kwargs):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        content = '{"ok": true}' if kwargs.get("response_format") else "text"
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content), finish_reason="stop")], usage=None)


def client(monkeypatch, errors=(), **spec):
    monkeypatch.setenv("FAKE_KEY", "k")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    c = llm.LLMClient({"provider": "openai", "model": "m", "api_key_env": "FAKE_KEY", **spec})
    fake = FakeCompletions(errors)
    c._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    return c, fake


def test_empty_temperature_means_provider_default(monkeypatch):
    c, _ = client(monkeypatch, temperature="")
    assert c.temperature is None


def test_sdk_builtin_retries_are_disabled(monkeypatch):
    monkeypatch.setenv("FAKE_KEY", "k")
    c = llm.LLMClient({"provider": "openai", "model": "m", "api_key_env": "FAKE_KEY"})
    assert c._client.max_retries == 0  # 只保留一层重试，避免请求数被放大


def test_complete_honors_configured_retry_delays(monkeypatch):
    c, fake = client(monkeypatch, errors=[ConnectionError()] * 5, retry_delays=[1])
    with pytest.raises(RuntimeError):
        c.complete("s", "u")
    assert fake.calls == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_errors_are_not_retried(monkeypatch, status):
    c, fake = client(monkeypatch, errors=[APIError(status)] * 5)
    with pytest.raises(RuntimeError):
        c.complete("s", "u")
    assert fake.calls == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_rate_limit_and_server_errors_are_retried(monkeypatch, status):
    c, fake = client(monkeypatch, errors=[APIError(status)])
    assert c.complete("s", "u") == "text"
    assert fake.calls == 2


def test_rejected_json_mode_is_remembered(monkeypatch):
    c, fake = client(monkeypatch, errors=[APIError(400)])
    with pytest.raises(APIError):
        c.complete_json("s", "u")
    assert c.structured == "text"  # 之后调用方直接走文本路径，不再每篇白调一次


def test_transient_json_failure_keeps_json_mode(monkeypatch):
    c, _ = client(monkeypatch, errors=[APIError(503)])
    with pytest.raises(APIError):
        c.complete_json("s", "u")
    assert c.structured == "auto"
