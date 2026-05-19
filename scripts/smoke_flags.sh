#!/usr/bin/env bash
# scripts/smoke_flags.sh -- exercise the new CLI flags on install.sh and
# run.sh without starting servers, installing system binaries, or
# touching the host.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

log="$(mktemp)"
trap 'rm -f "$log"' EXIT

want() {
  # want PATTERN -- assert PATTERN appears in $log
  if ! grep -qF -- "$1" "$log"; then
    echo "FAIL: expected to find: $1" >&2
    echo "--- log ---" >&2
    cat "$log" >&2
    exit 1
  fi
}

assert_exit() {
  # assert_exit EXPECTED ACTUAL LABEL
  if [ "$2" -ne "$1" ]; then
    echo "FAIL: $3 expected exit $1, got $2" >&2
    cat "$log" >&2
    exit 1
  fi
}

echo "--- install.sh --help ---"
set +e
./install.sh --help >"$log" 2>&1
rc=$?
set -e
assert_exit 0 "$rc" "install.sh --help"
want "Usage: ./install.sh"
want "--yes"
want "--noninteractive"
want "--no-launch"
want "--skip-ollama"
want "--skip-model-pull"
want "--model TAG"
echo "ok"

echo
echo "--- run.sh --help ---"
set +e
./run.sh --help >"$log" 2>&1
rc=$?
set -e
assert_exit 0 "$rc" "run.sh --help"
want "Usage: ./run.sh"
want "--host ADDR"
want "--port N"
want "--model TAG"
want "--open-browser"
want "--no-launch"
echo "ok"

echo
echo "--- install.sh --bogus (rejects unknown flag with exit 3) ---"
set +e
./install.sh --bogus >"$log" 2>&1
rc=$?
set -e
assert_exit 3 "$rc" "install.sh --bogus"
want "unknown option: --bogus"
echo "ok"

echo
echo "--- run.sh --bogus (rejects unknown flag with exit 3) ---"
set +e
./run.sh --bogus >"$log" 2>&1
rc=$?
set -e
assert_exit 3 "$rc" "run.sh --bogus"
want "unknown option: --bogus"
echo "ok"

echo
echo "--- install.sh --no-launch + --noninteractive + --skip-ollama ---"
set +e
./install.sh --no-launch --noninteractive --skip-ollama --skip-model-pull >"$log" 2>&1
rc=$?
set -e
assert_exit 0 "$rc" "install.sh --no-launch flag suite"
want "install complete."
# Should NOT have asked the launch question at all.
if grep -qF "Launch the tutor now" "$log"; then
  echo "FAIL: --no-launch should suppress the launch prompt" >&2
  cat "$log" >&2
  exit 1
fi
echo "ok"

echo
echo "--- run.sh --no-launch preflight passes without binding a port ---"
set +e
./run.sh --no-launch --skip-ollama --port 8902 >"$log" 2>&1
rc=$?
set -e
assert_exit 0 "$rc" "run.sh --no-launch"
want "preflight passed"
echo "ok"

echo
echo "--- run.sh port-in-use detection -> exit 4 ---"
# Bind a port with bash itself so we don't depend on `nc` or `python -m`.
python3 - <<'PY' &
import socket, time
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", 8903))
s.listen(1)
time.sleep(8)
PY
listener_pid=$!
# Give it a moment to bind.
for _ in $(seq 1 20); do
  python3 -c "import socket;s=socket.socket();s.settimeout(0.2);s.connect(('127.0.0.1',8903))" >/dev/null 2>&1 && break
  sleep 0.1
done
set +e
./run.sh --skip-ollama --port 8903 >"$log" 2>&1
rc=$?
set -e
kill "$listener_pid" 2>/dev/null || true
wait "$listener_pid" 2>/dev/null || true
assert_exit 4 "$rc" "run.sh port-in-use"
want "already in use"
echo "ok"

echo
echo "flags smoke ok"
