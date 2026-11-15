"""AI model providers: a registry the committee can change at runtime.

A provider is a configuration (name, protocol, base URL, model, key). Three protocols are supported:

  anthropic  - Claude Messages API (official `anthropic` SDK)
  gemini     - Google Gemini REST API
  openai     - any OpenAI-compatible Chat Completions endpoint: OpenAI, Ollama, OpenRouter, Groq, Mistral,
               DeepSeek, Together, LM Studio, vLLM ... (set the base URL)

plus 'offline' (no network; stored extractions for the demo applications).

Each protocol has two adapters: a JSON completion for extraction and a ToolChat for the resolution agent.
Adding a protocol means adding one entry to JSON_CALLS and one ToolChat subclass to CHAT_KINDS.

Keys live in server memory (or come from an environment variable) and are never persisted or sent to the
browser. Non-secret provider settings are saved in the database so custom providers survive a restart.
Every extraction answer is cached by (provider, model, prompt hash), so re-running is reproducible.
"""
import hashlib
import json
import os
import re
from dataclasses import dataclass, field

import httpx

from . import config, db

PROTOCOLS = {"anthropic": "Claude (Anthropic API)", "gemini": "Google Gemini API", "openai": "OpenAI-compatible API"}

# Templates offered when adding a provider. Only the base URL is prefilled; the model is the user's choice.
PRESETS = [
    {"id": "openai", "label": "OpenAI", "kind": "openai", "base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY"},
    {"id": "openrouter", "label": "OpenRouter", "kind": "openai", "base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY"},
    {"id": "groq", "label": "Groq", "kind": "openai", "base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY"},
    {"id": "mistral", "label": "Mistral", "kind": "openai", "base_url": "https://api.mistral.ai/v1", "key_env": "MISTRAL_API_KEY"},
    {"id": "deepseek", "label": "DeepSeek", "kind": "openai", "base_url": "https://api.deepseek.com/v1", "key_env": "DEEPSEEK_API_KEY"},
    {"id": "together", "label": "Together AI", "kind": "openai", "base_url": "https://api.together.xyz/v1", "key_env": "TOGETHER_API_KEY"},
    {"id": "ollama", "label": "Ollama (local)", "kind": "openai", "base_url": "http://localhost:11434/v1", "key_required": False},
    {"id": "lmstudio", "label": "LM Studio (local)", "kind": "openai", "base_url": "http://localhost:1234/v1", "key_required": False},
    {"id": "custom", "label": "Other OpenAI-compatible server", "kind": "openai", "base_url": "", "key_required": False},
]

PROVIDERS = {
    "anthropic": {"label": "Claude (Anthropic API)", "kind": "anthropic", "model": config.ANTHROPIC_MODEL, "key_env": "ANTHROPIC_API_KEY", "builtin": True},
    "gemini": {"label": "Google Gemini", "kind": "gemini", "model": config.GEMINI_MODEL, "key_env": "GEMINI_API_KEY", "builtin": True},
    "openai": {"label": "OpenAI", "kind": "openai", "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
               "model": os.environ.get("OPENAI_MODEL", ""), "key_env": "OPENAI_API_KEY", "builtin": True},
}
_KEYS = {}  # provider id -> key entered in the interface (memory only)
ACTIVE = {"provider": "offline"}
for _pid in ("gemini", "anthropic", "openai"):
    if os.environ.get(PROVIDERS[_pid]["key_env"]) and (PROVIDERS[_pid].get("model") or _pid != "openai"):
        ACTIVE["provider"] = _pid
        break

_SAVED = "settings:providers"
_FIELDS = ("label", "kind", "base_url", "model", "key_env", "key_required")


class LLMError(Exception):
    pass


# ------------------------------------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------------------------------------
def _key(pid):
    p = PROVIDERS.get(pid) or {}
    return _KEYS.get(pid) or (os.environ.get(p["key_env"], "") if p.get("key_env") else "")


def active():
    """Configuration of the selected provider (with its key), or None for offline."""
    if config.PUBLIC_DEMO:
        return None
    pid = ACTIVE["provider"]
    if pid not in PROVIDERS:
        return None
    return {"id": pid, **PROVIDERS[pid], "key": _key(pid)}


