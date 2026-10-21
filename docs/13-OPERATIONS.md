# 13 - Operations: run, monitor, back up, upgrade, troubleshoot

## 1. Start and stop

| | Windows | Linux |
|---|---|---|
| foreground | `brain.cmd serve` (Ctrl+C stops the server and the code engine) | `./brain.sh serve` |
| at logon | setup `-Autostart` → scheduled task `AI-BRAIN` | (use the service below) |
| as a service | NSSM, see below | setup `--autostart` → systemd user service: `systemctl --user {start,stop,status} ai-brain`, logs `journalctl --user -u ai-brain -f`; `sudo loginctl enable-linger <user>` to start at boot |
| ready? | the console prints `READY …`; `GET /api/status` → `"ready": true` | same |

Windows service with NSSM (from the internal software repository):
```
nssm install AI-BRAIN "D:\AI-BRAIN\.venv\Scripts\python.exe" "D:\AI-BRAIN\brain.py" serve
nssm set AI-BRAIN AppDirectory D:\AI-BRAIN
nssm start AI-BRAIN
```

Start-up timings: code engine 5-30 s (it loads its embedding model), document engine under a second, corporate API
probe up to 60 s, then the first sync: about 1-3 minutes per 10,000 files for the code graph, plus one embedding pass over all
symbols for the multilingual code vectors; later syncs touch only changed files and symbols. If the system is not
ready after 15 minutes the log says so and the Overview page shows why.

## 2. Monitoring
- `GET /healthz` (no authentication) for liveness; `GET /api/status` (authenticated) for readiness with details per
  engine, the corporate API probe and running jobs.
- UI **Overview** (engines, corporate API, agents, jobs) and **Logs**.
- Log files: `data/logs/server.log` (also the document engine) and `data/logs/codebase-memory.log`.
- The code engine's query process restarts by itself on the next query; *Restart engine* on the Overview cards
  restarts either engine. The document engine finishes missing vectors and picture descriptions at every start and
  every 10 minutes.
- `brain doctor` reports whether the OCR fallback is installed and how large the vector cache is.

## 3. Command line from other machines
`brain.py` also runs on a developer machine that has this folder and Python 3.13: set `BRAIN_URL=http://brain:8765`
and `BRAIN_API_TOKEN=…`, then `brain search …`, `brain ask …`, `brain drift` and `brain enhance … --path .` talk to
the server.

## 4. Backup and restore
Stop the server (or accept a crash-consistent copy) and copy `data/`, `.env` and `repos.json`. To restore, copy
them back and start. Code graphs and code vectors can always be rebuilt from git; the document graph is rebuilt from `data/originals/`; decision memory (`data/memory/`) exists only in the backup
with *Re-index all*.

## 5. Upgrade
1. Back up.
2. Replace the program files; keep `.env`, `repos.json`, `data/` and `.venv/`.
3. Run setup again: it keeps `.env` and `repos.json` and installs new package versions from `wheels/`.
4. Start the server.
5. If the new version changes the embedding model or `BRAIN_EMBEDDING_DIM`, see section 6.

## 6. Changing models

| Change | Effect |
|---|---|
| `BRAIN_LLM_MODEL`, `BRAIN_ASK_MODEL`, `BRAIN_ENHANCE_MODEL`, `BRAIN_GUIDE_MODEL`, `BRAIN_SRS_MODEL` | live, for the next request; the UI comboboxes choose per request |
| `BRAIN_VLM_MODEL` | live: pictures not described yet, and pictures OCR read meanwhile, are described within 10 minutes; described pictures keep their text, and a picture described once is never sent again (description cache by SHA-1) |
| `BRAIN_EMBEDDING_MODEL` or `BRAIN_EMBEDDING_DIM` | the document engine restarts and embeds every passage again by itself; the multilingual code vectors are rebuilt at the next sync. The vector cache keys vectors by model, so switching back to an earlier model costs no API call |
| `BRAIN_DOC_CHUNK_CHARS` or a new version of the converter | applies to documents indexed afterwards; *Re-index all* on the Documents page applies it to every document |

## 7. Troubleshooting

| Symptom | Where to look | Fix |
|---|---|---|
| Login says wrong password | `.env` `BRAIN_UI_USER`, `BRAIN_UI_PASSWORD` | both are case-sensitive; after 5 failures wait 60 s |
| Server exits: "BRAIN_UI_PASSWORD is empty" | `.env` | set a password, or bind to `127.0.0.1` |
| Document graph card shows *error* | the card's detail; `data/logs/server.log` | the data folder is not writable, or SQLite has no FTS5 (`brain doctor` checks it) |
| Vectors stay below the passage count | Documents page, the activity line | the embedding endpoint failed ("vectors postponed"); fix the API: the next upload or start completes them; keyword and concept search work meanwhile |
| Pictures are not described | Documents page, *Pictures described* | `BRAIN_VLM_MODEL` is empty, wrong or not a vision model ("picture descriptions postponed"), or the hourly budget `BRAIN_VLM_MAX_PER_HOUR` is used up; meanwhile OCR reads their text when installed (`brain doctor`). Fix the model: the next round (every 10 minutes) completes them |
| The vision gateway is slow | the activity line, "timeout after …" | lower `BRAIN_VLM_TIMEOUT` (OCR takes over for that picture) or `BRAIN_VLM_MAX_PER_HOUR` |
| A deleted branch still has an overlay | Repositories, *Branch overlays* | the webhook needs push events on all branches; otherwise the next update of the repository removes it, or ✕ |
| An upload is rejected as unsupported | the job result | convert the file to a supported format (the message lists them) |
| `brain doctor`: embedding dimension differs | doctor output | set `BRAIN_EMBEDDING_DIM` to the printed value; the passages are embedded again by themselves |
| Code graph card: binary not found or does not run | Overview card | run setup again; an antivirus false positive: allow-list `bin\windows\codebase-memory-mcp.exe` by the SHA-256 in `bin/SHA256SUMS` |
| Repository sync fails | the job error on Overview; Repositories | server address (`BRAIN_GITLAB_URL`, `BRAIN_TFS_URL`), credentials (`BRAIN_GITLAB_TOKEN`, `BRAIN_TFS_TOKEN`, `BRAIN_GIT_TOKEN`, the repository's own token), proxy, TLS (`BRAIN_GIT_CA_BUNDLE`, `BRAIN_GIT_SSL_VERIFY`), local path exists |
| Code vectors show an error on Repositories | the sync job log | the embedding endpoint failed; the code graph is still updated; fix the API and press *Update*, or set `BRAIN_CODE_VECTORS=local` |
| Ask or enhance notes "tool calling not supported" | the answer's notes | the gateway has no tool calling: the automatic fallback is fine, or set `BRAIN_AGENT_TOOL_CALLING=off` |
| Ask or enhance runs out of time | the answer's notes | raise `BRAIN_ASK_TIMEOUT` / `BRAIN_ENHANCE_TIMEOUT` or `BRAIN_LLM_TIMEOUT`; lower the `*_MAX_STEPS` values |
| The model combobox lists only the configured models | `GET /api/models` → `error` | the gateway does not offer `GET /models`; type the model name in Settings |
| Colleagues cannot open the UI | firewall | open `BRAIN_PORT` (setup offers it on Windows); `BRAIN_HOST=0.0.0.0` |
| Webhook problems | Repositories → Webhook deliveries | [09-WEBHOOKS.md](09-WEBHOOKS.md) §7 |
| Turkish characters look wrong in a Windows console | the console code page | display only, the data is UTF-8; use `chcp 65001` or the UI |
