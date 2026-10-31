// The service worker: the site works offline after the first visit.
'use strict';

const CACHE = 'devoprotect-__VERSION__';
const ASSETS = __ASSETS__;
const OPTIONAL = __OPTIONAL__;
const PREFIX = CACHE.slice(0, CACHE.indexOf('-') + 1);
const INDEX = 'names.npz';
const INDEX_CACHE = 'names-index';
const isIndex = url => new URL(url).pathname.endsWith('/' + INDEX);

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(ASSETS);
    await Promise.all(OPTIONAL.map(u => cache.add(u).catch(() => null)));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const k of await caches.keys()) if (k.startsWith(PREFIX) && k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== self.location.origin) return;
  event.respondWith((async () => {
    const index = isIndex(req.url);
    const cache = await caches.open(index ? INDEX_CACHE : CACHE);
    const hit = await cache.match(req, { ignoreSearch: true });
    if (hit && !index) return hit;
    let res;
    try {
      res = await fetch(req);
    } catch (e) {
      if (hit) return hit;
      throw e;
    }
    if (res.ok && res.status === 200) cache.put(req, res.clone()).catch(() => null);
    return res;
  })());
});