def active_label():
    p = active()
    return f"{p['label']} · {p.get('model') or 'no model set'}" if p else "offline"


def load_saved():
    """Restore non-secret provider settings saved earlier (called at startup, after db.init)."""
    saved = db.cache_get(_SAVED) or {}
    for pid, p in (saved.get("providers") or {}).items():
        PROVIDERS[pid] = {**PROVIDERS.get(pid, {}), **{k: v for k, v in p.items() if k in _FIELDS}, "builtin": pid in ("anthropic", "gemini", "openai")}
    if saved.get("active") in PROVIDERS or saved.get("active") == "offline":
        ACTIVE["provider"] = saved["active"]


def _save():
    db.cache_put(_SAVED, {"active": ACTIVE["provider"], "providers": {pid: {k: p.get(k) for k in _FIELDS if k in p} for pid, p in PROVIDERS.items()}})


def settings_public():
    return {"provider": ACTIVE["provider"], "active_label": active_label(), "protocols": PROTOCOLS, "presets": PRESETS,
            "public_demo": config.PUBLIC_DEMO,
            "providers": [{"id": pid, "label": p["label"], "kind": p["kind"], "base_url": p.get("base_url"), "model": p.get("model") or "",
                           "key_set": bool(_key(pid)), "key_required": p.get("key_required", True), "key_env": p.get("key_env"),
                           "builtin": p.get("builtin", False)} for pid, p in PROVIDERS.items()]}


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:40] or "provider"


def update_settings(s):
    """s = {provider?: id, providers?: {id: {label, kind, base_url, model, key}}}. A key of null/absent leaves it unchanged."""
    for pid, p in (s.get("providers") or {}).items():
        if pid == "offline":
            raise LLMError("'offline' is reserved.")
        if pid not in PROVIDERS:
            pid = _slug(pid)
        if pid not in PROVIDERS and p.get("kind") not in PROTOCOLS:
            raise LLMError(f"Unknown protocol '{p.get('kind')}'. Use one of: {', '.join(PROTOCOLS)}.")
        cur = dict(PROVIDERS.get(pid) or {"label": p.get("label") or pid, "kind": p["kind"], "builtin": False})
        for k in ("label", "base_url", "model", "key_required"):
            if k in p and p[k] is not None:
                cur[k] = p[k].strip() if isinstance(p[k], str) else p[k]
        if not cur.get("builtin") and p.get("kind") in PROTOCOLS:
            cur["kind"] = p["kind"]
        if cur["kind"] == "openai" and not cur.get("base_url"):
            raise LLMError(f"Provider '{cur['label']}' needs a base URL.")
        PROVIDERS[pid] = cur  # committed only after validation
        if p.get("key") is not None:
            _KEYS[pid] = p["key"].strip()
    if s.get("provider"):
        if s["provider"] != "offline" and s["provider"] not in PROVIDERS:
            raise LLMError(f"Unknown provider '{s['provider']}'.")
        ACTIVE["provider"] = s["provider"]
    _save()
    return settings_public()


def delete_provider(pid):
    p = PROVIDERS.get(pid)
    if not p:
        raise LLMError(f"Unknown provider '{pid}'.")
    if p.get("builtin"):
        raise LLMError("Built-in providers cannot be removed.")
    PROVIDERS.pop(pid)
    _KEYS.pop(pid, None)
    if ACTIVE["provider"] == pid:
        ACTIVE["provider"] = "offline"
    _save()
    return settings_public()


def _check(p):
    if not p.get("model"):
        raise LLMError(f"No model is set for {p['label']}. Enter one under AI model.")
    if p.get("key_required", True) and not p["key"]:
        raise LLMError(f"No API key is set for {p['label']}.")


