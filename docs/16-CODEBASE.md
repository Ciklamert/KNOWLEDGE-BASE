# 16 - The codebase: every file and its important facts

Size: about 6,350 lines of Python (with docstrings), a 750-line UI script, 270 lines of HTML and 220 lines of CSS.
No framework beyond FastAPI and uvicorn; 12 direct Python dependencies.

## 1. Root

| File | Facts |
|---|---|
| `brain.py` | The CLI (`serve`, `doctor`, `sync`, `search`, `ask`, `enhance`, `guide`, `drift`, `hook`, `connect`, `version`). Refuses any Python other than 3.13. Except `serve` and `doctor`, commands talk to a running server over HTTP: `BRAIN_URL`, else `BRAIN_PUBLIC_URL`, else the local host and port; bearer token `BRAIN_API_TOKEN`, else basic auth. `drift` and `enhance --path` compute git facts in the local checkout (`git fetch origin main`, `git merge-base HEAD origin/main`, `git diff --name-only origin/main...HEAD`, `git status --porcelain`) and guess the repository from the remote URL. `doctor` prints PASS / WARN / FAIL per check (configuration, corporate API, code engine, SQLite FTS5, packages, git, repositories) and exits non-zero on any FAIL. `hook` installs or removes the git hooks that update AI-BRAIN after every pull of the tracked branch. |
| `brain.cmd`, `brain.sh` | launchers that run `brain.py` with `.venv`; they print how to install when `.venv` is missing |
| `setup.ps1`, `setup.sh` | offline installers ([02](02-INSTALLATION.md)); require Python 3.13; can be run again (they keep `.env`, `repos.json` and `data/`, and rebuild `.venv` only when it is not 3.13) |
| `requirements.txt` | 11 pinned packages: fastapi, uvicorn, python-multipart, httpx, numpy, pdfplumber, pypdfium2, python-docx, python-pptx, openpyxl, pillow |
| `wheels/` | those packages and their dependencies for Python 3.13 on Windows x64 and Linux x86-64 (41 files, about 80 MB) |
| `bin/` | code engine archives and `SHA256SUMS`; setup unpacks to `bin/windows/` or `bin/linux/` |
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
  restart. Unknown keys are refused, except `CBM__*`. Saving increases the live-update counter.
- `public_view()` sends the schema with current values to the UI; secrets only as "set / not set". Groups "Git
  servers" and "Updates & webhooks" are marked for the Repositories page.
- `passthrough("CBM__")`: raw code-engine variables.
- Repositories: `load_repos()`, `load_sets()` (also reads per-repository `"sets"` lists), `normalize_repo()` (name
  sanitised to `[A-Za-z0-9_.-]`, `url` or `path` required, `{"gitlab": …}` / `{"tfs": …}` turned into shorthands,
  provider detected), `save_repos()` (unique names, webhook secret generated once, empty token keeps the stored
  one, set members must exist, atomic write).
- `resolve_url()` expands `gitlab:` and `tfs:` shorthands at use time; `git_credentials(url, repo)` picks the
  repository's own token, else the GitLab or TFS token by URL prefix, else `BRAIN_GIT_USER`/`BRAIN_GIT_TOKEN`
  (user `oauth2` when none is set); `provider_of()` detects gitlab, tfs, git or local.
- `data_dir()`, `path()`, `secret_key()` (random key persisted in `data/.secret_key`), `model(role)` (role model
  or `BRAIN_LLM_MODEL`; roles ask, enhance, srs, guide), `tls_verify()`.
- On import: reconfigures stdout/stderr to UTF-8 so Turkish text cannot crash a cp1254 Windows console.

## 3. brain/jobs.py
`Job` (id, kind, title, state running/done/error, step, progress 0-1, the last 100 steps, result, error, start
and end time). `start(kind, title, fn, background=True)` runs `fn(job)` in a thread and records the outcome with a
short traceback on error. The last 200 jobs stay in memory. `tick()` / `version()`: one counter that increases on
every visible change (job steps and ends, documents, repositories, settings, webhook deliveries); `/api/events`
streams it to the UI.

