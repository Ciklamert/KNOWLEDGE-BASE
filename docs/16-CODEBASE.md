# 16 - The codebase: every file and its important facts

Size: about 5,300 lines of Python (with docstrings), a 670-line UI script, 240 lines of HTML and 210 lines of CSS.
No framework beyond FastAPI and uvicorn, which LightRAG already brings.

## 1. Root

| File | Facts |
|---|---|
| `brain.py` | The CLI (`serve`, `doctor`, `sync`, `search`, `ask`, `enhance`, `drift`, `connect`, `version`). Refuses any Python other than 3.13. Except `serve` and `doctor`, commands talk to a running server over HTTP: `BRAIN_URL`, else `BRAIN_PUBLIC_URL`, else the local host and port; bearer token `BRAIN_API_TOKEN`, else basic auth. `drift` and `enhance --path` compute git facts in the local checkout (`git fetch origin main`, `git merge-base HEAD origin/main`, `git diff --name-only origin/main...HEAD`, `git status --porcelain`) and guess the repository from the remote URL. `doctor` prints PASS / WARN / FAIL per check and exits non-zero on any FAIL. |
| `brain.cmd`, `brain.sh` | launchers that run `brain.py` with `.venv`; they print how to install when `.venv` is missing |
| `setup.ps1`, `setup.sh` | offline installers ([02](02-INSTALLATION.md)); require Python 3.13; can be run again (they keep `.env`, `repos.json` and `data/`, and rebuild `.venv` only when it is not 3.13) |
| `requirements.txt` | `lightrag-hku[api]==1.5.7` (pinned, because the provider uses its REST API and variable names) plus pdfplumber, pypdfium2, python-pptx, openpyxl |
| `wheels/` | every package for Python 3.13 on Windows x64 and Linux x86-64 |
| `bin/` | code engine archives and `SHA256SUMS`; setup unpacks to `bin/windows/` or `bin/linux/` |
| `vendor/tiktoken_cache/` | tokenizer files LightRAG would otherwise download |
| `.env.example` | generated; every setting with its help text and default |
| `repos.example.json` | GitLab, TFS, other-server and local-path repositories, with sets |
| `INSTALL.html` | the installation guide with Windows and Linux tabs |

## 2. brain/settings.py
- `SCHEMA`: a list of `Setting(key, default, group, help, kind, choices, restart)`, the single source for the
  Settings and Repositories pages, validation, `.env.example` and [03-CONFIGURATION.md](03-CONFIGURATION.md).
  `kind` is str, int, float, bool, secret or choice; `restart` is empty (live), `code`, `docs` or `server`.
- Precedence: the `.env` file, then the process environment, then the default (`raw()`); `get()` returns typed
  values. The file path is `BRAIN_CONFIG_FILE` or `.env` in the install folder.
- `update()` validates, rewrites only the changed lines (comments and order kept; new keys are appended under
  "changed from the web UI"), writes atomically (`.tmp` + `os.replace`), reloads, and returns which engines must
  restart. Unknown keys are refused, except `LIGHTRAG__*` and `CBM__*`.
- `public_view()` sends the schema with current values to the UI; secrets only as "set / not set". Groups "Git
  servers" and "Updates & webhooks" are marked for the Repositories page.
- `passthrough("LIGHTRAG__")` / `passthrough("CBM__")`: raw engine variables.
- Repositories: `load_repos()`, `load_sets()` (also reads per-repository `"sets"` lists), `normalize_repo()` (name
  sanitised to `[A-Za-z0-9_.-]`, `url` or `path` required, `{"gitlab": …}` / `{"tfs": …}` turned into shorthands,
  provider detected), `save_repos()` (unique names, webhook secret generated once, empty token keeps the stored
  one, set members must exist, atomic write).
- `resolve_url()` expands `gitlab:` and `tfs:` shorthands at use time; `git_credentials(url, repo)` picks the
  repository's own token, else the GitLab or TFS token by URL prefix, else `BRAIN_GIT_USER`/`BRAIN_GIT_TOKEN`
  (user `oauth2` when none is set); `provider_of()` detects gitlab, tfs, git or local.
- `data_dir()`, `path()`, `secret_key()` (random key persisted in `data/.secret_key`), `model(role)` (role model
  or `BRAIN_LLM_MODEL`; roles ask, enhance, srs, lightrag), `tls_verify()`.
