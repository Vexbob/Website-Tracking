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

               
self.addEventListener('install', e => {
    e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(()=>{}));
    self.skipWaiting();
});
self.addEventListener('activate', e => {
    e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))));
    self.clients.claim();
});
self.addEventListener('fetch', e => {
    const url = new URL(e.request.url);
    if (url.hostname.includes('railway.app') || url.pathname.startsWith('/api/') || url.pathname === '/token') return;
    if (e.request.method === 'GET' && url.origin === self.location.origin) {
        e.respondWith(caches.match(e.request).then(r => r || fetch(e.request).then(resp => {
            const clone = resp.clone();
            caches.open(CACHE).then(c => c.put(e.request, clone)).catch(()=>{});
            return resp;
        }).catch(() => caches.match('/'))));
    }
});