# ------------------------------------------------------------------------------------------------
# JSON completion (extraction)
# ------------------------------------------------------------------------------------------------
def parse_json(text):
    text = (text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except ValueError:
            pass
    a, b = text.find("{"), text.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(text[a:b + 1])
        except ValueError:
            pass
    raise LLMError("The model's reply was not valid JSON.")


def _anthropic_client(p):
    import anthropic
    return anthropic, anthropic.Anthropic(api_key=p["key"], max_retries=3, base_url=p.get("base_url") or None)


def _anthropic_errors(anthropic, e):
    if isinstance(e, anthropic.AuthenticationError):
        return LLMError("The Anthropic API key was rejected.")
    if isinstance(e, anthropic.RateLimitError):
        return LLMError("Anthropic rate limit reached; try again shortly.")
    if isinstance(e, anthropic.APIStatusError):
        return LLMError(f"Anthropic error {e.status_code}: {str(e.message)[:300]}")
    if isinstance(e, anthropic.APIConnectionError):
        return LLMError("Could not reach the Anthropic API.")
    return None


def _json_anthropic(p, prompt):
    anthropic, client = _anthropic_client(p)
    try:
        with client.messages.stream(model=p["model"], max_tokens=32000, messages=[{"role": "user", "content": prompt}]) as stream:
            msg = stream.get_final_message()
        _count_anthropic(msg)
    except anthropic.APIError as e:
        raise (_anthropic_errors(anthropic, e) or LLMError(str(e)[:300])) from e
    if msg.stop_reason == "refusal":
        raise LLMError("Claude declined to process these documents.")
    return "".join(b.text for b in msg.content if b.type == "text")


# ------------------------------------------------------------------------------------------------
# Usage accounting: model calls, tokens and retry waits, counted per thread inside usage_scope()
# (a background job opens one scope per run; outside a scope nothing is counted).
# ------------------------------------------------------------------------------------------------
import contextlib
import threading

_usage_local = threading.local()


@contextlib.contextmanager
def usage_scope():
    u = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "retries": 0, "waited_seconds": 0.0}
    prev = getattr(_usage_local, "u", None)
    _usage_local.u = u
    try:
        yield u
    finally:
        _usage_local.u = prev


def _count(inp=0, out=0, calls=1, retries=0, waited=0.0):
    u = getattr(_usage_local, "u", None)
    if u is not None:
        u["calls"] += calls
        u["input_tokens"] += int(inp or 0)
        u["output_tokens"] += int(out or 0)
        u["retries"] += retries
        u["waited_seconds"] = round(u["waited_seconds"] + waited, 1)


def _count_json(j):
    """Token counts from a Gemini or OpenAI-style JSON response."""
    if not isinstance(j, dict):
        return
    if "usageMetadata" in j:
        m = j["usageMetadata"]
        _count(m.get("promptTokenCount"), (m.get("candidatesTokenCount") or 0) + (m.get("thoughtsTokenCount") or 0))
    else:
        m = j.get("usage") or {}
        _count(m.get("prompt_tokens"), m.get("completion_tokens"))


def _count_anthropic(msg):
    u = getattr(msg, "usage", None)
    _count(getattr(u, "input_tokens", 0) + (getattr(u, "cache_read_input_tokens", 0) or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0),
           getattr(u, "output_tokens", 0))


RETRY_STATUS = (429, 500, 502, 503, 504)
RETRY_WAITS = (3, 8, 15, 30, 45)  # seconds between attempts for temporary failures (~100 s in total: overload spikes often pass)


_TOO_LARGE = ("request too large", "too many tokens", "context_length", "maximum context", "reduce the length", "request_too_large")


def _provider_message(r):
    """The human-readable error text a provider put in its JSON body, if any."""
    try:
        j = r.json()
        e = j.get("error") if isinstance(j, dict) else None
        msg = (e.get("message") if isinstance(e, dict) else e) or (j.get("message") if isinstance(j, dict) else None)
        return str(msg)[:400] if msg else r.text[:400]
    except ValueError:
        return r.text[:400]


def _too_large(r):
    return r.status_code in (400, 413, 429) and any(x in r.text.lower() for x in _TOO_LARGE)