- On import: sets `TIKTOKEN_CACHE_DIR` to `vendor/tiktoken_cache`, and reconfigures stdout/stderr to UTF-8 so
  Turkish text cannot crash a cp1254 Windows console.

## 3. brain/jobs.py
`Job` (id, kind, title, state running/done/error, step, progress 0-1, the last 100 steps, result, error, start
and end time). `start(kind, title, fn, background=True)` runs `fn(job)` in a thread and records the outcome with a
short traceback on error. The last 200 jobs stay in memory.

## 4. brain/llm.py
`chat(messages, model, timeout, max_tokens, temperature, tools)` returns the assistant message (content,
tool_calls). `embed(texts)` uses `BRAIN_EMBEDDING_BASE_URL`/`_API_KEY` when set. `models()` lists `GET /models`
(cached for a minute). `check()` makes one tiny chat call and one embedding call and reports the real vector size.
Errors are `LLMError` with the HTTP status, which the agent loop uses to detect gateways without tool calling. TLS:
`BRAIN_CA_BUNDLE`, `BRAIN_VERIFY_TLS`; proxies from the environment are honoured.

## 5. brain/auth.py
Session cookie `brain_session` = base64(user|expiry) + HMAC-SHA256; it becomes invalid when it expires or the
user name changes. `check_password()` counts failures per address; `locked()` after 5 failures within 60 s.
`identify()` tries cookie, then bearer token, then basic auth.

## 6. brain/providers/__init__.py
`Engine` (state stopped/starting/ready/error, `start`, `stop`, `health`), `CodeGraph` and `DocGraph` with required
and optional methods ([08](08-PLUGINS.md)); `get(kind)`, `code()`, `docs()`, `reload(kind)` (stop, re-create from
the current setting, start). The loader accepts a module name in `brain/providers/` or `package.module:Class`.

## 7. brain/providers/codebase_memory.py
- `binary()`: `CBM_BIN` or `bin/<os>/codebase-memory-mcp[.exe]`.
- Environment: `CBM_CACHE_DIR=data/cbm` plus `CBM__*`. Fact: the cache directory must not be world-writable (the
  engine refuses otherwise), so it lives in the install's data folder, not in the system temp folder.
- `_Stdio`: one persistent JSON-RPC connection over stdin/stdout; a lock serialises queries; on failure it
  restarts the process and retries once.
- `index()`: a separate `cli --progress --json index_repository` process with `name=<project>` and
  `mode=CBM_INDEX_MODE`, bounded by `CBM_INDEX_TIMEOUT`; progress lines go to the job; one index at a time. Fact:
  the engine normalises project names (`billing--feature/x` → `billing-feature-x`), so the returned name is stored.
- `remove()`: `delete_project`, then it deletes `<project>.db`, `-wal` and `-shm` itself after stopping the query
  process (Windows cannot delete open files). Fact: version 0.11 answers `not_found` for caches under non-ASCII
  paths such as `Masaüstü`.
- `search()`: per project `search_graph` with the keywords (BM25) and with `semantic_query` (first 8 key terms,
  bundled code model), fused by reciprocal rank (k = 60); `matched` records which list found each hit.
- `hits_for()`: tests ×0.5, symbols under three lines ×0.6, skips folders, files, variables and external symbols.
- `with_code()`: up to 40 source lines read from the indexed root, never outside it.
- `symbols()`: every function, method, class, interface, enum, struct, trait, type, route, record and object with
  label, short name, path, signature, docstring and the first 25 lines (at most 2,000 characters): the text the
  multilingual code vector index embeds.
- `neighbors()`: graph expansion over CALLS, INHERITS, IMPLEMENTS, OVERRIDE, HTTP_CALLS, ASYNC_CALLS, DATA_FLOWS.
- `annotate()`: signature, up to 6 callers and callees, up to 4 parents.
- `files()` (glob over the `file_hashes` table, at most 300), `read()` (at most 400 lines, numbered, path-guarded),
  `grep()` (the engine's `search_code`, graph-ranked).
- `relations()`, `find()`, `symbol()`, `node()`, `graph()` (lifts method-level edges to their owning classes,
  cached by database modification time), `ego()`: read-only SQL on the engine's SQLite file (`mode=ro`).
- `tool()`: maps `trace`, `snippet`, `architecture`, `query_graph`, `file_outline` to the engine's tools.

## 8. brain/providers/lightrag.py
- `child_env()`: maps `BRAIN_*` and `LIGHTRAG_*` settings to LightRAG's variables (`LLM_BINDING_HOST`,
  `LLM_MODEL`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `TIMEOUT`, `LLM_TIMEOUT`, `EMBEDDING_TIMEOUT`, `MAX_ASYNC`,
  `MAX_PARALLEL_INSERT`, `SUMMARY_LANGUAGE`, `CHUNK_SIZE`, `CHUNK_OVERLAP_SIZE`, `VLM_LLM_MODEL`, …), disables
  LightRAG's reranker and remote image downloads, adds `NO_PROXY` for 127.0.0.1, then applies `LIGHTRAG__*`.
