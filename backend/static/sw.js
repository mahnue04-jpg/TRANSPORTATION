const CACHE_NAME = "amicor-pwa-v2";
const CORE_ASSETS = [
  "/app",
  "/static/index.html",
  "/static/render.js",
  "/static/streaming.js",
  "/static/orchestrator.js",
  "/static/tools.js",
  "/static/manifest.webmanifest"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS)).catch(() => Promise.resolve())
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const isSameOrigin = url.origin === self.location.origin;
  const path = url.pathname;

  const isAppShell = req.mode === "navigate" || path === "/app" || path === "/static/index.html";
  const isCriticalRuntimeAsset = isSameOrigin && (
    path === "/static/render.js" ||
    path === "/static/streaming.js" ||
    path === "/static/orchestrator.js" ||
    path === "/static/tools.js" ||
    path.startsWith("/static/runtime/") ||
    path.startsWith("/static/ux/") ||
    path.startsWith("/static/monitoring/")
  );

  // Network-first for API calls to keep data fresh.
  if (req.url.includes("/api/")) {
    event.respondWith(
      fetch(req).catch(() => caches.match(req).then((cached) => cached || new Response("{\"detail\":\"offline\"}", { status: 503, headers: { "Content-Type": "application/json" } })))
    );
    return;
  }

  // Network-first for app shell and critical runtime assets to prevent stale hydration bundles.
  if (isAppShell || isCriticalRuntimeAsset) {
    event.respondWith(
      fetch(req)
        .then((network) => {
          const clone = network.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, clone)).catch(() => {});
          return network;
        })
        .catch(() => caches.match(req).then((cached) => cached || Response.error()))
    );
    return;
  }

  // Cache-first for static assets.
  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req).then((network) => {
        const clone = network.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(req, clone)).catch(() => {});
        return network;
      });
    })
  );
});
