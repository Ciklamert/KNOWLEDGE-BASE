"""Minimal client for the corporate OpenAI-compatible API: /chat/completions (with optional tool calling)
and /embeddings. It is the only code in this server that talks to the AI service."""
from __future__ import annotations

import threading

import httpx

from . import settings as cfg


class LLMError(RuntimeError):
    def __init__(self, msg: str, status: int = 0):
        super().__init__(msg)
        self.status = status


def _client() -> httpx.Client:
    return httpx.Client(verify=cfg.tls_verify(), trust_env=True)


def _post(url: str, key: str, body: dict, timeout: float) -> dict:
    if not url.startswith("http"):
        raise LLMError("BRAIN_LLM_BASE_URL is not set")
    try:
        with _client() as c:
            r = c.post(url, json=body, timeout=timeout, headers={"Authorization": f"Bearer {key}"})
    except httpx.TimeoutException:
        raise LLMError(f"timeout after {timeout:.0f}s calling {url}") from None
    except httpx.HTTPError as exc:
        raise LLMError(f"cannot reach {url}: {exc}") from None
    if r.status_code >= 400:
        raise LLMError(f"{url} -> HTTP {r.status_code}: {r.text[:400]}", r.status_code)
    try:
        return r.json()
    except ValueError:
        raise LLMError(f"{url} returned non-JSON: {r.text[:200]}") from None


_meter = threading.local()


def start_meter() -> None:
    """Count the chat calls and tokens of the current thread (one ask / enhance / guide / requirements run)."""
    _meter.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def read_meter() -> dict:
    return dict(getattr(_meter, "usage", None) or {})


def chat(messages: list[dict], model: str, timeout: float | None = None, max_tokens: int = 1000,
         temperature: float = 0.1, tools: list[dict] | None = None) -> dict:
    """Return the assistant message dict ({"content": ..., "tool_calls": [...]})."""
    body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if tools:
        body.update(tools=tools, tool_choice="auto")
    base = cfg.get("BRAIN_LLM_BASE_URL").rstrip("/")
    data = _post(f"{base}/chat/completions", cfg.get("BRAIN_LLM_API_KEY"), body, timeout or cfg.get("BRAIN_LLM_TIMEOUT"))
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"unexpected chat response: {str(data)[:300]}") from None
    msg["content"] = (msg.get("content") or "").strip()
    usage = getattr(_meter, "usage", None)
    if usage is not None:
        u = data.get("usage") or {}
        usage["calls"] += 1
        usage["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
        usage["completion_tokens"] += int(u.get("completion_tokens") or 0)
    return msg


def embed(texts: list[str], timeout: float | None = None, cache: bool = True) -> list[list[float]]:
    """Vectors of these texts. Texts embedded before with the same model come from the persistent cache (vcache);
    only the others are sent to the API."""
    from . import vcache
    model = cfg.get("BRAIN_EMBEDDING_MODEL")
    use = cache and vcache.enabled()
    found = vcache.get(model, texts) if use else {}
    todo = [i for i in range(len(texts)) if i not in found]
    if todo:
        base = (cfg.get("BRAIN_EMBEDDING_BASE_URL") or cfg.get("BRAIN_LLM_BASE_URL")).rstrip("/")
        key = cfg.get("BRAIN_EMBEDDING_API_KEY") or cfg.get("BRAIN_LLM_API_KEY")
        data = _post(f"{base}/embeddings", key, {"model": model, "input": [texts[i] for i in todo]},
                     timeout or cfg.get("BRAIN_LLM_TIMEOUT"))
        rows = [r["embedding"] for r in sorted(data.get("data", []), key=lambda d: d.get("index", 0))]
        if len(rows) != len(todo):
            raise LLMError(f"embeddings: asked for {len(todo)} vectors, got {len(rows)}")
        if use:
            vcache.put(model, [texts[i] for i in todo], rows)
        found.update(zip(todo, rows))
    return [found[i] for i in range(len(texts))]


_models: dict = {"t": 0.0, "list": []}


def models() -> list[str]:
    """Model ids the corporate API lists (GET /models), cached for a minute."""
    import time
    if time.time() - _models["t"] < 60 and _models["list"]:
        return _models["list"]
    base = cfg.get("BRAIN_LLM_BASE_URL").rstrip("/")
    if not base.startswith("http"):
        raise LLMError("BRAIN_LLM_BASE_URL is not set")
    try:
        with _client() as c:
            r = c.get(f"{base}/models", timeout=15, headers={"Authorization": f"Bearer {cfg.get('BRAIN_LLM_API_KEY')}"})
    except httpx.HTTPError as exc:
        raise LLMError(f"cannot list models: {exc}") from None
    if r.status_code >= 400:
        raise LLMError(f"{base}/models -> HTTP {r.status_code}", r.status_code)
    ids = sorted({str(m.get("id")) for m in (r.json().get("data") or []) if isinstance(m, dict) and m.get("id")})
    _models.update(t=time.time(), list=ids)
    return ids


def check() -> dict:
    """Start-up / doctor probe: one tiny chat call and one embedding call."""
    out = {"chat": None, "embedding": None, "dim": None, "errors": []}
    try:
        out["chat"] = bool(chat([{"role": "user", "content": "Reply with: OK"}], cfg.get("BRAIN_LLM_MODEL"),
                                timeout=min(60.0, cfg.get("BRAIN_LLM_TIMEOUT")), max_tokens=5) is not None)
    except LLMError as exc:
        out["chat"] = False
        out["errors"].append(f"chat: {exc}")
    try:
        v = embed(["health check"], timeout=min(60.0, cfg.get("BRAIN_LLM_TIMEOUT")), cache=False)
        out["dim"] = len(v[0]) if v else None
        out["embedding"] = out["dim"] == cfg.get("BRAIN_EMBEDDING_DIM")
        if not out["embedding"]:
            out["errors"].append(f"embedding: model returns {out['dim']} dimensions but BRAIN_EMBEDDING_DIM="
                                 f"{cfg.get('BRAIN_EMBEDDING_DIM')}")
    except LLMError as exc:
        out["embedding"] = False
        out["errors"].append(f"embedding: {exc}")
    return out
