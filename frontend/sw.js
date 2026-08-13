importScripts('/js/version.js');
const CACHE = 'vexbob-' + APP_VERSION;
const SHELL = ['/', '/index.html', '/css/style.css', '/js/version.js', '/js/api.js', '/icon.svg', '/manifest.webmanifest',
               '/private/login.html', '/private/activate.html',
               '/ausgaben/', '/ausgaben/index.html',
               '/ausgaben/neu.html', '/ausgaben/bon.html',
               '/ausgaben/laeden.html', '/ausgaben/kategorien.html',
               '/ausgaben/statistik.html',
               '/ausgaben/ausgaben.js', '/ausgaben/dashboard.js', '/ausgaben/neu.js',
               '/ausgaben/bon.js', '/ausgaben/laeden.js', '/ausgaben/kategorien.js',
               '/ausgaben/statistik.js'];

// Baut aus einer möglicherweise redirected Response eine "saubere" Response.
// Safari/iOS lehnt Responses mit .redirected=true bei Navigation-Requests
// mit "response served by service worker has redirections" ab.
async function stripRedirect(resp) {
    if (!resp || !resp.redirected) return resp;
    const body = await resp.blob();
    return new Response(body, { status: resp.status, statusText: resp.statusText, headers: resp.headers });
}

async function precache() {
    const cache = await caches.open(CACHE);
    await Promise.all(SHELL.map(async url => {
        try {
            const resp = await fetch(url, { redirect: 'follow', credentials: 'same-origin' });
            if (!resp.ok) return;
            const clean = await stripRedirect(resp);
            await cache.put(url, clean);
        } catch (e) { /* skip */ }
    }));
}

self.addEventListener('install', e => {
    e.waitUntil(precache().then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
    e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
        .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
    const req = e.request;
    const url = new URL(req.url);
    // API/Backend nie anfassen
    if (url.hostname.includes('railway.app') || url.pathname.startsWith('/api/') || url.pathname === '/token') return;
    if (req.method !== 'GET' || url.origin !== self.location.origin) return;

    // Navigation-Requests: network-first, redirected Response neu bauen
    if (req.mode === 'navigate' || req.destination === 'document') {
        e.respondWith((async () => {
            try {
                const fresh = await fetch(req, { redirect: 'follow', credentials: 'same-origin' });
                const clean = await stripRedirect(fresh);
                if (fresh.ok) {
                    caches.open(CACHE).then(c => c.put(req, clean.clone())).catch(()=>{});
                }
                return clean;
            } catch (netErr) {
                const cached = await caches.match(req) || await caches.match(url.pathname) || await caches.match('/');
                return cached ? stripRedirect(cached) : new Response('offline', { status: 503 });
            }
        })());
        return;
    }

    // Statische Assets: cache-first
    e.respondWith((async () => {
        const cached = await caches.match(req);
        if (cached) return stripRedirect(cached);
        try {
            const resp = await fetch(req, { redirect: 'follow' });
            if (resp.ok && resp.type === 'basic') {
                const clone = resp.clone();
                caches.open(CACHE).then(c => c.put(req, clone)).catch(()=>{});
            }
            return resp;
        } catch (e) {
            const fallback = await caches.match('/');
            return fallback ? stripRedirect(fallback) : new Response('offline', { status: 503 });
        }
    })());
});