// SW_VERSION: v1.34.0 — dieser Kommentar MUSS bei jedem Release mit hochgezaehlt
// werden. Browser erkennen Service-Worker-Updates NUR anhand eines Byte-Diffs
// der sw.js-Datei selbst — was sw.js per importScripts() nachlaedt (version.js)
// wird dabei NICHT verglichen. Ohne diese Zeile bleibt der Service Worker also
// ewig "installiert", der Cache-Name aendert sich nie, und Nutzer bekommen
// alte, laengst reparierte JS-Dateien (z.B. produkte.js) fuer immer aus dem
// Cache statt vom Server. Das war die eigentliche Ursache dafuer, dass die
// Produkte-Seite trotz Backend-/Frontend-Fixes weiterhin leer blieb.
importScripts('/js/version.js');
// v1.33.0: API_BASE aus config.js im SW verfuegbar machen, damit der
// API-Bypass unten nicht mehr auf den Hostnamen 'railway.app' fest
// verdrahtet ist. Umzug auf eigene Domain funktioniert damit ohne
// SW-Code-Aenderung. importScripts wirft, wenn die Datei fehlt -- daher
// try/catch, damit ein defekter Deploy nicht den ganzen SW killt.
let API_ORIGIN = '';
try {
    importScripts('/js/config.js');
    if (self.VEXBOB_CONFIG && self.VEXBOB_CONFIG.API_BASE) {
        API_ORIGIN = new URL(self.VEXBOB_CONFIG.API_BASE).origin;
    }
} catch (e) { /* config optional */ }
const CACHE = 'vexbob-' + APP_VERSION;
const SHELL = ['/', '/index.html', '/css/style.css', '/js/version.js', '/js/api.js',
               '/js/nav-switcher.js', '/js/sw-update.js', '/icon.svg', '/manifest.webmanifest',
               '/private/login.html', '/private/activate.html',
               '/ausgaben/', '/ausgaben/index.html',
               '/ausgaben/neu.html', '/ausgaben/bon.html',
               '/ausgaben/laeden.html', '/ausgaben/kategorien.html',
               '/ausgaben/statistik.html',
               '/ausgaben/ausgaben.js', '/ausgaben/dashboard.js', '/ausgaben/neu.js',
               '/ausgaben/bon.js', '/ausgaben/laeden.js', '/ausgaben/kategorien.js',
               '/ausgaben/statistik.js',
               '/health/', '/health/index.html', '/health/health.css', '/health/health.js',
               '/css/statistics.css', '/admin/', '/admin/index.html', '/admin/admin.css',
               '/ausgaben/dashboard.css'];

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
    // API/Backend nie anfassen. v1.33.0: statt hardgecodeten 'railway.app'-Match
    // pruefen wir den echten API-Origin aus config.js -- funktioniert 1:1 nach
    // einem Custom-Domain-Umzug ohne SW-Aenderung.
    if ((API_ORIGIN && url.origin === API_ORIGIN)
        || url.pathname.startsWith('/api/')
        || url.pathname === '/token') return;
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

    // Statische Assets: stale-while-revalidate statt cache-first.
    // v1.21.1: Vorher wurde bei einem Cache-Hit NIE nachgeschaut, ob es eine
    // neue Version gibt — das JS blieb im aktiven Tab quasi fuer immer alt,
    // bis der User manuell den Cache leerte. Jetzt wird die gecachte Version
    // sofort ausgeliefert (schnell!), aber PARALLEL im Hintergrund vom Server
    // geholt und der Cache aktualisiert — der naechste Seitenaufruf ist dann
    // automatisch aktuell, ganz ohne manuelles Eingreifen.
    e.respondWith((async () => {
        const cached = await caches.match(req);
        const network = fetch(req, { redirect: 'follow' }).then(resp => {
            if (resp.ok && resp.type === 'basic') {
                caches.open(CACHE).then(c => c.put(req, resp.clone())).catch(()=>{});
            }
            return resp;
        }).catch(() => null);
        if (cached) {
            // Cache sofort liefern, Netzwerk-Update laeuft nebenher weiter.
            network.catch(()=>{});
            return stripRedirect(cached);
        }
        const fresh = await network;
        if (fresh) return fresh;
        const fallback = await caches.match('/');
        return fallback ? stripRedirect(fallback) : new Response('offline', { status: 503 });
    })());
});

// v1.21.1: Erlaubt der Seite, den Service Worker aktiv "SKIP_WAITING" zu
// schicken, sobald ein Update erkannt wurde -> siehe sw-update.js.
self.addEventListener('message', e => {
    if (e.data === 'SKIP_WAITING') self.skipWaiting();
});