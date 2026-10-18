#!/usr/bin/env bash
# Start Pulse Decision OS: API (:8000) + Next.js UI (:3000)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

pick_python() {
  local candidates=(
    "${PULSE_PYTHON:-}"
    "$ROOT/.venv/bin/python"
    "$ROOT/venv/bin/python"
    "/Applications/Xcode.app/Contents/Developer/usr/bin/python3"
    "python3"
  )
  local py
  for py in "${candidates[@]}"; do
    [[ -z "$py" ]] && continue
    if command -v "$py" >/dev/null 2>&1 || [[ -x "$py" ]]; then
      if "$py" -c "import fastapi, uvicorn, sqlalchemy" >/dev/null 2>&1; then
        echo "$py"
        return 0
      fi
    fi
  done
  return 1
}

if ! PYTHON="$(pick_python)"; then
  echo "error: no Python with fastapi/uvicorn/sqlalchemy found." >&2
  echo "  Create a venv, install requirements.txt, or set PULSE_PYTHON=/path/to/python" >&2
  exit 1
fi

if [[ ! -d "$ROOT/apps/web/node_modules" ]]; then
  echo "Installing web deps…"
  (cd "$ROOT/apps/web" && npm install)
fi

API_PID=""
WEB_PID=""

cleanup() {
  echo ""
  echo "Stopping…"
  [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "$WEB_PID" ]] && kill "$WEB_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "API  → http://127.0.0.1:8000  ($PYTHON)"
echo "UI   → http://127.0.0.1:3000"
echo ""

"$PYTHON" -m uvicorn backend.api.server:app --reload --host 127.0.0.1 --port 8000 &
API_PID=$!

(cd "$ROOT/apps/web" && npm run dev -- --hostname 127.0.0.1 --port 3000) &
WEB_PID=$!

echo "Open http://127.0.0.1:3000/analyse  (Ctrl+C to stop both)"
wait
