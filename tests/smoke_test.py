"""End-to-end smoke test against a RUNNING server (use with tests/mock_openai.py or the real corporate API).

  python tests/smoke_test.py --url http://127.0.0.1:8765 --user admin --password ... --token ...
         [--origin PATH_OF_A_GIT_REPO_CONFIGURED_AS_URL --repo NAME]   (also tests webhooks, drift, overlays)

Each check prints PASS/FAIL; the exit code is the number of failures.
"""
import argparse
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
FAILS = []


def check(name, cond, info=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {str(info)[:300]}")
    if not cond:
        FAILS.append(name)


def wait_job(c, job_id, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] != "running":
            return j
        time.sleep(1)
    return {"state": "timeout"}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", required=True)
    ap.add_argument("--token", default="")
    ap.add_argument("--origin", help="path of the git repo a configured repository clones from (url)")
    ap.add_argument("--repo", default="billing")
    ap.add_argument("--gitlab-secret", default="")
    ap.add_argument("--tfs-user", default="")
    ap.add_argument("--tfs-password", default="")
    a = ap.parse_args()

    # ---- authentication
    anon = httpx.Client(base_url=a.url, timeout=60)
    check("anonymous API is rejected", anon.get("/api/status").status_code == 401)
    check("health endpoint is public", anon.get("/healthz").status_code == 200)
    check("wrong password is rejected", anon.post("/api/login", json={"username": a.user, "password": "x"}).status_code == 401)
    ui = httpx.Client(base_url=a.url, timeout=300)
    check("login sets a session cookie", ui.post("/api/login", json={"username": a.user, "password": a.password}).status_code == 200)
    check("cookie without X-Brain-UI cannot change state", ui.post("/api/search", json={"query": "x"}).status_code == 403)
    ui.headers["X-Brain-UI"] = "1"
    c = httpx.Client(base_url=a.url, timeout=600, auth=(a.user, a.password))
    if a.token:
        t = httpx.Client(base_url=a.url, timeout=60, headers={"Authorization": f"Bearer {a.token}"})
        check("bearer token works", t.get("/api/me").status_code == 200)

    st = c.get("/api/status").json()
    check("system is ready (code + docs + agents)", st["ready"], {k: v["state"] for k, v in st["engines"].items()})

    # ---- documents
    note = "# Ödeme Kuralları\nRefunds above 5000 TL need manager approval (iade onayı). The RefundPolicy applies to all channels."
    r = ui.post("/api/docs/upload", files={"files": ("refund-policy.md", note.encode("utf-8"), "text/markdown")})
    j = wait_job(ui, r.json()["job"])
    check("document upload job", j["state"] == "done", j.get("error"))
    end = time.time() + 180
    doc = None
    while time.time() < end:
        docs = ui.get("/api/docs").json()["documents"]
        doc = next((d for d in docs if d["name"].startswith("refund-policy")), None)
        if doc and doc["status"] in ("processed", "failed"):
            break
        time.sleep(2)
    check("document processed by LightRAG", doc and doc["status"] == "processed", doc)
    r = c.get("/api/docs/markdown", params={"name": "refund-policy.md"})
    check("converted Markdown kept for preview", r.status_code == 200 and "Ödeme" in r.json()["markdown"], r.text[:120])

    # ---- search (no LLM)
    r = c.post("/api/search", json={"query": "charge customer invoice KDV"}).json()
    check("search finds code", len(r["code"]) > 0, [h["name"] for h in r["code"][:5]])
    check("search pipeline: analysis + semantic re-rank", "semantic re-rank" in r.get("pipeline", [])
          and all("similarity" in h for h in r["code"]), r.get("pipeline"))
    r = c.post("/api/search", json={"query": "refund manager approval RefundPolicy"}).json()
    check("search finds documents", len(r["docs"].get("chunks", [])) > 0, r["errors"])
    r = c.post("/api/search", json={"query": "iade onayı refund", "scope": "docs"}).json()
    check("Turkish document search", any("refund" in ch["source"] for ch in r["docs"].get("chunks", [])),
          [ch["source"] for ch in r["docs"].get("chunks", [])])
    r = c.post("/api/search", json={"query": "charge", "set": "no-such-set"}).json()
    check("unknown set is reported", any("unknown repository set" in e for e in r["errors"]), r["errors"])

    # ---- ask / enhance
    r = c.post("/api/ask", json={"question": "How is a customer charged?"}).json()
    check("ask agent answers", bool(r["answer"]) and r["llm"], r["answer"][:120])
    check("ask agent used tools", len(r["steps"]) > 0, r["steps"])
    check("ask: model-expanded search terms", "refund_payment" in r["analysis"].get("expanded", [])
          or "chargeCustomer" in r["analysis"].get("expanded", []), r["analysis"].get("expanded"))
    r = c.post("/api/enhance", json={"prompt": "add a refund feature to billing"}).json()
    check("enhance agent returns a prompt", "##" in r["enhanced"], r["enhanced"][:120])
    r = ui.post("/api/ask", json={"question": "Müşteriden nasıl ödeme alınır?", "async": True}).json()
    j = wait_job(ui, r["job"])
    check("async ask job with progress steps", j["state"] == "done" and len(j["steps"]) >= 2, j.get("error"))

    # ---- MCP
    h = {"Authorization": f"Bearer {a.token}"} if a.token else {}
    m = httpx.Client(base_url=a.url, timeout=300, headers=h, auth=None if a.token else (a.user, a.password))
    r = m.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}}).json()
    check("MCP initialize", r["result"]["serverInfo"]["name"] == "ai-brain")
    tools = [t["name"] for t in m.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()["result"]["tools"]]
    check("MCP tools/list", {"search", "ask", "enhance_prompt", "check_branch"} <= set(tools), tools)
    r = m.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                             "params": {"name": "search", "arguments": {"query": "apply vat"}}}).json()
    check("MCP tools/call search", not r["result"]["isError"] and "apply_vat" in r["result"]["content"][0]["text"],
          r["result"]["content"][0]["text"][:200])
    r = m.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                             "params": {"name": "symbol", "arguments": {"name": "charge_customer"}}}).json()
    check("MCP tools/call symbol", "charge_customer" in r["result"]["content"][0]["text"], r["result"]["content"][0]["text"][:200])

    # ---- three sources, AI tools (read / grep / files), evidence
    r = c.post("/api/search", json={"query": "charge customer invoice", "scope": "all"}).json()
    check("three sources counted", r.get("sources", {}).get("code graph", 0) > 0 and "document passages" in r["sources"], r.get("sources"))
    check("hits explain why they matched", all(h.get("matched") for h in r["code"]), [h.get("matched") for h in r["code"][:3]])
    check("hits carry graph context (callers/callees)", any(h.get("callers") or h.get("callees") for h in r["code"]),
          [(h["name"], h.get("callers"), h.get("callees")) for h in r["code"][:4]])
    check("code graph expansion ran", any("code graph expansion" in p for p in r["pipeline"]), r["pipeline"])
    def mcp_call(name, args):
        res = m.post("/mcp", json={"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": name, "arguments": args}}).json()
        return res["result"]["content"][0]["text"], res["result"]["isError"]
    text, err = mcp_call("files", {"pattern": "**/*.py", "repos": [a.repo]})
    check("MCP files (glob replacement)", not err and "invoice.py" in text, text[:200])
    text, err = mcp_call("read", {"repo": a.repo, "path": "src/billing/invoice.py", "start": 1, "end": 12})
    check("MCP read (read replacement)", not err and "InvoiceService" in text and "lines 1-12" in text, text[:200])
    text, err = mcp_call("grep", {"pattern": "apply_vat", "repos": [a.repo]})
    check("MCP grep (grep replacement)", not err and "apply_vat" in text, text[:200])
    r = c.get("/api/code/files", params={"pattern": "*.ts", "target": f"repo:{a.repo}"}).json()
    check("REST files", any(f.endswith("api.ts") for f in r["files"]), r)
    r = c.post("/api/ask", json={"question": "How is VAT applied?"}).json()
    check("ask returns its evidence", len(r.get("evidence", {}).get("code", [])) > 0, list(r.get("evidence", {}).keys()))

    # ---- models, repositories + sets, scopes, semantic code search, requirements writer
    r = c.get("/api/models").json()
    check("models listed from the API", "mock-chat" in r["models"] and "mock-embed" not in r["models"], r)
    r = c.post("/api/ask", json={"question": "How is a customer charged?", "model": "mock-chat"}).json()
    check("ask uses the chosen model", r.get("model") == "mock-chat", r.get("model"))
    repos_now = c.get("/api/repos").json()
    names = [x["name"] for x in repos_now["repos"]]
    r = ui.put("/api/repos", json={"repos": [{k: x[k] for k in ("name", "provider", "url", "path", "branch")} for x in repos_now["repos"]],
                                   "sets": {"payments": [a.repo]}})
    check("repositories and sets saved", r.status_code == 200 and r.json()["sets"] == {"payments": [a.repo]}, r.text[:200])
    repos_now = c.get("/api/repos").json()
    mine = next(x for x in repos_now["repos"] if x["name"] == a.repo)
    check("each repository has its own webhook", mine["webhook"]["url"].endswith(f"/webhooks/repo/{a.repo}")
          and len(mine["webhook"]["secret"]) == 32, mine["webhook"])
    r = c.post("/api/search", json={"query": "apply vat", "scope": "code", "target": "set:payments"}).json()
    check("set scope searches the set's repositories", r["projects"] == [a.repo], r["projects"])
    others = [n for n in names if n != a.repo]
    if others:
        r = c.post("/api/search", json={"query": "login", "scope": "code", "target": f"repo:{others[0]}"}).json()
        check("single-repository scope", r["projects"] == [others[0]], r["projects"])
        r = c.post("/api/search", json={"query": "charge customer login", "scope": "code", "target": "set:all", "k": 4}).json()
        check("a set keeps every repository in the result", len({h["project"] for h in r["code"]}) == 2,
              [(h["project"], h["name"]) for h in r["code"]])
    r = c.post("/api/search", json={"query": "müşteriden ödeme alma", "scope": "semantic", "target": "set:all"}).json()
    check("semantic code search (vector indexes)", len(r["code"]) > 0 and "multilingual code vector index" in r["pipeline"],
          (r["pipeline"], r["errors"]))
    check("formats listed", "default" in c.get("/api/srs/templates").json()["templates"])
    r = ui.post("/api/srs", json={"topic": "billing and payments", "target": "set:payments"}).json()
    j = wait_job(ui, r["job"], 600)
    res = j.get("result") or {}
    check("requirements specification written", j["state"] == "done" and "FR-001" in res.get("markdown", "")
          and "Traceability" in res.get("markdown", ""), (j.get("error"), res.get("errors")))
    check("specification listed", any(d["name"] == res.get("name") for d in c.get("/api/srs/documents").json()["documents"]))

    # ---- settings round trip
    old = next(s for s in c.get("/api/settings").json()["settings"] if s["key"] == "BRAIN_SEARCH_TOP_K")["value"]
    r = ui.put("/api/settings", json={"changes": {"BRAIN_SEARCH_TOP_K": "5"}})
    new = next(s for s in c.get("/api/settings").json()["settings"] if s["key"] == "BRAIN_SEARCH_TOP_K")["value"]
    check("settings saved to the config file", r.status_code == 200 and new == "5", r.text[:200])
    ui.put("/api/settings", json={"changes": {"BRAIN_SEARCH_TOP_K": old}})
    check("invalid setting rejected", ui.put("/api/settings", json={"changes": {"BRAIN_PORT": "abc"}}).status_code == 400)

    # ---- git: webhooks, drift, branch overlay
    if a.origin:
        origin = Path(a.origin)
        Path(origin, "src/billing/refund.py").write_text(
            "def refund_payment(customer_id: str, amount: float) -> bool:\n    \"\"\"Refund a payment.\"\"\"\n    return amount > 0\n",
            encoding="utf-8")
        git(origin, "add", "-A")
        git(origin, "commit", "-qm", "add refund")
        hook = c.get("/api/repos").json()
        own = next(x for x in hook["repos"] if x["name"] == a.repo)["webhook"]
        payload = {"object_kind": "push", "ref": "refs/heads/main"}
        r = anon.post(f"/webhooks/repo/{a.repo}", json=payload, headers={"X-Gitlab-Token": "wrong", "X-Gitlab-Event": "Push Hook"})
        check("own webhook rejects a wrong secret", r.status_code == 401)
        r = anon.post(f"/webhooks/repo/{a.repo}", json=payload, headers={"X-Gitlab-Token": own["secret"], "X-Gitlab-Event": "Push Hook"})
        check("own GitLab webhook accepted", r.status_code == 202, r.text)
        if r.status_code == 202 and r.json().get("job"):
            wait_job(c, r.json()["job"])
        time.sleep(2.5)   # debounce window of the test configuration
        if a.gitlab_secret:
            payload = {"object_kind": "merge_request", "project": {"name": a.repo, "git_http_url": str(origin)},
                       "object_attributes": {"action": "merge", "state": "merged", "target_branch": "main"}}
            r = anon.post("/webhooks/gitlab", json=payload, headers={"X-Gitlab-Token": "wrong"})
            check("gitlab webhook rejects a wrong secret", r.status_code == 401)
            r = anon.post("/webhooks/gitlab", json=payload, headers={"X-Gitlab-Token": a.gitlab_secret,
                                                                    "X-Gitlab-Event": "Merge Request Hook"})
            check("gitlab merge webhook accepted", r.status_code == 202, r.text)
            if r.status_code == 202 and r.json().get("job"):
                j = wait_job(c, r.json()["job"])
                check("webhook sync job", j["state"] == "done", j.get("error"))
            r = c.post("/api/search", json={"query": "refund payment", "scope": "code"}).json()
            check("merged code is searchable", any(h["name"] == "refund_payment" for h in r["code"]),
                  [h["name"] for h in r["code"]])
            r = anon.post("/webhooks/gitlab", json={**payload, "object_attributes": {"action": "merge", "target_branch": "dev"}},
                          headers={"X-Gitlab-Token": a.gitlab_secret})
            check("gitlab merge to other branch ignored", r.status_code == 200 and "ignored" in r.json(), r.text)
        if a.tfs_password:
            auth = "Basic " + base64.b64encode(f"{a.tfs_user}:{a.tfs_password}".encode()).decode()
            payload = {"eventType": "git.pullrequest.merged",
                       "resource": {"status": "completed", "mergeStatus": "succeeded", "targetRefName": "refs/heads/main",
                                    "repository": {"name": a.repo, "remoteUrl": str(origin)}}}
            r = anon.post("/webhooks/tfs", json=payload, headers={"Authorization": auth})
            check("tfs PR-merged webhook accepted", r.status_code == 202, r.text)
            r = anon.post("/webhooks/tfs", json=payload)
            check("tfs webhook without auth rejected", r.status_code == 401)

        # a feature branch cut before a change on main that touches the same file
        base = git(origin, "rev-parse", "HEAD")
        git(origin, "checkout", "-qb", "feature/discount")
        p = Path(origin, "src/billing/tax.py")
        p.write_text(p.read_text(encoding="utf-8") + "\n\ndef discount(amount):\n    return amount * 0.9\n", encoding="utf-8")
        git(origin, "commit", "-qam", "discount")
        git(origin, "checkout", "-q", "main")
        p.write_text(p.read_text(encoding="utf-8").replace("0.20", "0.18"), encoding="utf-8")
        git(origin, "commit", "-qam", "vat change on main")
        r = c.post("/api/drift", json={"repo": a.repo, "branch": "feature/discount"}).json()
        check("drift: branch behind main detected", r.get("behind") == 1, r.get("facts"))
        check("drift: conflict-risk file found", "src/billing/tax.py" in r.get("risk_files", []), r.get("risk_files"))
        check("drift: recommendations given", any(x["action"] == "rebase_now" for x in r["recommendations"]),
              [x["action"] for x in r["recommendations"]])
        r = c.post("/api/drift", json={"repo": a.repo, "branch": "local-only", "base_commit": base,
                                       "changed_files": ["src/billing/tax.py"]}).json()
        check("drift for an unpushed branch", "src/billing/tax.py" in r.get("risk_files", []), r.get("facts"))
        r = c.post(f"/api/repos/{a.repo}/branches", json={"branch": "feature/discount"}).json()
        j = wait_job(c, r["job"], 600)
        check("branch overlay indexed", j["state"] == "done", j.get("error"))
        r = c.post("/api/search", json={"query": "discount amount", "scope": "code", "branch": "feature/discount"}).json()
        check("branch overlay is searched for that branch", any(h["name"] == "discount" for h in r["code"]),
              [(h["project"], h["name"]) for h in r["code"]])
        r = c.delete(f"/api/repos/{a.repo}/branches/feature/discount")
        check("branch overlay removed", r.status_code == 200, r.text[:200])

    # ---- cleanup of the test document
    if doc:
        check("document delete", c.delete(f"/api/docs/{doc['id']}").status_code == 200)
    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    sys.exit(len(FAILS))


if __name__ == "__main__":
    main()