- `parser_rule()`: `LIGHTRAG_PARSER`, or `*:native-iteP,*:legacy-R` with a vision model and `*:native-teP,*:legacy-R`
  without (`i` images, `t` tables, `e` equations, `P` heading-aware paragraph chunking).
- `_spawn()`: writes a placeholder `.env` in LightRAG's working directory. Fact: `lightrag-server` asks
  "continue? (yes/NO)" when that file is missing and stdin looks like a terminal; on Windows even `NUL` counts, so
  without the placeholder it exits with EOFError. Real values come from the environment, which LightRAG's
  `load_dotenv(override=False)` never overrides.
- `start()`: waits for `/health` up to `LIGHTRAG_STARTUP_TIMEOUT`; a watchdog restarts a crashed process up to
  5 times.
- `upload()`: keeps the original in `data/originals/`, converts it (`convert.to_markdown`), keeps the Markdown in
  `data/converted/`, uploads `<file>.md` or `<file>.textpack`.
- `search()`: `POST /query/data` with `hl_keywords` (concepts) and `ll_keywords` (key terms), so LightRAG skips its
  keyword-extraction model call.
- `documents()` (paginated, shows the uploaded name), `pipeline()`, `graph()`, `labels()`, `delete()` (also deletes
  the cached extraction results), `markdown()`.

## 9. brain/providers/convert.py
`to_markdown(filename, data)` turns every supported format into Markdown and returns the stored name, the payload
and the Markdown:
- **PDF** (pdfplumber + pypdfium2): text in reading order, headings from font sizes, ruled tables as HTML, embedded
  pictures cropped at 2× (smaller than 64 pixels: skipped), pages without a text layer and pages with charts or
  diagrams drawn as vector paths rendered whole for the vision model.
- **Word**: headings from styles, lists, bold and italic, tables, pictures.
- **PowerPoint**: titles, bullets, tables, chart data, pictures, speaker notes.
- **Excel**: each sheet as HTML tables of 200 rows (header repeated), at most 2,000 rows and 40 columns per sheet.
- **HTML** (dependency-free converter), **CSV/TSV** (tables), **source code and configuration files** (fenced code
  blocks), **text** (UTF-8, then Turkish Windows code page cp1254, then Latin-1), **Markdown** (as is), **images**.
- A picture repeated more than twice (logos, page headers) is kept only twice.
- With pictures the result is a `.textpack` (a zip with `text.md` and `assets/`), otherwise `.md`. Unknown binary
  formats are rejected with the list of supported formats.

## 10. brain/query.py
Prompt analysis ([05](05-SEARCH-ASK-ENHANCE.md) §2): tokeniser (words, identifiers, paths, quoted phrases), English
and Turkish stop-word lists plus `BRAIN_STOPWORDS_EXTRA`, scoring, Turkish suffix / English plural / identifier-part
variants, concepts, language; `analyze(text)` and `summary(analysis)`.

## 11. brain/codevec.py
The multilingual code vector index ([ADR-020](decisions/ADR-020-semantic-code-search.md)). `update(project)` embeds new
and changed symbols (by content hash) in parallel batches (`BRAIN_CODE_VECTORS_BATCH`, `_PARALLEL`, `_MAX`) and
reuses the rest; a different embedding model or dimension rebuilds the index. Storage:
`data/codevec/<project>.npz` (model name, qualified names, hashes, int8 L2-normalised vectors: one byte per
dimension). `search(query_vector, projects, k)` is a NumPy dot product; `remove()`.

## 12. brain/search.py
`search()` runs the pipeline of [05](05-SEARCH-ASK-ENHANCE.md) §3: analysis, parallel recall (code engine,
code vectors, LightRAG), `_bridge_terms()` (document → code), `neighbors()` (graph expansion), `rerank()` (cached
corporate embeddings, 20,000 entries), `_diversify()` (repository balance), `annotate()`. `_merge()` fuses hit lists
by reciprocal rank and unites `matched`; `_tag()` labels a list. `render()` turns a result into Markdown within a
size budget; `sources()` lists citations; `evidence()` is the compact copy for the UI's evidence panels.

