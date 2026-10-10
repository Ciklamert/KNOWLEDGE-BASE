# 04 - Repositories and sets

## 1. Where repositories are defined
Repositories and sets live in `repos.json` in the install folder (another file: environment variable
`BRAIN_REPOS_FILE`). The **Repositories** page edits it; it can also be edited by hand. The server reads it on
every request, so changes apply without a restart. Everything about repositories is on that page: the list with
each repository's state and webhook, the editor, the sets, the git-server and webhook settings, the branch-drift
check and the webhook delivery history.

```json
{
  "repos": [
    {"name": "billing",    "provider": "gitlab", "url": "gitlab:payments/billing", "branch": "main", "webhook_secret": "<generated>"},
    {"name": "web-portal", "provider": "tfs",    "url": "tfs:Portal/web-portal",   "branch": "main", "webhook_secret": "<generated>"},
    {"name": "legacy-api", "provider": "git",    "url": "https://git.other-team.corp.local/legacy/api.git",
     "user": "svc-brain", "token": "<own token>", "webhook_secret": "<generated>"},
    {"name": "shared-lib", "provider": "local",  "path": "D:/src/shared-lib", "aliases": ["corp/shared-lib"], "webhook_secret": "<generated>"}
  ],
  "sets": {"payments": ["billing", "web-portal", "shared-lib"], "backend": ["billing", "legacy-api", "shared-lib"]}
}
```

### Repository fields

| Field | Required | Meaning |
|---|---|---|
| `name` | yes (taken from the URL or path when missing) | unique id and the code-graph project name; characters other than letters, digits, `_ . -` become `-` |
| `url` | `url` or `path` | git URL, `gitlab:group/project` or `tfs:Project/repo`; the server clones it into `data/repos/<name>` and **owns** that clone |
| `path` | `url` or `path` | an existing checkout on the server; it is never reset, only fast-forwarded when clean and on `branch` |
| `branch` | no (default `BRAIN_DEFAULT_BRANCH` = `main`) | the branch the code graph follows; webhooks for other branches are ignored |
| `provider` | no (detected) | `gitlab`, `tfs`, `git` or `local`; decides which webhook setup steps the UI shows |
| `webhook_secret` | generated | secret of the repository's own webhook `/webhooks/repo/<name>`; generated when the repository is saved, or at server start for repositories added by hand |
| `user`, `token` | no | this repository's own git credentials (for example a GitLab project access token); otherwise the server's |
| `aliases` | no | other names the group-level webhooks may use for this repository (for example `group/project`) |

`"gitlab": "group/project"` or `"tfs": "Project/repo"` may be written instead of `"url"`. A secret or token left
empty in the UI keeps the stored value. `repos.json` contains secrets: protect it like `.env` (setup gives both
mode 600 on Linux).

### Corporate GitLab and TFS servers
The addresses of the git servers are settings, so repositories do not repeat them:

| Setting | Example | Used for |
|---|---|---|
| `BRAIN_GITLAB_URL` | `https://gitlab.corp.local` | `gitlab:group/project` → `https://gitlab.corp.local/group/project.git` |
| `BRAIN_GITLAB_USER`, `BRAIN_GITLAB_TOKEN` | any name, a token with `read_repository` | credentials for every URL on `BRAIN_GITLAB_URL` |
| `BRAIN_TFS_URL` | `https://tfs.corp.local/tfs/DefaultCollection` | `tfs:Project/repo` → `<BRAIN_TFS_URL>/Project/_git/repo` (`tfs:Project/_git/repo` also works) |
| `BRAIN_TFS_USER`, `BRAIN_TFS_TOKEN` | any name, a PAT with *Code (read)* | credentials for every URL on `BRAIN_TFS_URL` |
| `BRAIN_GIT_USER`, `BRAIN_GIT_TOKEN` | | credentials for any other git server |
| `BRAIN_GIT_CA_BUNDLE`, `BRAIN_GIT_SSL_VERIFY` | `C:\certs\corp-ca.pem`, `true` | TLS trust for the git servers |
| `BRAIN_GIT_TIMEOUT` | `900` | seconds for one clone or fetch |

Shorthands are expanded each time they are used: when a server moves, change one setting and every repository
follows. Full URLs work too; their credentials are chosen by comparing the URL with `BRAIN_GITLAB_URL` and
`BRAIN_TFS_URL`.

## 2. Single repository
One entry and no sets. Every request covers it.

## 3. Multiple repositories and sets
- Every repository is its own code-graph project (`data/cbm/<name>.db`) with its own code vectors
  (`data/codevec/<name>.npz`). Repositories are indexed one after another.
