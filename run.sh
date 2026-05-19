#!/usr/bin/env bash
# run.sh -- launch the Python tutor backend, which also serves the frontend.
#
# Run `./run.sh --help` for the full option list.
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

usage() {
  cat <<'EOF'
Usage: ./run.sh [options]

Starts the FastAPI backend, which also serves the static PWA frontend
on the same port. Prints the URL and, if requested, opens it in your
default browser.

Options:
  -h, --help              Show this help and exit.
      --host ADDR         Bind address (default 127.0.0.1).
                          Equivalent to TUTOR_HOST=ADDR.
      --port N            TCP port (default 8001).
                          Equivalent to TUTOR_PORT=N.
      --model TAG         Use Ollama model TAG (default gemma3:4b).
                          Equivalent to TUTOR_MODEL=TAG.
      --open-browser      After the server reports healthy, open the URL
                          in the default browser (`open` on macOS,
                          `xdg-open` on Linux). Silent on other OSes.
      --no-launch         Run all preflight checks (venv, Ollama probe,
                          port-in-use) and exit 0 without starting the
                          server. Useful for CI dry-runs.
      --skip-ollama       Skip the Ollama reachability check. Equivalent
                          to TUTOR_SKIP_OLLAMA=1.
  -y, --yes               Auto-answer "yes" to start-Ollama prompt.
                          Equivalent to PYTHON_TUTOR_ASSUME_YES=1.
  -n, --noninteractive    Never prompt. Equivalent to
                          TUTOR_NONINTERACTIVE=1.

Environment variables (all still honored):
  TUTOR_HOST                       default 127.0.0.1
  TUTOR_PORT                       default 8001
  TUTOR_MODEL                      default gemma3:4b
  TUTOR_SKIP_OLLAMA=1              skip Ollama probe
  TUTOR_NONINTERACTIVE=1           never prompt; auto-answer "no"
  PYTHON_TUTOR_NONINTERACTIVE=1    alias for TUTOR_NONINTERACTIVE
  PYTHON_TUTOR_ASSUME_YES=1        auto-answer "yes"

Exit codes:
  0  server started (or --no-launch dry-run succeeded)
  3  invalid CLI arguments
  4  port already in use (use --port to choose another)
EOF
}

TUTOR_HOST="${TUTOR_HOST:-127.0.0.1}"
TUTOR_PORT="${TUTOR_PORT:-8001}"
TUTOR_MODEL="${TUTOR_MODEL:-gemma3:4b}"
TUTOR_SKIP_OLLAMA="${TUTOR_SKIP_OLLAMA:-0}"
TUTOR_NONINTERACTIVE="${TUTOR_NONINTERACTIVE:-${PYTHON_TUTOR_NONINTERACTIVE:-0}}"
PYTHON_TUTOR_ASSUME_YES="${PYTHON_TUTOR_ASSUME_YES:-0}"
OPEN_BROWSER=0
NO_LAUNCH=0

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --host)
      if [ $# -lt 2 ]; then err "--host needs an argument"; exit 3; fi
      TUTOR_HOST="$2"; shift 2 ;;
    --host=*) TUTOR_HOST="${1#--host=}"; shift ;;
    --port)
      if [ $# -lt 2 ]; then err "--port needs an argument"; exit 3; fi
      TUTOR_PORT="$2"; shift 2 ;;
    --port=*) TUTOR_PORT="${1#--port=}"; shift ;;
    --model)
      if [ $# -lt 2 ]; then err "--model needs an argument"; exit 3; fi
      TUTOR_MODEL="$2"; shift 2 ;;
    --model=*) TUTOR_MODEL="${1#--model=}"; shift ;;
    --open-browser) OPEN_BROWSER=1; shift ;;
    --no-launch) NO_LAUNCH=1; shift ;;
    --skip-ollama) TUTOR_SKIP_OLLAMA=1; shift ;;
    -y|--yes) PYTHON_TUTOR_ASSUME_YES=1; shift ;;
    -n|--noninteractive) TUTOR_NONINTERACTIVE=1; shift ;;
    --) shift; break ;;
    *) err "unknown option: $1 (try --help)"; exit 3 ;;
  esac
