# 08 - Plug-ins: replacing the code engine or LightRAG

Everything outside `brain/providers/` talks to two abstract interfaces, `CodeGraph` and `DocGraph`. Replacing an
engine means writing one class and changing one setting; search, agents, the requirements writer, MCP, REST, the UI
and the webhooks keep working.

## 1. Choosing a provider

| Setting | Default | Value |
|---|---|---|
| `BRAIN_CODE_PROVIDER` | `codebase_memory` | a module name in `brain/providers/` (its class `Provider`), or `package.module:ClassName` |
| `BRAIN_DOC_PROVIDER` | `lightrag` | the same |

Changing it in **Settings** stops the old engine and starts the new one; changing it in `.env` needs a server
restart. The loader checks that the class implements the right interface.

## 2. The contracts (`brain/providers/__init__.py`)

Life cycle for both (`Engine`): `start()` makes the engine ready (it may block; it runs in a background job) and
sets `self.state` (`stopped`, `starting`, `ready`, `error`) and `self.detail`; `stop()`; `health()` returns
`{provider, state, detail}` and may add more.

### CodeGraph
A *project* is one indexed tree: a repository (named like the repository) or a branch overlay
(`<repo>--<branch>`).

| Method | Required | Contract |
|---|---|---|
| `index(project, path, log)` | yes | (re)index the tree at `path` as `project`, incrementally where possible; report with `log(message, progress)`; return stats including the final `project` name, `nodes`, `edges` |
| `remove(project)` | yes | delete that project's index |
| `projects()` | yes | `[{name, root, indexed_at, nodes, edges}]` |
| `search(query, keywords, projects, k, mode)` | yes | **no model call**; `keywords` = ranked key terms, then variants; `mode` = `hybrid`, `semantic` or `lexical`; hits `{project, id, qn, name, label, path, line1, line2, score, code, matched}` |
| `relations(hits, limit)` | no | `[{project, type, a, b}]` edges around the hits |
| `neighbors(hits, limit)` | no | graph expansion: hits wired to the given hits, each with `matched` saying how |
| `annotate(hits)` | no | add `signature`, `callers`, `callees`, `parents` |
| `with_code(hits)` | no | attach source lines as `code` |
| `symbols(project, limit)` | no | `[{qn, text}]` for every function, class and route: what the multilingual code vector index embeds; `[]` disables that index |
| `hits_for(project, scored)` | no | `{qualified name: score}` → hits in the `search` shape (used by the code vector index) |
| `files(project, pattern, limit)` | no | indexed file paths matching a glob |
| `read(project, path, start, end)` | no | `{project, path, start, end, total_lines, text}` |
| `grep(project, pattern, regex, file_pattern, limit)` | no | text matches as Markdown |
| `symbol(name, projects)` | no | Markdown with definition, source, callers and callees |
| `tool(name, args)` | no | deep tools as text: `trace`, `snippet`, `architecture` (the `overview` tool), `query_graph`, `file_outline` |
| `graph(project, limit)`, `ego(project, node_id, depth)`, `node(project, node_id)`, `find(q, projects, limit)` | no | data for the Code graph page |

### DocGraph

| Method | Required | Contract |
|---|---|---|
| `upload(filename, data)` | yes | ingest a file; return `{file, status, message, …}` |
| `add_text(name, text)` | yes | ingest a note |
| `delete(doc_ids)` | yes | remove documents and everything derived from them |
| `documents()` | yes | `[{id, name, status, chunks, updated_at, error}]` |
| `search(query, keywords, chunks, top_k, concepts)` | yes | **no chat call**; `keywords` = key terms + variants, `concepts` = themes; return `{chunks: [{source, content}], entities: [{name, type, description}], relations: [{a, b, description}]}` |
| `pipeline()` | no | ingestion progress `{busy, job, message, batch, batches, docs, history}` |
| `graph(label, max_nodes, depth)` | no | `{nodes: [{id, name, kind, description}], links: [{source, target, type, description}], truncated}` |
| `labels(q)` | no | entity names |
| `markdown(name)` | no | the Markdown a document was converted to |

## 3. A new document engine, step by step
1. Create `brain/providers/mydocs.py` (or a module in any importable package on the server).
2. Implement the class:
   ```python
   from brain.providers import DocGraph
   from brain import settings as cfg

   class Provider(DocGraph):
       name = "mydocs"

       def start(self):
           # connect or spawn; read your own settings with cfg.raw("MYDOCS_URL", "http://127.0.0.1:7000")
           self.state, self.detail = "ready", "connected"

       def upload(self, filename, data): ...
       def add_text(self, name, text): ...
       def delete(self, doc_ids): ...
       def documents(self): ...
       def search(self, query, keywords, chunks, top_k, concepts=None): ...
   ```
   To keep the Markdown conversion, call `brain.providers.convert.to_markdown(filename, data)` in `upload`.
3. Set `BRAIN_DOC_PROVIDER=mydocs` (or `mycompany.brain_ext:MyDocs`).
4. Put its own settings in `.env` under any name and read them with `cfg.raw("NAME", "default")`, or add them to
   the schema in `brain/settings.py` and run `python tools/gen_config.py`, so they appear in the UI and in
   [03-CONFIGURATION.md](03-CONFIGURATION.md).
5. Run `brain doctor`, start the server, run `tests/smoke_test.py`.

## 4. A new code engine
The same steps with `CodeGraph`. Map the engine's project concept to "one index per repository name", return hits
in the documented shape and keep `search` free of model calls. If the engine has no call graph, leave
`relations`, `neighbors` and `annotate` at their defaults; search and the agents work with what is there.

## 5. Candidates

| Engine | Kind | Notes |
|---|---|---|
| GitNexus, CodeGraphContext, code-graph-rag | code | need Node or an external graph database (Neo4j, Kuzu, Memgraph); wrap their MCP server or CLI in `CodeGraph` |
| Sourcegraph / Zoekt | code (search only) | good lexical search; no relations |
| graphify | code | no vector search; see [18-ENGINE-COMPARISON.md](18-ENGINE-COMPARISON.md) |
| RAGFlow, Haystack, Microsoft GraphRAG | documents | wrap their REST API in `DocGraph`; keep `search` free of chat calls |
| LightRAG with PostgreSQL or Neo4j storage | documents | no new provider: set `LIGHTRAG__LIGHTRAG_GRAPH_STORAGE=Neo4JStorage` (and the other storage variables) with their connection variables through `LIGHTRAG__…` |

## 6. Data when switching
Each provider keeps its own data under `data/`. Switching does not delete the old engine's data, so switching back
works. A new document engine starts empty: upload the files in `data/originals/` again.
