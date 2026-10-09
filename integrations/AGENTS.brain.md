<!-- ai-brain:start -->
## AI-BRAIN first (code graph + code vectors + document graph)

This organisation runs AI-BRAIN. It knows every configured repository (code graph: symbols, calls, inheritance,
routes; code vectors: code by meaning, in Turkish or English) and the business documents (rules, specifications,
decisions).

**Use it instead of grep, glob and reading many files.**

| Instead of | Use (MCP server `brain`) |
|---|---|
| grep / rg | `search` (all sources, ranked; every hit has location, signature, callers, callees and why it matched) or `grep` (exact text or regex) |
| glob | `files` (glob over the indexed files of a repository or a set) |
| reading files to understand code | `snippet` (one symbol), `read` (a line range), `symbol`, `trace` (call chains) |
| guessing business rules | `search` with `scope=docs`, or `ask` (rules, decisions and facts with sources) |
| planning a change | `enhance_prompt` (task, context, impact, plan, acceptance criteria) |

When the current branch is not `main`: run `git rev-parse --abbrev-ref HEAD`, `git merge-base HEAD origin/main`,
`git diff --name-only origin/main...HEAD` and `git status --porcelain`, call `check_branch` with the results and follow
its recommendations. AI-BRAIN describes `main`; for files you changed, trust your working copy.

Without MCP (pi, scripts): the same over REST with `Authorization: Bearer $BRAIN_API_TOKEN`:
```bash
curl -s -H "Authorization: Bearer $BRAIN_API_TOKEN" -H "Content-Type: application/json" \
     -d '{"query":"<what you are looking for>"}' "$BRAIN_URL/api/search" | jq -r .markdown
curl -s -H "Authorization: Bearer $BRAIN_API_TOKEN" "$BRAIN_URL/api/code/files?pattern=**/*.sql&target=set:all" | jq -r '.files[]'
curl -s -H "Authorization: Bearer $BRAIN_API_TOKEN" "$BRAIN_URL/api/code/read?repo=<repo>&path=<path>&start=1&end=120" | jq -r .text
curl -s -H "Authorization: Bearer $BRAIN_API_TOKEN" -H "Content-Type: application/json" \
     -d '{"pattern":"<text or regex>","regex":true,"target":"set:all"}' "$BRAIN_URL/api/code/grep" | jq -r .text
curl -s -H "Authorization: Bearer $BRAIN_API_TOKEN" -H "Content-Type: application/json" \
     -d '{"prompt":"<the user request>"}' "$BRAIN_URL/api/enhance" | jq -r .enhanced
```
Open files locally only to edit them, and check AI-BRAIN's locations in your working copy before editing.
<!-- ai-brain:end -->
