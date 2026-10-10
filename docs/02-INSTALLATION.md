# 02 - Installation, step by step

The same guide as a web page with Windows and Linux tabs: [INSTALL.html](../INSTALL.html).

## 1. What you need

| Item | Windows | Linux |
|---|---|---|
| Operating system | Windows 10/11 or Windows Server 2019+, 64-bit | x86-64 with glibc 2.17+ (RHEL/Rocky 8+, Ubuntu 20.04+, Debian 11+) |
| Python | **3.13** from python.org, with *Add python.exe to PATH* ticked | `python3.13` and `python3.13-venv` |
| git | Git for Windows | the `git` package |
| Hardware | 4 CPU cores, 8 GB RAM (16 GB for large monorepos), 10 GB disk plus 3× the source code size | same |
| Network in | TCP port 8765 (configurable) from users, agents and the git servers | same |
| Network out | the corporate API and the git servers only | same |
| Corporate API | base URL ending in `/v1`, an API key, a chat model, an embedding model and its vector size (bge-m3: 1024); optionally a vision model | same |

## 2. Nothing to download
The folder contains every Python package for Python 3.13 on Windows and Linux (`wheels/`), the code engine for
both systems (`bin/`) and the tokenizer files LightRAG needs (`vendor/`). Setup installs with
`pip --no-index`, so no internet access is needed at any step. Details: [14-OFFLINE-PACKAGING.md](14-OFFLINE-PACKAGING.md).

## 3. Copy the folder
- Windows: for example to `D:\AI-BRAIN`. Do not use a folder that OneDrive or another sync tool manages.
- Linux: for example to `/opt/ai-brain`, owned by the account that will run the server.

## 4. Run setup

### Windows
1. Open PowerShell in the folder (File Explorer → Shift + right-click → *Open PowerShell window here*).
2. Run `powershell -ExecutionPolicy Bypass -File .\setup.ps1`.
3. Setup does, in this order:
   1. finds Python 3.13 (`-Python <path>`, then `py -3.13`, `python3.13`, `python`, `python3`) and warns if git is missing;
   2. creates `.venv` (and recreates it if it was built with another Python version);
   3. installs every package from `wheels\` with `pip --no-index`;
   4. checks the SHA-256 of the code engine archive against `bin\SHA256SUMS`, unpacks it to `bin\windows\` and runs
      it once;
   5. creates `.env` from `.env.example` with a random `BRAIN_API_TOKEN` and `BRAIN_SECRET_KEY`, and opens it in
      Notepad for the required values (section 5); an existing `.env` is kept;
   6. creates an empty `repos.json` if there is none;
   7. runs `brain doctor`;
   8. offers a Windows Firewall rule for the port and a scheduled task `AI-BRAIN` that starts the server at logon.
4. Options: `-NonInteractive` (no questions), `-Python C:\Python313\python.exe`, `-Firewall`, `-Autostart`.

### Linux
1. `cd /opt/ai-brain && chmod +x setup.sh brain.sh && ./setup.sh`
2. The same steps; `.env` and `repos.json` get mode 600, `.env` opens in `$EDITOR` (default `vi`), and instead of a
   scheduled task setup offers a systemd user service `ai-brain`.
3. Options: `--non-interactive`, `--python /usr/bin/python3.13`, `--autostart`.

Setup can be run again at any time: it keeps `.env`, `repos.json` and `data/`.

## 5. Fill in `.env`

Required:

| Key | Example | Meaning |
|---|---|---|
| `BRAIN_UI_PASSWORD` | a strong password | login for the UI and for basic auth (user `BRAIN_UI_USER`, default `admin`) |
| `BRAIN_LLM_BASE_URL` | `https://llm-gateway.corp.local/v1` | the corporate OpenAI-compatible API; must end in `/v1` |
| `BRAIN_LLM_API_KEY` | `sk-…` | its key |
| `BRAIN_LLM_MODEL` | `qwen3-32b` | default chat model for ask, enhance, the requirements writer and LightRAG |
| `BRAIN_EMBEDDING_MODEL` | `bge-m3` | multilingual embedding model (documents, code vectors, re-ranking) |
| `BRAIN_EMBEDDING_DIM` | `1024` | its vector size; `brain doctor` prints the real size |

Often useful:

