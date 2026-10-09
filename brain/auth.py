"""Authentication for everything except /healthz and the webhooks (which carry their own secrets).

Accepted credentials, checked in this order:
  1. session cookie `brain_session` set by the login page (HMAC-signed, expires after BRAIN_SESSION_HOURS);
  2. `Authorization: Bearer <BRAIN_API_TOKEN>` for AI agents (REST and MCP);
  3. `Authorization: Basic <BRAIN_UI_USER:BRAIN_UI_PASSWORD>` (curl, scripts).
Cookie-authenticated state-changing requests must also carry the header `X-Brain-UI: 1`; browsers cannot add it
cross-site without a CORS pre-flight, which this server never grants, so it blocks CSRF.
Repeated wrong passwords from one address are slowed down (5 failures -> 60 s lock-out).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

from . import settings as cfg

COOKIE = "brain_session"
_fails: dict[str, list[float]] = {}


def _sign(payload: str) -> str:
    return hmac.new(cfg.secret_key(), payload.encode(), hashlib.sha256).hexdigest()


def make_session(user: str) -> str:
    payload = f"{user}|{int(time.time() + cfg.get('BRAIN_SESSION_HOURS') * 3600)}"
    return base64.urlsafe_b64encode(payload.encode()).decode() + "." + _sign(payload)


def read_session(value: str | None) -> str | None:
    if not value or "." not in value:
        return None
    b64, sig = value.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(b64.encode()).decode()
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    user, _, exp = payload.rpartition("|")
    if not exp.isdigit() or int(exp) < time.time() or user != cfg.get("BRAIN_UI_USER"):
        return None   # expired, or the user name was changed since
    return user


def locked(ip: str) -> bool:
    recent = [t for t in _fails.get(ip, []) if time.time() - t < 60]
    _fails[ip] = recent
    return len(recent) >= 5


def check_password(user: str, password: str, ip: str = "?") -> bool:
    want = cfg.get("BRAIN_UI_PASSWORD")
    ok = bool(want) and hmac.compare_digest(user.encode(), cfg.get("BRAIN_UI_USER").encode()) \
        and hmac.compare_digest(password.encode(), want.encode())
    if not ok:
        _fails.setdefault(ip, []).append(time.time())
    return ok


def identify(headers: dict, cookies: dict, ip: str) -> tuple[str | None, str]:
    """Returns (user or None, method) for a request."""
    user = read_session(cookies.get(COOKIE))
    if user:
        return user, "cookie"
    auth = headers.get("authorization", "")
    token = cfg.get("BRAIN_API_TOKEN")
    if auth.lower().startswith("bearer ") and token and hmac.compare_digest(auth[7:].strip(), token):
        return "agent", "token"
    if auth.lower().startswith("basic ") and not locked(ip):
        try:
            u, _, p = base64.b64decode(auth[6:]).decode("utf-8").partition(":")
        except ValueError:
            return None, ""
        if check_password(u, p, ip):
            return u, "basic"
    return None, ""
