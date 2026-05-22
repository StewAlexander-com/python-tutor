#!/usr/bin/env bash
# check_site.sh — light validity / asset checks for the hero landing page.
#
# Runs from repo root. Exits non-zero on the first failure, with a clear
# message and an exit code that's safe for CI.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SITE="$ROOT/site"
HTML="$SITE/index.html"
CSS="$SITE/style.css"

fail() { echo "✗ $*" >&2; exit 1; }
ok()   { echo "✓ $*"; }

[ -f "$HTML" ] || fail "site/index.html missing"
[ -f "$CSS" ]  || fail "site/style.css missing"
ok "site/index.html and site/style.css present"

# Required meta tags / sections — grep for substrings.
need() {
  grep -q -- "$1" "$HTML" || fail "site/index.html missing: $1"
}
need "<title>Python Tutor"
need 'property="og:title"'
need 'property="og:image"'
need 'name="twitter:card"'
need 'id="why"'
need 'id="loop"'
need 'id="screens"'
need 'id="start"'
ok "required <head> and section anchors present"

# Every local href/src under site/ must resolve to a real file.
# (We only check ./relative paths — external URLs are skipped.)
python3 - "$HTML" "$SITE" <<'PY'
import re, sys, os
html_path, site_dir = sys.argv[1], sys.argv[2]
src = open(html_path, encoding="utf-8").read()
refs = re.findall(r'(?:href|src)\s*=\s*"(\./[^"]+)"', src)
missing = []
for r in refs:
    rel = r[2:]  # drop "./"
    rel = rel.split("#", 1)[0].split("?", 1)[0]
    p = os.path.join(site_dir, rel)
    if not os.path.exists(p):
        missing.append(r)
if missing:
    print("✗ missing local assets:", file=sys.stderr)
    for m in missing:
        print("    " + m, file=sys.stderr)
    sys.exit(1)
print(f"✓ all {len(refs)} local references resolve")
PY

# Should NOT contain hard-coded localhost links (would break in prod).
if grep -nE 'href="http://localhost' "$HTML" >/dev/null; then
    fail "site/index.html contains hard-coded http://localhost hrefs"
fi
ok "no hard-coded localhost hrefs"

# Cheap structural sanity check: balanced <main> tag.
opens=$(grep -c '<main' "$HTML" || true)
closes=$(grep -c '</main>' "$HTML" || true)
[ "$opens" = "$closes" ] || fail "unbalanced <main> tags ($opens open, $closes close)"
ok "<main> tags balanced"

echo "site checks passed"
