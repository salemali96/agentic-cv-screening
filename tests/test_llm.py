"""Model layer: retries, rate-limit hints, provider errors, usage accounting, provider settings."""
import httpx
import pytest

from backend import llm


class R:
    def __init__(self, status, text="", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}

    def json(self):
        import json
        return json.loads(self.text)


def test_wait_hint_parsing():
    assert llm._wait_hint(R(429, headers={"retry-after": "7"})) == 7
    assert llm._wait_hint(R(429, "Please try again in 1m2.5s")) == pytest.approx(63.0)
    assert llm._wait_hint(R(429, "try again in 450ms")) == pytest.approx(0.95)
    assert llm._wait_hint(R(429, "try again in 10m")) is None or llm._wait_hint(R(429, "try again in 10m")) <= 65
    assert llm._wait_hint(R(503, "busy")) is None


def test_too_large_is_not_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(1) or R(413, '{"error":{"message":"Request too large for model"}}'))
    monkeypatch.setattr(llm, "RETRY_WAITS", (0, 0, 0))
    r = llm._post("http://x", {}, {}, 5, "X")
    assert r.status_code == 413 and len(calls) == 1


def test_temporary_failures_are_retried_and_counted(monkeypatch):
    seq = [R(503, "{}"), R(429, '{"error":{"message":"try again in 0s"}}'), R(200, "{}")]
    monkeypatch.setattr(httpx, "post", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(llm, "RETRY_WAITS", (0, 0, 0))
    with llm.usage_scope() as u:
        r = llm._post("http://x", {}, {}, 5, "X")
    assert r.status_code == 200 and u["retries"] == 2


def test_provider_message_is_surfaced(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: R(429, '{"error":{"message":"TPM limit 8000, requested 9500"}}'))
    monkeypatch.setattr(llm, "RETRY_WAITS", (0,))
    with pytest.raises(llm.LLMError, match="TPM limit 8000"):
        llm._openai_post({"base_url": "http://x/v1", "key": "", "label": "Groq"}, {"model": "m"})


def test_usage_counting_from_responses():
    with llm.usage_scope() as u:
        llm._count_json({"usage": {"prompt_tokens": 120, "completion_tokens": 30}})
        llm._count_json({"usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 5, "thoughtsTokenCount": 5}})
    assert u == {"calls": 2, "input_tokens": 170, "output_tokens": 40, "retries": 0, "waited_seconds": 0.0}
    llm._count(100, 100)  # outside a scope: ignored, no error


def test_bad_provider_configs_are_refused(client):
    r = client.put("/api/settings", json={"providers": {"x": {"label": "X", "kind": "openai"}}})
    assert r.status_code == 400 and "x" not in llm.PROVIDERS
    r = client.put("/api/settings", json={"providers": {"y": {"label": "Y", "kind": "foo"}}})
    assert r.status_code == 400 and "y" not in llm.PROVIDERS


def test_keys_never_reach_the_browser(client, fake_server):
    client.put("/api/settings", json={"providers": {"k": {"label": "K", "kind": "openai", "base_url": fake_server.url, "model": "m", "key": "sk-secret-123"}}})
    body = client.get("/api/settings").text
    assert "sk-secret-123" not in body
    client.delete("/api/settings/providers/k")
