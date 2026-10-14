# 10 - Working on a branch while the code graph follows `main`

## 1. The problem
The code graph is updated when something is merged into a repository's tracked branch (`main`). A developer works
on `feature/x`. Two things can then be out of date:
- **`main` moved on.** Other merges landed after the branch was cut. The branch is *behind*; merging it later may
  conflict, and AI-BRAIN already shows code the developer does not have yet.
- **The branch differs from `main`.** For every file the developer changed, AI-BRAIN shows `main`'s version (old
  signatures, missing new functions).

## 2. What AI-BRAIN does

### 2.1 It detects the drift and recommends what to do
`brain/drift.py` compares the branch with the indexed `main`, without any model call, and returns facts and an
ordered list of concrete recommendations. It is available as MCP `check_branch`, `POST /api/drift`,
`brain drift` and on the Repositories page (*Is my branch behind the knowledge base?*).

| Situation | Recommendation (`action`) |
|---|---|
| AI-BRAIN itself indexed an older commit than `origin/main` | `sync_brain`: update now (`POST /api/repos/<name>/sync`, the Update button or MCP `sync_repo`); if it repeats, check the webhook |
| the branch is behind `main` **and** some files changed on both sides | `rebase_now`: `git fetch origin && git rebase origin/main` (or merge), with the list of conflict-risk files to resolve first |
| the branch is behind `main`, no file changed on both sides | `rebase_safe`: rebasing should be clean |
| the branch contains the latest `main` | reported as a fact: no merge drift |
| the developer changed files | `trust_local_files`: for these files read the working copy; use AI-BRAIN for everything else |
| tests cover the changed files or the code that calls them | `run_tests`: the test files to run before pushing (from `impact`); `tests_to_run` lists the single tests |
| 10 or more changed files on a branch | `index_branch`: build a branch overlay so search and agents see the branch's code |
| an overlay exists but is older than the branch head | `refresh_overlay` |
| no merge-base can be determined | `send_git_facts`: push the branch, or pass `base_commit` and `changed_files` |
| nothing to do | `none` |

AI-BRAIN recommends even where it cannot act itself: rebasing and resolving conflicts stay with the developer.

### 2.2 Branch overlays
`POST /api/repos/<repo>/branches {"branch": "feature/x"}` (UI: *Index a branch…* on the repository's row) fetches
the pushed branch into a git worktree `data/worktrees/<repo>--<branch>` and indexes it as an extra project
`<repo>--<branch>`, with its own code vectors. Every search, ask and enhance request with `branch=feature/x` then
uses the overlay **instead of** `main` for that repository; other repositories in the set still use `main`. Remove
the overlay after merging (✕ on the Repositories page, or `DELETE /api/repos/<repo>/branches/feature/x`).

### 2.3 Enhance includes it
`enhance_prompt` with `repo` and `branch` (plus `base_commit` and `changed_files` when available) runs the check
and puts the findings into **Notes for the agent**, so the coding agent knows which files to read locally and
whether to rebase first.

## 3. How to use it

**Developer, in the checkout** (with `brain.py` from this folder, `BRAIN_URL` and `BRAIN_API_TOKEN` set):
```bash
brain drift                                     # computes merge-base and changed files locally, asks the server
brain enhance "add a discount to invoices" --path .
```
`brain drift` fetches `origin/main` locally, computes the merge-base, the changed files (committed and
uncommitted) and the head commit, guesses the repository from the remote URL (or takes `--repo`) and calls the
server.

**AI agent over MCP:** the `check_branch` tool description tells the agent to run
`git rev-parse --abbrev-ref HEAD`, `git merge-base HEAD origin/main`, `git diff --name-only origin/main...HEAD` and
`git status --porcelain` locally and pass the results. This also works for branches that were never pushed.

**UI:** Repositories → *Is my branch behind the knowledge base?* → repository, branch, and optionally merge-base and
changed files.

## 4. How the numbers are computed
On the server's checkout of the repository:
- `main_head` = `origin/<tracked branch>` after a fetch (if the fetch fails: the indexed commit).
- `base_commit` = the caller's value, or `git merge-base origin/main origin/<branch>` for a pushed branch.
- `behind` = `git rev-list --count <base_commit>..<main_head>`.
- `main_files` = `git diff --name-only <base_commit>..<main_head>`.
- `branch_files` = the caller's `changed_files` ∪ `git diff --name-only <base_commit>..origin/<branch>`.
- `risk_files` = `branch_files` ∩ `main_files`.
- When the caller's `head_commit` differs from `origin/<branch>`, the report says the branch has unpushed or
  unpulled commits.
