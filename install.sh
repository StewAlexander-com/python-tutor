#!/usr/bin/env bash
# install.sh -- idempotent setup for the offline Python tutor.
#
# Run `./install.sh --help` for the full option list.
#
# What this script does:
#   1. Prints a one-screen preflight report (OS, Python, Ollama, model).
#   2. Verifies Python >= 3.10.
#   3. Creates backend/.venv if missing; rebuilds it if broken or if the
#      repo has been moved since it was created (virtualenvs are path-
#      sensitive -- moving them silently breaks the shebangs inside).
#   4. Installs backend dependencies (dev extras included for tests).
#      On network/DNS failure, prints actionable offline-wheelhouse hints.
#   5. Detects Ollama, the daemon, and the default model. For each
#      missing prerequisite it prompts y/N. Default answer is "no";
#      nothing is installed silently.
#   6. Optionally launches ./run.sh -- gated by y/N.
#
# Backwards compatibility:
#   Every previously documented env var still works. New CLI flags are
#   sugar over those env vars and never override an explicit env setting.
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

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Sets up the Python tutor: creates backend/.venv, installs backend deps,
and (with your consent) probes for Ollama and the default model.

Options:
  -h, --help              Show this help and exit.
  -y, --yes               Assume "yes" to every prompt (installs Ollama,
                          starts the daemon, pulls the model, launches).
                          Equivalent to PYTHON_TUTOR_ASSUME_YES=1.
  -n, --noninteractive    Never prompt; auto-answer "no" to every prompt.
                          Equivalent to TUTOR_NONINTERACTIVE=1.
      --no-launch         Do not prompt to launch ./run.sh after install.
      --skip-ollama       Skip every Ollama probe. Equivalent to
                          TUTOR_SKIP_OLLAMA=1.
      --skip-model-pull   Skip `ollama pull`. Equivalent to
                          TUTOR_SKIP_MODEL_PULL=1.
      --model TAG         Pull and check for TAG instead of gemma3:4b.
                          Equivalent to TUTOR_MODEL=TAG.

Environment variables (all still honored):
  TUTOR_MODEL                      default "gemma3:4b"
  TUTOR_SKIP_OLLAMA=1              skip every Ollama probe
  TUTOR_SKIP_MODEL_PULL=1          skip the `ollama pull` step
  TUTOR_NONINTERACTIVE=1           never prompt; assume "no"
  PYTHON_TUTOR_NONINTERACTIVE=1    alias for TUTOR_NONINTERACTIVE
  PYTHON_TUTOR_ASSUME_YES=1        never prompt; assume "yes"
  PYTHON_TUTOR_AUTOLAUNCH=1        after install, exec ./run.sh
  PIP_INDEX_URL / PIP_EXTRA_INDEX_URL / PIP_FIND_LINKS / PIP_NO_INDEX
                                   honored as usual by pip (see
                                   docs/install-runtime-workflow.md for
                                   offline-wheelhouse setup).

Exit codes:
  0  success
  1  Python is too old or missing
  2  pip install failed
  3  invalid CLI arguments
EOF
}

# ----- defaults --------------------------------------------------------------
TUTOR_MODEL="${TUTOR_MODEL:-gemma3:4b}"
TUTOR_SKIP_OLLAMA="${TUTOR_SKIP_OLLAMA:-0}"
TUTOR_SKIP_MODEL_PULL="${TUTOR_SKIP_MODEL_PULL:-0}"
TUTOR_NONINTERACTIVE="${TUTOR_NONINTERACTIVE:-${PYTHON_TUTOR_NONINTERACTIVE:-0}}"
PYTHON_TUTOR_ASSUME_YES="${PYTHON_TUTOR_ASSUME_YES:-0}"
PYTHON_TUTOR_AUTOLAUNCH="${PYTHON_TUTOR_AUTOLAUNCH:-0}"
NO_LAUNCH=0

# ----- arg parsing -----------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    -y|--yes) PYTHON_TUTOR_ASSUME_YES=1; shift ;;
    -n|--noninteractive) TUTOR_NONINTERACTIVE=1; shift ;;
    --no-launch) NO_LAUNCH=1; shift ;;
    --skip-ollama) TUTOR_SKIP_OLLAMA=1; shift ;;
    --skip-model-pull) TUTOR_SKIP_MODEL_PULL=1; shift ;;
    --model)
      if [ $# -lt 2 ]; then err "--model needs an argument"; exit 3; fi
      TUTOR_MODEL="$2"; shift 2 ;;
    --model=*) TUTOR_MODEL="${1#--model=}"; shift ;;
    --) shift; break ;;
    *)
      err "unknown option: $1 (try --help)"
      exit 3
      ;;
  esac
done

