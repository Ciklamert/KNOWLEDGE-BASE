# ADR-008 - Authentication: one user from configuration, signed cookie, bearer token for agents

**Status:** accepted · **Requirement:** R24

## Decision
- People: `BRAIN_UI_USER` / `BRAIN_UI_PASSWORD` from the configuration. Login issues an HMAC-SHA256-signed, HttpOnly,
  SameSite=Strict cookie valid for `BRAIN_SESSION_HOURS`.
- Agents: `Authorization: Bearer <BRAIN_API_TOKEN>`. Scripts: HTTP basic authentication with the user and password.
- CSRF: cookie-authenticated changes must send `X-Brain-UI: 1`; CORS is never granted.
- Five failed logins from one address within a minute → HTTP 429. Constant-time comparisons everywhere.
- The server refuses to listen on a non-loopback address without a password. HTTPS is optional
  (`BRAIN_TLS_CERT` / `BRAIN_TLS_KEY`).
- Webhooks use their own secrets (ADR-018), never the user password.

## Alternatives
LDAP / Active Directory or OIDC: the requirement asks for a user name and password from the configuration, and an
air-gapped network may not expose an identity provider; an SSO reverse proxy can be added in front without code
changes. JWT: no benefit over a signed cookie for one server.

## Consequences
Simple to run, no user database. One shared account means no per-user audit trail; an SSO reverse proxy provides one
when required.