done

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
  for _ in $(seq 1 20); do
    if ollama_daemon_up; then
      ok "ollama serve is up (pid $pid; log: /tmp/ollama-serve.log)"
      return 0
    fi
    sleep 0.5
  done
  err "ollama serve did not become reachable on :11434 within 10s."
  return 1
}

# Port-in-use detection. Returns 0 if a listener is already bound.
# Uses /dev/tcp (bash builtin) so we don't depend on lsof / ss / netstat.
port_in_use() {
  local host="$1" port="$2"
  # Probe both 127.0.0.1 and the user-specified host. If the user picks
  # 0.0.0.0 we still want to detect a local listener on 127.0.0.1.
  (exec 3<>"/dev/tcp/127.0.0.1/$port") >/dev/null 2>&1 && { exec 3<&- 3>&-; return 0; }
  if [ "$host" != "127.0.0.1" ] && [ "$host" != "0.0.0.0" ] && [ "$host" != "localhost" ]; then
    (exec 3<>"/dev/tcp/$host/$port") >/dev/null 2>&1 && { exec 3<&- 3>&-; return 0; }
  fi
  return 1
}

venv_dir="backend/.venv"
if [ ! -x "$venv_dir/bin/uvicorn" ]; then
  warn "venv not found or uvicorn missing -- running ./install.sh first"
  TUTOR_NONINTERACTIVE="${TUTOR_NONINTERACTIVE:-1}" \
  TUTOR_SKIP_OLLAMA=1 \
  PYTHON_TUTOR_AUTOLAUNCH=0 \
  ./install.sh --no-launch
fi

if [ "$TUTOR_SKIP_OLLAMA" = "1" ]; then
  warn "TUTOR_SKIP_OLLAMA=1 -- skipping Ollama reachability check"
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

# Port-in-use check before exec'ing uvicorn -- uvicorn's error is ugly.
if port_in_use "$TUTOR_HOST" "$TUTOR_PORT"; then
  err "Port $TUTOR_PORT is already in use on $TUTOR_HOST."
  err "Either stop whatever is listening, or pick another port:"
  err "    ./run.sh --port 8002"
  exit 4
fi

if [ "$NO_LAUNCH" = "1" ]; then
  ok "--no-launch: preflight passed; would start uvicorn on http://${TUTOR_HOST}:${TUTOR_PORT}/"
  exit 0
fi

export TUTOR_MODEL
export TUTOR_SERVE_FRONTEND=1

url="http://${TUTOR_HOST}:${TUTOR_PORT}/"

echo
ok "starting backend on $url"
ok "open that URL in your browser. Press Ctrl-C to stop."
ok "tip: append '2>&1 | tee /tmp/python-tutor-run.log' to capture server logs."
echo

if [ "$OPEN_BROWSER" = "1" ]; then
  # Spawn a watcher that opens the browser once /api/health is healthy.
  # We background this BEFORE exec'ing uvicorn so it survives the exec.
  (
    healthy_url="http://127.0.0.1:${TUTOR_PORT}/api/health"
    for _ in $(seq 1 60); do
      if curl -fsS --max-time 1 "$healthy_url" >/dev/null 2>&1; then
        opener=""
        case "$(uname -s 2>/dev/null || echo unknown)" in
          Darwin) opener="open" ;;
          Linux)
            if command -v xdg-open >/dev/null 2>&1; then opener="xdg-open"; fi ;;
        esac
        if [ -n "$opener" ]; then
          "$opener" "$url" >/dev/null 2>&1 || true
        fi
        exit 0
      fi
      sleep 0.5
    done
  ) &
fi

# Tee uvicorn output to a log file so users have one canonical place to
# look when something fails. The `tee` keeps the live console output the
# same as before, but persists to disk.
cd backend
exec ./.venv/bin/uvicorn app.main:app \
  --host "$TUTOR_HOST" \
  --port "$TUTOR_PORT"
