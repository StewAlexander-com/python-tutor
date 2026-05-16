/* =========================================================
   tutor-chat.js — Offline Python Tutor
   Floating chat panel that talks to the local FastAPI backend
   (POST /api/chat) backed by Ollama/Gemma.

   - Resolves backend base URL from (in order):
       1. window.TUTOR_BACKEND_URL (set by an inline script)
       2. <meta name="tutor-backend"> content
       3. localStorage key "tutor-backend"
       4. Same-origin (empty string) — used when the backend is
          configured with TUTOR_SERVE_FRONTEND=1
       5. http://localhost:8001 — local dev fallback
   - Probes GET {base}/api/health and shows a banner if degraded.
   - Sends multi-turn history; injects the current section as a
     short user-side context line when one is open.
   - In-memory transcript only (matches the rest of the app).
   ========================================================= */

(() => {
  'use strict';

  // ---------- Config resolution ----------
  function resolveBackend() {
    if (typeof window.TUTOR_BACKEND_URL === 'string') return window.TUTOR_BACKEND_URL;
    const meta = document.querySelector('meta[name="tutor-backend"]');
    if (meta && meta.content) return meta.content.trim();
    try {
      const stored = localStorage.getItem('tutor-backend');
      if (stored) return stored;
    } catch (_) { /* localStorage may be disabled */ }
    // Heuristic: if we're served from a static file server on :8000 or :5500
    // and the user hasn't configured anything, assume the backend is on :8001.
    const { protocol, hostname, port } = location;
    if (port && port !== '8001' && (hostname === 'localhost' || hostname === '127.0.0.1')) {
      return `${protocol}//${hostname}:8001`;
    }
    return '';
  }

  const BACKEND = resolveBackend();
  const api = (path) => (BACKEND ? BACKEND.replace(/\/$/, '') : '') + path;

  // ---------- State ----------
  const state = {
    open: false,
    history: [],          // [{role:'user'|'assistant', content:string}]
    pending: false,
    health: null,         // last health payload (or null)
  };

  // ---------- Small DOM helpers ----------
  const escapeHtml = (s) =>
    String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[c]);

  // Minimal markdown-ish renderer: ```code blocks```, `inline`, and \n\n paragraphs.
  function renderMarkdownish(text) {
    const parts = [];
    let i = 0;
    const src = String(text);
    while (i < src.length) {
      const fenceStart = src.indexOf('```', i);
      if (fenceStart === -1) {
        parts.push({ type: 'text', value: src.slice(i) });
        break;
      }
      if (fenceStart > i) parts.push({ type: 'text', value: src.slice(i, fenceStart) });
      const fenceEnd = src.indexOf('```', fenceStart + 3);
      if (fenceEnd === -1) {
        // Unterminated fence — treat the rest as code so streaming partials don't break.
        const after = src.slice(fenceStart + 3);
        const nl = after.indexOf('\n');
        const lang = nl === -1 ? '' : after.slice(0, nl).trim();
        const code = nl === -1 ? '' : after.slice(nl + 1);
        parts.push({ type: 'code', lang, value: code });
        break;
      }
      const inner = src.slice(fenceStart + 3, fenceEnd);
      const nl = inner.indexOf('\n');
      const lang = nl === -1 ? '' : inner.slice(0, nl).trim();
      const code = nl === -1 ? inner : inner.slice(nl + 1);
      parts.push({ type: 'code', lang, value: code });
      i = fenceEnd + 3;
    }
    return parts.map((p) => {
      if (p.type === 'code') {
        const langClass = p.lang ? ` data-lang="${escapeHtml(p.lang)}"` : '';
        return `<pre class="tutor-chat__code"${langClass}><code>${escapeHtml(p.value.replace(/\n$/, ''))}</code></pre>`;
      }
      // text: escape, then inline code, then paragraph splits
      const escaped = escapeHtml(p.value).replace(/`([^`\n]+)`/g, '<code class="tutor-chat__icode">$1</code>');
      return escaped
        .split(/\n{2,}/)
        .map((para) => `<p>${para.replace(/\n/g, '<br>')}</p>`)
        .join('');
    }).join('');
  }

  function renderRefs(docs) {
    if (!docs || !Array.isArray(docs.references) || !docs.references.length) return '';
    const items = docs.references.map((r) => {
      const url = String(r.url || '');
      const label = escapeHtml(r.label || url);
      return `<li><a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${label}</a></li>`;
    }).join('');
    const status = docs.online ? (docs.online_ok ? 'verified' : 'offline · unverified') : 'offline';
    return `<aside class="tutor-chat__refs" aria-label="References">
      <header><strong>References</strong> <span>${escapeHtml(status)}</span></header>
      <ul>${items}</ul>
    </aside>`;
  }

  // ---------- Mount UI ----------
  function mount() {
    if (document.getElementById('tutorChatRoot')) return; // already mounted

    const root = document.createElement('div');
    root.id = 'tutorChatRoot';
    root.className = 'tutor-chat';
    root.innerHTML = `
      <button class="tutor-chat__fab" id="tutorChatFab" aria-label="Open tutor chat" aria-expanded="false" aria-controls="tutorChatPanel">
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <path d="M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H9l-4 4V7a2 2 0 0 1 2-2Z"
                fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
        </svg>
        <span class="tutor-chat__fab-label">Ask tutor</span>
      </button>

      <section class="tutor-chat__panel" id="tutorChatPanel" hidden aria-label="Tutor chat">
        <header class="tutor-chat__head">
          <div class="tutor-chat__head-text">
            <p class="tutor-chat__eyebrow">Local tutor</p>
            <h2 class="tutor-chat__title">Ask about Python</h2>
            <p class="tutor-chat__sub" id="tutorChatSub">Connecting…</p>
          </div>
          <button class="tutor-chat__close" id="tutorChatClose" aria-label="Close tutor chat">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
            </svg>
          </button>
        </header>

        <div class="tutor-chat__banner" id="tutorChatBanner" hidden></div>

        <div class="tutor-chat__log" id="tutorChatLog" role="log" aria-live="polite"></div>

        <form class="tutor-chat__form" id="tutorChatForm" autocomplete="off">
          <label class="tutor-chat__field">
            <span class="tutor-chat__label">Your question</span>
            <textarea
              id="tutorChatInput"
              rows="2"
              placeholder="e.g. Why does my for-loop print nothing?"
              required></textarea>
          </label>
          <div class="tutor-chat__row">
            <button type="button" class="tutor-chat__ghost" id="tutorChatReset" aria-label="Clear conversation">Clear</button>
            <button type="submit" class="tutor-chat__send" id="tutorChatSend">Send</button>
          </div>
        </form>
      </section>
    `;
    document.body.appendChild(root);

    const fab = root.querySelector('#tutorChatFab');
    const panel = root.querySelector('#tutorChatPanel');
    const closeBtn = root.querySelector('#tutorChatClose');
    const form = root.querySelector('#tutorChatForm');
    const input = root.querySelector('#tutorChatInput');
    const resetBtn = root.querySelector('#tutorChatReset');
    const log = root.querySelector('#tutorChatLog');
    const sub = root.querySelector('#tutorChatSub');
    const banner = root.querySelector('#tutorChatBanner');
    const sendBtn = root.querySelector('#tutorChatSend');

    fab.addEventListener('click', () => toggle(true, { panel, fab, input }));
    closeBtn.addEventListener('click', () => toggle(false, { panel, fab, input }));
    resetBtn.addEventListener('click', () => {
      state.history = [];
      renderLog(log);
    });

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text || state.pending) return;
      input.value = '';
      sendMessage(text, { log, sendBtn, sub });
    });

    input.addEventListener('keydown', (e) => {
      // Cmd/Ctrl + Enter sends; plain Enter inserts newline (matches modern chat UX).
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        form.requestSubmit();
      }
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && state.open) toggle(false, { panel, fab, input });
    });

    renderLog(log);
    probeHealth(sub, banner);
  }

  function toggle(open, { panel, fab, input }) {
    state.open = open;
    panel.hidden = !open;
    fab.setAttribute('aria-expanded', open ? 'true' : 'false');
    fab.classList.toggle('is-open', open);
    if (open) {
      // Give the panel a tick to render, then focus.
      setTimeout(() => input && input.focus(), 30);
    }
  }

  // ---------- Backend calls ----------
  async function probeHealth(subEl, bannerEl) {
    try {
      const res = await fetch(api('/api/health'), { method: 'GET' });
      const data = await res.json();
      state.health = data;
      const where = BACKEND || 'same origin';
      if (data.status === 'ok') {
        subEl.textContent = `Connected · ${data.default_model} · ${where}`;
        bannerEl.hidden = true;
      } else {
        subEl.textContent = `Backend reachable, Ollama unavailable · ${where}`;
        bannerEl.hidden = false;
        bannerEl.textContent = `Ollama did not respond at ${data.ollama_url}. Start it with “ollama serve” and pull ${data.default_model}.`;
      }
    } catch (err) {
      state.health = null;
      subEl.textContent = `Backend unreachable · ${BACKEND || 'same origin'}`;
      bannerEl.hidden = false;
      bannerEl.textContent = `Could not reach the tutor backend at ${BACKEND || location.origin}. Start it with: uvicorn app.main:app --port 8001`;
    }
  }

  function currentSectionContext() {
    // Best-effort: read from the DOM the main app already populated.
    const title = document.getElementById('secTitle');
    const view = document.getElementById('view-section');
    if (!view || view.hidden || !title || !title.textContent) return null;
    const num = document.getElementById('secNum');
    const label = num && num.textContent ? `${num.textContent.trim()} — ${title.textContent.trim()}` : title.textContent.trim();
    return label;
  }

  async function sendMessage(text, { log, sendBtn, sub }) {
    const section = currentSectionContext();
    const userContent = section
      ? `Context: I am currently reading "${section}".\n\n${text}`
      : text;

    state.history.push({ role: 'user', content: userContent });
    state.pending = true;
    sendBtn.disabled = true;
    sendBtn.textContent = 'Thinking…';
    renderLog(log, { pending: true });

    try {
      const res = await fetch(api('/api/chat'), {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ messages: state.history }),
      });
      if (!res.ok) {
        const detail = await safeReadError(res);
        throw new Error(`HTTP ${res.status}: ${detail}`);
      }
      const data = await res.json();
      const content = (data && data.message && data.message.content) || '';
      const docs = data && data.docs ? data.docs : null;
      state.history.push({ role: 'assistant', content, docs });
    } catch (err) {
      state.history.push({
        role: 'assistant',
        content: `_⚠ Tutor backend error: ${err && err.message ? err.message : err}_\n\nMake sure the backend is running (\`uvicorn app.main:app --port 8001\`) and Ollama is up (\`ollama serve\`).`,
      });
    } finally {
      state.pending = false;
      sendBtn.disabled = false;
      sendBtn.textContent = 'Send';
      renderLog(log);
    }
  }

  async function safeReadError(res) {
    try {
      const data = await res.json();
      return data && data.detail ? data.detail : JSON.stringify(data);
    } catch (_) {
      try { return await res.text(); } catch (_) { return res.statusText; }
    }
  }

  // ---------- Render ----------
  function renderLog(log, opts = {}) {
    const messages = state.history;
    if (messages.length === 0 && !opts.pending) {
      log.innerHTML = `
        <div class="tutor-chat__empty">
          <p>Ask a Python question. The tutor explains the <em>why</em> first,
          then shows minimal code, then a one-line challenge.</p>
          <p class="tutor-chat__hint">Tip: open a section and ask "explain this with a smaller example".</p>
        </div>`;
      return;
    }
    const html = messages.map((m) => {
      const who = m.role === 'user' ? 'You' : 'Tutor';
      const cls = m.role === 'user' ? 'tutor-chat__msg tutor-chat__msg--user' : 'tutor-chat__msg tutor-chat__msg--asst';
      const refs = m.role === 'assistant' ? renderRefs(m.docs) : '';
      return `
        <article class="${cls}">
          <header class="tutor-chat__who">${who}</header>
          <div class="tutor-chat__body">${renderMarkdownish(m.content)}</div>
          ${refs}
        </article>`;
    }).join('');
    const pending = opts.pending
      ? `<article class="tutor-chat__msg tutor-chat__msg--asst is-pending">
           <header class="tutor-chat__who">Tutor</header>
           <div class="tutor-chat__body"><p><span class="tutor-chat__dots"><span></span><span></span><span></span></span></p></div>
         </article>`
      : '';
    log.innerHTML = html + pending;
    log.scrollTop = log.scrollHeight;
  }

  // ---------- Boot ----------
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }

  // Expose a tiny helper for power users / tests.
  window.TutorChat = {
    get backend() { return BACKEND; },
    get state() { return { ...state, history: state.history.slice() }; },
    open() { document.getElementById('tutorChatFab') && document.getElementById('tutorChatFab').click(); },
  };
})();
