/* ============================================================
   Offline Python Tutor — Service Worker
   Cache-first for shell, network-first for content
   ============================================================ */

const CACHE_VERSION = 'pytutor-v2026-05-16c';
const SHELL_ASSETS = [
  './',
  './index.html',
  './base.css',
  './style.css',
  './tutor-chat.css',
  './tutor-codelab.css',
  './app.js',
  './tutor-chat.js',
  './tutor-codelab.js',
  './manifest.json',
  './assets/favicon.svg',
  './content/sections.json'
];

/* ---------- Install: pre-cache the app shell ---------- */
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_VERSION)
      .then(cache => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())   // Activate immediately
  );
});

/* ---------- Activate: purge old caches ---------- */
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== CACHE_VERSION)
          .map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())   // Take control of all tabs
  );
});

/* ---------- Fetch: stale-while-revalidate for shell, network-first for fonts ---------- */
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // Skip cross-origin requests except fonts
  if (url.origin !== location.origin) {
    // Let font requests through to network (they have their own CDN caching)
    return;
  }

  // Never cache tutor backend API calls — they must hit the live FastAPI server.
  if (url.pathname.startsWith('/api/')) {
    return;
  }

  // For navigation requests, serve the shell (SPA)
  if (e.request.mode === 'navigate') {
    e.respondWith(
      caches.match('./index.html')
        .then(cached => cached || fetch(e.request))
    );
    return;
  }

  // Stale-while-revalidate for everything else
  e.respondWith(
    caches.open(CACHE_VERSION).then(cache =>
      cache.match(e.request).then(cached => {
        const fetchPromise = fetch(e.request).then(response => {
          if (response.ok) {
            cache.put(e.request, response.clone());
          }
          return response;
        }).catch(() => cached);

        return cached || fetchPromise;
      })
    )
  );
});