## 13. brain/agents.py
Prompts `GROUNDING`, `TOOL_GUIDE`, `ASK_SYSTEM`, `ENHANCE_SYSTEM`, `EXPAND_SYSTEM` ([ADR-022](decisions/ADR-022-prompt-design.md));
`expand()` (one short call for extra search terms; returns `[]` on any error); `TOOLS` (OpenAI function schemas of
the ten tools); `Context` (the scope: projects, `describe()` for the model, `run_tool()`); `run_agent()` (the loop:
deadline, step limit, at most 4 tools per round, 8,000 characters per tool result, switch to one grounded call on
HTTP 400/404/422/501 in `auto` mode); `ask()`, `enhance()`, `fallback_prompt()`.

## 14. brain/srs.py
The requirements writer ([17](17-REQUIREMENTS-WRITER.md)): `SRS_SYSTEM`, `PLAN_SYSTEM`, `DEFAULT_TEMPLATE`; formats
(`templates`, `get_template`, `save_template`, `delete_template`, `parse`); outputs (`documents`, `read`, `delete`);
`write()`: evidence → plan → one part per capability → the other sections → placeholders, numbering and traceability
appendix → `data/srs/output/<timestamp>-<title>.md` plus a `.json` with metadata.

## 15. brain/repos.py
Registry and sets (the implicit set `all`), `resolve_scope()` (a branch overlay replaces its repository when
`branch` matches), `git()` (token as an `http.extraHeader`, `GIT_TERMINAL_PROMPT=0`, no console window on
Windows, credentials masked in errors, `BRAIN_GIT_TIMEOUT`), `update_checkout()`, `sync_repo()` (update, index,
code vectors, state), `sync_all()` (one at a time), `request_sync()` (debounce), `index_branch()` /
`remove_branch()` (git worktrees), `state()` in `data/state.json`, `webhook_info()`, `overview()`.

## 16. brain/drift.py
`check()` fetches `main` and the branch, finds the merge-base, counts commits behind, builds the file sets and the
conflict-risk files, and returns ordered recommendations ([10](10-BRANCH-DRIFT.md)); `render()` writes Markdown.

## 17. brain/webhooks.py
`repo_hook(name)` (the repository's own webhook; GitLab or TFS recognised from the request), `gitlab()` and `tfs()`
(group-level hooks), `_norm()` (URL normalisation: scheme, credentials, `.git`, `/_git/`, ssh `:`), `match_repo()`
(exact, then the last two path parts), `LOG` (the last 50 deliveries).

## 18. brain/mcp.py
`TOOLS` (15 tools with JSON schemas), `call_tool()`, `handle()` (`initialize` with version negotiation and
instructions, `ping`, `tools/list`, `tools/call`; notifications get no reply, so the HTTP answer is 202).

## 19. brain/server.py
`boot()` (webhook secrets, three start-up jobs, initial and interval sync), the `guard` middleware (public paths,
`identify()`, CSRF header), every route of [06-API.md](06-API.md), and `main()` (log file, password guard for
non-loopback addresses, the selector event loop on Windows, TLS, the `READY` announcer).

## 20. brain/ui/
`index.html` (login and the eleven pages), `app.js` (API helper that adds the CSRF header, job follower, a small
Markdown renderer, prompt-analysis chips, the shared result renderer and evidence panel, force-graph wrappers, one
init/refresh pair per page), `style.css` (light and dark colour tokens, responsive layout),
`vendor/force-graph.min.js` (MIT, v1.52.0).

## 21. tests/ and tools/
`tests/mock_openai.py` (a fake corporate API), `tests/smoke_test.py` (the end-to-end test), `tests/test_static.py`
(the static checks) ([15](15-TESTING.md)); `tools/gen_config.py` (writes `.env.example` and
`docs/03-CONFIGURATION.md` from the schema; `--check` mode is used by the static test).

## 22. integrations/
`AGENTS.brain.md` (a block to append to `AGENTS.md` or `CLAUDE.md`: use AI-BRAIN instead of grep, glob and read,
with `curl` commands for agents without MCP); `claude-code/brain-enhance.md` (the `/brain-enhance` command for
Claude Code).
