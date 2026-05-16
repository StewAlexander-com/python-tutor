#!/usr/bin/env bash
# install.sh — idempotent setup for the offline Python tutor.
#
# What this script does:
#   1. Verifies Python >= 3.10.
#   2. Creates backend/.venv if missing.
#   3. Installs backend dependencies (dev extras included for tests).
#   4. Checks whether Ollama is installed and running, and offers to pull
#      the default model. Never installs Ollama itself.
#
# What this script does NOT do:
#   - Start a server.
#   - Install Ollama, brew, curl, or any system package.
#   - Modify files outside the repository.
#
# Environment overrides:
#   TUTOR_MODEL              default "gemma3:4b"
#   TUTOR_SKIP_OLLAMA=1      skip every Ollama probe
#   TUTOR_SKIP_MODEL_PULL=1  skip the `ollama pull` step
#   TUTOR_NONINTERACTIVE=1   never prompt; assume defaults
set -euo pipefail

repo_root="$(cd "$(dirname "$0")" && pwd)"
cd "$repo_root"

# ----- pretty output ---------------------------------------------------------
if [ -t 1 ]; then
  c_red='\033[31m'; c_grn='\033[32m'; c_yel='\033[33m'; c_blu='\033[34m'; c_off='\033[0m'
else
  c_red=''; c_grn=''; c_yel=''; c_blu=''; c_off=''
fi
say()  { printf "%b%s%b\n" "$c_blu" "[install] $*" "$c_off"; }
ok()   { printf "%b%s%b\n" "$c_grn" "[install] $*" "$c_off"; }
warn() { printf "%b%s%b\n" "$c_yel" "[install] $*" "$c_off"; }
err()  { printf "%b%s%b\n" "$c_red" "[install] $*" "$c_off" >&2; }

TUTOR_MODEL="${TUTOR_MODEL:-gemma3:4b}"
TUTOR_SKIP_OLLAMA="${TUTOR_SKIP_OLLAMA:-0}"
TUTOR_SKIP_MODEL_PULL="${TUTOR_SKIP_MODEL_PULL:-0}"
TUTOR_NONINTERACTIVE="${TUTOR_NONINTERACTIVE:-0}"

# ----- 1. Python -------------------------------------------------------------
PY=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    ver="$("$candidate" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo "0.0")"
    major="${ver%%.*}"
    minor="${ver##*.}"
    if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
      PY="$candidate"
      break
    fi
  fi
done

if [ -z "$PY" ]; then
  err "Python 3.10+ is required and was not found on PATH."
  err "macOS:   brew install python@3.12"
  err "Debian:  sudo apt-get install python3.12 python3.12-venv"
  err "Fedora:  sudo dnf install python3.12"
  exit 1
fi
ok "using $PY ($("$PY" --version 2>&1))"

# ----- 2. venv ---------------------------------------------------------------
venv_dir="backend/.venv"
if [ ! -d "$venv_dir" ]; then
  say "creating virtualenv at $venv_dir"
  "$PY" -m venv "$venv_dir"
else
  ok "venv already present at $venv_dir"
fi

# Validate the venv actually works (handles partial/corrupt venvs).
if ! "$venv_dir/bin/python" -c "import sys" >/dev/null 2>&1; then
  warn "venv at $venv_dir looks broken; recreating"
  rm -rf "$venv_dir"
  "$PY" -m venv "$venv_dir"
fi

# ----- 3. dependencies -------------------------------------------------------
say "upgrading pip and installing backend deps"
"$venv_dir/bin/python" -m pip install --upgrade --quiet pip
"$venv_dir/bin/pip" install --quiet -r backend/requirements-dev.txt
ok "backend dependencies installed"

# ----- 4. Ollama -------------------------------------------------------------
if [ "$TUTOR_SKIP_OLLAMA" = "1" ]; then
  warn "TUTOR_SKIP_OLLAMA=1 — skipping Ollama checks"
else
  if ! command -v ollama >/dev/null 2>&1; then
    warn "ollama is not installed."
    warn "  macOS:  brew install ollama && ollama serve &"
    warn "  Linux:  curl -fsSL https://ollama.com/install.sh | sh && ollama serve &"
    warn "Re-run ./install.sh after installing Ollama to pull the default model."
    warn "The web UI will still work — chat replies will fail until Ollama is up."
  else
    ok "ollama is installed ($(command -v ollama))"
    # Probe the daemon.
    if curl -fsS --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
      ok "ollama daemon is reachable on http://localhost:11434"
      if [ "$TUTOR_SKIP_MODEL_PULL" = "1" ]; then
        warn "TUTOR_SKIP_MODEL_PULL=1 — skipping model pull"
      else
        # Does the model already exist locally?
        if curl -fsS --max-time 2 http://localhost:11434/api/tags 2>/dev/null \
             | grep -F -q "\"$TUTOR_MODEL\""; then
          ok "model '$TUTOR_MODEL' already present"
        else
          say "pulling model '$TUTOR_MODEL' (this can take several minutes)…"
          if ollama pull "$TUTOR_MODEL"; then
            ok "model '$TUTOR_MODEL' ready"
          else
            warn "ollama pull failed. You can retry later with: ollama pull $TUTOR_MODEL"
          fi
        fi
      fi
    else
      warn "ollama is installed but the daemon is not running."
      warn "Start it in another terminal: ollama serve"
      warn "Then re-run ./install.sh to pull the default model."
    fi
  fi
fi

# ----- next step -------------------------------------------------------------
echo
ok "install complete."
echo
echo "Next step:"
echo "    ./run.sh        # starts the tutor at http://localhost:8001/"
echo
echo "Then open http://localhost:8001/ in your browser."
