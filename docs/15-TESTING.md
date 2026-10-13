# 15 - Testing

## 1. Static checks (no server needed)
```bash
.venv/Scripts/python tests/test_static.py      # Linux: .venv/bin/python
```
The script exits with the number of failures. It checks:
- the interpreter is Python 3.13 and every module imports;
- both providers load through the plug-in registry;
- `.env.example` and `docs/03-CONFIGURATION.md` match the settings schema;
- every REST route is documented in `docs/06-API.md` and every MCP tool in `docs/07-MCP-AND-AGENTS.md`;
- prompt analysis: Turkish and identifier key terms, identifiers ranked first, stop-words, Turkish stems and
  identifier parts, language, quoted phrases, the extra stop-word setting;
- settings: invalid values rejected, changes written to the file with the right restart scope, pass-through
  variables, LightRAG timeouts passed to the child process;
- repositories: `gitlab:` and `tfs:` shorthands, credentials chosen by host, `{gitlab: …}` fields, webhook
  matching, per-repository secrets generated and kept, providers detected, sets stored, unknown set members
  rejected, the own webhook rejecting a wrong GitLab secret and accepting a TFS secret;
- document conversion: Word, HTML, CSV and code to Markdown; binary files rejected; a Word file without an
  extension or with a wrong one recognised by its content; notebook, e-mail with an attachment, zip archive and RSS
  feed converted; PDF page headers and footers removed;
- the 24-hour update: the right repositories are due (old, failed long ago, never updated);
- requirements formats: the default format parses into 10 sections, IDs are numbered, a format without sections
  and deleting `default` are rejected;
- the decision records, the bundled wheels (Python 3.13 only), the required files, and every Markdown link in the
  documentation resolves;
- the documentation describes the system as it is (no change-history wording).

## 2. End-to-end test (real engines; mock or real corporate API)
1. **Mock gateway**, for machines without the corporate API: `python tests/mock_openai.py 9000`. It answers
   `GET /v1/models`, `/v1/embeddings` with deterministic vectors (size 256) and `/v1/chat/completions` with
   LightRAG-format extractions, tool calls for the agents, expansion terms, plans and short answers.
2. **A test configuration**, for example `test.env`:
   ```
   BRAIN_HOST=127.0.0.1
   BRAIN_PORT=8799
   BRAIN_UI_PASSWORD=test-pass
   BRAIN_API_TOKEN=test-token
   BRAIN_LLM_BASE_URL=http://127.0.0.1:9000/v1
   BRAIN_LLM_API_KEY=test
   BRAIN_LLM_MODEL=mock-chat
   BRAIN_EMBEDDING_MODEL=mock-embed
   BRAIN_EMBEDDING_DIM=256
   BRAIN_GITLAB_URL=/path/to/gl
   BRAIN_GITLAB_WEBHOOK_SECRET=gl-secret
   BRAIN_TFS_WEBHOOK_USER=tfs
   BRAIN_TFS_WEBHOOK_PASSWORD=tfs-pass
   BRAIN_WATCH_LOCAL_SECONDS=5
   ```
   and a `test-repos.json` with the repository `billing`, `"url": "gitlab:payments/billing"`. The "origin" is a
   local git repository at `/path/to/gl/payments/billing.git` (so the `gitlab:` shorthand is tested as well) with the
   sample files `src/billing/invoice.py`, `tax.py` and `gateway.py`. Add `BRAIN_DATA_DIR=<empty folder>` to start
   from an empty data folder.
3. **Start**: `BRAIN_CONFIG_FILE=test.env BRAIN_REPOS_FILE=test-repos.json python brain.py serve`.
4. **Run**:
   ```bash
   python tests/smoke_test.py --url http://127.0.0.1:8799 --password test-pass --token test-token \
          --origin /path/to/gl/payments/billing.git --repo billing --gitlab-secret gl-secret --tfs-user tfs --tfs-password tfs-pass
   ```
   The exit code is the number of failures.

What it covers:
- readiness and the first sync (clone, index, code vectors) finished;
- authentication: anonymous request refused, wrong password, cookie with and without the CSRF header, bearer token;
- readiness of both engines and the corporate API;
- documents: upload and processing of a Turkish text, the converted Markdown, search finds it, delete;
- search: code and documents, a Turkish question, an unknown set, the pipeline stages, source counts, graph
  expansion, semantic scope with the multilingual code vectors;
- models: the list and a chosen model named in the answer;
- ask (tools used, model-expanded terms), enhance, background jobs with progress;
- MCP: initialize, tools/list, search, symbol, read, grep, files;
- token economy and exact lookups: the tool list stays under 6,000 characters, `outline`, `read` without a
  repository, `grep mode=files`, `symbol` by qualified name, `search detail=brief` smaller than `full`, an
  identifier in the question ranked first;
- learning: the structure overview and a project guide with its token usage;
- settings: round trip and validation;
- repositories and sets: saving, set scope, single-repository scope, repository balance in a set;
- webhooks: GitLab group hook (wrong secret, merge accepted, merged code searchable, other branch ignored), TFS
  group hook (accepted, unauthenticated rejected), the repository's own hook (URL, secret, wrong secret rejected,
  push accepted);
- branch drift: commits behind, conflict-risk file, recommendations, unpushed branch;
- branch overlay: index, search with `branch`, remove;
- a local checkout: a new commit on its tracked branch (as after a pull) is noticed and indexed automatically, and the
  new code is searchable;
- requirements writer: formats listed, a specification written with the default format, and one for something new
  (mode `new`, the `new-feature` format, the related-existing-system appendix).

## 3. Test record
Windows 11, Python 3.13.16, codebase-memory-mcp 0.11.0, LightRAG 1.5.7, mock gateway, empty data folder:
- `setup.ps1 -NonInteractive` built `.venv` and installed every package from `wheels/` with `--no-index`;
- all static checks pass;
- all 76 end-to-end checks pass; `brain hook` was installed in a checkout, and a `git pull` of `main` started an
  update on the server; cold start to `ready` takes about 10 seconds.

The Linux installer is syntax-checked; it has not been run on a Linux machine. GitLab and TFS were simulated with
their webhook payloads; no real GitLab or TFS server was used.

## 4. With the real corporate API
Point the test configuration at the real `BRAIN_LLM_*` and `BRAIN_EMBEDDING_*` values instead of the mock. The
structural checks (search, webhooks, drift, overlays, authentication, MCP) do not depend on the model; the ask,
enhance and requirements checks then depend on the model following instructions. Answer quality has to be judged
with real questions (see [19-REVIEW.md](19-REVIEW.md) §5).