## 4. brain/llm.py
`chat(messages, model, timeout, max_tokens, temperature, tools)` returns the assistant message (content,
tool_calls; a message may carry a picture for the vision model) and adds the call's token usage to the current
thread's meter (`start_meter()`, `read_meter()`). `embed(texts)` takes the vectors it has from the vector cache
(`vcache`) and sends only the other texts, using `BRAIN_EMBEDDING_BASE_URL`/`_API_KEY` when set. `models()` lists `GET /models`
(cached for a minute). `check()` makes one tiny chat call and one embedding call and reports the real vector size.
Errors are `LLMError` with the HTTP status, which the agent loop uses to detect gateways without tool calling. TLS:
`BRAIN_CA_BUNDLE`, `BRAIN_VERIFY_TLS`; proxies from the environment are honoured.

## 4b. brain/vcache.py and brain/ocr.py
`vcache`: the persistent embedding cache `data/vectors.db` (SQLite; key = SHA-1 of model and text; int8 unit
vector; day of last use). `get()`, `put()`, `prune()` (entries unused for `BRAIN_VECTOR_CACHE_DAYS`, called daily by
`repos.refresh_stale()`), `stats()` (for `brain doctor`).
`ocr`: `available()` (RapidOCR importable and `BRAIN_OCR` not `off`), `read(bytes)` (the text lines above
`BRAIN_OCR_MIN_SCORE`; one picture at a time; the engine is loaded on first use).

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
- `tidy()`: removes the engine's paging and timing fields (`total_*`, `*_offset`, `limit`, `has_more: false`,
  `elapsed_ms` …) from tool answers, so agents do not pay tokens for them.
- `exact()`: symbols whose name or qualified-name tail equals an identifier of the question, and the main symbols of
  a named file; search ranks them first.
- `symbol()`: one symbol compactly: location, signature, docstring, source (`auto` = whole up to 60 lines, else 40;
  `full` up to 400; `none`), callers, callees, parents, tests (15 names each), other matches as one line each.