# ----- prompt helper ---------------------------------------------------------
# confirm "Question" [default-no|default-yes]
# Returns 0 for yes, 1 for no. Default is "no" unless overridden.
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
    printf "%b%s%b %s [no TTY → no]\n" "$c_yel" "[install]" "$c_off" "$question"
    return 1
  fi

  local hint
  if [ "$default_choice" = "default-yes" ]; then hint="[Y/n]"; else hint="[y/N]"; fi

  local reply=""
  printf "%b%s%b %s %s " "$c_blu" "[install]" "$c_off" "$question" "$hint"
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

# ----- OS detection ----------------------------------------------------------
uname_s="$(uname -s 2>/dev/null || echo unknown)"
case "$uname_s" in
  Darwin) os_kind=macos ;;
  Linux)  os_kind=linux ;;
  *)      os_kind=other ;;
esac

ollama_install_cmd_macos='brew install ollama'
ollama_install_cmd_linux='curl -fsSL https://ollama.com/install.sh | sh'

# ----- Python detection ------------------------------------------------------
# Pick the newest Python >= 3.10 available. Bug-fixed semver parser:
# the previous version split on "." with ${ver##*.} which returned the
# PATCH component on 3-component versions like "3.10.0" or "3.14.4".
PY=""
py_ver=""
parse_py_ver() {
  # Echoes "MAJOR MINOR" or nothing if unparseable.
  local bin="$1"
  "$bin" -c 'import sys; print("%d %d" % sys.version_info[:2])' 2>/dev/null || true
}
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    read -r maj min < <(parse_py_ver "$candidate")
    if [ -n "${maj:-}" ] && [ -n "${min:-}" ]; then
      if [ "$maj" -gt 3 ] || { [ "$maj" -eq 3 ] && [ "$min" -ge 10 ]; }; then
        PY="$candidate"
        py_ver="$maj.$min"
        break
      fi
    fi
  fi
done

# ----- preflight report ------------------------------------------------------
ollama_bin="$(command -v ollama 2>/dev/null || echo '(not found)')"
ollama_status="not installed"
if command -v ollama >/dev/null 2>&1; then
  if curl -fsS --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
    ollama_status="installed + daemon reachable"
  else
    ollama_status="installed (daemon down)"
  fi
fi

echo
say "Preflight"
say "  repo:    $repo_root"
say "  os:      $uname_s ($os_kind)"
if [ -n "$PY" ]; then
  say "  python:  $PY ($("$PY" --version 2>&1))"
else
  say "  python:  (none ≥3.10 found)"
fi
say "  ollama:  $ollama_status [$ollama_bin]"
say "  model:   $TUTOR_MODEL"
if [ "$TUTOR_SKIP_OLLAMA" = "1" ]; then
  say "  mode:    skip-ollama"
elif [ "$PYTHON_TUTOR_ASSUME_YES" = "1" ]; then
  say "  mode:    assume-yes"
elif [ "$TUTOR_NONINTERACTIVE" = "1" ]; then
  say "  mode:    noninteractive (auto-no)"
else
  say "  mode:    interactive"
fi
echo

# ----- 1. Python -------------------------------------------------------------
if [ -z "$PY" ]; then
  err "Python 3.10+ is required and was not found on PATH."
  err "macOS:   brew install python@3.12"
  err "Debian:  sudo apt-get install python3.12 python3.12-venv"
  err "Fedora:  sudo dnf install python3.12"
  exit 1
fi
ok "using $PY ($py_ver)"

# ----- 2. venv ---------------------------------------------------------------
venv_dir="backend/.venv"
venv_marker="$venv_dir/.tutor_repo_root"

needs_create=0
needs_rebuild=0

if [ ! -d "$venv_dir" ]; then
  needs_create=1
elif ! "$venv_dir/bin/python" -c "import sys" >/dev/null 2>&1; then
  warn "venv at $venv_dir looks broken; rebuilding"
  needs_rebuild=1
elif [ -f "$venv_marker" ] && [ "$(cat "$venv_marker" 2>/dev/null || true)" != "$repo_root" ]; then
  warn "venv was created in a different directory:"
  warn "  saved: $(cat "$venv_marker" 2>/dev/null || true)"
  warn "  now:   $repo_root"
  warn "virtualenvs are path-sensitive; rebuilding."
  needs_rebuild=1
fi

if [ "$needs_rebuild" = "1" ]; then
  rm -rf "$venv_dir"
  needs_create=1
fi

if [ "$needs_create" = "1" ]; then
  say "creating virtualenv at $venv_dir"
  "$PY" -m venv "$venv_dir"
else
  ok "venv already present at $venv_dir"
fi
echo "$repo_root" > "$venv_marker"

# ----- 3. dependencies -------------------------------------------------------
say "upgrading pip and installing backend deps"
pip_log="$(mktemp -t tutor-pip-XXXXXX.log 2>/dev/null || mktemp)"

