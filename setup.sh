#!/usr/bin/env bash
# AI-BRAIN - one-shot installer for Linux. Fully offline: every package is in wheels/. Requires Python 3.13.
#
#   ./setup.sh                      interactive
#   ./setup.sh --non-interactive    no questions
#   options: --python /usr/bin/python3.13   --autostart (systemd user service)
set -euo pipefail
cd "$(dirname "$0")"
WANT="3.13"; PY=""; NONINT=0; AUTO=0
while [ $# -gt 0 ]; do
  case "$1" in
    --python) PY="$2"; shift 2 ;;
    --non-interactive) NONINT=1; shift ;;
    --autostart) AUTO=1; shift ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
done
step(){ printf '\n== %s\n' "$1"; }
ask(){ if [ "$NONINT" = 1 ]; then echo n; else read -r -p "$1 " a; echo "${a:-n}"; fi; }
secret(){ "$1" -c 'import secrets;print(secrets.token_hex(24))'; }

step "Python $WANT"
for c in "$PY" python3.13 python3 python; do
  [ -n "$c" ] || continue
  if command -v "$c" >/dev/null 2>&1 && [ "$("$c" -c 'import sys;print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" = "$WANT" ]; then PY="$c"; break; fi
  PY=""
done
[ -n "$PY" ] || { echo "Python $WANT not found (install python3.13 and python3.13-venv, or pass --python /path/to/python3.13)"; exit 1; }
echo "using $PY ($("$PY" --version))"
command -v git >/dev/null || echo "WARNING: git not found; repositories cannot be cloned or updated."

step "Virtual environment (.venv)"
if [ -x .venv/bin/python ] && [ "$(.venv/bin/python -c 'import sys;print("%d.%d" % sys.version_info[:2])')" != "$WANT" ]; then
  echo "existing .venv uses another Python: recreating it"; rm -rf .venv
fi
[ -x .venv/bin/python ] || "$PY" -m venv .venv
VPY="$PWD/.venv/bin/python"

step "Python packages (offline, from wheels/)"
"$VPY" -m pip install --no-index --find-links wheels -r requirements.txt || {
  echo "offline package install failed: is the wheels/ folder complete? (see docs/14-OFFLINE-PACKAGING.md)"; exit 1; }

step "Code graph engine (codebase-memory-mcp)"
if [ ! -x bin/linux/codebase-memory-mcp ]; then
  (cd bin && grep linux-amd64-portable SHA256SUMS | sha256sum -c -)
  mkdir -p bin/linux && tar xzf bin/codebase-memory-mcp-linux-amd64-portable.tar.gz -C bin/linux
  chmod +x bin/linux/codebase-memory-mcp
fi
bin/linux/codebase-memory-mcp --version || echo "WARNING: the code engine did not run (see docs/13-OPERATIONS.md)"

step "Configuration (.env, repos.json)"
if [ ! -f .env ]; then
  sed -e "s/^BRAIN_API_TOKEN=$/BRAIN_API_TOKEN=$(secret "$VPY")/" -e "s/^BRAIN_SECRET_KEY=$/BRAIN_SECRET_KEY=$(secret "$VPY")/" .env.example > .env
  chmod 600 .env
  echo "created .env (random BRAIN_API_TOKEN and BRAIN_SECRET_KEY generated)"
  if [ "$NONINT" = 0 ]; then
    echo "Fill in the REQUIRED values (BRAIN_UI_PASSWORD, BRAIN_LLM_BASE_URL, BRAIN_LLM_API_KEY, BRAIN_LLM_MODEL, BRAIN_EMBEDDING_MODEL, BRAIN_EMBEDDING_DIM)."
    "${EDITOR:-vi}" .env
  fi
else
  echo ".env exists: kept"
fi
[ -f repos.json ] || { printf '{\n  "repos": [],\n  "sets": {}\n}\n' > repos.json; echo "created an empty repos.json (add repositories in the UI or see repos.example.json)"; }
chmod 600 repos.json   # holds the webhook secrets and any per-repository tokens

step "Self-check"
"$VPY" brain.py doctor || echo "Some checks failed: fix .env (or the UI Settings page later) and run ./brain.sh doctor"

if [ "$AUTO" = 1 ] || [ "$(ask 'Install a systemd user service "ai-brain" (start at boot)? [y/N]')" = "y" ]; then
  step "Autostart (systemd user service)"
  mkdir -p ~/.config/systemd/user
  cat > ~/.config/systemd/user/ai-brain.service <<EOF
[Unit]
Description=AI-BRAIN (code graph + document graph + agents)
After=network-online.target
[Service]
WorkingDirectory=$PWD
ExecStart=$VPY $PWD/brain.py serve
Restart=on-failure
[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload && systemctl --user enable --now ai-brain
  echo "logs: journalctl --user -u ai-brain -f    (start without login: sudo loginctl enable-linger $USER)"
fi
PORT=$(grep -E '^BRAIN_PORT=' .env | cut -d= -f2); PORT=${PORT:-8765}
printf '\nInstalled.\n  Start:   ./brain.sh serve      then open http://<this-machine>:%s\n  Check:   ./brain.sh doctor\n  Agents:  ./brain.sh connect\n  Firewall (if used): sudo firewall-cmd --add-port=%s/tcp --permanent && sudo firewall-cmd --reload\n' "$PORT" "$PORT"
