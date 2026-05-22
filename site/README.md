# Project website / start page

A small static landing page for Python Tutor. It mirrors the app's
dark / amber aesthetic and explains the local-first loop without
needing to launch the backend.

**Published at:** <https://stewalexander-com.github.io/python-tutor/>

Deployed automatically by [`.github/workflows/pages.yml`](../.github/workflows/pages.yml)
on every push to `main` that touches `site/`.

## Files

```
site/
├── index.html                 # the landing page (full SEO + social meta)
├── style.css                  # design tokens mirror frontend/base.css
├── site.webmanifest           # PWA manifest, references the icons below
└── assets/
    ├── favicon.svg            # vector favicon, primary
    ├── favicon.ico            # 16/32/48 multi-res ICO for legacy clients
    ├── favicon-16.png
    ├── favicon-32.png
    ├── apple-touch-icon.png   # 180×180, full-bleed dark
    ├── icon-192.png           # PWA / Android home-screen
    ├── icon-512.png           # PWA / Android home-screen
    ├── og-image.png           # 1200×630 — Facebook, LinkedIn, Messenger, X
    ├── og-image-square.png    # 1200×1200 — square share / iMessage previews
    └── screenshots/           # six UI screenshots, lazy-loaded
```

## Social preview & SEO

`index.html` includes:

- standard SEO: `<title>`, `description`, `keywords`, `robots`, canonical
- Open Graph (Facebook / LinkedIn / Messenger / iMessage / Slack):
  `og:type`, `og:site_name`, `og:title`, `og:description`, `og:url`,
  `og:image` (+ `secure_url`, `type`, `width`, `height`, `alt`)
- Twitter / X: `twitter:card=summary_large_image` plus title, description,
  image, and `twitter:image:alt`
- JSON-LD `SoftwareApplication` for Google rich results
- a full favicon set + `site.webmanifest` for PWA installs

`og:image` and `twitter:image` use **absolute** `https://` URLs (most
social scrapers reject relative paths). All other assets use relative
paths so the page works under the `/python-tutor/` GitHub Pages subpath
and under `file://` previews.

### Validate the social preview

After deploy, paste the live URL into one of these debuggers — they
fetch the page server-side and show what each platform will render:

- Facebook / Messenger: <https://developers.facebook.com/tools/debug/>
- LinkedIn: <https://www.linkedin.com/post-inspector/>
- X / Twitter: <https://cards-dev.twitter.com/validator> (or just paste
  into a draft tweet)
- Generic: <https://www.opengraph.xyz/>

If you change the OG image, click "scrape again" in the FB debugger to
bust the cache; LinkedIn caches for ~7 days and has no manual flush.

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

- referenced screenshots and social assets exist on disk
- complete `<head>` meta package: title, description, robots, canonical,
  theme-color, full Open Graph set, full Twitter card set
- `og:image` and `twitter:image` are absolute `https://` URLs
- favicon package (svg, ico, 16/32 png, apple-touch-icon 180×180,
  192 / 512 PWA icons) and `site.webmanifest` are present, with all
  PNGs at their declared dimensions
- `site.webmanifest` is valid JSON and every icon resolves
- no `localhost:` URLs are baked into hrefs/srcs
- key sections (`#why`, `#loop`, `#screens`, `#start`) are wired up

CI invokes the same script.
