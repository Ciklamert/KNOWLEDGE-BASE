"""Stand-in for a corporate OpenAI-compatible gateway, for tests WITHOUT the real API (never for production).

/v1/embeddings        deterministic hashed bag-of-words vectors (similar text -> similar vector)
/v1/chat/completions  tool calling for the agents; expansion terms; requirement plans; picture descriptions; answers
/v1/models            the model list
Run:  python tests/mock_openai.py [port]      (default 127.0.0.1:9000, any API key)
"""
import hashlib
import json
import re
import sys

import numpy as np
import uvicorn
from fastapi import FastAPI, Request

DIM = 256
app = FastAPI()
CALLS = {"embed": 0, "chat": 0, "tool_calls": 0, "vision": 0}


def _vec(text: str) -> list[float]:
    v = np.zeros(DIM, dtype=np.float32)
    for t in re.findall(r"\w{3,}", re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower()):
        h = int(hashlib.md5(t.encode()).hexdigest(), 16)
        v[h % DIM] += 1.0 if (h >> 8) % 2 else -1.0
    n = np.linalg.norm(v)
    return (v / n if n else v + 1e-3).tolist()


@app.post("/v1/embeddings")
async def embeddings(req: Request):
    body = await req.json()
    CALLS["embed"] += 1
    inp = body["input"] if isinstance(body["input"], list) else [body["input"]]
    return {"object": "list", "model": body.get("model"),
            "data": [{"object": "embedding", "index": i, "embedding": _vec(t)} for i, t in enumerate(inp)],
            "usage": {"prompt_tokens": 1, "total_tokens": 1}}


def _reply(body: dict) -> dict:
    msgs = body.get("messages", [])
    if any(isinstance(m.get("content"), list) for m in msgs):   # a picture for the vision model
        CALLS["vision"] += 1
        return {"role": "assistant", "content": "Bar chart: monthly refunds 2025, January 120, February 95. Title: İade Grafiği."}
    text = "\n".join(str(m.get("content", "")) for m in msgs)
    if "You plan a Software Requirements Specification" in text:
        return {"role": "assistant", "content": json.dumps({"system_name": "Billing", "summary": "Invoices and payments.",
                "capabilities": [{"name": "Invoicing", "description": "Create invoices with VAT", "queries": ["invoice vat"],
                                  "excerpt": "invoices with VAT"},
                                 {"name": "Payments", "description": "Charge customers", "queries": ["charge customer"]}],
                "per_capability_sections": [2], "glossary": [{"term": "VAT", "definition": "Value added tax"}]})}
    if "requirements writer" in text and not body.get("tools"):
        return {"role": "assistant", "content": "- FR-? When an invoice is created, the system shall add VAT. (Status: New)"}
    if "search terms for a code + document knowledge base" in text:
        return {"role": "assistant", "content": '["chargeCustomer", "refund_payment", "invoice"]'}
    if body.get("tools"):
        if not any(m.get("role") == "tool" for m in msgs):
            CALLS["tool_calls"] += 1
            return {"role": "assistant", "content": "", "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "symbol", "arguments": json.dumps({"name": "charge_customer"})}}]}
        tool_out = [m["content"] for m in msgs if m.get("role") == "tool"][-1]
        if "requirements writer" in text:
            return {"role": "assistant", "content": "### Capability\n- FR-? The system shall charge the customer. "
                    "(Status: Implemented; tool chars " + str(len(tool_out)) + ")"}
        if "prompt enhancer" in text.lower():
            kind = "[bug fix]" if re.search(r"fail|error|bug|hata", text.split("<developer_request>")[-1], re.I) else "[new feature]"
            return {"role": "assistant", "content": f"## Task\n{kind} (mock) Implement the request.\n## What exists today\n"
                    "- `billing/src/billing/invoice.py:15` — charge_customer\n## Implementation plan\n1. Edit.\n"
                    "## Acceptance criteria\n- Tests pass.\n\n(tool result seen: " + str(len(tool_out)) + " chars)"}
        return {"role": "assistant", "content": "(mock answer) charge_customer creates an invoice and calls the "
                "gateway. Source: `billing/src/billing/invoice.py:15-17`. Tool result chars: " + str(len(tool_out))}
    if "Reply with: OK" in text:
        return {"role": "assistant", "content": "OK"}
    return {"role": "assistant", "content": "Mock summary: " + text[-200:].replace("\n", " ")}


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    CALLS["chat"] += 1
    msg = _reply(body)
    return {"id": "x", "object": "chat.completion", "model": body.get("model"),
            "choices": [{"index": 0, "finish_reason": "tool_calls" if msg.get("tool_calls") else "stop", "message": msg}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}


@app.get("/v1/models")
async def models():
    return {"data": [{"id": "mock-chat"}, {"id": "mock-embed"}, {"id": "mock-vision"}]}


@app.get("/calls")
async def calls():
    return CALLS


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 9000, log_level="warning")
