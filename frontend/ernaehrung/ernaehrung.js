/* ernaehrung.js — v1.82.0
 *
 * Grundgeruest des Ernaehrungs-Moduls: Navigation, Reiter und Freigabe der
 * Seite. Daten holt hier noch nichts -- das Modul steht unter "In Arbeit",
 * und die leeren Zustaende in index.html sagen, warum noch nichts da ist.
 *
 * Wenn das Backend dazukommt, gehoert genau hierhin:
 *
 *   const API = {
 *       tag:       (d)  => apiCall('/api/food/day/' + d),
 *       gerichte:  ()   => apiCall('/api/food/dishes'),
 *       vorschlag: (qs) => apiCall('/api/food/suggestions' + qs),
 *       barcode:   (c)  => apiCall('/api/food/barcode/' + c),
 *   };
 *
 * Drei Entscheidungen stehen schon fest und tragen das ganze Modul:
 *
 *   1. **Zwei Mengenstufen, nicht Gramm.** Erfasst wird "normal" oder
 *      "uebermaessig". Gramm waeren genauer, aber nur, wenn jemand sie wiegt
 *      -- geschaetzte Gramm sind bloss eine Grobstufe mit falscher Stelle
 *      hinter dem Komma. Die Stufe gehoert deshalb ins Datenmodell, nicht in
 *      eine Umrechnung.
 *   2. **Vorschlaege kommen vor der Suche.** Gegessen wird sich wiederholend;
 *      wer dreimal taeglich durch eine Liste suchen muss, hoert nach einer
 *      Woche auf. Die Vorschlagsliste haengt an Wochentag und Uhrzeit.
 *   3. **Der Barcode fuellt nur vor.** Was aus einer fremden Datenbank kommt,
 *      bleibt aenderbar und als fremde Herkunft erkennbar -- Naehrwerte auf
 *      Packungen und in Datenbanken weichen regelmaessig voneinander ab.
 */

const TABS = ['heute', 'gerichte', 'scanner'];

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
