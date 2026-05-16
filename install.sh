#!/usr/bin/env bash
# install.sh — idempotent setup for the offline Python tutor.
#
# What this script does:
#   1. Verifies Python >= 3.10.
#   2. Creates backend/.venv if missing.
#   3. Installs backend dependencies (dev extras included for tests).
#   4. Detects Ollama, the Ollama daemon, and the default model. For each
#      missing prerequisite it prompts y/N before doing anything that
#      changes the host. Default answer is "no". Nothing is installed
#      silently.
#   5. If everything is ready (or after install) optionally offers to
#      launch the app via ./run.sh — again gated by y/N.
#
# What this script does NOT do:
#   - Install Ollama, Homebrew, curl, or any other system package without
#     the user typing "y" (or running with PYTHON_TUTOR_ASSUME_YES=1).
#   - Modify files outside the repository.
#
# Environment overrides:
#   TUTOR_MODEL                      default "gemma3:4b"
#   TUTOR_SKIP_OLLAMA=1              skip every Ollama probe
#   TUTOR_SKIP_MODEL_PULL=1          skip the `ollama pull` step
#   TUTOR_NONINTERACTIVE=1           never prompt; assume "no" to every
#                                    install/start/pull/launch question
#   PYTHON_TUTOR_NONINTERACTIVE=1    alias for TUTOR_NONINTERACTIVE
#   PYTHON_TUTOR_ASSUME_YES=1        non-interactive but assume "yes" —
#                                    suitable for unattended setup where
#                                    the operator has approved installs
#   PYTHON_TUTOR_AUTOLAUNCH=1        after install, exec ./run.sh
#                                    automatically (still respects the
#                                    Ollama probes)
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
TUTOR_NONINTERACTIVE="${TUTOR_NONINTERACTIVE:-${PYTHON_TUTOR_NONINTERACTIVE:-0}}"
PYTHON_TUTOR_ASSUME_YES="${PYTHON_TUTOR_ASSUME_YES:-0}"
PYTHON_TUTOR_AUTOLAUNCH="${PYTHON_TUTOR_AUTOLAUNCH:-0}"

# ----- prompt helper ---------------------------------------------------------
# confirm "Question" [default-no|default-yes]
# Returns 0 for yes, 1 for no. Default is "no" unless overridden.
# PYTHON_TUTOR_ASSUME_YES=1 always answers yes.
# TUTOR_NONINTERACTIVE=1 (without ASSUME_YES) always answers no.
# Accepted yes responses: y, Y, yes, Yes, YES. Anything else is "no".
confirm() {
  local question="$1"
  local default_choice="${2:-default-no}"

  if [ "$PYTHON_TUTOR_ASSUME_YES" = "1" ]; then
    printf "%b%s%b %s [auto-yes]\n" "$c_blu" "[install]" "$c_off" "$question"
    return 0
  fi
  if [ "$TUTOR_NONINTERACTIVE" = "1" ]; then
    printf "%b%s%b %s [auto-no]\n" "$c_blu" "[install]" "$c_off" "$question"
    return 1
  fi
  if [ ! -t 0 ]; then
    # No TTY and no explicit choice — be conservative.
    printf "%b%s%b %s [no TTY → no]\n" "$c_yel" "[install]" "$c_off" "$question"
    return 1
  fi

  local hint
  if [ "$default_choice" = "default-yes" ]; then
    hint="[Y/n]"
  else
    hint="[y/N]"
  fi

  local reply=""
  printf "%b%s%b %s %s " "$c_blu" "[install]" "$c_off" "$question" "$hint"
  IFS= read -r reply || reply=""
  case "$reply" in
    y|Y|yes|Yes|YES) return 0 ;;
    n|N|no|No|NO)    return 1 ;;
    "")
      if [ "$default_choice" = "default-yes" ]; then return 0; fi
      return 1
      ;;
    *) return 1 ;;
  esac
}

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
# Python deps in the venv are non-destructive — install without asking.
say "upgrading pip and installing backend deps"
"$venv_dir/bin/python" -m pip install --upgrade --quiet pip
"$venv_dir/bin/pip" install --quiet -r backend/requirements-dev.txt
ok "backend dependencies installed"

# ----- 4. Ollama -------------------------------------------------------------
# Steps 4a–4c only run when not skipped. Each system-level action prompts
# the user first. Defaults are "no" so a stray Enter never installs.

# Detect OS so we can suggest the right command.
uname_s="$(uname -s 2>/dev/null || echo unknown)"
case "$uname_s" in
  Darwin) os_kind=macos ;;
  Linux)  os_kind=linux ;;
  *)      os_kind=other ;;
esac

ollama_install_cmd_macos='brew install ollama'
ollama_install_cmd_linux='curl -fsSL https://ollama.com/install.sh | sh'

print_ollama_manual_hint() {
  warn "You can install Ollama manually any time:"
  case "$os_kind" in
    macos) warn "  $ollama_install_cmd_macos" ;;
    linux) warn "  $ollama_install_cmd_linux" ;;
    *)     warn "  See https://ollama.com/download for your platform." ;;
  esac
  warn "Then re-run ./install.sh to pull the default model."
  warn "The web UI will still work — chat replies will fail until Ollama is up."
}

