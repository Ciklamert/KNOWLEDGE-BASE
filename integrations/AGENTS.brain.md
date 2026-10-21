<!-- ai-brain:start -->
## AI-BRAIN first (code graph + code vectors + document graph)

This organisation runs AI-BRAIN. It knows every configured repository (code graph: symbols, calls, inheritance,
routes; code vectors: code by meaning, in Turkish or English) and the business documents (rules, specifications,
decisions). Use it instead of grep, glob and reading whole files; it costs fewer tokens.

| Instead of | Use (MCP server `brain`) |
|---|---|
| reading a file to understand a function | `symbol` (source, callers, callees in one answer) |
| reading a whole file | `outline` (declarations with line ranges), then `read` only the lines you need |
| grep / rg | `grep` (`mode=files` to only locate) |
| glob | `files` |
| exploring an unknown repository | `overview` |
| searching by idea, or in Turkish | `search` (`detail=brief` to scan; `scope=docs` for business rules) |
| planning a bug fix, a new feature or any change | `enhance_prompt` |
| what a change breaks, which tests to run | `impact` (files or symbols) |
| an article, section or requirement of a document; a term's definition; who must do what | `doc` (outline, unit, refs, define, obligations) |
| what earlier sessions decided or learned | `recall` at the start; `remember` what the next session needs |

At the start of every task, call `recall` with the task in a few words. When a task is done, call `remember` once
for each thing the next session would otherwise have to rediscover: a `decision` (what was chosen and why), a `rule`
(a business rule found in code or documents), a `gotcha` (a trap and how to avoid it) or a `convention` (how this
codebase does things). Give a short title, the text, the `repo` and the code `paths` it concerns. Do not record what
the code or git history already says.

When the current branch is not a main branch (`main`, or `develop` / `release/...` where the team keeps several):
run `git rev-parse --abbrev-ref HEAD`, `git merge-base HEAD origin/<main you branched from>`,
`git diff --name-only origin/<main>...HEAD` and `git status --porcelain`, call `check_branch` with the results and
follow its recommendations. AI-BRAIN describes the main branches; for files you changed, trust your working copy.

Without MCP (pi, scripts): the same over REST with `Authorization: Bearer $BRAIN_API_TOKEN`:
```bash
H="Authorization: Bearer $BRAIN_API_TOKEN"
curl -s -H "$H" -H "Content-Type: application/json" -d '{"query":"<what you look for>","detail":"brief"}' "$BRAIN_URL/api/search" | jq -r .markdown
curl -s -H "$H" "$BRAIN_URL/api/code/symbol?name=<SymbolName>" | jq -r .text
curl -s -H "$H" "$BRAIN_URL/api/code/outline?path=<path>" | jq -r .text
curl -s -H "$H" "$BRAIN_URL/api/code/read?path=<path>&start=1&end=120" | jq -r .text
curl -s -H "$H" -H "Content-Type: application/json" -d '{"pattern":"<text>","mode":"files"}' "$BRAIN_URL/api/code/grep" | jq -r .text
curl -s -H "$H" "$BRAIN_URL/api/code/files?pattern=**/*.sql" | jq -r '.files[]'
curl -s -H "$H" -H "Content-Type: application/json" -d '{"prompt":"<the user request>"}' "$BRAIN_URL/api/enhance" | jq -r .enhanced
curl -s -H "$H" "$BRAIN_URL/api/memory?q=<the task in a few words>" | jq -r '.memories[] | "[\(.type)] \(.title): \(.text)"'
curl -s -H "$H" -H "Content-Type: application/json" -d '{"type":"gotcha","title":"<short title>","text":"<what and why>","repo":"<repo>","paths":["<path>"]}' "$BRAIN_URL/api/memory"
```
Open files locally only to edit them, and check AI-BRAIN's locations in your working copy before editing.
<!-- ai-brain:end -->
