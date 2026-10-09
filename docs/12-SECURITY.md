# 12 - Security

## 1. Network

| Direction | What | Notes |
|---|---|---|
| inbound | `BRAIN_PORT` (default 8765): UI, REST, MCP, webhooks | bind address `BRAIN_HOST` (default `0.0.0.0`); open the firewall only to the networks of users, agents and git servers |
| local only | LightRAG on `127.0.0.1:LIGHTRAG_PORT` (default 9631) | never exposed; `NO_PROXY` keeps its traffic away from proxies |
| outbound | `BRAIN_LLM_BASE_URL` (and `BRAIN_EMBEDDING_BASE_URL` if set) | the only AI traffic; TLS verified (`BRAIN_CA_BUNDLE` for an internal CA, `BRAIN_VERIFY_TLS`) |
| outbound | GitLab (`BRAIN_GITLAB_URL`), TFS (`BRAIN_TFS_URL`), other git servers | clone and fetch over HTTPS with a token header, or SSH |
| none | code engine | makes no network calls |

## 2. Authentication and sessions
- **People**: one account, `BRAIN_UI_USER` / `BRAIN_UI_PASSWORD` from the configuration. The server refuses to
  listen on a non-loopback address while the password is empty.
- **Session**: login creates a cookie signed with HMAC-SHA256 (key `BRAIN_SECRET_KEY`, or a random key stored in
  `data/.secret_key`). It expires after `BRAIN_SESSION_HOURS` (default 12). Changing the user name or the key ends
  every session.
- **Agents**: `Authorization: Bearer <BRAIN_API_TOKEN>`; setup generates a random 48-character token. An empty
  token disables bearer access.
- **Scripts**: HTTP basic authentication with the user and password.
- **CSRF**: requests authenticated by the cookie that change something must carry `X-Brain-UI: 1`; browsers cannot
  add that header cross-site without a CORS pre-flight, and the server never sends CORS headers.
- **Brute force**: five failed logins from one address within a minute → HTTP 429 for that minute.
- All secret comparisons are constant-time.

## 3. Webhooks
- Per-repository hooks use the repository's own generated secret (32 hexadecimal characters): GitLab sends it as
  `X-Gitlab-Token`, TFS as the basic-auth password.
- Group-level hooks use `BRAIN_GITLAB_WEBHOOK_SECRET` or `BRAIN_TFS_WEBHOOK_USER` / `BRAIN_TFS_WEBHOOK_PASSWORD`;
  they answer 503 until configured.
- A webhook can only start an update of an already configured repository's tracked branch. It cannot run commands,
  add repositories or change settings.

## 4. HTTPS
Set `BRAIN_TLS_CERT` and `BRAIN_TLS_KEY` (PEM) and restart; cookies are then marked `Secure`. Alternatively terminate
TLS at a reverse proxy (IIS ARR, nginx) and set `BRAIN_HOST=127.0.0.1`.

## 5. Secrets at rest
- `.env` holds the API key, the password, the tokens and the webhook secrets; `repos.json` holds per-repository
  webhook secrets and tokens. On Linux setup gives both mode 600; on Windows keep the folder readable only by the
  service account and administrators.
- The UI and the API never return secret values, only whether they are set. `list_repos` (MCP) leaves out
  webhooks and secrets; `GET /api/repos` leaves out tokens.
- Git tokens are passed to git as an HTTP header for each command; they are never written into clone
  configurations, and error messages mask them.

## 6. Data
Uploaded documents, converted Markdown, indexed code and all indexes stay under `data/` on the server. Content
leaves the server only towards the corporate API: document chunks for extraction and embedding, code symbol texts
for the multilingual code vectors, prompts with retrieved context for the agents. Setting
`BRAIN_CODE_VECTORS=local` keeps all code on the server.

## 7. Hardening checklist
1. A strong `BRAIN_UI_PASSWORD`; rotate `BRAIN_API_TOKEN` when people leave.
2. HTTPS (`BRAIN_TLS_CERT` / `BRAIN_TLS_KEY`) or a TLS reverse proxy.
3. Firewall the port to known networks.
4. Run the server under a dedicated account without administrator rights.
5. Protect and back up `data/`, `.env` and `repos.json`.
6. One shared account means no per-user audit trail; if that is required, put an SSO reverse proxy in front.
