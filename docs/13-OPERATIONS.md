# 13 - Operations: run, monitor, back up, upgrade, troubleshoot

## 1. Start and stop

| | Windows | Linux |
|---|---|---|
| foreground | `brain.cmd serve` (Ctrl+C stops the server and both engines) | `./brain.sh serve` |
| at logon | setup `-Autostart` → scheduled task `AI-BRAIN` | (use the service below) |
| as a service | NSSM, see below | setup `--autostart` → systemd user service: `systemctl --user {start,stop,status} ai-brain`, logs `journalctl --user -u ai-brain -f`; `sudo loginctl enable-linger <user>` to start at boot |
| ready? | the console prints `READY …`; `GET /api/status` → `"ready": true` | same |

Windows service with NSSM (from the internal software repository):
```
nssm install AI-BRAIN "D:\AI-BRAIN\.venv\Scripts\python.exe" "D:\AI-BRAIN\brain.py" serve
nssm set AI-BRAIN AppDirectory D:\AI-BRAIN
nssm start AI-BRAIN
```

Start-up timings: code engine 5-30 s (it loads its embedding model), LightRAG 10-40 s, corporate API probe up to
60 s, then the first sync: about 1-3 minutes per 10,000 files for the code graph, plus one embedding pass over all
symbols for the multilingual code vectors; later syncs touch only changed files and symbols. If the system is not
ready after 15 minutes the log says so and the Overview page shows why.

## 2. Monitoring
- `GET /healthz` (no authentication) for liveness; `GET /api/status` (authenticated) for readiness with details per
  engine, the corporate API probe and running jobs.
- UI **Overview** (engines, corporate API, agents, jobs) and **Logs**.
- Log files: `data/logs/server.log`, `data/logs/lightrag.log`, `data/logs/codebase-memory.log`.
- LightRAG is supervised: if it exits it is restarted, up to 5 times; after that the error and log tail stay on the
  Overview card until *Restart engine* is pressed. The code engine's query process restarts by itself on the next
  query.

## 3. Command line from other machines
`brain.py` also runs on a developer machine that has this folder and Python 3.13: set `BRAIN_URL=http://brain:8765`
and `BRAIN_API_TOKEN=…`, then `brain search …`, `brain ask …`, `brain drift` and `brain enhance … --path .` talk to
the server.

## 4. Backup and restore
Stop the server (or accept a crash-consistent copy) and copy `data/`, `.env` and `repos.json`. To restore, copy
them back and start. Code graphs and code vectors can always be rebuilt from git; the document graph can only be
rebuilt by uploading the documents again, which is why `data/originals/` keeps every uploaded file.

## 5. Upgrade
1. Back up.
2. Replace the program files; keep `.env`, `repos.json`, `data/` and `.venv/`.
3. Run setup again: it keeps `.env` and `repos.json` and installs new package versions from `wheels/`.
4. Start the server.
5. If the new version changes the embedding model or `BRAIN_EMBEDDING_DIM`, see section 6.

## 6. Changing models

| Change | Effect |
|---|---|
| `BRAIN_LLM_MODEL`, `BRAIN_ASK_MODEL`, `BRAIN_ENHANCE_MODEL`, `BRAIN_SRS_MODEL` | live, for the next request; the UI comboboxes choose per request; a change of `BRAIN_LLM_MODEL` also restarts LightRAG, which uses it when `LIGHTRAG_LLM_MODEL` is empty |
| `LIGHTRAG_LLM_MODEL` | LightRAG restarts by itself; affects documents ingested afterwards |
| `BRAIN_VLM_MODEL` | LightRAG restarts; affects documents ingested afterwards |
| `BRAIN_EMBEDDING_MODEL` or `BRAIN_EMBEDDING_DIM` | the multilingual code vectors are rebuilt automatically at the next sync; the document graph must be rebuilt: stop the server, delete `data/lightrag/` and `data/documents/`, start, and upload the files from `data/originals/` again |

## 7. Troubleshooting

| Symptom | Where to look | Fix |
|---|---|---|
| Login says wrong password | `.env` `BRAIN_UI_USER`, `BRAIN_UI_PASSWORD` | both are case-sensitive; after 5 failures wait 60 s |
| Server exits: "BRAIN_UI_PASSWORD is empty" | `.env` | set a password, or bind to `127.0.0.1` |
| Document graph card shows *error* | the card's log tail; `data/logs/lightrag.log` | wrong URL, key or model; wrong embedding size; port `LIGHTRAG_PORT` in use (change it) |
| Documents end as *failed* | the error column on the Documents page | "VLM … not available": `BRAIN_VLM_MODEL` is wrong or not a vision model (fix or clear it); timeouts: raise `LIGHTRAG_LLM_TIMEOUT` or `LIGHTRAG_EMBEDDING_TIMEOUT`, lower `LIGHTRAG_MAX_ASYNC` |
| An upload is rejected as unsupported | the job result | convert the file to a supported format (the message lists them) |
| `brain doctor`: embedding dimension differs | doctor output | set `BRAIN_EMBEDDING_DIM` to the printed value; if documents were already ingested, rebuild the document graph (section 6) |
| Code graph card: binary not found or does not run | Overview card | run setup again; an antivirus false positive: allow-list `bin\windows\codebase-memory-mcp.exe` by the SHA-256 in `bin/SHA256SUMS` |
| Repository sync fails | the job error on Overview; Repositories | server address (`BRAIN_GITLAB_URL`, `BRAIN_TFS_URL`), credentials (`BRAIN_GITLAB_TOKEN`, `BRAIN_TFS_TOKEN`, `BRAIN_GIT_TOKEN`, the repository's own token), proxy, TLS (`BRAIN_GIT_CA_BUNDLE`, `BRAIN_GIT_SSL_VERIFY`), local path exists |
| Code vectors show an error on Repositories | the sync job log | the embedding endpoint failed; the code graph is still updated; fix the API and press *Update*, or set `BRAIN_CODE_VECTORS=local` |
| Ask or enhance notes "tool calling not supported" | the answer's notes | the gateway has no tool calling: the automatic fallback is fine, or set `BRAIN_AGENT_TOOL_CALLING=off` |
| Ask or enhance runs out of time | the answer's notes | raise `BRAIN_ASK_TIMEOUT` / `BRAIN_ENHANCE_TIMEOUT` or `BRAIN_LLM_TIMEOUT`; lower the `*_MAX_STEPS` values |
| The model combobox lists only the configured models | `GET /api/models` → `error` | the gateway does not offer `GET /models`; type the model name in Settings |
| Colleagues cannot open the UI | firewall | open `BRAIN_PORT` (setup offers it on Windows); `BRAIN_HOST=0.0.0.0` |
| Webhook problems | Repositories → Webhook deliveries | [09-WEBHOOKS.md](09-WEBHOOKS.md) §7 |
| Turkish characters look wrong in a Windows console | the console code page | display only, the data is UTF-8; use `chcp 65001` or the UI |
