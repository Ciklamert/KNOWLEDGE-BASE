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
| what earlier sessions decided or learned | `recall` at the start; `remember` what the next session needs |

When the current branch is not `main`: run `git rev-parse --abbrev-ref HEAD`, `git merge-base HEAD origin/main`,
`git diff --name-only origin/main...HEAD` and `git status --porcelain`, call `check_branch` with the results and follow
its recommendations. AI-BRAIN describes `main`; for files you changed, trust your working copy.

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
```
Open files locally only to edit them, and check AI-BRAIN's locations in your working copy before editing.
<!-- ai-brain:end -->
