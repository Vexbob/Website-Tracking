/* ernaehrung.js — v1.85.0
 *
 * Das Ernaehrungs-Modul. Bisher gebaut: der Lebensmittel-Bestand und wie er
 * sich fuellt -- ueber den Strichcode oder die Textsuche bei Open Food Facts.
 * Gerichte und das Tagebuch folgen; die leeren Zustaende dort sagen, woran
 * es noch fehlt.
 *
 * Drei Entscheidungen, die das Modul tragen:
 *
 *   1. **Zwei Mengenstufen, nicht Gramm.** Erfasst wird spaeter "normal"
 *      oder "uebermaessig". Gramm waeren genauer, aber nur, wenn jemand
 *      wiegt -- geschaetzte Gramm sind eine Grobstufe mit falscher Stelle
 *      hinter dem Komma. ``portion_g`` am Lebensmittel ist die Bruecke von
 *      der Stufe zur Naehrwerttabelle.
 *   2. **Fremde Daten bleiben fremd.** Was von Open Food Facts kommt, ist
 *      ein Vorschlag: aenderbar, als Herkunft erkennbar, und fehlende
 *      Angaben bleiben leer. Eine 0 bei Ballaststoffen liefe in jeder
 *      Tagessumme mit, ohne zu stimmen.
 *   3. **Der eigene Bestand geht vor.** Derselbe Artikel zum zweiten Mal
 *      gescannt zeigt die eigenen, vielleicht korrigierten Werte.
 */

const API = {
    barcode:  (c)  => apiCall('/api/food/barcode/' + encodeURIComponent(c)),
    suche:    (q)  => apiCall('/api/food/search?q=' + encodeURIComponent(q)),
    bestand:  ()   => apiCall('/api/food/items'),
    aufnehmen:(d)  => apiCall('/api/food/items', { method: 'POST', body: d }),
    entfernen:(id) => apiCall('/api/food/items/' + id, { method: 'DELETE' }),
};

const TABS = ['heute', 'gerichte', 'scanner'];

const state = { bestand: [], vorschlag: null };

const esc = (v) => String(v == null ? '' : v)
    .replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const melde = (text, art) => { if (window.Toast) Toast[art || 'info'](text); };

// Naehrwerte in der Reihenfolge, in der sie gelesen werden. "fehlt" ist ein
// eigener Zustand -- nicht 0.
const WERTE = [
    { key: 'kcal',      label: 'kcal',          einheit: '' },
    { key: 'protein_g', label: 'Eiweiß',        einheit: ' g' },
    { key: 'fiber_g',   label: 'Ballaststoffe', einheit: ' g' },
    { key: 'carbs_g',   label: 'Kohlenhydrate', einheit: ' g' },
    { key: 'fat_g',     label: 'Fett',          einheit: ' g' },
];

const zahl = (v, einheit) => v == null
    ? '<span class="ern-fehlt">keine Angabe</span>'
    : v.toLocaleString('de-DE', { maximumFractionDigits: 1 }) + einheit;

function naehrwertZeile(p) {
    return `<div class="ern-werte">${WERTE.map(w => `
        <div class="ern-wert">
            <div class="ern-wert-lbl">${w.label}</div>
            <div class="ern-wert-num">${zahl(p[w.key], w.einheit)}</div>
        </div>`).join('')}</div>
        <p class="ern-klein">je 100 g${p.portion_g ? ` · übliche Portion ${p.portion_g} g` : ''}</p>`;
}

function zeichneTreffer(ziel, produkt, bekannt, notiz) {
    state.vorschlag = produkt;
    const el = document.getElementById(ziel);
    if (!produkt && bekannt) {
        el.innerHTML = `<div class="v-row ern-treffer">
            <div class="ern-kopf"><strong>${esc(bekannt.name)}</strong>
                <span class="ern-herkunft">schon im Bestand</span></div>
            ${naehrwertZeile(bekannt)}
            ${notiz ? `<p class="ern-klein">${esc(notiz)}</p>` : ''}
        </div>`;
        return;
    }
    if (!produkt) { el.innerHTML = ''; return; }
    el.innerHTML = `<div class="v-row ern-treffer">
        <div class="ern-kopf">
            <strong>${esc(produkt.name)}</strong>
            ${produkt.brand ? `<span class="ern-marke">${esc(produkt.brand)}</span>` : ''}
            <span class="ern-herkunft">Open Food Facts</span>
        </div>
        ${naehrwertZeile(produkt)}
        ${bekannt ? '<p class="ern-klein">Dieses Lebensmittel ist bereits im Bestand — Übernehmen aktualisiert die Werte.</p>' : ''}
        ${produkt.missing && produkt.missing.length
            ? `<p class="ern-klein">Dort fehlen: ${produkt.missing.length} Angabe(n). Du kannst sie nach dem Übernehmen von der Packung nachtragen.</p>`
            : ''}
        <div class="ern-tasten">
            <button type="button" class="v-btn v-btn--primary" id="ernUebernehmen">In den Bestand</button>
        </div>
    </div>`;
    const knopf = document.getElementById('ernUebernehmen');
    if (knopf) knopf.addEventListener('click', () => uebernehmen(produkt));
}

