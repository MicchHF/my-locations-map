// Service Worker for @dalazareva locations PWA
const CACHE_NAME = 'dalazareva-cache-v13-live';
const PRECACHE_URLS = [
  './',
  './index.html',
  './manifest.json',
  './style.css',
  './icon-192.png',
  './icon-512.png',
  './apple-touch-icon.png',
  './icon.svg'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_URLS).catch((err) => {
        console.warn('Pre-caching non-fatal warning:', err);
      });
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Do not intercept non-GET requests or external analytics / maps
  if (event.request.method !== 'GET') return;
  if (url.origin !== self.location.origin) return;

  const isCode = url.pathname.endsWith('.js') || url.pathname.endsWith('.css') || url.pathname.endsWith('.html') || url.pathname.endsWith('/') || url.pathname.includes('/admin') || url.pathname.includes('/users-admin');

  if (isCode) {
    // Network-First for code/html files so updates apply immediately
    event.respondWith(
      fetch(event.request).then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200) {
          const responseClone = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseClone));
        }
        return networkResponse;
      }).catch(() => caches.match(event.request))
    );
  } else {
    // Stale-while-revalidate for local photos and icons
    event.respondWith(
      caches.match(event.request).then((cachedResponse) => {
        const fetchPromise = fetch(event.request).then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const responseClone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseClone));
          }
          return networkResponse;
        }).catch(() => cachedResponse);

        return cachedResponse || fetchPromise;
      })
    );
  }
});
