/* =========================================================
   app.js — Offline Python Tutor (adapted from Python Power User)
   - Fetches sections.json
   - Hash routing: #/, #/beginner, #/power, #/s/<key>
   - Renders hero, browser, and section view
   - Parses demo_source into prose + code + prompts
   - Minimal Python syntax highlighter
   - Search filter in drawer and browser
   - In-memory state only (no localStorage — sandbox safe)
   ========================================================= */

(() => {
  'use strict';

  // ---------- State ----------
  const state = {
    sections: [],
    sectionsByKey: new Map(),
    mode: 'beginner',           // 'beginner' | 'power'
    route: { view: 'home', key: null },
    currentTab: 'teaching',     // 'teaching' | 'reference'
  };

  // Difficulty grouping, indexed by section number (1..46)
  const DIFFICULTY = [
    { title: 'Foundations · start here', range: [1, 9],  key: 'foundations' },
    { title: 'Flow & data shaping',      range: [10, 12], key: 'flow' },
    { title: 'Functions & abstraction',  range: [13, 17], key: 'functions' },
    { title: 'Objects & design',         range: [18, 22], key: 'objects' },
    { title: 'Errors & iteration',       range: [23, 28], key: 'errors' },
    { title: 'Working with the world',   range: [29, 36], key: 'world' },
    { title: 'Mastery & polish',         range: [37, 46], key: 'mastery' },
  ];

  // One-liner summaries for cards (beginner vs power) — derived from goals,
  // tightened where needed so cards read like promises, not shrugs.
  // Fallback: use the section's own goal_* string.
  const cardHints = {}; // (populated after load; currently derived on the fly)

  // ---------- DOM refs ----------
  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

  const el = {
    topbar:        $('#topbar'),
    menuBtn:       $('#menuBtn'),
    drawer:        $('#drawer'),
    drawerClose:   $('#drawerClose'),
    drawerBackdrop:$('#drawerBackdrop'),
    drawerList:    $('#drawerList'),
    drawerSearch:  $('#drawerSearch'),

    viewHome:      $('#view-home'),
    viewBrowser:   $('#view-browser'),
    viewSection:   $('#view-section'),

    browserEyebrow:$('#browserEyebrow'),
    browserTitle:  $('#browserTitle'),
    browserLede:   $('#browserLede'),
    browserGroups: $('#browserGroups'),
    browserSearch: $('#browserSearch'),
    browserToggles:$$('.browser__tools .toggle__btn'),

    secNum:   $('#secNum'),
    secTitle: $('#secTitle'),
    secWhy:   $('#secWhy'),
    secBody:  $('#secBody'),
    secPrev:  $('#secPrev'),
    secNext:  $('#secNext'),
    crumbPath: $('#crumbPath'),
    crumbTitle:$('#crumbTitle'),
    tabs:     $$('.tabs__btn'),
    topbarLinks: $$('.topbar__link[data-path]'),
  };

  // ---------- HTML helpers ----------
  const escapeHtml = (s) =>
    String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[c]);

  const frag = (html) => {
    const t = document.createElement('template');
    t.innerHTML = html;
    return t.content;
  };

  // ---------- Python syntax highlighter (lightweight) ----------
  const PY_KEYWORDS = new Set([
    'False','None','True','and','as','assert','async','await','break','class',
    'continue','def','del','elif','else','except','finally','for','from','global',
    'if','import','in','is','lambda','nonlocal','not','or','pass','raise','return',
    'try','while','with','yield','match','case'
  ]);
  const PY_BUILTINS = new Set([
    'abs','all','any','ascii','bin','bool','breakpoint','bytearray','bytes',
    'callable','chr','classmethod','compile','complex','delattr','dict','dir',
    'divmod','enumerate','eval','exec','exit','filter','float','format',
    'frozenset','getattr','globals','hasattr','hash','help','hex','id','input',
    'int','isinstance','issubclass','iter','len','list','locals','map','max',
    'memoryview','min','next','object','oct','open','ord','pow','print',
    'property','range','repr','reversed','round','set','setattr','slice',
    'sorted','staticmethod','str','sum','super','tuple','type','vars','zip',
    '__import__','self','cls'
  ]);

  function highlightPython(code) {
    // Tokenize: we use a regex that matches one token at a time.
    // Order matters — longest / most-specific first.
    const tokens = [];
    const src = code;
    const regex = new RegExp([
      // triple-quoted strings (multi-line): '''...''' or """..."""
      `("""[\\s\\S]*?"""|'''[\\s\\S]*?''')`,
      // single-line string (single or double quotes)
      `("(?:\\\\.|[^"\\\\\\n])*"|'(?:\\\\.|[^'\\\\\\n])*')`,
      // comment
      `(#[^\\n]*)`,
      // decorators
      `(@[A-Za-z_][A-Za-z0-9_.]*)`,
      // numbers
      `(\\b\\d+\\.?\\d*(?:[eE][-+]?\\d+)?\\b)`,
      // identifier (keywords/builtins/fn calls distinguished below)
      `([A-Za-z_][A-Za-z0-9_]*)`,
      // operators / punctuation
      `([+\\-*/%=<>!&|^~]+|[\\(\\)\\[\\]\\{\\},;:\\.])`,
      // whitespace
      `(\\s+)`,
      // anything else
      `([\\s\\S])`,
    ].join('|'), 'g');

    let m;
    let out = '';
    while ((m = regex.exec(src)) !== null) {
      const [match, tStr3, tStr, tCom, tDec, tNum, tId, tOp, tWs] = m;
      if (tStr3 !== undefined) {
        out += `<span class="tok-str">${escapeHtml(match)}</span>`;
      } else if (tStr !== undefined) {
        out += `<span class="tok-str">${escapeHtml(match)}</span>`;
      } else if (tCom !== undefined) {
        out += `<span class="tok-com">${escapeHtml(match)}</span>`;
      } else if (tDec !== undefined) {
        out += `<span class="tok-dec">${escapeHtml(match)}</span>`;
      } else if (tNum !== undefined) {
        out += `<span class="tok-num">${escapeHtml(match)}</span>`;
      } else if (tId !== undefined) {
        if (PY_KEYWORDS.has(match)) {
          out += `<span class="tok-kw">${escapeHtml(match)}</span>`;
        } else if (PY_BUILTINS.has(match)) {
          out += `<span class="tok-builtin">${escapeHtml(match)}</span>`;
        } else {
          // Function call? peek ahead for (
          const nextChar = src[regex.lastIndex];
          if (nextChar === '(') {
            out += `<span class="tok-fn">${escapeHtml(match)}</span>`;
          } else {
            out += escapeHtml(match);
          }
        }
      } else if (tOp !== undefined) {
        if (/^[\(\)\[\]\{\},;:\.]$/.test(match)) {
          out += `<span class="tok-punc">${escapeHtml(match)}</span>`;
        } else {
          out += `<span class="tok-op">${escapeHtml(match)}</span>`;
        }
      } else if (tWs !== undefined) {
        out += escapeHtml(match);
      } else {
        out += escapeHtml(match);
      }
    }
    return out;
  }

  // ---------- demo_source parser ----------
  /*
    Grammar we tolerate:
      1. First non-blank block is the function signature  def demo_xxx():
      2. Then an indented triple-quoted docstring (optional).
         Inside: heading "Big picture:" and bullet lines starting with "-" or "*"
      3. Then body lines:
         - "# ..."   -> prose comment (consecutive merged into paragraph)
         - "#? ..."  -> prompt callout
         - code line -> collect until next prose block, emit as code block
         - blank      -> separator (flush collected code)
         - `_header(...)` calls and internal helpers -> skipped
  */

  function dedent(lines) {
    const nonEmpty = lines.filter((l) => l.trim().length);
    if (!nonEmpty.length) return lines;
    const min = Math.min(...nonEmpty.map((l) => l.match(/^[ \t]*/)[0].length));
    return lines.map((l) => l.slice(min));
  }

  // Turn a block of docstring text into {intro, sections[]}.
  // Sections are delimited by headings like "Big picture:", "HOW IT WORKS:",
  // "WHY IT MATTERS:", "EXAMPLES:", "PERFORMANCE RULES OF THUMB:".
  // Each section has {title, paragraphs[], bullets[], code?}.
  function parseDocstring(docText) {
    const result = { intro: null, sections: [] };
    if (!docText) return result;

    // Identify a heading line: either "Big picture:" (title-case) or an ALL-CAPS heading
    // (may include a parenthetical like "EXAMPLES (code → result):") followed by a colon.
    // We accept an optional parenthesized suffix after the main ALL-CAPS part.
    const headingRegex = /^\s*(Big picture|[A-Z][A-Z \-&/]{2,}[A-Z])(\s*\([^)]*\))?\s*:\s*$/;

    const rawLines = docText.split('\n');
    // First, locate heading positions
    const idxs = [];
    for (let k = 0; k < rawLines.length; k++) {
      if (headingRegex.test(rawLines[k])) idxs.push(k);
    }

    const tidyTitle = (t) => {
      const s = t.trim();
      if (/^Big picture$/i.test(s)) return 'Big picture';
      // Title-case an ALL-CAPS heading
      return s.split(/\s+/).map((w, i) => {
        if (w.length <= 3 && i > 0) return w.toLowerCase();
        return w[0] + w.slice(1).toLowerCase();
      }).join(' ');
    };

    // Intro = anything before first heading
    const firstIdx = idxs.length ? idxs[0] : rawLines.length;
    const introRaw = rawLines.slice(0, firstIdx).join('\n').trim();
    if (introRaw) {
      // Collapse to paragraph(s); strip leading "NN — TITLE" prefix from each.
      const titlePrefix = /^\d+\s*[—\-]\s*[A-Za-z][A-Za-z0-9 &()'\/_\-]*\s*[:.—\-]?\s*/;
      result.intro = introRaw.split(/\n\s*\n/)
        .map((p) => p.replace(/\s+/g, ' ').trim())
        .map((p) => p.replace(titlePrefix, '').trim())
        .filter(Boolean);
    }

    // Build sections
    for (let s = 0; s < idxs.length; s++) {
      const headLine = rawLines[idxs[s]];
      const titleMatch = headLine.match(headingRegex);
      const title = tidyTitle(titleMatch[1]);
      const end = (s + 1 < idxs.length) ? idxs[s + 1] : rawLines.length;
      const bodyLines = rawLines.slice(idxs[s] + 1, end);
      // Detect "EXAMPLES (code -> result)" style sections: treat body as preformatted
      const isExamples = /examples/i.test(title);
      if (isExamples) {
        // Keep body as a code-like block; trim blank outer lines
        const codeLines = dedent(bodyLines);
        while (codeLines.length && !codeLines[0].trim()) codeLines.shift();
        while (codeLines.length && !codeLines[codeLines.length - 1].trim()) codeLines.pop();
        result.sections.push({ title, code: codeLines.join('\n') });
        continue;
      }
      // Otherwise parse paragraphs + bullets
      const paragraphs = [];
      const bullets = [];
      let current = null;
      let currentP = null;
      for (const l of bodyLines) {
        const trim = l.trim();
        if (!trim) {
          if (current) { bullets.push(current); current = null; }
          if (currentP) { paragraphs.push(currentP); currentP = null; }
          continue;
        }
        if (/^[-*•]\s+/.test(trim)) {
          if (current) bullets.push(current);
          if (currentP) { paragraphs.push(currentP); currentP = null; }
          current = trim.replace(/^[-*•]\s+/, '');
        } else if (current) {
          // continuation of a bullet
          current += ' ' + trim;
        } else {
          // paragraph text
          currentP = currentP ? currentP + ' ' + trim : trim;
        }
      }
      if (current) bullets.push(current);
      if (currentP) paragraphs.push(currentP);
      result.sections.push({ title, paragraphs, bullets });
    }
    return result;
  }

  function parseDemoSource(source) {
    if (!source || !source.trim()) {
      return { doc: { intro: null, sections: [] }, blocks: [] };
    }

    const allLines = source.split('\n');

    // 1. Find and skip the def line
    let i = 0;
    while (i < allLines.length && !/^\s*def\s+/.test(allLines[i])) i++;
    if (i < allLines.length && /^\s*def\s+/.test(allLines[i])) i++;

    // 2. Extract docstring
    let docText = '';
    while (i < allLines.length && !allLines[i].trim()) i++;
    if (i < allLines.length && /^\s*("""|''')/.test(allLines[i])) {
      const q = allLines[i].trim().slice(0, 3);
      const dLines = [];
      const startLine = allLines[i];
      const afterOpen = startLine.indexOf(q);
      const restOfStart = startLine.slice(afterOpen + 3);
      if (restOfStart.includes(q)) {
        dLines.push(restOfStart.slice(0, restOfStart.indexOf(q)));
        i++;
      } else {
        dLines.push(restOfStart);
        i++;
        while (i < allLines.length && !allLines[i].includes(q)) {
          dLines.push(allLines[i]);
          i++;
        }
        if (i < allLines.length) {
          const last = allLines[i];
          dLines.push(last.slice(0, last.indexOf(q)));
          i++;
        }
      }
      docText = dedent(dLines).join('\n').trim();
    }

    // Strip ASCII-art frames: leading/trailing box-drawing corner lines, and pipe walls.
    // Lines that are just ─ ═ ─ ━ characters → remove.
    // Lines that start and end with │/┃/| walls → strip the walls.
    docText = docText
      .split('\n')
      .filter((l) => !/^[\s┌┐└┘├┤┬┴┼─━═╔╗╚╝=\-+]+$/.test(l))
      .map((l) => l.replace(/^\s*[│┃|]\s?/, '').replace(/\s?[│┃|]\s*$/, ''))
      .join('\n')
      .trim();

    const doc = parseDocstring(docText);

    // 3. Walk body, building blocks
    const bodyLines = dedent(allLines.slice(i));
    const blocks = [];
    let proseBuffer = [];
    let codeBuffer = [];

    const flushProse = () => {
      if (proseBuffer.length) {
        const text = proseBuffer
          .map((l) => l.replace(/^\s*#\s?/, ''))
          .join(' ')
          .replace(/\s+/g, ' ')
          .trim();
        if (text) blocks.push({ type: 'prose', text });
        proseBuffer = [];
      }
    };
    const flushCode = () => {
      if (codeBuffer.length) {
        // trim leading/trailing blank lines within the code block
        while (codeBuffer.length && !codeBuffer[0].trim()) codeBuffer.shift();
        while (codeBuffer.length && !codeBuffer[codeBuffer.length - 1].trim()) codeBuffer.pop();
        if (codeBuffer.length) {
          blocks.push({ type: 'code', text: codeBuffer.join('\n') });
        }
        codeBuffer = [];
      }
    };
    const flushProseAndCode = () => { flushCode(); flushProse(); };

    for (let j = 0; j < bodyLines.length; j++) {
      const raw = bodyLines[j];
      const ltrim = raw.trimStart();

      // Blank line: separates; flush code, keep prose buffer
      if (!ltrim.trim()) {
        flushCode();
        flushProse();
        continue;
      }

      // Skip internal helper calls that are noise to a reader
      if (/^_header\s*\(/.test(ltrim)) continue;

      // Section divider: #* ── NAME ── (renders as a subheading)
      const sectionMatch = ltrim.match(/^#\*\s*(?:[\-─—=]+\s*)?(.+?)\s*(?:[\-─—=]+\s*)?$/);
      if (ltrim.startsWith('#*') && sectionMatch && sectionMatch[1].replace(/[\-─—=\s]+/g, '').length > 0) {
        flushProseAndCode();
        const title = sectionMatch[1].replace(/[─—]+/g, '').replace(/\s+/g, ' ').trim();
        if (title && !/^[\-─—=]+$/.test(title)) {
          blocks.push({ type: 'subhead', text: title });
        }
        continue;
      }

      // Prompt callout (#? question)
      if (ltrim.startsWith('#?')) {
        flushProseAndCode();
        const promptText = ltrim.replace(/^#\?\s?/, '').trim();
        blocks.push({ type: 'prompt', text: promptText });
        continue;
      }

      // Warning callout (#! watch out)
      if (ltrim.startsWith('#!')) {
        flushProseAndCode();
        const text = ltrim.replace(/^#!\s?/, '').trim();
        blocks.push({ type: 'warn', text });
        continue;
      }

      // Stand-alone comment line
      if (ltrim.startsWith('#')) {
        flushCode();
        proseBuffer.push(raw);
        continue;
      }

      // Code line — flush prose, accumulate
      flushProse();
      codeBuffer.push(raw);
    }
    flushCode();
    flushProse();

    return { doc, blocks };
  }

  function parseExercises(source) {
    if (!source || !source.trim()) return [];
    // Split by numbered markers "# 1.", "# 2." etc.
    // Each item may span multiple lines that start with "#"
    const items = [];
    const lines = source.split('\n');
    let current = null;
    for (const line of lines) {
      const m = line.match(/^\s*#\s*(\d+)[.)]\s*(.*)$/);
      if (m) {
        if (current) items.push(current.trim());
        current = m[2];
      } else if (current !== null) {
        const cm = line.match(/^\s*#\s?(.*)$/);
        if (cm) current += ' ' + cm[1].trim();
      }
    }
    if (current) items.push(current.trim());
    return items.filter(Boolean);
  }

  // ---------- Rendering: prose ----------
  // Turn plain prose into HTML with `backtick` -> <code>, quotes preserved.
  function proseToHtml(text) {
    let s = escapeHtml(text);
    // `code` or "code-like tokens in quotes"
    s = s.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
    // “curly” too
    s = s.replace(/“([^”]+)”/g, '<code class="inline-code">$1</code>');
    return s;
  }

  // ---------- Rendering: section ----------
  function sectionCard(sec) {
    const desc = state.mode === 'power'
      ? (sec.goal_power || sec.goal_beginner || '')
      : (sec.goal_beginner || sec.goal_power || '');
    const num = String(sec.number).padStart(2, '0');
    const tag = state.mode === 'power' ? 'TL;DR' : 'start here';
    return `
      <a class="card" href="#/s/${encodeURIComponent(sec.key)}">
        <div class="card__head">
          <span class="card__num">${num}</span>
          <span class="card__tag">${escapeHtml(tag)}</span>
        </div>
        <h3 class="card__title">${escapeHtml(sec.title)}</h3>
        <p class="card__desc">${escapeHtml(desc)}</p>
      </a>
    `;
  }

  function renderBrowser(filter = '') {
    const q = filter.trim().toLowerCase();
    let groupsHtml = '';
    for (const group of DIFFICULTY) {
      const items = state.sections.filter((s) => {
        if (s.number < group.range[0] || s.number > group.range[1]) return false;
        if (!q) return true;
        return (
          s.title.toLowerCase().includes(q) ||
          (s.goal_beginner || '').toLowerCase().includes(q) ||
          (s.goal_power || '').toLowerCase().includes(q) ||
          s.key.toLowerCase().includes(q)
        );
      });
      if (!items.length) continue;
      groupsHtml += `
        <div class="browser__group">
          <h3 class="browser__group-title">${escapeHtml(group.title)}
            <span style="color:var(--ink-3); margin-left:.5em;">· ${items.length}</span>
          </h3>
          <div class="browser__grid">${items.map(sectionCard).join('')}</div>
        </div>
      `;
    }
    if (!groupsHtml) {
      groupsHtml = `<div class="pending">No sections match <strong>${escapeHtml(filter)}</strong>. Try a different term.</div>`;
    }
    el.browserGroups.innerHTML = groupsHtml;

    // eyebrow + title according to mode
    if (state.mode === 'power') {
      el.browserEyebrow.textContent = 'Quick reference';
      el.browserTitle.textContent = 'All 46 sections — at a glance';
      el.browserLede.textContent = 'TL;DRs, patterns, and the reason each feature exists. Tap a section for the full quick reference.';
    } else {
      el.browserEyebrow.textContent = 'Beginner path';
      el.browserTitle.textContent = 'Start with the foundations';
      el.browserLede.textContent = 'Each card names a goal. Walk them in order, or jump to whatever you need.';
    }
    // Toggle aria-selected
    for (const btn of el.browserToggles) {
      btn.setAttribute('aria-selected', btn.dataset.mode === state.mode ? 'true' : 'false');
    }
  }

  // ----- Render section view -----
  function renderSection(key) {
    const sec = state.sectionsByKey.get(key);
    if (!sec) {
      // 404: unknown section key — show a helpful message instead of silently going home
      el.viewHome.hidden = true;
      el.viewBrowser.hidden = true;
      el.viewSection.hidden = false;
      el.crumbPath.textContent = 'Home';
      el.crumbPath.href = '#/';
      el.crumbTitle.textContent = 'Not found';
      el.secNum.textContent = '';
      el.secTitle.textContent = 'Section not found';
      el.secWhy.textContent = `No section matches "${key}". Pick one from the list.`;
      el.secBody.innerHTML = `
        <div class="pending">
          <p>This section key doesn't exist. It may have been renamed or removed.</p>
          <p style="margin-top:1rem">
            <a href="#/beginner" style="color:var(--amber);text-decoration:underline">Browse all sections →</a>
          </p>
        </div>`;
      setSecNav(el.secPrev, null, 'prev');
      setSecNav(el.secNext, null, 'next');
      for (const b of el.tabs) b.setAttribute('aria-selected', 'false');
      document.title = 'Not found — Offline Python Tutor';
      return;
    }
    const num = String(sec.number).padStart(2, '0');

    // Breadcrumbs + header
    el.crumbPath.textContent = state.mode === 'power' ? 'Quick reference' : 'Beginner';
    el.crumbPath.href = state.mode === 'power' ? '#/power' : '#/beginner';
    el.crumbTitle.textContent = sec.title;
    el.secNum.textContent = `Section ${num}`;
    el.secTitle.textContent = sec.title;
    el.secWhy.textContent = (state.mode === 'power')
      ? (sec.goal_power || sec.goal_beginner || '')
      : (sec.goal_beginner || sec.goal_power || '');

    // Prev / next based on numeric order
    const idx = state.sections.findIndex((s) => s.key === key);
    const prev = state.sections[idx - 1];
    const next = state.sections[idx + 1];
    setSecNav(el.secPrev, prev, 'prev');
    setSecNav(el.secNext, next, 'next');

    // Body: depends on tab
    if (state.currentTab === 'reference') {
      renderReferenceBody(sec);
    } else {
      renderTeachingBody(sec);
    }

    // Tabs
    for (const b of el.tabs) {
      b.setAttribute('aria-selected', b.dataset.tab === state.currentTab ? 'true' : 'false');
    }

    // Drawer active
    highlightDrawerItem(sec.key);
  }

  function setSecNav(a, sec, dir) {
    if (!sec) {
      a.setAttribute('aria-disabled', 'true');
      a.href = '#';
      a.querySelector('.secnav__title').textContent = dir === 'prev' ? 'Start of path' : 'End of path';
      return;
    }
    a.removeAttribute('aria-disabled');
    a.href = `#/s/${encodeURIComponent(sec.key)}`;
    a.querySelector('.secnav__title').textContent = `${String(sec.number).padStart(2, '0')} · ${sec.title}`;
  }

  function renderBlocksHtml(blocks) {
    if (!blocks.length) return '';
    let html = '<div class="prose">';
    for (const block of blocks) {
      if (block.type === 'prose') {
        html += `<p>${proseToHtml(block.text)}</p>`;
      } else if (block.type === 'prompt') {
        html += `<div class="prompt"><span class="prompt__mark">#?</span><span>${proseToHtml(block.text)}</span></div>`;
      } else if (block.type === 'warn') {
        html += `<div class="prompt prompt--warn"><span class="prompt__mark">!</span><span>${proseToHtml(block.text)}</span></div>`;
      } else if (block.type === 'subhead') {
        html += `<h4 class="block-sub">${escapeHtml(block.text)}</h4>`;
      } else if (block.type === 'code') {
        html += codeBlock(block.text, 'python');
      }
    }
    html += '</div>';
    return html;
  }

  function renderDocstringHtml(doc, opts = {}) {
    // opts.ledeOnly: just the intro/big-picture lede card
    let html = '';
    const introText = (doc.intro || []).join(' ');
    // Find the "Big picture" section (if any) and the rest
    // Choose a lede source: prefer explicit "Big picture", else "How it works".
    const bigSec = doc.sections.find((s) => /big picture/i.test(s.title))
                || doc.sections.find((s) => /^how it/i.test(s.title));
    const otherSecs = doc.sections.filter((s) => s !== bigSec);

    // Intro lines like "05 — LISTS" are just titles; don't echo them.
    const isNoiseIntro = (t) => {
      if (!t) return true;
      const clean = t.replace(/[^a-z]/gi, '').toLowerCase();
      return clean.length < 6 || /^\d+[a-z]+$/i.test(clean);
    };
    const useIntro = introText && !isNoiseIntro(introText) ? introText : '';

    // The lede combines intro text + big-picture content
    if (useIntro || bigSec) {
      html += `<div class="lede-card">`;
      html += `<p class="eyebrow">Big picture</p>`;
      if (useIntro) html += `<p>${proseToHtml(useIntro)}</p>`;
      if (bigSec) {
        if (bigSec.paragraphs && bigSec.paragraphs.length) {
          for (const p of bigSec.paragraphs) html += `<p>${proseToHtml(p)}</p>`;
        }
        if (bigSec.bullets && bigSec.bullets.length) {
          html += `<ul>${bigSec.bullets.map((b) => `<li>${proseToHtml(b)}</li>`).join('')}</ul>`;
        }
      }
      html += `</div>`;
    }

    if (opts.ledeOnly) return html;

    // Render the remaining sections (HOW IT WORKS, WHY IT MATTERS, etc.)
    for (const sec of otherSecs) {
      html += `<h3 class="h-sub">${escapeHtml(sec.title)}</h3>`;
      if (sec.code !== undefined) {
        html += codeBlock(sec.code, 'python', 'examples');
        continue;
      }
      html += `<div class="prose">`;
      if (sec.paragraphs && sec.paragraphs.length) {
        for (const p of sec.paragraphs) html += `<p>${proseToHtml(p)}</p>`;
      }
      if (sec.bullets && sec.bullets.length) {
        html += `<ul>${sec.bullets.map((b) => `<li>${proseToHtml(b)}</li>`).join('')}</ul>`;
      }
      html += `</div>`;
    }
    return html;
  }

  function renderTeachingBody(sec) {
    const parsed = parseDemoSource(sec.demo_source);
    const tryItems = parseExercises(sec.try_this_source);

    let html = '';

    // Docstring lede + additional sections (HOW IT WORKS / WHY IT MATTERS / EXAMPLES)
    html += renderDocstringHtml(parsed.doc);

    // Teaching walkthrough from the function body
    if (parsed.blocks.length) {
      html += `<h3 class="h-sub">Walk through it</h3>`;
      html += renderBlocksHtml(parsed.blocks);
    } else if (!parsed.doc.intro && !parsed.doc.sections.length) {
      // No demo content at all
      html += `<div class="pending">
        <p><strong>Hands-on demo coming.</strong></p>
        <p style="margin-top:.5rem; color:var(--ink-2); font-size:var(--text-sm)">
          For now, this section is covered conceptually in neighbouring chapters. The quick-reference tab still applies.
        </p>
      </div>`;
    }

    // Try it yourself
    if (tryItems.length) {
      html += `<h3 class="h-sub">Try it yourself</h3>`;
      html += `<ol class="exerciselist">${tryItems.map((it) => `<li>${proseToHtml(it)}</li>`).join('')}</ol>`;
    }

    // Prompts from the JSON (curiosity nudges) — only if not already in blocks
    if (Array.isArray(sec.prompts) && sec.prompts.length) {
      const inlinePromptTexts = new Set(parsed.blocks.filter((b) => b.type === 'prompt').map((b) => b.text.trim()));
      const extra = sec.prompts.filter((p) => !inlinePromptTexts.has(String(p).trim()));
      if (extra.length) {
        html += `<h3 class="h-sub">Stop and predict</h3>`;
        for (const p of extra) {
          html += `<div class="prompt"><span class="prompt__mark">?</span><span>${proseToHtml(p)}</span></div>`;
        }
      }
    }

    el.secBody.innerHTML = html;
    wireCopyButtons(el.secBody);
    wireScrollHints(el.secBody);
    if (window.TutorCodeLab && typeof window.TutorCodeLab.mountInto === 'function') {
      window.TutorCodeLab.mountInto(el.secBody, sec);
    }
  }

  function renderReferenceBody(sec) {
    const speedItems = parseExercises(sec.speed_run_source);
    const tryItems = parseExercises(sec.try_this_source);
    const parsed = parseDemoSource(sec.demo_source);

    let html = '';

    // TL;DR
    const tldr = sec.goal_power || sec.goal_beginner || '';
    if (tldr) {
      html += `
        <div class="tldr">
          <p class="tldr__label">TL;DR</p>
          <p>${proseToHtml(tldr)}</p>
        </div>
      `;
    }

    // Code pattern — extract the LONGEST code block from parsed.blocks
    const codeBlocks = parsed.blocks.filter((b) => b.type === 'code');
    const codeSorted = codeBlocks.slice().sort((a, b) => b.text.length - a.text.length);
    if (codeSorted.length) {
      html += `<h3 class="h-sub">Core pattern</h3>`;
      html += codeBlock(codeSorted[0].text, 'python', 'copy-ready');
      if (codeSorted.length > 1) {
        html += `<h3 class="h-sub">Related patterns</h3>`;
        for (const cb of codeSorted.slice(1, 3)) {
          html += codeBlock(cb.text, 'python');
        }
      }
    } else {
      // Fall back to EXAMPLES section in docstring
      const examplesSec = parsed.doc.sections.find((s) => /examples/i.test(s.title));
      if (examplesSec && examplesSec.code) {
        html += `<h3 class="h-sub">Core pattern</h3>`;
        html += codeBlock(examplesSec.code, 'python', 'examples');
      }
    }

    // Speed run
    if (speedItems.length) {
      html += `<h3 class="h-sub">Speed run</h3>`;
      html += `<ol class="exerciselist">${speedItems.map((it) => `<li>${proseToHtml(it)}</li>`).join('')}</ol>`;
    } else if (tryItems.length) {
      // Fallback to try-this if no speed run
      html += `<h3 class="h-sub">Exercises</h3>`;
      html += `<ol class="exerciselist">${tryItems.map((it) => `<li>${proseToHtml(it)}</li>`).join('')}</ol>`;
    }

    // Root cause — prefer an explicit "WHY IT MATTERS" section, else the big-picture / how-it-works bullets.
    const whySec = parsed.doc.sections.find((s) => /why/i.test(s.title));
    const bigSec = parsed.doc.sections.find((s) => /big picture/i.test(s.title))
              || parsed.doc.sections.find((s) => /^how it/i.test(s.title));
    const introText = (parsed.doc.intro || []).join(' ');
    if (whySec || bigSec || introText) {
      html += `<h3 class="h-sub">Why this exists</h3>`;
      html += `<div class="rootcause">`;
      const source = whySec || bigSec;
      if (!whySec && introText) html += `<p>${proseToHtml(introText)}</p>`;
      if (source) {
        if (source.paragraphs && source.paragraphs.length) {
          for (const p of source.paragraphs) html += `<p>${proseToHtml(p)}</p>`;
        }
        if (source.bullets && source.bullets.length) {
          html += `<ul class="prose" style="padding-left:1.2em; list-style:disc; margin-top:.75rem;">`;
          for (const b of source.bullets) html += `<li>${proseToHtml(b)}</li>`;
          html += `</ul>`;
        }
      }
      html += `</div>`;
    }

    if (!html) {
      html = `<div class="pending"><p><strong>Reference content coming.</strong></p>
        <p style="margin-top:.5rem; color:var(--ink-2); font-size:var(--text-sm)">This section has no code patterns yet — the beginner tab may still have prose.</p></div>`;
    }

    el.secBody.innerHTML = html;
    wireCopyButtons(el.secBody);
    wireScrollHints(el.secBody);
  }

  function codeBlock(text, lang = 'python', label = 'python') {
    const highlighted = highlightPython(text);
    return `
      <figure class="codeblock">
        <figcaption class="codeblock__head">
          <span class="codeblock__label">${escapeHtml(label)}</span>
          <button class="codeblock__copy" type="button" aria-label="Copy code">Copy</button>
        </figcaption>
        <pre><code class="code-py">${highlighted}</code></pre>
      </figure>
    `;
  }

  function wireCopyButtons(root) {
    for (const btn of $$('.codeblock__copy', root)) {
      btn.addEventListener('click', () => {
        const pre = btn.closest('.codeblock').querySelector('pre');
        const text = pre.innerText;
        try {
          navigator.clipboard.writeText(text);
          const prev = btn.textContent;
          btn.textContent = 'Copied';
          setTimeout(() => { btn.textContent = prev; }, 1400);
        } catch (_) {
          // Fallback: select
          const range = document.createRange();
          range.selectNodeContents(pre);
          const sel = window.getSelection();
          sel.removeAllRanges(); sel.addRange(range);
        }
      });
    }
  }

  /* ---- Scroll-hint chevrons for overflowing code blocks ---- */
  function wireScrollHints(root) {
    // Skip on desktop — only helpful on mobile
    if (window.innerWidth >= 760) return;

    for (const block of $$('.codeblock', root)) {
      const pre = block.querySelector('pre');
      if (!pre) continue;

      // Remove any existing hint (re-render safety)
      const old = block.querySelector('.codeblock__scroll-hint');
      if (old) old.remove();

      // Only add if content actually overflows
      if (pre.scrollWidth <= pre.clientWidth + 2) continue;

      const hint = document.createElement('div');
      hint.className = 'codeblock__scroll-hint';
      hint.setAttribute('aria-hidden', 'true');
      hint.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>`;

      // Tap the chevron → scroll the pre a bit to the right
      hint.querySelector('svg').addEventListener('click', () => {
        pre.scrollBy({ left: 120, behavior: 'smooth' });
      });

      block.appendChild(hint);

      // Hide the hint once the user scrolls, show again if scrolled back to start
      let ticking = false;
      pre.addEventListener('scroll', () => {
        if (ticking) return;
        ticking = true;
        requestAnimationFrame(() => {
          const atEnd = pre.scrollLeft + pre.clientWidth >= pre.scrollWidth - 8;
          const scrolled = pre.scrollLeft > 10;
          hint.classList.toggle('is-hidden', atEnd || scrolled);
          ticking = false;
        });
      }, { passive: true });
    }
  }

  // ---------- Drawer ----------
  function renderDrawerList(filter = '') {
    const q = filter.trim().toLowerCase();
    const items = state.sections.filter((s) => {
      if (!q) return true;
      return s.title.toLowerCase().includes(q) ||
             (s.goal_beginner || '').toLowerCase().includes(q) ||
             (s.goal_power || '').toLowerCase().includes(q);
    });
    if (!items.length) {
      el.drawerList.innerHTML = `<div class="drawer__empty">No match for “${escapeHtml(filter)}”</div>`;
      return;
    }
    el.drawerList.innerHTML = items.map((s) => `
      <a class="drawer__item" href="#/s/${encodeURIComponent(s.key)}" data-key="${escapeHtml(s.key)}">
        <span class="drawer__item-num">${String(s.number).padStart(2, '0')}</span>
        <span class="drawer__item-title">${escapeHtml(s.title)}</span>
      </a>
    `).join('');
    highlightDrawerItem(state.route.key);
  }

  function highlightDrawerItem(key) {
    for (const a of $$('.drawer__item', el.drawerList)) {
      a.classList.toggle('is-active', a.dataset.key === key);
    }
  }

  function openDrawer() {
    el.drawer.hidden = false;
    el.drawerBackdrop.hidden = false;
    // force reflow for transition
    void el.drawer.offsetWidth;
    el.drawer.classList.add('is-open');
    el.drawerBackdrop.classList.add('is-open');
    el.menuBtn.setAttribute('aria-expanded', 'true');
    document.body.style.overflow = 'hidden';
  }
  function closeDrawer() {
    el.drawer.classList.remove('is-open');
    el.drawerBackdrop.classList.remove('is-open');
    el.menuBtn.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
    setTimeout(() => {
      if (!el.drawer.classList.contains('is-open')) {
        el.drawer.hidden = true;
        el.drawerBackdrop.hidden = true;
      }
    }, 260);
  }

  // ---------- Routing ----------
  function navigate(hash, replace = false) {
    if (replace) history.replaceState(null, '', hash);
    else location.hash = hash;
    handleRoute();
  }

  function handleRoute() {
    const raw = (location.hash || '#/').replace(/^#/, '');
    // Normalize
    const parts = raw.split('/').filter(Boolean); // e.g. ['s','variables'] or ['beginner']
    let view = 'home';
    let key = null;

    if (parts.length === 0) {
      view = 'home';
    } else if (parts[0] === 'beginner') {
      view = 'browser'; state.mode = 'beginner';
    } else if (parts[0] === 'power') {
      view = 'browser'; state.mode = 'power';
    } else if (parts[0] === 's' && parts[1]) {
      view = 'section';
      key = decodeURIComponent(parts[1]);
    } else {
      view = 'home';
    }

    state.route = { view, key };

    // Toggle views
    el.viewHome.hidden = view !== 'home';
    el.viewBrowser.hidden = view !== 'browser';
    el.viewSection.hidden = view !== 'section';

    // Update topbar active link
    for (const a of el.topbarLinks) {
      a.classList.toggle('topbar__link--active',
        (a.dataset.path === 'beginner' && view === 'browser' && state.mode === 'beginner') ||
        (a.dataset.path === 'power'    && view === 'browser' && state.mode === 'power')
      );
    }

    if (view === 'browser') {
      renderBrowser(el.browserSearch.value || '');
    } else if (view === 'section') {
      renderSection(key);
    }

    // Dynamic page title (renderSection may have already set a 404 title — don't overwrite)
    if (view === 'section' && key && state.sectionsByKey.has(key)) {
      document.title = `${state.sectionsByKey.get(key).title} — Offline Python Tutor`;
    } else if (view === 'browser') {
      document.title = `${state.mode === 'power' ? 'Quick Reference' : 'Beginner Path'} — Offline Python Tutor`;
    } else if (view === 'home') {
      document.title = 'Offline Python Tutor — a local-first learning frontend';
    }
    // For view === 'section' with unknown key, renderSection already set the 404 title

    // Scroll to top for clarity
    window.scrollTo({ top: 0, behavior: 'instant' in window ? 'instant' : 'auto' });

    // Close drawer on navigation
    closeDrawer();
  }

  // ---------- Wire events ----------
  function wireEvents() {
    window.addEventListener('hashchange', handleRoute);

    el.menuBtn.addEventListener('click', () => {
      if (el.drawer.classList.contains('is-open')) closeDrawer();
      else openDrawer();
    });
    el.drawerClose.addEventListener('click', closeDrawer);
    el.drawerBackdrop.addEventListener('click', closeDrawer);

    el.drawerSearch.addEventListener('input', (e) => renderDrawerList(e.target.value));
    el.browserSearch.addEventListener('input', (e) => renderBrowser(e.target.value));

    for (const b of el.browserToggles) {
      b.addEventListener('click', () => {
        state.mode = b.dataset.mode;
        // Rebuild and update hash
        navigate(state.mode === 'power' ? '#/power' : '#/beginner');
      });
    }

    for (const b of el.tabs) {
      b.addEventListener('click', () => {
        state.currentTab = b.dataset.tab;
        if (state.route.view === 'section') renderSection(state.route.key);
      });
    }

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeDrawer();
    });
  }

  // ---------- Load ----------
  async function load() {
    try {
      const res = await fetch('content/sections.json', { cache: 'no-cache' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const sections = (data.sections || []).slice().sort((a, b) => a.number - b.number);
      state.sections = sections;
      state.sectionsByKey = new Map(sections.map((s) => [s.key, s]));
    } catch (err) {
      console.error('Failed to load sections.json', err);
      el.viewHome.innerHTML = `
        <div style="max-width:42rem; margin: 6rem auto; padding: 2rem; background: var(--bg-1); border: 1px solid var(--line-2); border-radius: 12px;">
          <h2 style="color: var(--ink-0); margin-bottom: 1rem;">Could not load sections</h2>
          <p style="color: var(--ink-2); line-height:1.6;">Tried to fetch <code class="inline-code">content/sections.json</code> but got an error: <strong>${escapeHtml(String(err.message || err))}</strong>.</p>
          <p style="color: var(--ink-3); margin-top:1rem; font-size: 0.9rem;">If you opened this file directly via <code class="inline-code">file://</code>, serve it over HTTP — e.g. <code class="inline-code">python3 -m http.server</code>.</p>
        </div>
      `;
      return;
    }

    renderDrawerList();
    wireEvents();
    handleRoute();
  }

  // Kick off
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
})();
