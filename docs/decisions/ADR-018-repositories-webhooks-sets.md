# ADR-018 - One webhook per repository; sets as repository groups; one scope combobox

**Status:** accepted · **Requirements:** R21, R19

## Decision
- **Every repository has its own webhook**: `POST /webhooks/repo/<name>` with its own secret, generated when the
  repository is saved (or at server start for repositories added by hand) and stored in `repos.json`. GitLab or TFS is
  recognised from the request: GitLab sends the secret as `X-Gitlab-Token`, TFS as the basic-auth password. The
  repository's **provider** (gitlab, tfs, git, local; detected when empty) decides which setup steps the UI shows.
  Group-level hooks (`/webhooks/gitlab`, `/webhooks/tfs`) remain for one hook covering many repositories.
- A repository may have its **own token** (for example a GitLab project access token); otherwise its server's token is
  used.
- **Sets** are stored as `"sets": {"payments": ["billing", "web"]}` in `repos.json` and edited with checkboxes. The
  implicit set `all` holds every repository.
- **One scope combobox** on Search, Ask, Enhance and Requirements: one repository or a set. For a set, the search keeps
  every repository with relevant code in the result (repository balance), the agents are told the request covers all
  of its repositories, and they can query each one with `repo=<name>` and the `overview` tool.
- The **Repositories page** holds everything about repositories: the list with each webhook (URL, secret, steps), the
  editor, the sets, the git-server and webhook settings, the branch-drift check and the delivery history. The Settings
  page shows the rest.

## Alternatives
One secret per git server for all repositories (a leaked secret affects all of them, and webhooks must be matched by
URL); sets as a list on each repository (harder to see and edit a set as a whole).

## Consequences
Adding a repository gives it a ready-to-paste webhook. Per-repository hooks need no URL matching, so other host names,
mirrors or renamed projects cannot break them. `repos.json` holds secrets and must be protected like `.env` (setup
does so on Linux).