- A **set** is a named group of repositories (`"sets"` in `repos.json`, edited with checkboxes). The implicit set
  **`all`** contains every repository. A repository can belong to any number of sets.
- Search, Ask, Enhance and the Requirements writer have a **Scope** combobox: one repository or one set
  (API: `target=repo:<name>` or `target=set:<name>`; also `set` and `repos`).
- For a set, every repository of the set is searched. The result keeps at least one place (two when there is
  room) for every repository that has relevant code, and the agents are told the request concerns all of them
  and can query each one with `repo=<name>`.
- Results always name the repository: `repo/path:line`.
- Use sets for systems: a payments set of backend, portal and shared library answers cross-repository questions
  ("who calls the charge endpoint?") from exactly the code that belongs together.
- Documents are shared by all sets (one document graph). For separate document spaces, run a second instance with
  its own `BRAIN_DATA_DIR` and port.

## 4. Updating

| Trigger | What is updated |
|---|---|
| server start (`BRAIN_SYNC_ON_START=true`) | all repositories |
| the repository's own webhook, or a group-level GitLab/TFS webhook, for the tracked branch | that repository ([09-WEBHOOKS.md](09-WEBHOOKS.md)) |
| *Update* / *Update all now* in the UI, `brain sync [name]`, MCP `sync_repo`, `POST /api/repos/{name}/sync`, `POST /api/repos/sync` | that repository / all |
| a pull (or merge, or commit) of the tracked branch in a **local checkout** | that repository, within `BRAIN_WATCH_LOCAL_SECONDS` (default 30): the server notices that the branch head moved |
| a `git pull` of the tracked branch in **any developer checkout** with the AI-BRAIN git hook (`brain hook`) | that repository, right after the pull |
| `BRAIN_SYNC_INTERVAL_MINUTES` above 0 | all repositories, periodically (when webhooks are not possible) |

An update starts at once and pulls immediately: there is no waiting window. If another request for the same
repository arrives while its update is running (a merge usually fires a merge and a push event, or a developer
pulls again), it is not lost and not run in parallel: the running update runs once more when it finishes, so the
newest commit is always indexed.

One update does:
1. **Server-managed clone**: clone on first use (`--single-branch`, no tags), afterwards `fetch` the tracked
   branch, `checkout -B <branch> origin/<branch>`, `reset --hard origin/<branch>`. **Local checkout**: `pull
   --ff-only` only when it is clean and on the tracked branch; otherwise it is indexed as it is and the job says
   why.
2. Incremental index by the code engine (file content hashes): after a typical merge it takes seconds.
3. Multilingual code vectors for new and changed symbols only.
4. The indexed commit, time, node and edge counts and any error are stored in `data/state.json` and shown on the
   Repositories page.

### Updating on every pull
- **Local-path repositories** need nothing: every `BRAIN_WATCH_LOCAL_SECONDS` the server compares the head of the
  tracked branch with the indexed commit. When someone pulls (or merges, or commits) on that branch, the next check
  starts an update. A checkout that is on another branch is left alone. `0` turns the check off.
- **Any checkout, also on developer machines**: `brain hook [PATH] [--repo NAME]` installs two git hooks,
  `post-merge` (runs after every `git pull`) and `post-rewrite` (after `git pull --rebase`). When the pulled branch
  is the repository's tracked branch, the hook runs `brain sync NAME` in the background, so the server pulls its own
  clone at once. It needs `BRAIN_URL` and `BRAIN_API_TOKEN` in the developer's environment (or this folder's `.env`)
  and never blocks git. `brain hook --remove` removes it; an existing hook that is not AI-BRAIN's is never
  overwritten (the command prints the line to add instead).
- **Server-managed clones** change only when the server pulls: webhooks, the hook above, the buttons, the CLI, MCP
  or the interval.

## 5. Git credentials
- HTTPS with a token: the repository's own `user`/`token`, else the GitLab or TFS credentials when the URL is on
  that server, else `BRAIN_GIT_USER`/`BRAIN_GIT_TOKEN`. The token is passed to git as an HTTP header for each
  command; it is never written to disk or to the clone's configuration, and error messages mask it.
- SSH: use a `git@…` URL and an SSH key of the account that runs the server. Git runs with
  `GIT_TERMINAL_PROMPT=0`, so it can never wait for a password prompt.
- Internal CA: `BRAIN_GIT_CA_BUNDLE=<pem>`; as a last resort `BRAIN_GIT_SSL_VERIFY=false`.

## 6. Removing a repository
Remove it in the editor (✕, then **Save repositories and sets**) or from `repos.json`. It leaves every set, so
searches, agents and webhooks no longer use it. To free disk space, stop the server and delete
`data/cbm/<name>.db`, `data/codevec/<name>.npz` and `data/repos/<name>/`.
