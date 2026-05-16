#!/usr/bin/env bash
# scripts/smoke_prompts.sh — exercise the y/N prompt code paths in install.sh
# without ever installing system binaries or starting daemons.
#
# We invoke install.sh with various env combos and assert:
#   - the install completes,
#   - prompts auto-resolve (no hangs waiting for stdin),
#   - the auto-no / auto-yes markers print as expected,
#   - backend/.venv is left usable.
#
# To keep the test fast and avoid actually starting uvicorn, we shadow
# run.sh with a no-op stub when testing the ASSUME_YES auto-launch path.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

log="$(mktemp)"
stub_dir="$(mktemp -d)"
trap 'rm -f "$log"; rm -rf "$stub_dir"' EXIT

# Set TUTOR_SKIP_OLLAMA in every invocation so we never run apt/brew/curl.

echo "--- Run 1: TUTOR_SKIP_OLLAMA=1 + TUTOR_NONINTERACTIVE=1 (CI baseline) ---"
TUTOR_SKIP_OLLAMA=1 TUTOR_NONINTERACTIVE=1 ./install.sh </dev/null 2>&1 | tee "$log"
grep -q "install complete." "$log" || { echo "FAIL: missing 'install complete.'" >&2; exit 1; }
test -x backend/.venv/bin/python || { echo "FAIL: venv missing" >&2; exit 1; }
grep -q "Launch the tutor now" "$log" || { echo "FAIL: launch prompt did not fire" >&2; exit 1; }
grep -q "\[auto-no\]" "$log" || { echo "FAIL: auto-no marker missing" >&2; exit 1; }
echo "ok: run 1"

echo
echo "--- Run 2: PYTHON_TUTOR_NONINTERACTIVE alias ---"
PYTHON_TUTOR_NONINTERACTIVE=1 TUTOR_SKIP_OLLAMA=1 ./install.sh </dev/null 2>&1 | tee "$log"
grep -q "install complete." "$log" || { echo "FAIL: alias produced no successful install" >&2; exit 1; }
grep -q "\[auto-no\]" "$log" || { echo "FAIL: alias did not trigger auto-no" >&2; exit 1; }
echo "ok: run 2"

echo
echo "--- Run 3: PYTHON_TUTOR_ASSUME_YES auto-launches (stubbed run.sh) ---"
# Replace ./run.sh with a stub for the duration of this test. We can't
# safely write to repo_root/run.sh (we'd corrupt the working copy), so we
# wrap install.sh: copy it to a temp dir, point it at a stubbed run.sh.
cat >"$stub_dir/run.sh" <<'STUB'
#!/usr/bin/env bash
echo "[stub-run] would launch uvicorn here"
exit 0
STUB
chmod +x "$stub_dir/run.sh"
# Run install.sh from its real location but with PATH-shadowed exec target.
# install.sh execs "$repo_root/run.sh" by absolute path, so PATH shadowing
# alone won't catch it. Instead we temporarily symlink run.sh aside.
mv run.sh "$stub_dir/run.sh.real"
ln -s "$stub_dir/run.sh" run.sh
set +e
PYTHON_TUTOR_ASSUME_YES=1 TUTOR_SKIP_OLLAMA=1 ./install.sh </dev/null 2>&1 | tee "$log"
rc=${PIPESTATUS[0]}
set -e
rm -f run.sh
mv "$stub_dir/run.sh.real" run.sh
chmod +x run.sh
test "$rc" -eq 0 || { echo "FAIL: ASSUME_YES install exited $rc" >&2; exit 1; }
grep -q "\[auto-yes\]" "$log" || { echo "FAIL: auto-yes marker missing" >&2; exit 1; }
grep -q "\[stub-run\] would launch uvicorn here" "$log" || \
  { echo "FAIL: did not exec run.sh under ASSUME_YES" >&2; exit 1; }
echo "ok: run 3"

echo
echo "prompt smoke ok"
