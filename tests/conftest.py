"""Shared fixtures. Every test session uses a fresh temporary database and no real API keys.
Agents are tested against a local fake model server that speaks the OpenAI chat-completions protocol."""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["CVSCREEN_DB"] = str(Path(tempfile.mkdtemp()) / "test.sqlite3")
for _k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "CVSCREEN_PASSWORD", "CVSCREEN_PUBLIC_DEMO"):
    os.environ.pop(_k, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import llm  # noqa: E402
from backend.app import app  # noqa: E402


class FakeModel:
    """script(body, n) -> list of (tool, args) for the n-th assistant turn, or ("http", status, message) to fail."""

    def __init__(self):
        self.script = None
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                n = sum(1 for m in body.get("messages", []) if m["role"] == "assistant")
                step = outer.script(body, n)
                if isinstance(step, tuple) and step and step[0] == "http":
                    data = json.dumps({"error": {"message": step[2]}}).encode()
                    self.send_response(step[1])
                else:
                    msg = {"role": "assistant", "content": None,
                           "tool_calls": [{"id": f"c{n}_{i}", "type": "function", "function": {"name": t, "arguments": json.dumps(a)}}
                                          for i, (t, a) in enumerate(step)]}
                    data = json.dumps({"choices": [{"message": msg, "finish_reason": "tool_calls"}],
                                       "usage": {"prompt_tokens": 100, "completion_tokens": 10}}).encode()
                    self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def steps(self, steps):
        """A fixed list of turns, indexed by how many assistant turns the conversation already has."""
        self.script = lambda body, n: steps[n]


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def fake_server():
    return FakeModel()


@pytest.fixture
def fake_model(client, fake_server, monkeypatch):
    """Select the fake model as the active provider for one test; back to offline afterwards."""
    monkeypatch.setattr(llm, "RETRY_WAITS", (0, 0))
    fake_server.requests.clear()
    r = client.put("/api/settings", json={"providers": {"fake": {"label": "Fake", "kind": "openai", "base_url": fake_server.url,
                                                                  "model": "fake", "key_required": False}}, "provider": "fake"})
    assert r.status_code == 200, r.text
    yield fake_server
    client.put("/api/settings", json={"provider": "offline"})


@pytest.fixture
def position(client):
    """A new position with the 14 demo applications extracted (offline: stored gold extractions)."""
    pid = client.post("/api/positions", json={"demo": True}).json()["id"]
    return pid


def ranking(client, pid):
    return {e["name"]: e for e in client.post(f"/api/positions/{pid}/rank", json={}).json()["ranking"]}
