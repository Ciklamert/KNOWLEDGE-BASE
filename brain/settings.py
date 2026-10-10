"""Every tunable value lives in ONE schema below and in ONE file: `.env` (path overridable with BRAIN_CONFIG_FILE).

Precedence (highest first): value in the .env file > process environment > schema default.
The web UI edits the same .env file in place (comments and order are preserved), so the file and the UI
can never disagree. Repositories and repository sets are structured data and live in `repos.json`.

Providers may also receive raw pass-through variables:  LIGHTRAG__<NAME>=value  -> <NAME>=value for the
LightRAG child process, CBM__<NAME>=value -> <NAME>=value for codebase-memory-mcp.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = (3, 13)   # the only supported version: wheels/ contains packages for exactly this one

for _s in (sys.stdout, sys.stderr):  # Turkish Windows consoles (cp1254) must never crash on unicode output
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


@dataclass(frozen=True)
class Setting:
    key: str
    default: str
    group: str
    help: str
    kind: str = "str"        # str | int | float | bool | secret | choice
    choices: tuple = ()
    restart: str = ""        # "" (live) | "code" | "docs" | "server": what must restart to apply a change


S = Setting
SCHEMA: list[Setting] = [
    # ---- server & access -------------------------------------------------------------------------------
    S("BRAIN_HOST", "0.0.0.0", "Server", "Bind address. 0.0.0.0 = reachable from any IP (login required).", restart="server"),
    S("BRAIN_PORT", "8765", "Server", "Port for UI, REST API, MCP and webhooks.", "int", restart="server"),
    S("BRAIN_PUBLIC_URL", "", "Server", "Address users and agents use, e.g. http://10.0.0.5:8765 (shown in the UI).", restart=""),
    S("BRAIN_UI_USER", "admin", "Server", "Login user name for the web UI and API (Basic auth).", restart=""),
    S("BRAIN_UI_PASSWORD", "", "Server", "Login password (UI + API). The server refuses to listen on a network address without it.", "secret"),
    S("BRAIN_API_TOKEN", "", "Server", "Bearer token for AI agents (REST + MCP). Empty = only user/password.", "secret"),
    S("BRAIN_SECRET_KEY", "", "Server", "Signs login cookies. Empty = generated once and stored in the data folder.", "secret"),
    S("BRAIN_SESSION_HOURS", "12", "Server", "How long a UI login stays valid.", "int"),
    S("BRAIN_TLS_CERT", "", "Server", "PEM certificate file to serve HTTPS (optional).", restart="server"),
    S("BRAIN_TLS_KEY", "", "Server", "PEM private key file for HTTPS (optional).", restart="server"),
    S("BRAIN_DATA_DIR", "data", "Server", "Where all state lives (graphs, documents, clones). Relative = inside the install.", restart="server"),
    S("BRAIN_MAX_UPLOAD_MB", "200", "Server", "Largest accepted document upload.", "int"),
    # ---- corporate OpenAI-compatible API ---------------------------------------------------------------
    S("BRAIN_LLM_BASE_URL", "", "Corporate API", "OpenAI-compatible base URL, ending in /v1.", restart="docs"),
    S("BRAIN_LLM_API_KEY", "", "Corporate API", "API key for the base URL.", "secret", restart="docs"),
    S("BRAIN_LLM_MODEL", "", "Corporate API", "Default chat model (used by every role that has no own model).", restart="docs"),
    S("BRAIN_EMBEDDING_MODEL", "", "Corporate API", "Embedding model (multilingual, e.g. bge-m3): documents, the multilingual code vectors and re-ranking.", restart="docs"),
    S("BRAIN_EMBEDDING_DIM", "1024", "Corporate API", "Embedding vector size. Changing it (or the model) requires re-ingesting documents; code vectors rebuild by themselves.", "int", restart="docs"),
    S("BRAIN_EMBEDDING_BASE_URL", "", "Corporate API", "Only if embeddings live on a different URL.", restart="docs"),
    S("BRAIN_EMBEDDING_API_KEY", "", "Corporate API", "Only if embeddings need a different key.", "secret", restart="docs"),
    S("BRAIN_VLM_MODEL", "", "Corporate API", "Vision model for images and scanned pages in documents (optional).", restart="docs"),
    S("BRAIN_CA_BUNDLE", "", "Corporate API", "Corporate CA certificate (PEM) for TLS interception.", restart="docs"),
    S("BRAIN_VERIFY_TLS", "true", "Corporate API", "Verify TLS certificates of the corporate API.", "bool", restart="docs"),
    S("BRAIN_LLM_TIMEOUT", "120", "Corporate API", "Default seconds for one chat/embedding HTTP call.", "float"),
    # ---- prompt analysis (first step of search, ask and enhance) -----------------------------------------
    S("BRAIN_QUERY_MAX_TERMS", "12", "Relevance", "How many key terms are extracted from a prompt (most important first).", "int"),
    S("BRAIN_STOPWORDS_EXTRA", "", "Relevance",
      "Extra stop-words to ignore, comma separated (company jargon, e.g. proje, ekip, ticket). Built-in: English + Turkish."),
    S("BRAIN_RERANK", "true", "Relevance",
      "Re-rank code and document results by meaning with the corporate embedding model (multilingual).", "bool"),
    S("BRAIN_RERANK_CANDIDATES", "30", "Relevance", "How many code candidates are re-ranked (more = better recall, slower).", "int"),
    S("BRAIN_RERANK_WEIGHT", "0.6", "Relevance", "Share of meaning vs. lexical rank in the final order (0-1).", "float"),
    S("BRAIN_DOC_BRIDGE", "true", "Relevance",
      "Use the domain entities found in documents as extra code-search terms (business words -> code).", "bool"),
    S("BRAIN_GRAPH_EXPAND", "true", "Relevance",
      "Add callers, callees and parents of the best code hits as candidates (code graph expansion).", "bool"),
    S("BRAIN_GRAPH_EXPAND_TOP", "5", "Relevance", "How many of the best code hits are expanded through the code graph.", "int"),
    S("BRAIN_QUERY_EXPANSION", "true", "Relevance",
      "Ask/enhance only: one short model call turns the prompt into extra search terms (English identifiers, synonyms, translations).", "bool"),
    S("BRAIN_QUERY_EXPANSION_TIMEOUT", "20", "Relevance", "Seconds for the expansion call; on timeout the search continues without it.", "float"),
    # ---- search (no LLM) -------------------------------------------------------------------------------
    S("BRAIN_SEARCH_TOP_K", "8", "Search", "Code hits returned per search.", "int"),
    S("BRAIN_SEARCH_DOC_CHUNKS", "6", "Search", "Document passages returned per search.", "int"),
    S("BRAIN_SEARCH_TIMEOUT", "60", "Search", "Seconds before a search part (code or docs) is abandoned.", "float"),
    S("BRAIN_CONTEXT_MAX_CHARS", "16000", "Search", "Size budget of rendered search context given to agents.", "int"),
    S("BRAIN_SEARCH_DETAIL", "normal", "Search",
      "How much of each code hit search writes for AI agents, MCP and the CLI (less = fewer tokens): brief = location, "
      "signature, callers, callees and why it matched; normal = also the source of the 3 best hits; full = the source "
      "of every hit. A request can choose another level.", "choice", ("brief", "normal", "full")),
    S("BRAIN_TOOL_MAX_TOKENS", "2500", "Search",
      "Approximate token limit of one code-tool answer for agents (trace, grep, overview); longer answers are cut "
      "and say how to get the rest.", "int"),
    # ---- ask agent -------------------------------------------------------------------------------------
    S("BRAIN_ASK_MODEL", "", "Ask agent", "Chat model for the ask agent (empty = BRAIN_LLM_MODEL)."),
    S("BRAIN_ASK_TIMEOUT", "180", "Ask agent", "Total seconds for one question (all steps).", "float"),
    S("BRAIN_ASK_MAX_STEPS", "6", "Ask agent", "Maximum tool-calling rounds before answering.", "int"),
    S("BRAIN_ASK_MAX_TOKENS", "1500", "Ask agent", "Maximum tokens of the answer.", "int"),
    S("BRAIN_ASK_TEMPERATURE", "0.1", "Ask agent", "Sampling temperature.", "float"),
    # ---- enhance agent ---------------------------------------------------------------------------------
    S("BRAIN_ENHANCE_MODEL", "", "Enhance agent", "Chat model for the prompt enhancer (empty = BRAIN_LLM_MODEL)."),
    S("BRAIN_ENHANCE_TIMEOUT", "120", "Enhance agent", "Total seconds for one enhancement (all steps).", "float"),
    S("BRAIN_ENHANCE_MAX_STEPS", "4", "Enhance agent", "Maximum tool-calling rounds before writing the prompt.", "int"),
    S("BRAIN_ENHANCE_MAX_TOKENS", "1800", "Enhance agent", "Maximum tokens of the enhanced prompt.", "int"),
    S("BRAIN_ENHANCE_TEMPERATURE", "0.2", "Enhance agent", "Sampling temperature.", "float"),
    # ---- project guide -----------------------------------------------------------------------------------
    S("BRAIN_GUIDE_MODEL", "", "Project guide", "Chat model for the project guide (empty = BRAIN_LLM_MODEL)."),
    S("BRAIN_GUIDE_TIMEOUT", "300", "Project guide", "Total seconds for one project guide (all steps).", "float"),
    S("BRAIN_GUIDE_MAX_STEPS", "5", "Project guide", "Maximum tool-calling rounds before writing the guide.", "int"),
    S("BRAIN_GUIDE_MAX_TOKENS", "3000", "Project guide", "Maximum tokens of the guide.", "int"),
    S("BRAIN_GUIDE_TEMPERATURE", "0.2", "Project guide", "Sampling temperature.", "float"),
    S("BRAIN_AGENT_TOOL_CALLING", "auto", "Corporate API",
      "auto = use native tool calling, fall back if the gateway rejects it; native; off = one-shot with context.",
      "choice", ("auto", "native", "off")),
    # ---- code graph ------------------------------------------------------------------------------------
    S("BRAIN_CODE_PROVIDER", "codebase_memory", "Code graph",
      "Code graph plug-in: a name in brain/providers or 'package.module:Class'.", restart="code"),
    S("CBM_BIN", "", "Code graph", "Path to codebase-memory-mcp (empty = bin/<os>/ of this install).", restart="code"),
    S("CBM_INDEX_MODE", "full", "Code graph", "full = all files + semantic vectors; moderate; fast = no vectors.",
      "choice", ("full", "moderate", "fast")),
    S("CBM_INDEX_TIMEOUT", "7200", "Code graph", "Seconds one repository index may take.", "float"),
    S("CBM_QUERY_TIMEOUT", "120", "Code graph", "Seconds one code-graph query may take.", "float"),
    S("BRAIN_SYNC_ON_START", "true", "Updates & webhooks", "Clone/update and index all repositories when the server starts.", "bool"),
    S("BRAIN_SYNC_INTERVAL_MINUTES", "0", "Updates & webhooks", "Also fetch+index every N minutes (0 = webhooks only).", "int"),
    S("BRAIN_WATCH_LOCAL_SECONDS", "30", "Updates & webhooks",
      "Local-path repositories: every N seconds, check whether the tracked branch moved (git pull, merge, commit) "
      "and re-index it (0 = off).", "int"),
    S("BRAIN_CODE_VECTORS", "both", "Code graph",
      "Semantic code search: local = only the code engine's bundled code embeddings (offline, English-oriented); "
      "both = also a code vector index built with the corporate multilingual embedding model (Turkish questions find "
      "English code by meaning; costs one embedding pass per changed symbol after each sync).",
      "choice", ("local", "both")),
    S("BRAIN_CODE_VECTORS_BATCH", "64", "Code graph", "Symbols per embedding request when building the corporate code vectors.", "int"),
    S("BRAIN_CODE_VECTORS_PARALLEL", "4", "Code graph", "Parallel embedding requests when building the corporate code vectors.", "int"),
    S("BRAIN_CODE_VECTORS_MAX", "200000", "Code graph", "Largest number of symbols embedded per repository.", "int"),
    # ---- git servers / updates & webhooks (shown on the Repositories page) -----------------------------
    S("BRAIN_DEFAULT_BRANCH", "main", "Updates & webhooks", "Branch the code graph follows when a repository does not name one."),
    S("BRAIN_GIT_TIMEOUT", "900", "Git servers", "Seconds for one git clone/fetch.", "float"),
    S("BRAIN_GITLAB_URL", "", "Git servers",
      "Corporate GitLab base URL, e.g. https://gitlab.corp.local. Repositories can then be written as gitlab:group/project."),
    S("BRAIN_GITLAB_USER", "", "Git servers", "User for HTTPS clone/fetch from BRAIN_GITLAB_URL (any name works with a token)."),
    S("BRAIN_GITLAB_TOKEN", "", "Git servers", "GitLab personal/project access token with read_repository.", "secret"),
    S("BRAIN_TFS_URL", "", "Git servers",
      "Corporate TFS / Azure DevOps Server collection URL, e.g. https://tfs.corp.local/tfs/DefaultCollection. "
      "Repositories can then be written as tfs:Project/repo."),
    S("BRAIN_TFS_USER", "", "Git servers", "User for HTTPS clone/fetch from BRAIN_TFS_URL."),
    S("BRAIN_TFS_TOKEN", "", "Git servers", "TFS / Azure DevOps personal access token with Code (read).", "secret"),
    S("BRAIN_GIT_USER", "", "Git servers", "User for HTTPS git on any other server (fallback credentials)."),
    S("BRAIN_GIT_TOKEN", "", "Git servers", "Token for HTTPS git on any other server (fallback credentials).", "secret"),
    S("BRAIN_GIT_CA_BUNDLE", "", "Git servers", "Corporate CA certificate (PEM) for the git servers' HTTPS."),
    S("BRAIN_GIT_SSL_VERIFY", "true", "Git servers", "Verify TLS for git (false only for broken internal CAs).", "bool"),
    S("BRAIN_WEBHOOK_EVENTS", "merge,push", "Updates & webhooks",
      "Events that trigger an update of the tracked branch: merge (MR/PR merged), push (any push to it)."),
    S("BRAIN_GITLAB_WEBHOOK_SECRET", "", "Updates & webhooks", "Group-level GitLab webhook secret (/webhooks/gitlab). Each repository also has its own webhook and secret.", "secret"),
    S("BRAIN_TFS_WEBHOOK_USER", "", "Updates & webhooks", "Group-level TFS service-hook user (/webhooks/tfs)."),
    S("BRAIN_TFS_WEBHOOK_PASSWORD", "", "Updates & webhooks", "Group-level TFS service-hook password (/webhooks/tfs). Each repository also has its own webhook and secret.", "secret"),
    # ---- requirements writer -------------------------------------------------------------------------
    S("BRAIN_SRS_MODEL", "", "Requirements writer", "Chat model for the requirements writer (empty = BRAIN_LLM_MODEL)."),
    S("BRAIN_SRS_TIMEOUT", "1800", "Requirements writer", "Total seconds for one specification (all sections).", "float"),
    S("BRAIN_SRS_MAX_CAPABILITIES", "12", "Requirements writer", "Most capabilities (feature areas) described in one specification.", "int"),
    S("BRAIN_SRS_MAX_TOKENS", "3000", "Requirements writer", "Maximum tokens per written section.", "int"),
    S("BRAIN_SRS_TEMPERATURE", "0.2", "Requirements writer", "Sampling temperature.", "float"),
    S("BRAIN_SRS_LANGUAGE", "auto", "Requirements writer", "Language of the specification: auto (same as the request), English, Turkish ..."),
    # ---- document graph --------------------------------------------------------------------------------
    S("BRAIN_DOC_PROVIDER", "lightrag", "Document graph",
      "Document graph plug-in: a name in brain/providers or 'package.module:Class'.", restart="docs"),
    S("LIGHTRAG_PORT", "9631", "Document graph", "Internal LightRAG port (127.0.0.1 only).", "int", restart="docs"),
    S("LIGHTRAG_LLM_MODEL", "", "Document graph", "Chat model for entity extraction (empty = BRAIN_LLM_MODEL).", restart="docs"),
    S("LIGHTRAG_LLM_TIMEOUT", "240", "Document graph",
      "LightRAG LLM_TIMEOUT: seconds for one chat call during entity/relation extraction and summaries.", "int",
      restart="docs"),
    S("LIGHTRAG_EMBEDDING_TIMEOUT", "60", "Document graph",
      "LightRAG EMBEDDING_TIMEOUT: seconds for one embedding call.", "int", restart="docs"),
    S("LIGHTRAG_TIMEOUT", "300", "Document graph",
      "LightRAG TIMEOUT: seconds the LightRAG server allows for one HTTP request.", "int", restart="docs"),
    S("LIGHTRAG_STARTUP_TIMEOUT", "180", "Document graph", "Seconds to wait for LightRAG to become healthy.", "float"),
    S("LIGHTRAG_REQUEST_TIMEOUT", "600", "Document graph", "Seconds for one request from this server to LightRAG.", "float"),
    S("LIGHTRAG_MAX_ASYNC", "4", "Document graph", "Concurrent LLM calls during ingestion.", "int", restart="docs"),
    S("LIGHTRAG_MAX_PARALLEL_INSERT", "2", "Document graph", "Documents processed in parallel.", "int", restart="docs"),
    S("LIGHTRAG_SUMMARY_LANGUAGE", "English", "Document graph", "Language of extracted entity descriptions (English, Turkish ...).", restart="docs"),
    S("LIGHTRAG_CHUNK_SIZE", "1200", "Document graph", "Tokens per chunk.", "int", restart="docs"),
    S("LIGHTRAG_CHUNK_OVERLAP", "100", "Document graph", "Token overlap between chunks.", "int", restart="docs"),
    S("LIGHTRAG_QUERY_MODE", "mix", "Document graph", "Retrieval mode: mix (graph+vectors), hybrid, local, global, naive.",
      "choice", ("mix", "hybrid", "local", "global", "naive")),
    S("LIGHTRAG_TOP_K", "20", "Document graph", "Entities/relations retrieved per query.", "int"),
    S("LIGHTRAG_PARSER", "", "Document graph", "Override LightRAG's parser routing (empty = automatic).", restart="docs"),
]
BY_KEY = {s.key: s for s in SCHEMA}
REPO_GROUPS = ("Git servers", "Updates & webhooks")   # edited on the Repositories page, not on Settings

_lock = threading.RLock()
_file_values: dict[str, str] = {}


def config_file() -> Path:
    p = Path(os.environ.get("BRAIN_CONFIG_FILE") or ROOT / ".env").expanduser()
    return p if p.is_absolute() else (ROOT / p)


_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return re.split(r"\s+#", v, 1)[0].strip()   # inline comment: KEY=value   # note


def _parse(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            m = _LINE.match(line)
            if m and not line.lstrip().startswith("#"):
                out[m.group(1)] = _unquote(m.group(2))
    return out


def reload() -> None:
    """Re-read the .env file (called at start and after every UI change)."""
    with _lock:
        _file_values.clear()
        _file_values.update(_parse(config_file()))


def raw(key: str, default: str | None = None) -> str:
    with _lock:
        if key in _file_values:
            return _file_values[key]
    if key in os.environ:
        return os.environ[key]
    if default is not None:
        return default
    return BY_KEY[key].default if key in BY_KEY else ""


def get(key: str):
    """Typed value of a schema key."""
    s = BY_KEY[key]
    v = raw(key).strip()
    if s.kind == "int":
        return int(float(v or s.default or 0))
    if s.kind == "float":
        return float(v or s.default or 0)
    if s.kind == "bool":
        return (v or s.default).lower() in ("1", "true", "yes", "on")
    return v


def passthrough(prefix: str) -> dict[str, str]:
    """LIGHTRAG__FOO=1 -> {"FOO": "1"} (file values override process environment)."""
    out = {k[len(prefix):]: v for k, v in os.environ.items() if k.startswith(prefix)}
    with _lock:
        out.update({k[len(prefix):]: v for k, v in _file_values.items() if k.startswith(prefix)})
    return out


def validate(key: str, value: str) -> str:
    s = BY_KEY.get(key)
    if s is None:
        if not re.fullmatch(r"(LIGHTRAG__|CBM__)[A-Z0-9_]+", key):
            raise ValueError(f"unknown setting {key}")
        return value
    value = str(value).strip()
    if "\n" in value or "\r" in value:
        raise ValueError(f"{key}: value must be one line")
    if s.kind == "int" and value:
        int(float(value))
    elif s.kind == "float" and value:
        float(value)
    elif s.kind == "bool" and value and value.lower() not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
        raise ValueError(f"{key}: expected true/false")
    elif s.kind == "choice" and value and value not in s.choices:
        raise ValueError(f"{key}: expected one of {', '.join(s.choices)}")
    return value


def _quote(v: str) -> str:
    return f'"{v}"' if (v and (" #" in v or v != v.strip() or v[0] in "\"'")) else v


def update(changes: dict[str, str]) -> list[str]:
    """Validate and write changes into the .env file in place. Returns the restart scopes affected."""
    clean = {k: validate(k, v) for k, v in changes.items()}
    path = config_file()
    with _lock:
        lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
        done = set()
        for i, line in enumerate(lines):
            m = _LINE.match(line)
            if m and not line.lstrip().startswith("#") and m.group(1) in clean:
                lines[i] = f"{m.group(1)}={_quote(clean[m.group(1)])}"
                done.add(m.group(1))
        new = [k for k in clean if k not in done]
        if new:
            lines += ["", "# ---- changed from the web UI ----"] if not any("changed from the web UI" in x for x in lines) else []
            lines += [f"{k}={_quote(clean[k])}" for k in new]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        reload()
    return sorted({BY_KEY[k].restart for k in clean if k in BY_KEY and BY_KEY[k].restart}
                  | ({"docs"} if any(k.startswith("LIGHTRAG__") for k in clean) else set())
                  | ({"code"} if any(k.startswith("CBM__") for k in clean) else set()))


def public_view() -> list[dict]:
    """Schema + current values for the UI (secrets are never sent back, only whether they are set)."""
    out = []
    for s in SCHEMA:
        v = raw(s.key)
        out.append({"key": s.key, "group": s.group, "page": "repos" if s.group in REPO_GROUPS else "settings",
                    "help": s.help, "kind": s.kind, "choices": list(s.choices),
                    "restart": s.restart, "default": s.default,
                    "value": ("" if s.kind == "secret" else v), "is_set": bool(v)})
    for prefix in ("LIGHTRAG__", "CBM__"):
        for k, v in passthrough(prefix).items():
            out.append({"key": prefix + k, "group": "Pass-through", "page": "settings", "help": "Raw variable for the engine.",
                        "kind": "str", "choices": [], "restart": "docs" if prefix == "LIGHTRAG__" else "code",
                        "default": "", "value": v, "is_set": True})
    return out


# ---------------------------------------------------------------- derived paths
def data_dir() -> Path:
    p = Path(get("BRAIN_DATA_DIR") or "data").expanduser()
    p = p if p.is_absolute() else ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p.resolve()


def path(*parts: str) -> Path:
    p = data_dir().joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


def secret_key() -> bytes:
    k = get("BRAIN_SECRET_KEY")
    if k:
        return k.encode()
    f = data_dir() / ".secret_key"
    if not f.exists():
        f.write_text(secrets.token_hex(32), encoding="utf-8")
    return f.read_text(encoding="utf-8").strip().encode()


def model(role: str) -> str:
    """Chat model for a role (ask, enhance, srs, guide, lightrag) with fallback to BRAIN_LLM_MODEL."""
    return get({"ask": "BRAIN_ASK_MODEL", "enhance": "BRAIN_ENHANCE_MODEL", "lightrag": "LIGHTRAG_LLM_MODEL",
                "srs": "BRAIN_SRS_MODEL", "guide": "BRAIN_GUIDE_MODEL"}[role]) \
        or get("BRAIN_LLM_MODEL")


def tls_verify():
    if get("BRAIN_CA_BUNDLE"):
        return get("BRAIN_CA_BUNDLE")
    return get("BRAIN_VERIFY_TLS")


# ---------------------------------------------------------------- repositories & sets (repos.json)
def repos_file() -> Path:
    p = Path(os.environ.get("BRAIN_REPOS_FILE") or ROOT / "repos.json").expanduser()
    return p if p.is_absolute() else ROOT / p


def _read_repos_file() -> dict:
    f = repos_file()
    return json.loads(f.read_text(encoding="utf-8-sig") or "{}") if f.exists() else {}


def load_repos() -> list[dict]:
    return [normalize_repo(r) for r in _read_repos_file().get("repos", [])]


def load_sets() -> dict[str, list[str]]:
    """Named repository sets. Stored as {"sets": {"payments": ["billing", "web"]}} in repos.json; the older
    per-repository "sets": [...] lists are still read and merged."""
    data = _read_repos_file()
    names = {normalize_repo(r)["name"] for r in data.get("repos", [])}
    out: dict[str, list[str]] = {}
    for name, members in (data.get("sets") or {}).items():
        out[str(name)] = [m for m in members if m in names]
    for r in data.get("repos", []):
        for sname in (r.get("sets") or []) if isinstance(r.get("sets"), list) else []:
            n = normalize_repo(r)["name"]
            if n not in out.setdefault(str(sname), []):
                out[str(sname)].append(n)
    return {k: v for k, v in sorted(out.items())}


def resolve_url(url: str) -> str:
    """Expand repository shorthands against the configured corporate servers (resolved on every use, so changing
    BRAIN_GITLAB_URL / BRAIN_TFS_URL moves every repository at once):
        gitlab:group/sub/project   -> <BRAIN_GITLAB_URL>/group/sub/project.git
        tfs:Project/repo           -> <BRAIN_TFS_URL>/Project/_git/repo     (tfs:Project/_git/repo also accepted)
    Full URLs and local paths are returned unchanged."""
    url = (url or "").strip()
    kind, _, rest = url.partition(":")
    rest = rest.strip("/")
    if kind == "gitlab" and rest and not rest.startswith("/"):
        base = get("BRAIN_GITLAB_URL").rstrip("/")
        if not base:
            raise ValueError(f"{url}: set BRAIN_GITLAB_URL to use gitlab: repository names")
        return f"{base}/{rest.removesuffix('.git')}.git"
    if kind == "tfs" and rest:
        base = get("BRAIN_TFS_URL").rstrip("/")
        if not base:
            raise ValueError(f"{url}: set BRAIN_TFS_URL to use tfs: repository names")
        if "/_git/" not in rest:
            project, _, repo = rest.partition("/")
            rest = f"{project}/_git/{repo or project}"
        return f"{base}/{rest}"
    return url


def git_credentials(url: str, repo: dict | None = None) -> tuple[str, str]:
    """(user, token) for an HTTPS git URL: the repository's own token if it has one, else the GitLab or TFS
    credentials when the URL is on that server, otherwise the generic BRAIN_GIT_USER / BRAIN_GIT_TOKEN."""
    if repo and repo.get("token"):
        return repo.get("user") or "oauth2", repo["token"]
    low = (url or "").lower()
    for base, user, token in (("BRAIN_GITLAB_URL", "BRAIN_GITLAB_USER", "BRAIN_GITLAB_TOKEN"),
                              ("BRAIN_TFS_URL", "BRAIN_TFS_USER", "BRAIN_TFS_TOKEN")):
        b = get(base).rstrip("/").lower()
        if b and low.startswith(b) and get(token):
            return get(user) or "oauth2", get(token)
    return get("BRAIN_GIT_USER") or "oauth2", get("BRAIN_GIT_TOKEN")


def provider_of(url: str, path: str = "") -> str:
    """gitlab | tfs | git | local, from the URL shorthand or host."""
    u = (url or "").lower()
    if not u:
        return "local"
    if u.startswith("gitlab:") or (get("BRAIN_GITLAB_URL") and u.startswith(get("BRAIN_GITLAB_URL").lower().rstrip("/"))) \
            or "gitlab" in u:
        return "gitlab"
    if u.startswith("tfs:") or "/_git/" in u or (get("BRAIN_TFS_URL") and u.startswith(get("BRAIN_TFS_URL").lower().rstrip("/"))):
        return "tfs"
    return "git"


def normalize_repo(r: dict) -> dict:
    if not r.get("url"):   # {"gitlab": "group/project"} / {"tfs": "Project/repo"} -> url shorthand
        for kind in ("gitlab", "tfs"):
            if r.get(kind):
                r = {**r, "url": f"{kind}:{str(r[kind]).strip('/')}"}
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(r.get("name") or "").strip()).strip("-")
    if not name:
        src = str(r.get("url") or r.get("path") or "").rstrip("/\\")
        name = re.sub(r"\.git$", "", re.split(r"[/\\:]", src)[-1]) if src else ""
    if not name:
        raise ValueError("every repository needs a name, url or path")
    if not r.get("url") and not r.get("path"):
        raise ValueError(f"repository {name}: give a git 'url' (server-managed clone) or a local 'path'")
    url, path = str(r.get("url") or "").strip(), str(r.get("path") or "").strip()
    provider = str(r.get("provider") or "").strip().lower() or provider_of(url, path)
    if provider not in ("gitlab", "tfs", "git", "local"):
        raise ValueError(f"repository {name}: provider must be gitlab, tfs, git or local")
    return {"name": name, "provider": provider, "url": url, "path": path,
            "branch": str(r.get("branch") or "").strip() or get("BRAIN_DEFAULT_BRANCH"),
            "webhook_secret": str(r.get("webhook_secret") or "").strip(),
            "user": str(r.get("user") or "").strip(), "token": str(r.get("token") or "").strip(),
            "aliases": list(r.get("aliases") or [])}


def save_repos(repos: list[dict], sets: dict[str, list[str]] | None = None) -> dict:
    """Validate and write repos.json. Every repository gets its own webhook secret (generated once). A secret or
    token sent back empty by the UI keeps the stored value."""
    old = {normalize_repo(r)["name"]: normalize_repo(r) for r in _read_repos_file().get("repos", [])}
    clean = []
    for r in repos:
        n = normalize_repo(r)
        prev = old.get(n["name"], {})
        n["webhook_secret"] = n["webhook_secret"] or prev.get("webhook_secret") or secrets.token_hex(16)
        n["token"] = n["token"] if r.get("token") not in (None, "") else prev.get("token", "")
        clean.append(n)
    names = [r["name"] for r in clean]
    if len(names) != len(set(names)):
        raise ValueError("repository names must be unique")
    sets = load_sets() if sets is None else sets
    clean_sets = {}
    for sname, members in sets.items():
        sname = re.sub(r"[^\w .-]+", "-", str(sname)).strip()
        if not sname or sname == "all":
            continue
        unknown = [m for m in members if m not in names]
        if unknown:
            raise ValueError(f"set {sname}: unknown repositories {', '.join(unknown)}")
        clean_sets[sname] = sorted(dict.fromkeys(members))
    f = repos_file()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"repos": clean, "sets": clean_sets}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, f)
    return {"repos": clean, "sets": clean_sets}


reload()
if (ROOT / "vendor" / "tiktoken_cache").is_dir():  # offline BPE files (LightRAG token counting)
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(ROOT / "vendor" / "tiktoken_cache"))
