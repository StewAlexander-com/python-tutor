# Hero website

A small static landing page for Python Tutor. It mirrors the app's
dark / amber aesthetic and explains the local-first loop without
needing to launch the backend.

## Files

```
site/
├── index.html                 # the landing page
├── style.css                  # design tokens mirror frontend/base.css
└── assets/
    ├── favicon.svg
    ├── og-image.png           # 1200×630 social card (reused from frontend)
    └── screenshots/           # six UI screenshots, lazy-loaded
```

## Preview locally

The page is pure static HTML + CSS — no build step.

```bash
cd site
python3 -m http.server 8080
# open http://localhost:8080/
```

Or open `site/index.html` directly in a browser (file://) — all asset
paths are relative.

## Why a separate landing

The app at `frontend/` is a PWA: lesson browser, code lab, tutor chat.
It assumes the FastAPI backend on `:8001`. The landing page is for
**people who haven't installed anything yet** — a credible 30-second
overview that points them at the repo and the two-command install.

## Checks

`scripts/check_site.sh` runs from the repo root and verifies:

- referenced screenshots and OG image exist on disk
- `<title>` and Open Graph tags are present
- no `localhost:` URLs are baked into hrefs/srcs
- key sections (`#why`, `#loop`, `#screens`, `#start`) are wired up

CI invokes the same script.
