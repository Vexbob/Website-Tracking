// v1.33.0: SW-safe. Frueher stand hier ``window.VEXBOB_CONFIG = ...`` --
// im Service Worker existiert ``window`` aber nicht, dadurch warf ein
// ``importScripts('/js/config.js')`` sofort. Wir nutzen jetzt ``self``
// (in Window UND WorkerGlobalScope definiert) und guarden den preconnect-
// Injection-Teil, der nur im Browser-Tab laeuft.
self.VEXBOB_CONFIG = {
    API_BASE: 'https://vexbob-production.up.railway.app'
};
// Alias fuer Legacy-Aufrufer, die noch ``window.VEXBOB_CONFIG`` lesen.
if (typeof window !== 'undefined') {
    window.VEXBOB_CONFIG = self.VEXBOB_CONFIG;
}

// v1.21.1: preconnect zum Backend so frueh wie moeglich injizieren (config.js
// wird als erstes Script geladen). Baut DNS-Lookup + TLS-Handshake bereits
// waehrend die restliche Seite parst auf, statt erst beim ersten fetch() -
// spart typischerweise 100-300ms bei der ersten API-Antwort.
if (typeof document !== 'undefined') {
    try {
        const link = document.createElement('link');
        link.rel = 'preconnect';
        link.href = self.VEXBOB_CONFIG.API_BASE;
        link.crossOrigin = 'anonymous';
        document.head.appendChild(link);
    } catch (e) {}
}
