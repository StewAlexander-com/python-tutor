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

# Start-page install content must be visible — this page is the entry point
# to the repo, so the clone/install/run commands have to be there literally.
need "git clone https://github.com/StewAlexander-com/python-tutor.git"
need "cd python-tutor"
need "./install.sh"
need "./run.sh --open-browser"
ok "clone / install / run commands present in start section"

# Quick links to repo, README, and issues from the start page.
need 'href="https://github.com/StewAlexander-com/python-tutor"'
need 'href="https://github.com/StewAlexander-com/python-tutor#readme"'
need 'href="https://github.com/StewAlexander-com/python-tutor/issues"'
ok "repo / README / issues links present"

# Copy-to-clipboard buttons should be wired to the command blocks.
need 'class="copy-btn"'
need 'data-copy-target="cmd-clone"'
need 'data-copy-target="cmd-install"'
need 'data-copy-target="cmd-run"'
ok "copy-to-clipboard buttons wired up"

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

# GitHub Pages deploy workflow must exist and reference the official actions.
PAGES_WF="$ROOT/.github/workflows/pages.yml"
[ -f "$PAGES_WF" ] || fail ".github/workflows/pages.yml missing (GitHub Pages deploy)"
grep -q "actions/configure-pages" "$PAGES_WF"      || fail "pages.yml missing actions/configure-pages"
grep -q "actions/upload-pages-artifact" "$PAGES_WF" || fail "pages.yml missing actions/upload-pages-artifact"
grep -q "actions/deploy-pages" "$PAGES_WF"          || fail "pages.yml missing actions/deploy-pages"
grep -q "path: site" "$PAGES_WF"                    || fail "pages.yml does not upload the site/ folder"
ok "GitHub Pages workflow present and references official actions"

echo "site checks passed"