| Key | Example | Meaning |
|---|---|---|
| `BRAIN_PUBLIC_URL` | `http://10.0.0.10:8765` | the address shown to users, agents and in webhook URLs |
| `BRAIN_VLM_MODEL` | `qwen2.5-vl-32b` | vision model for pictures and scanned pages in documents |
| `BRAIN_CA_BUNDLE` | `C:\certs\corp-ca.pem` | internal CA certificate of the corporate API |
| `BRAIN_GITLAB_URL`, `BRAIN_GITLAB_TOKEN` | `https://gitlab.corp.local` | corporate GitLab and a read token; repositories can be written as `gitlab:group/project` |
| `BRAIN_TFS_URL`, `BRAIN_TFS_TOKEN` | `https://tfs.corp.local/tfs/DefaultCollection` | corporate TFS collection and a read token; repositories can be written as `tfs:Project/repo` |
| `BRAIN_GIT_CA_BUNDLE` | `C:\certs\corp-ca.pem` | internal CA certificate of the git servers |
| `LIGHTRAG_SUMMARY_LANGUAGE` | `Turkish` | language of the entity descriptions LightRAG writes |

Every other value has a default; all of them are listed in [03-CONFIGURATION.md](03-CONFIGURATION.md) and can be
changed later in the UI (**Settings**, and **Repositories** for git servers and webhooks).

## 6. Check
Run `.\brain.cmd doctor` (Windows) or `./brain.sh doctor` (Linux). Every line must say PASS; WARN lines are hints.

| Message | Fix |
|---|---|
| `corporate chat endpoint` / `corporate embedding endpoint` FAIL | URL (ends in `/v1`), key, model names, proxy, `BRAIN_CA_BUNDLE` |
| `dim=768 (BRAIN_EMBEDDING_DIM=1024)` | set `BRAIN_EMBEDDING_DIM` to the printed number |
| `code engine runs` FAIL | antivirus quarantine (a known false positive): allow-list `bin\windows\codebase-memory-mcp.exe` by the SHA-256 in `bin\SHA256SUMS` |
| `python package …` FAIL | run setup again |
| `BRAIN_UI_PASSWORD` FAIL | set a password (required unless `BRAIN_HOST=127.0.0.1`) |

## 7. Start
Run `.\brain.cmd serve` or `./brain.sh serve`. The console prints `READY: code graph, document graph and the
agents (ask, enhance, guide, requirements) are up` when everything is ready; the first index of large repositories
continues in the background. Open `http://<server>:8765` from any machine and log in. The **Overview** page shows
every component, every job with its progress, and any error with its log.

## 8. Add repositories
1. UI → **Repositories** → *Add or edit repositories*: per repository a **name**, a **provider** (empty =
   detected), either a git **URL** (`gitlab:group/project`, `tfs:Project/repo` or a full URL; the server clones it)
   or a local **path** on the server, the **branch** to follow (default `main`) and, only if needed, an own token.
2. *Repository sets*: tick the repositories of each set (for example `payments`).
3. **Save repositories and sets**, then **Update all now**. Progress appears on Overview and Repositories; the
   first index of 10,000 files takes a few minutes, later updates take seconds.

Or edit `repos.json` directly (format: `repos.example.json`, details: [04-REPOSITORIES-AND-SETS.md](04-REPOSITORIES-AND-SETS.md)).

## 9. Add documents
UI → **Documents** → drop files or add a note. Status moves from *pending* to *processing* to *processed*;
failures show their reason.

## 10. Connect the webhooks
Each repository on the **Repositories** page shows its own webhook URL, secret and setup steps. Enter them in
GitLab or TFS: [09-WEBHOOKS.md](09-WEBHOOKS.md).

## 11. Connect AI agents
`brain connect` prints ready-to-paste configuration for Claude Code, opencode and pi with your URL and token.
Details: [07-MCP-AND-AGENTS.md](07-MCP-AND-AGENTS.md).

## 12. Run permanently
- Windows: setup's *Autostart* (scheduled task at logon), or a service wrapper such as NSSM running
  `.venv\Scripts\python.exe brain.py serve` in the folder (example in [13-OPERATIONS.md](13-OPERATIONS.md)).
- Linux: setup's systemd user service, plus `sudo loginctl enable-linger <user>` so it starts at boot.

## 13. HTTPS (optional)
Set `BRAIN_TLS_CERT` and `BRAIN_TLS_KEY` (PEM files) and restart, then use `https://` in webhooks and agent
configuration; or put a TLS reverse proxy in front and set `BRAIN_HOST=127.0.0.1`. See [12-SECURITY.md](12-SECURITY.md).
