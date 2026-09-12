/* schach.js — v1.82.0
 *
 * Grundgeruest des Schach-Moduls: Navigation, Reiter und Freigabe der Seite.
 * Daten holt hier noch nichts -- das Modul steht unter "In Arbeit", und die
 * leeren Zustaende in index.html sagen, warum noch nichts da ist.
 *
 * Wenn das Backend dazukommt, gehoert genau hierhin:
 *
 *   const API = {
 *       konten:  ()   => apiCall('/api/chess/accounts'),
 *       rating:  (qs) => apiCall('/api/chess/ratings' + qs),
 *       partien: (qs) => apiCall('/api/chess/games' + qs),
 *   };
 *
 * Zwei Dinge sind dabei schon entschieden und sollten so bleiben:
 *
 *   1. **Lichess und Chess.com bleiben getrennt.** Beide rechnen ihre
 *      Wertungszahl anders; eine gemeinsame Kurve waere eine Zahl, die es
 *      nirgends gibt. Zwei Reihen im selben Diagramm, je Plattform eine.
 *   2. **Partien werden abgeholt, nicht eingetippt.** Beide Plattformen geben
 *      sie oeffentlich heraus. Ein Eingabeformular fuer Partien waere Arbeit,
 *      die niemand macht, und ein Bestand, dem man nicht traut.
 */

const TABS = ['ueberblick', 'partien', 'konten'];

function activateTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.tab === tab));
    TABS.forEach(t => {
        const el = document.getElementById('tab-' + t);
        if (el) el.hidden = t !== tab;
    });
}

/* ------------------------------------------------------------------ Boot */

document.addEventListener('DOMContentLoaded', async () => {
    if (!isLoggedIn()) { location.href = '/private/login.html'; return; }
    // Freigabe direkt nach dem synchronen Login-Check: ab hier steht fest,
    // dass diese Seite bleibt. Haenge sie an eine Serverantwort, sieht man
    // bei einer haengenden Antwort nur den Seitenhintergrund.
    document.body.classList.add('ready');

    try {
        const me = await fetchMe();
        document.getElementById('userLabel').textContent = '👤 ' + me.username;
    } catch (e) { /* Name ist Beiwerk */ }

    document.getElementById('logoutBtn').addEventListener('click',
        () => { clearToken(); location.href = '/private/login.html'; });

    document.querySelectorAll('.tab-btn').forEach(b =>
        b.addEventListener('click', () => activateTab(b.dataset.tab)));
});