async function nachschlagen(e) {
    if (e) e.preventDefault();
    const code = document.getElementById('ernBarcode').value.trim();
    if (!code) return;
    document.getElementById('ernTreffer').innerHTML = '<span class="skel skel-block"></span>';
    try {
        const res = await API.barcode(code);
        zeichneTreffer('ernTreffer', res.found ? res.product : null,
                       res.known, res.note);
    } catch (err) {
        document.getElementById('ernTreffer').innerHTML =
            `<div class="empty"><span class="empty-mark">🔎</span>
             <p class="empty-text">${esc(err.message || 'Nicht gefunden.')}</p></div>`;
    }
}

async function suchen(text) {
    const ziel = document.getElementById('ernSuchTreffer');
    if (text.length < 2) { ziel.innerHTML = ''; return; }
    ziel.innerHTML = '<span class="skel skel-block"></span>';
    try {
        const res = await API.suche(text);
        if (!res.results.length) {
            ziel.innerHTML = `<div class="empty"><span class="empty-mark">🔎</span>
                <p class="empty-text">Nichts gefunden. Bei Losem ohne Strichcode lohnt sich
                oft ein allgemeinerer Begriff — „Apfel" statt „Apfel Elstar".</p></div>`;
            return;
        }
        ziel.innerHTML = res.results.map((p, i) => `
            <div class="v-row ern-treffer">
                <div class="ern-kopf"><strong>${esc(p.name)}</strong>
                    ${p.brand ? `<span class="ern-marke">${esc(p.brand)}</span>` : ''}</div>
                <p class="ern-klein">${zahl(p.kcal, '')} kcal · ${zahl(p.protein_g, ' g')} Eiweiß
                    · ${zahl(p.fiber_g, ' g')} Ballaststoffe</p>
                <div class="ern-tasten">
                    <button type="button" class="v-btn v-btn--sm" data-treffer="${i}">In den Bestand</button>
                </div>
            </div>`).join('');
        ziel.querySelectorAll('[data-treffer]').forEach(b =>
            b.addEventListener('click', () => uebernehmen(res.results[Number(b.dataset.treffer)])));
    } catch (err) {
        ziel.innerHTML = `<div class="empty is-error"><span class="empty-mark">⚠️</span>
            <p class="empty-text">${esc(err.message || 'Die Suche ging nicht.')}</p></div>`;
    }
}

async function uebernehmen(produkt) {
    try {
        await API.aufnehmen({
            name: produkt.name, brand: produkt.brand, barcode: produkt.barcode,
            source: 'off', kcal: produkt.kcal, protein_g: produkt.protein_g,
            carbs_g: produkt.carbs_g, sugar_g: produkt.sugar_g,
            fat_g: produkt.fat_g, sat_fat_g: produkt.sat_fat_g,
            fiber_g: produkt.fiber_g, salt_g: produkt.salt_g,
            portion_g: produkt.portion_g,
        });
        await ladeBestand();
        melde('In den Bestand aufgenommen.', 'success');
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    }
}

async function ladeBestand() {
    const ziel = document.getElementById('ernBestand');
    try {
        const res = await API.bestand();
        state.bestand = res.items;
    } catch (err) {
        ziel.innerHTML = `<div class="empty is-error"><span class="empty-mark">⚠️</span>
            <p class="empty-text">Der Bestand konnte nicht geladen werden.</p></div>`;
        return;
    }
    document.getElementById('ernBestandZahl').textContent =
        state.bestand.length ? state.bestand.length + ' Lebensmittel' : '';
    if (!state.bestand.length) {
        ziel.innerHTML = `<div class="empty"><span class="empty-mark">🥫</span>
            <p class="empty-text">Noch nichts aufgenommen. Was einmal hier steht, bleibt —
            auch wenn Open Food Facts den Eintrag später ändert.</p></div>`;
        return;
    }
    ziel.innerHTML = state.bestand.map(p => `
        <div class="v-row ern-zeile">
            <div class="ern-zeile-text">
                <strong>${esc(p.name)}</strong>
                ${p.brand ? `<span class="ern-marke">${esc(p.brand)}</span>` : ''}
                <div class="ern-klein">${zahl(p.kcal, '')} kcal · ${zahl(p.protein_g, ' g')} Eiweiß
                    · ${zahl(p.fiber_g, ' g')} Ballaststoffe · je 100 g</div>
            </div>
            <button type="button" class="v-btn v-btn--icon" data-weg="${p.id}"
                    aria-label="Entfernen" title="Entfernen">🗑️</button>
        </div>`).join('');
    ziel.querySelectorAll('[data-weg]').forEach(b =>
        b.addEventListener('click', () => entfernen(Number(b.dataset.weg))));
}

async function entfernen(id) {
    const p = state.bestand.find(x => x.id === id);
    const ok = await askConfirm({
        title: 'Entfernen?',
        text: `„${p ? p.name : 'Das Lebensmittel'}" wird aus dem Bestand gelöscht.`,
        confirmText: 'Entfernen', danger: true,
    });
    if (!ok) return;
    try {
        await API.entfernen(id);
        await ladeBestand();
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    }
}

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

    document.getElementById('ernScanForm').addEventListener('submit', nachschlagen);
    let tippen = null;
    document.getElementById('ernSuche').addEventListener('input', (e) => {
        clearTimeout(tippen);
        const wert = e.target.value.trim();
        // Erst tippen lassen: Open Food Facts wird ehrenamtlich betrieben,
        // eine Abfrage je Tastenanschlag waere unhoeflich.
        tippen = setTimeout(() => suchen(wert), 400);
    });

    await ladeBestand();
});
