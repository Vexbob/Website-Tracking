window.VEXBOB_CONFIG = {
    API_BASE: 'https://vexbob-production.up.railway.app'
};

// v1.21.1: preconnect zum Backend so frueh wie moeglich injizieren (config.js
// wird als erstes Script geladen). Baut DNS-Lookup + TLS-Handshake bereits
// waehrend die restliche Seite parst auf, statt erst beim ersten fetch() —
// spart typischerweise 100-300ms bei der ersten API-Antwort.
(function () {
    try {
        const link = document.createElement('link');
        link.rel = 'preconnect';
        link.href = window.VEXBOB_CONFIG.API_BASE;
        link.crossOrigin = 'anonymous';
        document.head.appendChild(link);
    } catch (e) {}
})();