def _wait_hint(r):
    """Seconds the provider asked us to wait (Retry-After header or 'try again in 7.5s' in the message), capped at 65."""
    ra = r.headers.get("retry-after", "")
    try:
        return min(65.0, float(ra))
    except ValueError:
        pass
    m = re.search(r"try again in\s+(?:(\d+)m)?\s*([\d.]+)\s*(ms|s)", r.text, re.I)
    if m:
        secs = (int(m.group(1) or 0) * 60) + float(m.group(2)) / (1000 if m.group(3).lower() == "ms" else 1)
        return min(65.0, secs + 0.5)
    return None


def _post(url, body, headers, timeout, label):
    """POST with retries for temporary failures (overload, rate limit, timeouts, dropped connections).
    Waits as long as the provider asks. A request that is too large for the limit is not retried (it can never fit).
    Returns the final httpx response; network failures that persist become LLMError."""
    import time
    wait = 0
    for i in range(len(RETRY_WAITS) + 1):
        if i:
            _count(calls=0, retries=1, waited=wait)
        if wait:
            time.sleep(wait)
        try:
            r = httpx.post(url, json=body, headers=headers, timeout=httpx.Timeout(timeout, connect=15))
        except (httpx.TimeoutException, httpx.TransportError) as e:
            if i == len(RETRY_WAITS):
                raise LLMError(f"{label} did not respond after {i + 1} attempts ({type(e).__name__}).") from e
            wait = RETRY_WAITS[i]
            continue
        if r.status_code not in RETRY_STATUS or _too_large(r) or i == len(RETRY_WAITS):
            return r
        wait = max(RETRY_WAITS[i], _wait_hint(r) or 0)
    return r


def _gemini_fail(r):
    if r.status_code == 200:
        return
    if r.status_code in RETRY_STATUS:
        raise LLMError(f"Gemini is overloaded or rate-limited right now (error {r.status_code}, still failing after {len(RETRY_WAITS) + 1} attempts). "
                       f"Try again later or choose another Gemini model. Gemini says: {_provider_message(r)}")
    if r.status_code in (401, 403):
        raise LLMError("Gemini rejected the API key.")
    raise LLMError(f"Gemini error {r.status_code}: {r.text[:300]}")