- `outline()`: the engine's `get_file_outline` (declarations with line ranges).
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
  `grep()` (the engine's `search_code`, graph-ranked; modes files / matches / full, folder filter, size limit).
- `relations()`, `find()`, `symbol()`, `node()`, `graph()` (lifts method-level edges to their owning classes,
  cached by database modification time), `ego()`: read-only SQL on the engine's SQLite file (`mode=ro`).
- `tool()`: maps `trace` and `architecture` to the engine's tools and passes `BRAIN_TOOL_MAX_TOKENS` to `trace`.
`impact()` reads the graph directly: the symbols of the changed files or names, the code that depends on them
(CALLS, HTTP_CALLS, ASYNC_CALLS, INHERITS, IMPLEMENTS, OVERRIDE, up to `depth` hops), routes through HANDLES edges,
tests through TESTS edges and test paths.

## 8. brain/providers/docgraph.py
The document engine ([ADR-002](decisions/ADR-002-document-graph.md)); no model call per chunk.
- Storage: one SQLite file `data/docs/docs.db` (tables `docs`, `chunks` with an int8 `vec` column, the FTS5 table
  `fts` (columns `body` and `stem`), `concepts` (with an int8 name vector), `mentions`, `links`, `rules`, `aliases`,
  `cards`, `meta`, `seen` = picture descriptions by SHA-1 and who made them: vision, ocr or decor) plus the pictures
  in `data/docs/assets/<doc>/`.
- `fold()` (lower case, ı = i, accents removed) and `lower()` (lower case that keeps Turkish letters whole);
  `stem()` (Turkish: one case, plural or possessive suffix, one final vowel, consonant softening undone; English:
  Snowball), `concept_key()` (folded, a suffix
  after an apostrophe removed, each word stemmed; identifiers and acronyms exact), `stemmed()`.
- `passages(md, limit)`: splits converted Markdown along headings into text passages (paragraphs whole, up to
  `BRAIN_DOC_CHUNK_CHARS`), table passages (40 rows, header repeated) and picture passages (alt text and caption),
  each with its section path and page (`<!-- page N -->` markers).
- `concepts_in()`: multi-word names in capitals, acronyms, code identifiers, quoted terms; `repeated_phrases()`:
  two-word phrases used at least twice in a document, in any word form; `definitions_in()`: "Term: definition"
  lines and two-column glossary tables; `rules_in()`: requirement sentences typed obligation, prohibition,
  recommendation or limit with their limits (`PROHIBIT`, `OBLIGE`, `ADVISE`, `LIMIT`), and table rows with numbers.
- `upload()`: keeps the original, converts it, stores the Markdown and pictures, indexes the passages, keyword index,
  concepts and links to and from other documents in one transaction (the document is searchable now), then starts
  `complete()` in the background. A document with the same name is replaced.
- `complete()`: embeds the passages without a vector in batches (`BRAIN_EMBED_BATCH`, `BRAIN_EMBED_PARALLEL`) and
  gives the pictures a text (`_describe_pictures()`, oldest first: a cached description by SHA-1; `_decorative()`
  skips pictures under `BRAIN_PICTURE_MIN_PX` or of nearly one colour (kind `decor`); the vision model within
  `_vision_budget()` and `BRAIN_VLM_TIMEOUT`, sent at most 1,600 pixels as JPEG (kind `figure`); otherwise OCR
  (kind `ocr`, upgraded to `figure` when the vision model answers later); `_picture_text()` re-derives the keyword
  index, concepts and rules); loops until nothing is left; then `_embed_concepts()` embeds the concept names in batches and `_alias()` records the concepts that mean
  the same (`BRAIN_CONCEPT_SIM`; recomputed locally when the setting changes). Runs at start-up too, so an
  interrupted or failed step is finished later, and every 10 minutes (`_every()`), so pictures waiting for the
  hourly budget or a failed call continue by themselves. A different embedding model or dimension clears the vectors at start;
  a stored index of an older analysis version is re-analysed from its passages (`reanalyse()`, no embedding of
  passages).
- `search()`: FTS5 BM25 over the folded keywords and phrases, passage vectors (the query embedding is shared with the
  code search), concept matches, fused by reciprocal rank; returns passages (`source` = document › section, page;
  `doc`; `kind`; `matched`; `similarity`), the rules in them, concepts with definitions and aliases, and facts
  (sentences naming two concepts); the concept list comes from `_ppr()` (Personalized PageRank over the
  passage-concept graph built by `_mentions()`, cached until the index changes); `concept_vectors()` gives search the
  concept vectors for the concept → code links.
- Document cards and themes (no model): `doc_facts()` (dates, effective date, versions, document numbers),
  `central_sentences()` (LexRank over TF-IDF of stemmed words), `minhash()` (near-identical documents), `_card()`,
  `cards()` (with `superseded_by` and `versions_of`, cached until the index changes), `themes()` (label propagation
  over the concept co-occurrence graph, named by the most mentioned concepts).
- `graph()`, `labels()`: concepts named in at least two passages (in a small library all of them), the documents
  that name them, related concepts and document links; `delete()` removes everything derived, including pictures,
  the original and the Markdown; `reindex()` converts and indexes every original again; `documents()`,
  `pipeline()`, `markdown()`.

## 8b. brain/providers/docgrammar.py
The document grammar ([ADR-029](decisions/ADR-029-document-grammar.md)): `normalize_lines()` (inline article, paragraph
and item markers of PDF text start a new line), `parse_units()` (parts, chapters, articles, numbered sections,
paragraphs, items, sub-items, annexes, requirement IDs; keys such as `art:5/par:2/ite:b`, `sec:4.3`, `req:REQ-004`),
`unit_keys()` (what a person types → keys), `find_refs()` (internal, requirement, law and standard references),
`find_definitions()`, `amendment()`, `core()`, `parse_statement()` (modality with RFC 2119, actor, action, object,
condition, exception, confidence; Turkish: "tarafından", passive verbs, predicates such as "zorunludur"; user stories)
and `gherkin()` (Given / When / Then). In the engine, `_grammar()` stores units, references (and a "reference" concept
per resolved reference, so PageRank follows them), definitions and statement slots; `doc_query()` answers the `doc`
tool.

## 9. brain/providers/convert.py
Every document becomes Markdown, following the idea of Microsoft's MarkItDown ([ADR-019](decisions/ADR-019-everything-to-markdown.md)):
- `convert(filename, data)` is the one entry point and returns a `Pack`: Markdown lines (`text`) and pictures
  (`assets`, `assets/<hash>.<ext>`).
- `sniff(data)` tells what the bytes are, whatever the name says: magic numbers (PDF, PNG, JPEG, GIF, WEBP), the
  files inside a zip (Word, PowerPoint, Excel, EPUB, plain zip), and the shape of text (notebook, JSON, RSS/Atom,
  XML, HTML, e-mail, text). Bytes with NUL characters that no converter accepts are rejected.
- `CONVERTERS` is the registry: each `Converter` names the extensions and content kinds it accepts. They are tried in
  this order: extension and content agree; a specific content kind (a `.xml` that is an RSS feed, a `.pdf` that is
  really a Word file); the extension; a generic content kind (JSON, XML, text). If one fails, the next is tried.
- Converters: **PDF** (pdfplumber + pypdfium2: reading order, headings from font sizes, ruled tables, pictures
  cropped at 2× (smaller than 64 pixels skipped), scanned pages and pages with drawn charts rendered whole, page
  markers, page headers and footers removed); **Word** (headings from styles, lists, bold and italic, tables,
  pictures); **PowerPoint** (titles, bullets, tables, chart data, pictures, speaker notes); **Excel** (one table per
  sheet, at most 2,000 rows and 40 columns); **HTML** (headings, nested lists, links, bold and italic, code blocks,
  image alt text, tables; navigation, side bars, forms, footers and scripts dropped); **CSV/TSV**; **JSON**
  (pretty-printed); **XML**; **RSS/Atom** (one section per item); **Jupyter notebooks** (Markdown cells, code cells in
  the notebook's language, shortened text outputs, image outputs); **EPUB** (chapters in reading order); **e-mail**
  `.eml` (headers, text, every convertible attachment); **zip** (every file inside, one level deep, at most 200 files
  of 25 MB); **images** (the picture plus size, date, camera and description from EXIF); **source code and
  configuration** (fenced blocks); **text** (UTF-8, then cp1254, then Latin-1; at most 2 million characters).
- `md_table()` writes Markdown pipe tables (pipes in cells escaped). `_tidy()` keeps the output token-efficient: no
  trailing spaces, no runs of blank lines; a picture repeated more than twice (logos) is kept only twice;
  `_drop_repeated()` removes PDF page headers and footers (lines at the top or bottom of at least 3 pages and half of
  all pages).

## 10. brain/query.py
Prompt analysis ([05](05-SEARCH-ASK-ENHANCE.md) §2): tokeniser (words, identifiers, paths, quoted phrases), English
and Turkish stop-word lists plus `BRAIN_STOPWORDS_EXTRA`, scoring, Turkish suffix / English plural / identifier-part
variants, concepts, language; `analyze(text)` and `summary(analysis)`.

## 11. brain/codevec.py
The multilingual code vector index ([ADR-020](decisions/ADR-020-semantic-code-search.md)). `update(project)` embeds new
and changed symbols (by content hash) in parallel batches (`BRAIN_EMBED_BATCH`, `BRAIN_EMBED_PARALLEL`,
`BRAIN_CODE_VECTORS_MAX`) and
reuses the rest; a different embedding model or dimension rebuilds the index. Storage:
`data/codevec/<project>.npz` (model name, qualified names, hashes, int8 L2-normalised vectors: one byte per
dimension). `search(query_vector, projects, k)` is a NumPy dot product; `vectors(hits)` returns the stored vectors
of given hits (used for re-ranking without an API call); `remove()`.

## 12. brain/search.py
`search()` runs the pipeline of [05](05-SEARCH-ASK-ENHANCE.md) §3: analysis, parallel recall (code engine,
code vectors, the document engine), `exact()` (named symbols), `_bridge_terms()` (document → code), `neighbors()` (graph
expansion), `query_vector()` (the question's one embedding: shared by concurrent callers, cached for 20,000
texts, waited for at most `BRAIN_EMBED_BUDGET`), `rerank()` (code candidates by their stored vectors), `_concept_code()` (document concepts → implementing code by stored vectors), `_pin()` (named symbols first), `_diversify()`
(repository balance), `annotate()`. `_merge()` fuses hit lists by reciprocal rank and unites `matched`; `_tag()`
labels a list. `render()` turns a result into Markdown at a detail level (`LEVELS`: brief, normal, full) within a
size budget; `sources()` lists citations; `evidence()` is the compact copy for the UI's evidence panels.

## 13. brain/agents.py
Prompts `GROUNDING`, `TOOL_GUIDE`, `ASK_SYSTEM`, `ENHANCE_SYSTEM` (one prompt for every request class), `GUIDE_SYSTEM`, `EXPAND_SYSTEM`
([ADR-022](decisions/ADR-022-prompt-design.md)); `expand()` (one short call for extra search terms; returns `[]` on
any error); `TOOLS` (OpenAI function schemas of the eleven tools); `cap()` (cuts a tool answer at
`BRAIN_TOOL_MAX_TOKENS`); `Context` (the scope: projects, `describe()` for the model, `targets()`, `_first()` (the
first repository where a file exists), `run_tool()` — also used by MCP and REST, so every surface answers the same
way); `run_agent()` (the loop: deadline, step limit, at most 4 tools per round, 8,000 characters per tool result,
repeated identical calls answered with a note, switch to one grounded call on HTTP 400/404/422/501 in `auto` mode);
`ask()`, `enhance()`, `guide()`, `fallback_prompt()`, `impact()` and `render_impact()` (blast radius per repository
in scope plus the document passages that name the changed code; no model call).

## 14. brain/srs.py
The requirements writer ([17](17-REQUIREMENTS-WRITER.md)): rules `RULES` and `WRITING_RULES`, the
planner `PLAN` (one of each, no modes); the user's formats (`templates`, `get_template`, `save_template`,
`delete_template`, `parse`: the headings of the most used level are the sections); outputs (`documents`, `read`,
`delete`); `_number()` numbers `XX-?` IDs per prefix; `write()`: evidence → plan (with
the sections to write per capability) → one part per capability → the other sections → placeholders, numbering and
appendix → `data/srs/output/<timestamp>-<title>.md` plus a `.json` with metadata. There is no built-in format.

## 15. brain/repos.py
Registry and sets (the implicit set `all`), `resolve_scope()` (a branch overlay replaces its repository when
`branch` matches), `git()` (token as an `http.extraHeader`, `GIT_TERMINAL_PROMPT=0`, no console window on
Windows, credentials masked in errors, `BRAIN_GIT_TIMEOUT`), `update_checkout()`, `sync_repo()` (update, index,
code vectors, stale memories, state), `sync_all()` (one at a time), `request_sync()` (starts at once; a request during a running
update makes it run once more), `watch_local()` (re-indexes local checkouts whose tracked branch moved), `refresh_stale()` and `due()` (every
repository at least every `BRAIN_SYNC_INTERVAL_MINUTES`, 24 hours by default),
`hook_script()` (the git hook `brain hook` installs), `index_branch()` /
`remove_branch()` (git worktrees; an overlay records `main` or its `base`), `mains()` (the main branch, then
`mains`), `_sync_mains()` (after every update: re-indexes other main branches whose head moved), `base_of()` (the
main a branch derives from: fewest commits not shared), `request_branch()` (one index job per branch at a time), `drop_branch()`,
`reconcile_branches()` (after every update: `git ls-remote --heads`, removes overlays of deleted branches),
`expire_branches()` and `expires_at()` (`BRAIN_BRANCH_TTL_DAYS`, counted from the last index or search; searches record
`used_at` at most hourly), `state()` in `data/state.json`, `webhook_info()`, `overview()`.

## 16. brain/drift.py
`check()` fetches `main` and the branch, finds the merge-base, counts commits behind, builds the file sets and the
conflict-risk files, the tests to run for the branch's files (`impact`), and returns ordered recommendations
([10](10-BRANCH-DRIFT.md)); `render()` writes Markdown.

## 16b. brain/memory.py
Decision memory ([ADR-028](decisions/ADR-028-agent-needs.md)): `remember()` (type, title, text, repository, paths,
source; type + title is the identity, a newer one replaces the older and keeps up to 5 old texts in `history`;
each memory is also a document `memory-<type>-<title>.md`), `recall()` (newest first, or ranked by the document
search and the words of a query), `forget()`, `check_stale()` (after every repository update: code paths that no
longer exist), `render()`. Stored in `data/memory/memories.json`.

## 17. brain/webhooks.py
`repo_hook(name)` (the repository's own webhook; GitLab or TFS recognised from the request), `gitlab()` and `tfs()`
(group-level hooks), `_norm()` (URL normalisation: scheme, credentials, `.git`, `/_git/`, ssh `:`), `match_repo()`
(exact, then the last two path parts), `_other_branch()` (a deleted branch removes its overlay; a push to a branch
with an overlay updates it), `LOG` (the last 50 deliveries).

## 18. brain/mcp.py
`TOOLS` (18 tools with terse JSON schemas; the scope arguments are explained once in `INSTRUCTIONS`),
`call_tool()` (code tools go through `agents.Context.run_tool`), `handle()` (`initialize` with version negotiation
and instructions, `ping`, `tools/list`, `tools/call`; notifications get no reply, so the HTTP answer is 202).

## 19. brain/server.py
`boot()` (webhook secrets, three start-up jobs, initial sync, the daily update and the local-pull watch), the `guard` middleware (public paths,
`identify()`, CSRF header), every route of [06-API.md](06-API.md), and `main()` (log file, password guard for
non-loopback addresses, the selector event loop on Windows, TLS, the `READY` announcer). `/api/events` streams
the live-update counter as server-sent events.

## 20. brain/ui/
`index.html` (login and the twelve pages), `app.js` (API helper that adds the CSRF header, job follower, a small
Markdown renderer with tables and links, prompt-analysis chips, the shared result renderer and evidence panel,
force-graph wrappers, one init/refresh pair per page, the live-update listener `live()` that refreshes the visible
page on every server event), `style.css` (light and dark colour tokens, responsive layout),
`vendor/force-graph.min.js` (MIT, v1.52.0).

## 21. tests/ and tools/
`tests/mock_openai.py` (a fake corporate API: embeddings, tool calls, plans, picture descriptions), `tests/smoke_test.py` (the end-to-end test), `tests/test_static.py`
(the static checks) ([15](15-TESTING.md)); `tools/gen_config.py` (writes `.env.example` and
`docs/03-CONFIGURATION.md` from the schema; `--check` mode is used by the static test).

## 22. integrations/
`AGENTS.brain.md` (a block to append to `AGENTS.md` or `CLAUDE.md`: use AI-BRAIN instead of grep, glob and read,
with `curl` commands for agents without MCP); `claude-code/brain-enhance.md` (the `/brain-enhance` command for
Claude Code).
