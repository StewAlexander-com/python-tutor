#!/usr/bin/env bash
# scripts/smoke_run.sh — launch the server, hit /api/health and /, then stop.
# Intended for CI and for verifying a local install end-to-end without Ollama.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

PORT="${TUTOR_PORT:-8801}"
export TUTOR_PORT="$PORT"
export TUTOR_SKIP_OLLAMA=1

# Launch in the background.
./run.sh > /tmp/tutor-smoke.log 2>&1 &
pid=$!
trap 'kill $pid 2>/dev/null || true; wait $pid 2>/dev/null || true' EXIT

# Wait up to 15s for the server to come up.
for _ in $(seq 1 30); do
  if curl -fsS --max-time 1 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

echo "--- /api/health ---"
curl -fsS "http://127.0.0.1:$PORT/api/health"
echo
echo "--- / (head) ---"
curl -fsS "http://127.0.0.1:$PORT/" | head -3
echo
echo "--- /api/config ---"
curl -fsS "http://127.0.0.1:$PORT/api/config" | head -c 200
echo
echo "smoke ok"
