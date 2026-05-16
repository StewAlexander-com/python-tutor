#!/usr/bin/env bash
# run.sh — launch the Python tutor backend, which also serves the frontend.
#
# Reads:
#   TUTOR_HOST                       default 127.0.0.1
#   TUTOR_PORT                       default 8001
#   TUTOR_MODEL                      default gemma3:4b (forwarded to backend)
#   TUTOR_SKIP_OLLAMA=1              skip the Ollama probe (still launches the server)
#   TUTOR_NONINTERACTIVE=1           never prompt; auto-answer "no"
#   PYTHON_TUTOR_NONINTERACTIVE=1    alias for TUTOR_NONINTERACTIVE
#   PYTHON_TUTOR_ASSUME_YES=1        auto-answer "yes" to start/pull prompts
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
TUTOR_NONINTERACTIVE="${TUTOR_NONINTERACTIVE:-${PYTHON_TUTOR_NONINTERACTIVE:-0}}"
PYTHON_TUTOR_ASSUME_YES="${PYTHON_TUTOR_ASSUME_YES:-0}"

# ----- prompt helper (mirrors install.sh) -----------------------------------
confirm() {
  local question="$1"
  local default_choice="${2:-default-no}"

  if [ "$PYTHON_TUTOR_ASSUME_YES" = "1" ]; then
    printf "%b%s%b %s [auto-yes]\n" "$c_blu" "[run]" "$c_off" "$question"
    return 0
  fi
  if [ "$TUTOR_NONINTERACTIVE" = "1" ]; then
    printf "%b%s%b %s [auto-no]\n" "$c_blu" "[run]" "$c_off" "$question"
    return 1
  fi
  if [ ! -t 0 ]; then
    printf "%b%s%b %s [no TTY → no]\n" "$c_yel" "[run]" "$c_off" "$question"
    return 1
  fi

  local hint
  if [ "$default_choice" = "default-yes" ]; then hint="[Y/n]"; else hint="[y/N]"; fi
  local reply=""
  printf "%b%s%b %s %s " "$c_blu" "[run]" "$c_off" "$question" "$hint"
  IFS= read -r reply || reply=""
  case "$reply" in
    y|Y|yes|Yes|YES) return 0 ;;
    n|N|no|No|NO)    return 1 ;;
    "")
      if [ "$default_choice" = "default-yes" ]; then return 0; fi
      return 1 ;;
    *) return 1 ;;
  esac
}

ollama_daemon_up() {
  curl -fsS --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1
}

start_ollama_now() {
  say "starting 'ollama serve' in the background"
  # shellcheck disable=SC2069
  nohup ollama serve >/tmp/ollama-serve.log 2>&1 &
  local pid=$!
  local tries
  for tries in $(seq 1 20); do
    if ollama_daemon_up; then
      ok "ollama serve is up (pid $pid; log: /tmp/ollama-serve.log)"
      return 0
    fi
    sleep 0.5
  done
  err "ollama serve did not become reachable on :11434 within 10s."
  return 1
}

venv_dir="backend/.venv"
if [ ! -x "$venv_dir/bin/uvicorn" ]; then
  warn "venv not found or uvicorn missing — running ./install.sh first"
  # Run install in noninteractive mode unless the operator already chose a
  # mode. We must not silently install Ollama from inside run.sh.
  TUTOR_NONINTERACTIVE="${TUTOR_NONINTERACTIVE:-1}" \
  TUTOR_SKIP_OLLAMA=1 \
  PYTHON_TUTOR_AUTOLAUNCH=0 \
  ./install.sh
fi

if [ "$TUTOR_SKIP_OLLAMA" = "1" ]; then
  warn "TUTOR_SKIP_OLLAMA=1 — skipping Ollama reachability check"
elif ! command -v ollama >/dev/null 2>&1; then
  warn "ollama is not installed; chat replies will fail (UI still works)."
  warn "  Run ./install.sh and answer 'y' when asked to install Ollama, or:"
  warn "  macOS:  brew install ollama"
  warn "  Linux:  curl -fsSL https://ollama.com/install.sh | sh"
elif ! ollama_daemon_up; then
  warn "ollama is installed but the daemon is not reachable on :11434."
  if confirm "Start 'ollama serve' in the background now?" default-no; then
    if ! start_ollama_now; then
      warn "Could not auto-start. Chat replies will return 503 until you run 'ollama serve'."
    fi
  else
    warn "Continuing without Ollama. Chat replies will return 503 until you run 'ollama serve'."
  fi
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
