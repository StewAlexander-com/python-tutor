#!/usr/bin/env node
/**
 * scripts/capture-screenshots.js
 *
 * Re-generates the README walkthrough screenshots under
 * docs/assets/screenshots/. Run from the repo root:
 *
 *   npm i --no-save playwright       # if not already
 *   npx playwright install chromium  # one-time browser download
 *   node scripts/capture-screenshots.js
 *
 * The script serves the static frontend on a local port and mocks
 * /api/health, /api/run, /api/evaluate, /api/chat so the UI shows
 * realistic states without requiring Ollama to be running. The
 * mocked responses are deterministic and do not represent real
 * model output — they exist purely to make the UI screenshots
 * reproducible. If you want screenshots of *real* model output,
 * start the backend (./run.sh) and point a browser at it manually.
 */
'use strict';

const path = require('path');
const http = require('http');
const fs = require('fs');

let chromium;
try {
  ({ chromium } = require('playwright'));
} catch (_) {
  console.error('playwright is not installed. Run: npm i --no-save playwright && npx playwright install chromium');
  process.exit(1);
}

const REPO = path.resolve(__dirname, '..');
const FRONTEND = path.join(REPO, 'frontend');
const OUT = path.join(REPO, 'docs/assets/screenshots');

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js':   'application/javascript; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg':  'image/svg+xml',
  '.png':  'image/png',
  '.ico':  'image/x-icon',
};

function serveStatic(root, port) {
  const server = http.createServer((req, res) => {
    let urlPath = req.url.split('?')[0];
    if (urlPath === '/' || urlPath === '') urlPath = '/index.html';
    const fp = path.normalize(path.join(root, urlPath));
    if (!fp.startsWith(root)) { res.statusCode = 403; return res.end('forbidden'); }
    fs.stat(fp, (err, stat) => {
      if (err || !stat.isFile()) { res.statusCode = 404; return res.end('not found'); }
      const ext = path.extname(fp).toLowerCase();
      res.setHeader('content-type', MIME[ext] || 'application/octet-stream');
      res.setHeader('cache-control', 'no-store');
      fs.createReadStream(fp).pipe(res);
    });
  });
  return new Promise((resolve) => server.listen(port, '127.0.0.1', () => resolve(server)));
}

function mockApi(route) {
  const url = route.request().url();
  const u = new URL(url);
  if (u.pathname === '/api/health') {
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        ollama: { ok: true, model: 'gemma3:4b', host: 'http://localhost:11434' },
        version: '0.1.0',
      }),
    });
  }
  if (u.pathname === '/api/run') {
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        stdout: "Hello, tutor!\nx = 42\ntype(x) = <class 'int'>\n",
        stderr: '', exit_code: 0, duration_ms: 47, timed_out: false, truncated: false,
      }),
    });
  }
  if (u.pathname === '/api/evaluate') {
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        assessment: 'on_track',
        feedback:
          "Nice — you read the value into `x`, printed it, and asked Python for its type. " +
          "That's exactly the variables-and-types loop in miniature.\n\n" +
          "One small nudge: try assigning a *different* type to the same name (`x = \"hello\"`) " +
          "and re-print `type(x)`. Notice how the *name* doesn't change type, the *object* does — " +
          "this is the heart of Python's dynamic typing.",
        next_step: "Re-bind `x` to a string, then to a list, and print `type(x)` each time.",
        model: 'gemma3:4b',
        docs: {
          online: true, online_ok: true,
          references: [
            { url: 'https://docs.python.org/3/library/stdtypes.html', label: 'Built-in types' },
            { url: 'https://docs.python.org/3/library/functions.html#type', label: 'type()' },
          ],
        },
      }),
    });
  }
  if (u.pathname === '/api/chat') {
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        reply:
          "In Python every value is an *object*, and each object knows its own type. " +
          "Names are just labels you stick on objects.",
        model: 'gemma3:4b',
      }),
    });
  }
  return route.continue();
}