def _json_gemini(p, prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{p['model']}:generateContent"
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    r = _post(url, body, {"x-goog-api-key": p["key"]}, 180, "Gemini")
    _gemini_fail(r)
    _count_json(r.json())
    parts = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    return "".join(x.get("text", "") for x in parts if not x.get("thought"))


def _openai_post(p, body, timeout=300):
    """POST /chat/completions. Optional parameters that a server rejects (temperature, response_format) are dropped and retried."""
    url = p["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {p['key']}"} if p["key"] else {}
    for _ in range(3):
        r = _post(url, body, headers, timeout, p["label"])
        if r.status_code == 200:
            j = r.json()
            _count_json(j)
            return j
        drop = [k for k in ("temperature", "response_format") if k in body and k in r.text]
        if r.status_code == 400 and drop:
            body = {k: v for k, v in body.items() if k not in drop}
            continue
        break
    if r.status_code in (401, 403):
        raise LLMError(f"{p['label']} rejected the API key.")
    msg = _provider_message(r)
    if _too_large(r):
        raise LLMError(f"The request is larger than {p['label']} allows for this model or plan. {p['label']} says: {msg}")
    if r.status_code == 429:
        raise LLMError(f"{p['label']} rate limit reached (still limited after {len(RETRY_WAITS) + 1} attempts). {p['label']} says: {msg}")
    if r.status_code in RETRY_STATUS:
        raise LLMError(f"{p['label']} is unavailable or overloaded right now (error {r.status_code}). Try again later or choose another model. {p['label']} says: {msg}")
    raise LLMError(f"{p['label']} error {r.status_code}: {msg}")


def _json_openai(p, prompt):
    j = _openai_post(p, {"model": p["model"], "messages": [{"role": "user", "content": prompt}], "temperature": 0,
                         "response_format": {"type": "json_object"}})
    return ((j.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


JSON_CALLS = {"anthropic": _json_anthropic, "gemini": _json_gemini, "openai": _json_openai}


def complete_json(prompt, purpose, offline_key=None, fresh=False):
    """Return (parsed_json, meta). offline_key lets the offline provider find a stored answer.
    fresh=True asks the model again instead of returning the cached answer (the new answer replaces it)."""
    p = active()
    pid, model = (p["id"], p.get("model") or "") if p else ("offline", "")
    h = hashlib.sha256(f"{pid}|{model}|{prompt}".encode()).hexdigest()
    cached = None if (fresh and p) else db.cache_get(h)
    if cached is not None:
        return cached, {"provider": pid, "model": model, "cached": True}
    if not p:
        if offline_key:
            stored = db.cache_get(f"offline:{purpose}:{offline_key}")
            if stored is not None:
                return stored, {"provider": "offline", "model": "stored extraction", "cached": True}
        raise LLMError("Offline mode has no stored extraction for these documents. Choose an AI provider under AI model.")
    _check(p)
    data = parse_json(JSON_CALLS[p["kind"]](p, prompt))
    db.cache_put(h, data)
    return data, {"provider": pid, "model": model, "cached": False}


# ------------------------------------------------------------------------------------------------
# Tool-use conversations (resolution agent). The agent loop in backend/agent.py is protocol-neutral:
#   chat = tool_chat(system, tools, first_user_text)
#   turn = chat.step()            -> Turn(texts, calls, stop)
#   chat.add_results([(call, result_dict, is_error), ...])
# Tools are given in one neutral form: {name, description, input_schema (JSON Schema)}.
# ------------------------------------------------------------------------------------------------
@dataclass
class Call:
    id: str
    name: str
    args: dict


@dataclass
class Turn:
    texts: list = field(default_factory=list)
    calls: list = field(default_factory=list)
    stop: str = "end"  # end | tool_use | refusal | max_tokens | error:<detail>


class ToolChat:
    def __init__(self, p, system, tools, first_user):
        _check(p)
        self.p, self.system, self.tools = p, system, tools
        self.start(first_user)

    def start(self, first_user):
        raise NotImplementedError

    def step(self):
        raise NotImplementedError

    def add_results(self, results):
        raise NotImplementedError


_FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
_EFFORT_MODELS = ("claude-fable-5", "claude-opus-5", "claude-sonnet-5", "claude-haiku-5", "claude-opus-4-6", "claude-opus-4-7",
                  "claude-opus-4-8", "claude-sonnet-4-6")


class AnthropicChat(ToolChat):
    def start(self, first_user):
        self.anthropic, self.client = _anthropic_client(self.p)
        self.messages = [{"role": "user", "content": first_user}]

    def step(self):
        model = self.p["model"]
        params = {"model": model, "max_tokens": 16000, "system": self.system, "tools": self.tools, "messages": self.messages}
        betas = []
        if model.startswith(_EFFORT_MODELS):
            params["output_config"] = {"effort": "medium"}
        if model in _FALLBACK_MODELS:
            # On a safety-classifier decline the API re-runs the turn on a fallback model instead of stopping.
            betas.append("server-side-fallback-2026-07-01")
            params["fallbacks"] = "default"
        for _ in range(5):  # pause_turn: send the paused turn back so the server continues it
            try:
                resp = self.client.beta.messages.create(betas=betas, **params)
                _count_anthropic(resp)
            except self.anthropic.APIError as e:
                raise (_anthropic_errors(self.anthropic, e) or LLMError(str(e)[:300])) from e
            self.messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "pause_turn":
                break
        texts = [b.text.strip() for b in resp.content if b.type == "text" and b.text.strip()]
        if resp.stop_reason in ("refusal", "max_tokens"):
            return Turn(texts, [], resp.stop_reason)
        calls = [Call(b.id, b.name, b.input if isinstance(b.input, dict) else {}) for b in resp.content if b.type == "tool_use"]
        return Turn(texts, calls, "tool_use" if calls else "end")

    def add_results(self, results):
        self.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": c.id, "content": _compact(res), "is_error": err}
            for c, res, err in results]})


def _compact(res):
    return json.dumps(res, ensure_ascii=False, default=str, separators=(",", ":"))


def _strip_additional(s):
    if isinstance(s, dict):
        return {k: _strip_additional(v) for k, v in s.items() if k != "additionalProperties"}
    if isinstance(s, list):
        return [_strip_additional(x) for x in s]
    return s


