#!/usr/bin/env bash
# run.sh — launch the Python tutor backend, which also serves the frontend.
#
# Reads:
#   TUTOR_HOST              default 127.0.0.1
#   TUTOR_PORT              default 8001
#   TUTOR_MODEL             default gemma3:4b (forwarded to backend)
#   TUTOR_SKIP_OLLAMA=1     skip the Ollama probe (still launches the server)
#
# If Ollama is unreachable we WARN but still start the server, so the user
# can browse lessons and exercises. Chat replies will fail with a clear
# 503 from the backend until Ollama is up.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")" && pwd)"
cd "$repo_root"

if [ -t 1 ]; then
  c_red='\033[31m'; c_grn='\033[32m'; c_yel='\033[33m'; c_blu='\033[34m'; c_off='\033[0m'
else
  c_red=''; c_grn=''; c_yel=''; c_blu=''; c_off=''
fi
say()  { printf "%b%s%b\n" "$c_blu" "[run] $*" "$c_off"; }
ok()   { printf "%b%s%b\n" "$c_grn" "[run] $*" "$c_off"; }
warn() { printf "%b%s%b\n" "$c_yel" "[run] $*" "$c_off"; }
err()  { printf "%b%s%b\n" "$c_red" "[run] $*" "$c_off" >&2; }

TUTOR_HOST="${TUTOR_HOST:-127.0.0.1}"
TUTOR_PORT="${TUTOR_PORT:-8001}"
TUTOR_MODEL="${TUTOR_MODEL:-gemma3:4b}"
TUTOR_SKIP_OLLAMA="${TUTOR_SKIP_OLLAMA:-0}"

venv_dir="backend/.venv"
if [ ! -x "$venv_dir/bin/uvicorn" ]; then
  warn "venv not found or uvicorn missing — running ./install.sh first"
  ./install.sh
fi

if [ "$TUTOR_SKIP_OLLAMA" = "1" ]; then
  warn "TUTOR_SKIP_OLLAMA=1 — skipping Ollama reachability check"
elif ! command -v ollama >/dev/null 2>&1; then
  warn "ollama is not installed; chat replies will fail (UI still works)."
  warn "  macOS:  brew install ollama && ollama serve &"
  warn "  Linux:  curl -fsSL https://ollama.com/install.sh | sh && ollama serve &"
elif ! curl -fsS --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
  warn "ollama is installed but the daemon is not reachable on :11434."
  warn "Start it in another terminal:  ollama serve"
  warn "Chat replies will return 503 until Ollama is up."
else
  ok "ollama daemon reachable on :11434"
fi

# Forward the chosen model + frontend-serving flag to the backend.
export TUTOR_MODEL
export TUTOR_SERVE_FRONTEND=1

# Friendly banner before we hand off to uvicorn.
echo
ok "starting backend on http://${TUTOR_HOST}:${TUTOR_PORT}/"
ok "open that URL in your browser. Press Ctrl-C to stop."
echo

cd backend
exec ./.venv/bin/uvicorn app.main:app \
  --host "$TUTOR_HOST" \
  --port "$TUTOR_PORT"
