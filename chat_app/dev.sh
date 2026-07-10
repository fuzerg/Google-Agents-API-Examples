#!/usr/bin/env bash
# Development launcher: runs the FastAPI backend (:8000) and the Vite dev
# server (:5173) with hot reload. The Vite dev server proxies /api to :8000.
#
# Open http://localhost:5173 in your browser.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$REPO_ROOT/chat_app"
VENV_PY="$REPO_ROOT/venv/bin/python3"

# Official Node.js install (Homebrew's shared-libnode build is unreliable here).
NODE_BIN="$HOME/.local/node/node-v24.18.0-darwin-arm64/bin"
if [ -d "$NODE_BIN" ]; then
  export PATH="$NODE_BIN:$PATH"
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found. Install Node.js or set NODE_BIN in dev.sh." >&2
  exit 1
fi

cleanup() {
  echo "Shutting down…"
  kill 0 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Pre-flight: clear any stale backend from a previous run that may still be
# holding :8000 (uvicorn --reload can leave a lingering worker). This does not
# touch the SQLite DB, so conversation history is preserved.
pkill -f "uvicorn main:app" 2>/dev/null || true
sleep 1

echo "Starting backend on http://127.0.0.1:8000 …"
(cd "$APP_DIR/backend" && "$VENV_PY" -m uvicorn main:app --reload --host 127.0.0.1 --port 8000) &

echo "Starting frontend on http://localhost:5173 …"
(cd "$APP_DIR/frontend" && npm run dev) &

wait
