/* sw-update.js — v1.21.1
 * Registriert den Service Worker und sorgt dafuer, dass ein neu erkanntes
 * Update SOFORT aktiv wird und die Seite automatisch neu laedt — der User
 * muss nie mehr manuell den Browser-Cache loeschen.
 *
 * Ablauf:
 * 1. register('/sw.js') wie bisher.
 * 2. Bei 'updatefound': sobald der neue Worker 'installed' ist (und es
 *    bereits einen aktiven Worker gab, also KEIN Erst-Install), schicken wir
 *    ihm 'SKIP_WAITING' — der wartet sonst standardmaessig, bis alle Tabs zu
 *    sind.
 * 3. Bei 'controllerchange' (der neue Worker hat uebernommen) laden wir die
 *    Seite einmalig neu, damit alle JS-Dateien frisch vom (jetzt aktiven)
 *    Worker kommen.
 * 4. registration.update() wird zusaetzlich bei jedem Tab-Fokus aufgerufen,
 *    damit auch lang offene Tabs zuverlaessig auf neue Versionen pruefen.
 *
 * Einbindung: <script src="/js/sw-update.js"></script> ersetzt die bisherigen
 * einzelnen `navigator.serviceWorker.register('/sw.js')`-Aufrufe.
 */
(function () {
    if (!('serviceWorker' in navigator)) return;

    let refreshing = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
        if (refreshing) return;
        refreshing = true;
        location.reload();
    });

    navigator.serviceWorker.register('/sw.js').then(reg => {
        // Falls schon ein Update im Hintergrund wartet (z.B. Tab war beim
        // letzten Deploy offen), sofort aktivieren.
        if (reg.waiting) reg.waiting.postMessage('SKIP_WAITING');

        reg.addEventListener('updatefound', () => {
            const installing = reg.installing;
            if (!installing) return;
            installing.addEventListener('statechange', () => {
                if (installing.state === 'installed' && navigator.serviceWorker.controller) {
                    // Es gab schon einen aktiven Worker -> echtes Update, nicht Erst-Install.
                    installing.postMessage('SKIP_WAITING');
                }
            });
        });

        // Bei Rueckkehr in den Tab (z.B. PWA aus dem Hintergrund) auf Updates pruefen.
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') reg.update().catch(() => {});
        });
    }).catch(() => {});
})();
