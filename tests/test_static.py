"""Static checks: no server, no network.   python tests/test_static.py   (exit code = failures)"""
import importlib
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_TMP = Path(tempfile.mkdtemp())
os.environ["BRAIN_CONFIG_FILE"] = str(_TMP / "test.env")   # never touch the real .env or data/
os.environ["BRAIN_DATA_DIR"] = str(_TMP / "data")
os.environ["BRAIN_REPOS_FILE"] = str(_TMP / "repos.json")
FAILS = []


def check(name, cond, info=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {info}")
    if not cond:
        FAILS.append(name)


def _raises(fn) -> bool:
    try:
        fn()
    except Exception:
        return True
    return False


def main():
    check(f"python 3.13 ({sys.version.split()[0]})", sys.version_info[:2] == (3, 13))
    for mod in ("brain.settings", "brain.query", "brain.jobs", "brain.llm", "brain.auth", "brain.search", "brain.repos", "brain.drift", "brain.agents",
                "brain.webhooks", "brain.mcp", "brain.server", "brain.codevec", "brain.srs", "brain.providers.codebase_memory", "brain.providers.lightrag",
                "brain.providers.convert"):
        try:
            importlib.import_module(mod)
            check(f"import {mod}", True)
        except Exception as exc:
            check(f"import {mod}", False, exc)

    from brain import providers, search
    from brain import settings as cfg
    check("code provider loads via registry", providers.code().name == "codebase_memory")
    check("doc provider loads via registry", providers.docs().name == "lightrag")

    sys.path.insert(0, str(ROOT / "tools"))
    import gen_config
    check(".env.example and 03-CONFIGURATION.md are up to date", gen_config.main(check=True) == 0)

    api_doc = (ROOT / "docs" / "06-API.md").read_text(encoding="utf-8")
    from brain.server import app
    for r in app.routes:
        path = getattr(r, "path", "")
        if path.startswith(("/api", "/webhooks", "/mcp", "/healthz")) and path != "/api/docs-ui":
            check(f"route documented: {path}", path.replace(":path}", "}") in api_doc)

    mcp_doc = (ROOT / "docs" / "07-MCP-AND-AGENTS.md").read_text(encoding="utf-8")
    from brain.mcp import TOOLS
    for t in TOOLS:
        check(f"MCP tool documented: {t['name']}", f"`{t['name']}`" in mcp_doc)

    from brain import query
    a = query.analyze("Müşteriden nasıl ödeme alınır ve KDV nerede uygulanır? chargeCustomer tax_rate")
    kw = a["keywords"]
    check("Turkish + identifier key terms", {"Müşteriden", "ödeme", "KDV", "chargeCustomer", "tax_rate"} <= set(kw), kw)
    check("identifiers ranked first", kw[:2] == ["chargeCustomer", "tax_rate"], kw)
    check("stop-words extracted", {"nasıl", "ve", "nerede"} <= set(a["stop_words"]) and "nasıl" not in kw, a["stop_words"])
    check("Turkish stem + identifier-part variants", {"Müşteri", "charge", "Customer", "tax", "rate"} <= set(a["variants"]), a["variants"])
    check("language detected", a["language"] == "tr", a["language"])
    b = query.analyze('How are "partial refunds" applied to invoices?')
    check("quoted phrase kept and ranked first", b["keywords"][0] == "partial refunds" and "invoice" in b["variants"], b)
    cfg.update({"BRAIN_STOPWORDS_EXTRA": "invoices"})
    check("extra stop-words setting", "invoices" in query.analyze("invoices total")["stop_words"])
    cfg.update({"BRAIN_STOPWORDS_EXTRA": ""})

    for key, bad in (("BRAIN_PORT", "abc"), ("BRAIN_VERIFY_TLS", "maybe"), ("CBM_INDEX_MODE", "turbo"), ("NOPE", "1")):
        try:
            cfg.validate(key, bad)
            check(f"rejects {key}={bad}", False)
        except ValueError:
            check(f"rejects {key}={bad}", True)
    scopes = cfg.update({"BRAIN_SEARCH_TOP_K": "5", "LIGHTRAG__MAX_GLEANING": "0"})
    check("update writes file and reports restarts", cfg.get("BRAIN_SEARCH_TOP_K") == 5 and "docs" in scopes, scopes)
    check("pass-through variables", cfg.passthrough("LIGHTRAG__").get("MAX_GLEANING") == "0")
    from brain.providers import lightrag as lr
    cfg.update({"LIGHTRAG_LLM_TIMEOUT": "777", "LIGHTRAG_EMBEDDING_TIMEOUT": "55", "LIGHTRAG_TIMEOUT": "333"})
    env = lr.Provider().child_env()
    check("LightRAG timeouts from settings", (env["LLM_TIMEOUT"], env["EMBEDDING_TIMEOUT"], env["TIMEOUT"]) ==
          ("777", "55", "333"), (env["LLM_TIMEOUT"], env["EMBEDDING_TIMEOUT"], env["TIMEOUT"]))

    try:
        cfg.resolve_url("gitlab:a/b")
        check("gitlab: shorthand needs BRAIN_GITLAB_URL", False)
    except ValueError:
        check("gitlab: shorthand needs BRAIN_GITLAB_URL", True)
    cfg.update({"BRAIN_GITLAB_URL": "https://gitlab.corp.local/", "BRAIN_GITLAB_TOKEN": "gl", "BRAIN_TFS_URL":
                "https://tfs.corp.local/tfs/DefaultCollection", "BRAIN_TFS_TOKEN": "tf", "BRAIN_GIT_TOKEN": "gen"})
    check("gitlab: shorthand", cfg.resolve_url("gitlab:pay/billing") == "https://gitlab.corp.local/pay/billing.git")
    check("tfs: shorthand", cfg.resolve_url("tfs:Portal/web") == "https://tfs.corp.local/tfs/DefaultCollection/Portal/_git/web")
    check("full URL unchanged", cfg.resolve_url("https://x/y.git") == "https://x/y.git")
    check("GitLab credentials chosen by host", cfg.git_credentials("https://gitlab.corp.local/pay/billing.git")[1] == "gl")
    check("TFS credentials chosen by host", cfg.git_credentials("https://tfs.corp.local/tfs/DefaultCollection/P/_git/r")[1] == "tf")
    check("fallback git credentials", cfg.git_credentials("https://other/x.git")[1] == "gen")
    check("{gitlab: ...} field accepted", cfg.normalize_repo({"gitlab": "pay/billing"})["url"] == "gitlab:pay/billing"
          and cfg.normalize_repo({"gitlab": "pay/billing"})["name"] == "billing")
    from brain import webhooks
    import json as _json
    cfg.repos_file().write_text(_json.dumps({"repos": [{"name": "billing", "url": "gitlab:pay/billing"},
                                                       {"name": "web", "url": "tfs:Portal/web"}]}), encoding="utf-8")
    m1 = webhooks.match_repo(["https://gitlab.corp.local/pay/billing.git"])
    m2 = webhooks.match_repo(["https://tfs.corp.local/tfs/DefaultCollection/Portal/_git/web"])
    check("webhooks match shorthand repositories", (m1 or {}).get("name") == "billing" and (m2 or {}).get("name") == "web")

    # repositories, sets, per-repository webhooks
    saved = cfg.save_repos([{"name": "billing", "url": "gitlab:pay/billing"}, {"name": "web", "url": "tfs:Portal/web"}],
                           {"payments": ["billing", "web"]})
    sec = saved["repos"][0]["webhook_secret"]
    check("webhook secret generated per repository", len(sec) == 32 and sec != saved["repos"][1]["webhook_secret"])
    check("providers detected", [r["provider"] for r in saved["repos"]] == ["gitlab", "tfs"])
    check("sets stored", cfg.load_sets() == {"payments": ["billing", "web"]})
    again = cfg.save_repos([{"name": "billing", "url": "gitlab:pay/billing", "webhook_secret": ""}], {})
    check("webhook secret kept on re-save", again["repos"][0]["webhook_secret"] == sec)
    cfg.save_repos(saved["repos"], {"payments": ["billing", "web"]})
    code, body = webhooks.repo_hook("billing", {"x-gitlab-token": "wrong"}, {"object_kind": "push"})
    check("own webhook rejects a wrong GitLab secret", code == 401, body)
    import base64 as _b64
    auth = "Basic " + _b64.b64encode(f"x:{saved['repos'][1]['webhook_secret']}".encode()).decode()
    code, body = webhooks.repo_hook("web", {"authorization": auth}, {"eventType": "git.push", "resource": {"refUpdates": [{"name": "refs/heads/dev"}]}})
    check("own webhook accepts TFS secret (other branch ignored)", code == 200 and "ignored" in body, body)
    try:
        cfg.save_repos([{"name": "a", "path": "x"}], {"s": ["nope"]})
        check("unknown set member rejected", False)
    except ValueError:
        check("unknown set member rejected", True)

    # every document -> Markdown
    import io as _io
    from docx import Document
    from brain.providers import convert
    d = Document(); d.add_heading("Ödeme Kuralları", 1); d.add_paragraph("Banka 503 döndüğünde üç kez denenir.")
    t = d.add_table(rows=2, cols=2); t.cell(0, 0).text = "Kod"; t.cell(1, 0).text = "503"
    buf = _io.BytesIO(); d.save(buf)
    name, payload, mdtext = convert.to_markdown("kurallar.docx", buf.getvalue())
    check("Word -> Markdown (heading, text, table)", name == "kurallar.docx.md" and "## Ödeme Kuralları" in mdtext
          and "<table>" in mdtext, mdtext[:120])
    name, _, mdtext = convert.to_markdown("p.html", b"<h2>Title</h2><p>Body <code>x()</code></p><script>bad()</script>")
    check("HTML -> Markdown", "## Title" in mdtext and "`x()`" in mdtext and "bad()" not in mdtext, mdtext)
    check("CSV -> table", "<table>" in convert.to_markdown("t.csv", b"a,b\n1,2\n")[2])
    check("code -> fenced block", "```python" in convert.to_markdown("x.py", b"def f(): pass")[2])
    try:
        convert.to_markdown("x.bin", b"\x00\x01\x02")
        check("binary rejected", False)
    except ValueError:
        check("binary rejected", True)

    # requirements writer formats
    from brain import srs
    head, secs = srs.parse(srs.DEFAULT_TEMPLATE)
    check("default format parses", len(secs) == 10 and sum(s["per_capability"] for s in secs) == 1 and "FORMAT GUIDE" not in head)
    check("requirement IDs numbered", srs._number("FR-? a FR-? b BR-? NFR-X") == "FR-001 a FR-002 b BR-001 NFR-001")
    try:
        srs.save_template("bad", "# no sections")
        check("format without sections rejected", False)
    except ValueError:
        check("format without sections rejected", True)
    check("default format cannot be deleted", _raises(lambda: srs.delete_template("default")))

    docs = sorted(p.name for p in (ROOT / "docs" / "decisions").glob("ADR-*.md"))
    check("architecture decision records present", len(docs) >= 22, len(docs))
    whl = [p.name for p in (ROOT / "wheels").glob("*.whl")]
    check("bundled wheels present", len(whl) > 100, len(whl))
    check("wheels are for Python 3.13 only", not [w for w in whl if re.search(r"-cp3(?!13)\d+-cp3", w)])
    for f in ("README.md", "INSTALL.html", "setup.ps1", "setup.sh", "brain.cmd", "brain.sh", "requirements.txt",
              "repos.example.json", "bin/SHA256SUMS"):
        check(f"file present: {f}", (ROOT / f).exists())
    for link in re.findall(r"\]\((?!http)([^)#]+)", (ROOT / "README.md").read_text(encoding="utf-8")):
        check(f"README link resolves: {link}", (ROOT / link).exists())
    md_files = sorted((ROOT / "docs").rglob("*.md")) + sorted((ROOT / "integrations").rglob("*.md"))
    broken = [f"{p.relative_to(ROOT)} -> {link}" for p in md_files
              for link in re.findall(r"\]\((?!http)([^)#\s]+)", p.read_text(encoding="utf-8"))
              if not (p.parent / link).exists()]
    check("every link in docs/ resolves", not broken, broken[:5])
    history = re.compile(r"\(added\b|\b[Rr]evised\b|\brevises ADR|\bextends ADR|requested on|second round|reference project")
    stale = [str(p.relative_to(ROOT)) for p in md_files + [ROOT / "README.md", ROOT / "INSTALL.html"]
             if history.search(p.read_text(encoding="utf-8"))]
    check("documentation describes the system as it is (no change-history wording)", not stale, stale)
    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    sys.exit(len(FAILS))


if __name__ == "__main__":
    main()
