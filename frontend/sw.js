// Arachiz Music — Service Worker para Soporte Offline y PWA (v4.2)
const CACHE_NAME = "arachiz-music-v4.2";
const APP_SHELL = [
  "/",
  "/index.html",
  "/style.css?v=4.2",
  "/app.js?v=4.2",
  "/favicon.svg",
  "/manifest.json"
];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(APP_SHELL).catch(() => {});
    })
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(keys.map((key) => caches.delete(key)));
    })
  );
  self.clients.claim();
});

// Estrategia Network-First: Siempre carga el código más reciente del servidor
// Si no hay conexión o falla la red, recurre inmediatamente al cache offline
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // No interceptar peticiones de streaming de audio grandes ni endpoints dinámicos del backend
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws")) {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200 && networkResponse.type === "basic") {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseToCache);
          });
        }
        return networkResponse;
      })
      .catch(() => {
        return caches.match(event.request).then((cached) => {
          return cached || caches.match("/");
        });
      })
  );
});