class GeminiChat(ToolChat):
    def start(self, first_user):
        self.contents = [{"role": "user", "parts": [{"text": first_user}]}]
        self.decl = []
        for t in self.tools:
            d = {"name": t["name"], "description": t["description"]}
            if t["input_schema"].get("properties"):  # Gemini rejects an object schema with no properties
                d["parameters"] = _strip_additional(t["input_schema"])
            self.decl.append(d)

    def step(self):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.p['model']}:generateContent"
        body = {"systemInstruction": {"parts": [{"text": self.system}]}, "contents": self.contents,
                "tools": [{"functionDeclarations": self.decl}], "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}}}
        r = _post(url, body, {"x-goog-api-key": self.p["key"]}, 180, "Gemini")
        _gemini_fail(r)
        _count_json(r.json())
        cand = (r.json().get("candidates") or [{}])[0]
        content = cand.get("content") or {}
        content.setdefault("role", "model")
        content.setdefault("parts", [])
        self.contents.append(content)  # kept whole: thought signatures must be sent back
        texts = [x["text"].strip() for x in content["parts"] if x.get("text", "").strip() and not x.get("thought")]
        calls = [Call(fc.get("id") or f"~gen{len(self.contents)}_{i}", fc.get("name"), fc.get("args") or {})
                 for i, fc in enumerate(x["functionCall"] for x in content["parts"] if "functionCall" in x)]
        finish = cand.get("finishReason")
        if not calls and finish not in (None, "STOP"):
            return Turn(texts, [], "max_tokens" if finish == "MAX_TOKENS" else ("refusal" if finish == "SAFETY" else f"error:{finish}"))
        return Turn(texts, calls, "tool_use" if calls else "end")

    def add_results(self, results):
        parts = []
        for c, res, _ in results:
            fr = {"name": c.name, "response": {"result": res}}
            if not c.id.startswith("~gen"):
                fr["id"] = c.id
            parts.append({"functionResponse": fr})
        self.contents.append({"role": "user", "parts": parts})


class OpenAIChat(ToolChat):
    def start(self, first_user):
        self.messages = [{"role": "system", "content": self.system}, {"role": "user", "content": first_user}]
        self.fns = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
                    for t in self.tools]

    def step(self):
        msgs = [{k: v for k, v in m.items() if not k.startswith("_")} for m in self.messages]
        j = _openai_post(self.p, {"model": self.p["model"], "messages": msgs, "tools": self.fns, "tool_choice": "auto"})
        ch = (j.get("choices") or [{}])[0]
        msg = ch.get("message") or {"role": "assistant", "content": ""}
        msg = {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")}
        msg["role"] = "assistant"
        self.messages.append(msg)
        texts = [msg["content"].strip()] if isinstance(msg.get("content"), str) and msg["content"].strip() else []
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            calls.append(Call(tc.get("id"), fn.get("name"), args if isinstance(args, dict) else {}))
        finish = ch.get("finish_reason")
        if not calls and finish == "length":
            return Turn(texts, [], "max_tokens")
        if not calls and finish == "content_filter":
            return Turn(texts, [], "refusal")
        return Turn(texts, calls, "tool_use" if calls else "end")

    KEEP_FULL = 6  # most recent tool results kept in full; older ones are shortened to save tokens

    def add_results(self, results):
        for c, res, _ in results:
            self.messages.append({"role": "tool", "tool_call_id": c.id, "content": _compact(res)})
        tool_msgs = [m for m in self.messages if m["role"] == "tool"]
        for m in tool_msgs[:-self.KEEP_FULL]:
            if len(m["content"]) > 300 and not m.get("_short"):
                m["content"] = m["content"][:300] + " …[older result shortened to save tokens; call the tool again if you need it]"
                m["_short"] = True


CHAT_KINDS = {"anthropic": AnthropicChat, "gemini": GeminiChat, "openai": OpenAIChat}


def tool_chat(system, tools, first_user):
    """Start a tool-use conversation with the selected provider, or return None in offline mode."""
    p = active()
    return CHAT_KINDS[p["kind"]](p, system, tools, first_user) if p else None
