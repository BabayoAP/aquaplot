/* AquaPlot service worker.
 *
 * The premise of this app is someone standing on a riverbank. Riverbanks are cut
 * banks, culverts and tree cover, which is to say they are where mobile signal
 * goes to die. An assessment tool that needs connectivity at the moment of
 * observation is a tool that gets used from the car park, later, from memory.
 *
 * So: the shell and the reference data are cached on first visit and served from
 * cache thereafter, and the page keeps an outbox for assessments recorded with no
 * connection. This worker deliberately does NOT queue the POSTs itself - the page
 * owns the outbox, in IndexedDB, where it can be inspected, retried and shown to
 * the person. A background sync the user cannot see is the wrong design for data
 * somebody walked to a stream to collect.
 */

const VERSION = "aquaplot-v1";
const SHELL = `${VERSION}-shell`;
const DATA = `${VERSION}-data`;

// Enough to complete a whole assessment offline: the page, and the vocabularies
// the questions and the identification guide are rendered from.
const SHELL_URLS = ["/", "/manifest.webmanifest", "/icon.svg"];
const DATA_URLS = ["/api/form", "/api/guide", "/api/pilots"];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const shell = await caches.open(SHELL);
    await shell.addAll(SHELL_URLS).catch(() => {});
    const data = await caches.open(DATA);
    await Promise.all(DATA_URLS.map((u) => fetch(u).then((r) => r.ok && data.put(u, r)).catch(() => {})));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keep = new Set([SHELL, DATA]);
    await Promise.all((await caches.keys()).filter((k) => !keep.has(k)).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;            // the outbox owns writes
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // never touch map tiles or iNaturalist

  if (DATA_URLS.includes(url.pathname)) {
    // Network first: the form and the catalogue do change between versions, and a
    // stale vocabulary would silently drop a citizen's answer on the server.
    event.respondWith((async () => {
      try {
        const fresh = await fetch(request);
        if (fresh.ok) (await caches.open(DATA)).put(url.pathname, fresh.clone());
        return fresh;
      } catch (e) {
        const hit = await caches.match(url.pathname);
        if (hit) return hit;
        throw e;
      }
    })());
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith((async () => {
      try {
        return await fetch(request);
      } catch (e) {
        // Offline: any navigation falls back to the check page, which is the only
        // one that works without a server anyway.
        return (await caches.match("/")) || Response.error();
      }
    })());
    return;
  }

  if (SHELL_URLS.includes(url.pathname)) {
    event.respondWith(caches.match(url.pathname).then((hit) => hit || fetch(request)));
  }
});