install_ollama_now() {
  case "$os_kind" in
    macos)
      if ! command -v brew >/dev/null 2>&1; then
        err "Homebrew is required to install Ollama on macOS automatically."
        err "Install brew from https://brew.sh, then re-run ./install.sh."
        return 1
      fi
      say "running: $ollama_install_cmd_macos"
      if brew install ollama; then
        ok "Ollama installed via Homebrew."
        return 0
      fi
      err "brew install ollama failed."
      return 1
      ;;
    linux)
      if ! command -v curl >/dev/null 2>&1; then
        err "curl is required to install Ollama on Linux automatically."
        err "Install curl with your package manager, then re-run ./install.sh."
        return 1
      fi
      say "running: $ollama_install_cmd_linux"
      # The official installer is documented at https://ollama.com/download.
      # It may use sudo internally; that is the upstream-documented path.
      if curl -fsSL https://ollama.com/install.sh | sh; then
        ok "Ollama installed."
        return 0
      fi
      err "Ollama installer exited non-zero."
      return 1
      ;;
    *)
      err "Automatic Ollama install is only supported on macOS and Linux."
      err "See https://ollama.com/download for your platform."
      return 1
      ;;
  esac
}

ollama_daemon_up() {
  curl -fsS --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1
}

start_ollama_now() {
  # Start the daemon as a backgrounded process. We do not write any
  # service-manager units; we just spawn `ollama serve`. The user can
  # always run it manually instead.
  say "starting 'ollama serve' in the background"
  # shellcheck disable=SC2069
  nohup ollama serve >/tmp/ollama-serve.log 2>&1 &
  local pid=$!
  # Give it a moment, then probe.
  for _ in $(seq 1 20); do
    if ollama_daemon_up; then
      ok "ollama serve is up (pid $pid; log: /tmp/ollama-serve.log)"
      return 0
    fi
    sleep 0.5
  done
  err "ollama serve did not become reachable on :11434 within 10s."
  err "Inspect /tmp/ollama-serve.log or run 'ollama serve' in another terminal."
  return 1
}

model_present() {
  curl -fsS --max-time 2 http://localhost:11434/api/tags 2>/dev/null \
    | grep -F -q "\"$TUTOR_MODEL\""
}

# Skip everything if the user asked us to.
if [ "$TUTOR_SKIP_OLLAMA" = "1" ]; then
  warn "TUTOR_SKIP_OLLAMA=1 — skipping Ollama checks"
else
  # 4a. Is the binary present?
  if ! command -v ollama >/dev/null 2>&1; then
    warn "Ollama is not installed."
    case "$os_kind" in
      macos|linux)
        if confirm "Install Ollama now? (will run the official upstream installer)" default-no; then
          if install_ollama_now; then
            ok "ollama is installed ($(command -v ollama 2>/dev/null || echo 'not on PATH yet'))"
          else
            print_ollama_manual_hint
          fi
        else
          print_ollama_manual_hint
        fi
        ;;
      *)
        print_ollama_manual_hint
        ;;
    esac
  fi

  # 4b. Is the daemon reachable?
  if command -v ollama >/dev/null 2>&1; then
    ok "ollama is installed ($(command -v ollama))"
    if ollama_daemon_up; then
      ok "ollama daemon is reachable on http://localhost:11434"
    else
      warn "Ollama is installed but the daemon is not running on :11434."
      if confirm "Start 'ollama serve' in the background now?" default-no; then
        if ! start_ollama_now; then
          warn "Could not auto-start. Run 'ollama serve' in another terminal and re-run ./install.sh."
        fi
      else
        warn "Skipping auto-start. Run 'ollama serve' yourself in another terminal."
      fi
    fi
  fi

  # 4c. Is the default model present?
  if command -v ollama >/dev/null 2>&1 && ollama_daemon_up; then
    if [ "$TUTOR_SKIP_MODEL_PULL" = "1" ]; then
      warn "TUTOR_SKIP_MODEL_PULL=1 — skipping model pull"
    elif model_present; then
      ok "model '$TUTOR_MODEL' already present"
    else
      warn "Model '$TUTOR_MODEL' is not present locally."
      if confirm "Pull '$TUTOR_MODEL' now? (this can take several minutes)" default-no; then
        if ollama pull "$TUTOR_MODEL"; then
          ok "model '$TUTOR_MODEL' ready"
        else
          warn "ollama pull failed. You can retry later with: ollama pull $TUTOR_MODEL"
        fi
      else
        warn "Skipping pull. Retry later with: ollama pull $TUTOR_MODEL"
      fi
    fi
  fi
fi

# ----- 5. Optional auto-launch ----------------------------------------------
echo
ok "install complete."
echo

launch_now=0
if [ "$PYTHON_TUTOR_AUTOLAUNCH" = "1" ]; then
  launch_now=1
elif confirm "Launch the tutor now (./run.sh)?" default-no; then
  # confirm() returns true when ASSUME_YES=1 or when the user typed y/yes.
  launch_now=1
fi

if [ "$launch_now" = "1" ]; then
  ok "launching ./run.sh"
  exec "$repo_root/run.sh"
fi

echo "Next step:"
echo "    ./run.sh        # starts the tutor at http://localhost:8001/"
echo
echo "Then open http://localhost:8001/ in your browser."
