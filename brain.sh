#!/usr/bin/env sh
# AI-BRAIN launcher: ./brain.sh serve | doctor | sync | search | ask | enhance | drift | connect
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ ! -x "$DIR/.venv/bin/python" ]; then
  echo "Not installed yet. Run: ./setup.sh"; exit 1
fi
exec "$DIR/.venv/bin/python" "$DIR/brain.py" "$@"