pip_install() {
  # Run pip with the captured log so we can show actionable hints on
  # failure. We do NOT use --quiet -- verbose output goes to the log file
  # and only a tail is shown on failure.
  if ! "$venv_dir/bin/python" -m pip install --upgrade pip >"$pip_log" 2>&1; then
    return 1
  fi
  if ! "$venv_dir/bin/pip" install -r backend/requirements-dev.txt >>"$pip_log" 2>&1; then
    return 1
  fi
}

if pip_install; then
  rm -f "$pip_log"
  ok "backend dependencies installed"
else
  err "pip install failed. Last 25 lines of pip output:"
  tail -n 25 "$pip_log" >&2 || true
  err "Full log: $pip_log"
  echo >&2
  if grep -qiE "name or service not known|temporary failure in name resolution|could not resolve|timed out|getaddrinfo|cannot connect to proxy|ssl: certificate" "$pip_log"; then
    err "This looks like a network/DNS/proxy problem reaching pypi.org."
    err "Workarounds:"
    err "  1. Retry from a network with pypi.org reachable."
    err "  2. Behind a corporate proxy:"
    err "       export HTTPS_PROXY=http://proxy.example:8080"
    err "       export HTTP_PROXY=http://proxy.example:8080"
    err "  3. Fully offline -- build a wheelhouse on a connected host:"
    err "       pip download -d wheelhouse -r backend/requirements-dev.txt"
    err "     copy wheelhouse/ to this host, then re-run as:"
    err "       PIP_NO_INDEX=1 PIP_FIND_LINKS=\"$repo_root/wheelhouse\" ./install.sh"
    err "  4. Internal mirror:"
    err "       PIP_INDEX_URL=https://pypi.internal/simple ./install.sh"
    err "See docs/install-runtime-workflow.md → 'Offline / restricted networks'."
  fi
  exit 2
fi

# ----- 4. Ollama -------------------------------------------------------------
print_ollama_manual_hint() {
  warn "You can install Ollama manually any time:"
  case "$os_kind" in
    macos) warn "  $ollama_install_cmd_macos" ;;
    linux) warn "  $ollama_install_cmd_linux" ;;
    *)     warn "  See https://ollama.com/download for your platform." ;;
  esac
  warn "Then re-run ./install.sh to pull the default model."
  warn "The web UI will still work -- chat replies will fail until Ollama is up."
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
      if brew install ollama; then ok "Ollama installed via Homebrew."; return 0; fi
      err "brew install ollama failed."
      return 1 ;;
    linux)
      if ! command -v curl >/dev/null 2>&1; then
        err "curl is required to install Ollama on Linux automatically."
        err "Install curl with your package manager, then re-run ./install.sh."
        return 1
      fi
      say "running: $ollama_install_cmd_linux"
      if curl -fsSL https://ollama.com/install.sh | sh; then ok "Ollama installed."; return 0; fi
      err "Ollama installer exited non-zero."
      return 1 ;;
    *)
      err "Automatic Ollama install is only supported on macOS and Linux."
      err "See https://ollama.com/download for your platform."
      return 1 ;;
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
  err "Inspect /tmp/ollama-serve.log or run 'ollama serve' in another terminal."
  return 1
}

model_present() {
  curl -fsS --max-time 2 http://localhost:11434/api/tags 2>/dev/null \
    | grep -F -q "\"$TUTOR_MODEL\""
}

if [ "$TUTOR_SKIP_OLLAMA" = "1" ]; then
  warn "TUTOR_SKIP_OLLAMA=1 -- skipping Ollama checks"
else
  # 4a. Binary present?
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
        fi ;;
      *) print_ollama_manual_hint ;;
    esac
  fi

  # 4b. Daemon reachable?
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

  # 4c. Default model present?
  if command -v ollama >/dev/null 2>&1 && ollama_daemon_up; then
    if [ "$TUTOR_SKIP_MODEL_PULL" = "1" ]; then
      warn "TUTOR_SKIP_MODEL_PULL=1 -- skipping model pull"
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
if [ "$NO_LAUNCH" = "1" ]; then
  : # --no-launch wins over everything else.
elif [ "$PYTHON_TUTOR_AUTOLAUNCH" = "1" ]; then
  launch_now=1
elif confirm "Launch the tutor now (./run.sh)?" default-no; then
  launch_now=1
fi

if [ "$launch_now" = "1" ]; then
  ok "launching ./run.sh"
  # Forward the model so the backend sees the same default.
  export TUTOR_MODEL
  exec "$repo_root/run.sh"
fi

echo "Next step:"
echo "    ./run.sh        # starts the tutor at http://localhost:8001/"
echo
echo "Then open http://localhost:8001/ in your browser."
