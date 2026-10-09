# ADR-004 - One settings schema, one `.env` file edited by the UI, `repos.json` for repositories

**Status:** accepted · **Requirement:** R4

## Decision
- `brain/settings.py` declares every setting once: key, default, group, help, type, choices and what must restart.
- Values live in **one file**, `.env` (another path with `BRAIN_CONFIG_FILE`). The UI edits that same file in place
  (only the changed lines; comments and order kept; atomic write) and restarts the affected engine.
- Precedence: file, then process environment, then default. The file wins so that a change made in the UI can never
  be silently overridden by an old environment variable.
- Raw engine variables pass through: `LIGHTRAG__NAME` and `CBM__NAME`, so every engine option is reachable,
  including ones AI-BRAIN does not know.
- Repositories and sets are structured data and live in `repos.json` (another path with `BRAIN_REPOS_FILE`), also
  edited in the UI.
- `.env.example` and `docs/03-CONFIGURATION.md` are generated from the schema; a static test fails when they differ.

## Alternatives
YAML or TOML configuration plus `.env` for secrets (two places to look); a settings database (not editable with a
text editor, harder to back up and compare); UI overrides stored separately (file and UI could disagree).

## Consequences
Every timeout, model, git server, webhook and engine value is adjustable from both the UI and the file, and is
documented automatically. Host, port, TLS and data-folder changes need a server restart, which the UI says.
