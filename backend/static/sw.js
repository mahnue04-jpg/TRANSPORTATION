const CACHE_NAME = "amicor-pwa-v1";
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

  // Network-first for API calls to keep data fresh.
  if (req.url.includes("/api/")) {
    event.respondWith(
      fetch(req).catch(() => caches.match(req).then((cached) => cached || new Response("{\"detail\":\"offline\"}", { status: 503, headers: { "Content-Type": "application/json" } })))
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