async function shot(page, name) {
  const file = path.join(OUT, name);
  await page.screenshot({ path: file, fullPage: false });
  console.log('wrote', path.relative(REPO, file));
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const port = 8773;
  const server = await serveStatic(FRONTEND, port);
  const base = `http://127.0.0.1:${port}/`;

  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 2,
    colorScheme: 'dark',
  });
  await ctx.route('**/sw.js', (r) => r.fulfill({ status: 404, body: '' }));
  await ctx.route('**/api/**', mockApi);
  const page = await ctx.newPage();

  // 01 — home
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.waitForSelector('.hero');
  await page.waitForTimeout(400);
  await shot(page, '01-home.png');

  // 02 — lesson browser
  await page.goto(base + '#/beginner', { waitUntil: 'networkidle' });
  await page.waitForSelector('#view-browser:not([hidden])');
  await page.waitForTimeout(500);
  await shot(page, '02-lesson-browser.png');

  // 03 — section view
  await page.goto(base, { waitUntil: 'networkidle' });
  const sectionKey = await page.evaluate(async () => {
    const res = await fetch('/content/sections.json');
    const d = await res.json();
    return d.sections[0].key;
  });
  await page.goto(`${base}#/s/${sectionKey}`, { waitUntil: 'networkidle' });
  await page.waitForSelector('#view-section:not([hidden])');
  await page.waitForSelector('.codelab');
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(400);
  await shot(page, '03-section-view.png');

  // 04 — code lab run
  await page.evaluate(() => {
    const ta = document.querySelector('#codelabEditor');
    if (ta) {
      ta.value = 'x = 42\nprint("Hello, tutor!")\nprint("x =", x)\nprint("type(x) =", type(x))\n';
      ta.dispatchEvent(new Event('input', { bubbles: true }));
    }
  });
  await page.click('#codelabRun');
  await page.waitForSelector('.codelab__runline');
  await page.evaluate(() => {
    const el = document.querySelector('.codelab');
    if (el) el.scrollIntoView({ block: 'start' });
    window.scrollBy(0, -80);
  });
  await page.waitForTimeout(400);
  await shot(page, '04-code-lab-run.png');

  // 05 — evaluate feedback
  await page.fill('#codelabQuestion', 'Why does type(x) change when I reassign x?');
  await page.click('#codelabEval');
  await page.waitForSelector('.codelab__feedback');
  await page.evaluate(() => {
    const el = document.querySelector('.codelab__feedback');
    if (el) el.scrollIntoView({ block: 'start' });
    window.scrollBy(0, -80);
  });
  await page.waitForTimeout(400);
  await shot(page, '05-evaluate-feedback.png');

  // 06 — floating chat panel
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(200);
  await page.click('#tutorChatFab');
  await page.waitForSelector('#tutorChatPanel:not([hidden])');
  await page.evaluate(async () => {
    try {
      const r = await fetch('/api/health');
      const d = await r.json();
      const sub = document.getElementById('tutorChatSub');
      const banner = document.getElementById('tutorChatBanner');
      if (sub) sub.textContent = `Connected · ${d.ollama?.model || 'local model'} · /api ready`;
      if (banner) { banner.hidden = true; banner.textContent = ''; }
    } catch (_) {}
  });
  await page.evaluate(() => {
    const log = document.getElementById('tutorChatLog');
    if (!log) return;
    const esc = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
    const codeBlock = `x = 42        # x labels an int\nx = "hello"   # now x labels a str — the int is GC'd\nprint(type(x))`;
    log.innerHTML = `
      <div class="tutor-chat__msg tutor-chat__msg--user">
        <p>In Python, what does it mean that variables are not typed?</p>
      </div>
      <div class="tutor-chat__msg tutor-chat__msg--assistant">
        <p>In Python every value is an <em>object</em>, and each object knows its own type. Names (what other languages call variables) are just labels you stick on objects.</p>
        <pre class="tutor-chat__code"><code>${esc(codeBlock)}</code></pre>
        <p>So <code>x</code> itself isn't typed — the <em>object it points to</em> is. That's why <code>type(x)</code> can change between lines without any cast.</p>
      </div>
    `;
    log.scrollTop = log.scrollHeight;
  });
  await page.waitForTimeout(400);
  await shot(page, '06-tutor-chat.png');

  await browser.close();
  server.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
