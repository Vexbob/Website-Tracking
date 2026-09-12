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
    gerichte: ()   => apiCall('/api/food/dishes'),
    gericht:  (d)  => apiCall('/api/food/dishes', { method: 'POST', body: d }),
    gerichtWeg: (id) => apiCall('/api/food/dishes/' + id, { method: 'DELETE' }),
    tag:      (d)  => apiCall('/api/food/day' + (d ? '?date=' + d : '')),
    eintragen:(d)  => apiCall('/api/food/log', { method: 'POST', body: d }),
    eintragWeg: (id) => apiCall('/api/food/log/' + id, { method: 'DELETE' }),
};

const TABS = ['heute', 'gerichte', 'scanner'];

const state = {
    bestand: [], vorschlag: null,
    tag: null, datum: null, gerichte: [],
    // Das Gericht, das gerade gebaut wird: {id, name, items:[{item_id, name, grams}]}
    entwurf: { id: null, name: '', items: [] },
};

const heute = () => new Date().toISOString().slice(0, 10);

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

/* ----------------------------------------------------------------- Tag
 *
 * Die Anzeige zeigt SPANNEN, keine Einzelwerte. Wer "Wraps, uebermaessig"
 * eintraegt, hat keine 612 kcal gegessen -- er hat irgendetwas zwischen
 * anderthalb und doppelt so viel wie eine Portion gegessen. Genau das steht
 * da: ein Balken mit Anfang und Ende, keine Scheibe eines Kreises.
 *
 * Das uebliche Halbkreis-Design der Ernaehrungs-Apps setzt eine genaue Zahl
 * und ein festes Ziel voraus. Beides gibt es hier nicht -- ein Ring, der zu
 * 73 % gefuellt ist, waere zwei Behauptungen auf einmal.
 */

const TAG_NAMEN = ['Sonntag', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag',
                   'Freitag', 'Samstag'];

const zahlKurz = (v) => Math.round(v).toLocaleString('de-DE');

function tagVerschieben(tage) {
    const d = new Date((state.datum || heute()) + 'T12:00:00');
    d.setDate(d.getDate() + tage);
    const neu = d.toISOString().slice(0, 10);
    // Nicht in die Zukunft: was morgen gegessen wird, weiss heute niemand.
    if (neu > heute()) return;
    ladeTag(neu);
}

function zeichneTagKopf() {
    const datum = state.datum || heute();
    const d = new Date(datum + 'T12:00:00');
    const istHeute = datum === heute();
    const gestern = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
    document.getElementById('ernTagName').textContent =
        istHeute ? 'Heute' : (datum === gestern ? 'Gestern' : TAG_NAMEN[d.getDay()]);
    document.getElementById('ernTagDatum').textContent =
        d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
    document.getElementById('ernTagVor').disabled = istHeute;
}

function zeichneSumme() {
    const t = state.tag;
    const kcal = t.totals.kcal;
    const anzahl = t.entries.length;
    document.getElementById('ernSumme').innerHTML = !anzahl
        ? `<div class="ern-summe-leer">Für diesen Tag ist noch nichts eingetragen.</div>`
        : `<div class="ern-summe-zahl">
               <span>${zahlKurz(kcal.min)}</span>
               <span class="ern-summe-bis">bis</span>
               <span>${zahlKurz(kcal.max)}</span>
               <span class="ern-summe-einheit">kcal</span>
           </div>
           <div class="ern-klein">geschätzt aus ${anzahl} ${anzahl === 1 ? 'Eintrag' : 'Einträgen'} — ${
               kcal.incomplete ? 'mindestens, es fehlen Angaben' : 'zwei Grobstufen ergeben eine Spanne, keine genaue Zahl'}</div>`;
}

/* Ein Band je Naehrwert: die Spur reicht bis zum Anderthalbfachen des
   Richtwerts, der Richtwert selbst steht als Strich darin. Gefuellt ist
   genau der Bereich zwischen der unteren und der oberen Schaetzung -- die
   Breite des Balkens IST die Unsicherheit. */
function band(makro, d) {
    const links = Math.min(100, (d.share_min / 1.5) * 100);
    const breite = Math.max(2, Math.min(100 - links, ((d.share_max - d.share_min) / 1.5) * 100));
    const einheit = makro === 'kcal' ? '' : ' g';
    return `<div class="ern-band${d.incomplete ? ' is-unvollstaendig' : ''}">
        <div class="ern-band-kopf">
            <span class="ern-band-lbl">${d.label}</span>
            <span class="ern-band-wert">${d.incomplete ? 'mind. ' : ''}${zahlKurz(d.min)}–${zahlKurz(d.max)}${einheit}</span>
        </div>
        <div class="ern-band-spur" role="img"
             aria-label="${d.label}: ${zahlKurz(d.min)} bis ${zahlKurz(d.max)}${einheit}, Richtwert ${zahlKurz(d.reference)}${einheit}">
            <span class="ern-band-marke" style="left:66.7%"></span>
            <span class="ern-band-fuell" style="left:${links.toFixed(1)}%;width:${breite.toFixed(1)}%"></span>
        </div>
        ${d.incomplete ? '<div class="ern-band-fuss">Eine Zutat macht dazu keine Angabe — der Wert ist mindestens so hoch.</div>' : ''}
    </div>`;
}

function zeichneBaender() {
    const t = state.tag;
    document.getElementById('ernBaender').innerHTML = t.entries.length
        ? t.macros.filter(m => m !== 'kcal').map(m => band(m, t.totals[m])).join('')
        : '';
    document.getElementById('ernMassstab').textContent = t.entries.length
        ? 'Der Strich im Balken ist der Richtwert für einen Tag. ' + t.reference_note
        : '';
}

function zeichneEintraege() {
    const t = state.tag;
    document.getElementById('ernEintraegeZahl').textContent =
        t.entries.length ? t.entries.length + ' an diesem Tag' : '';
    document.getElementById('ernEintraege').innerHTML = !t.entries.length
        ? `<div class="empty"><span class="empty-mark">🍽️</span>
             <p class="empty-text">Noch nichts eingetragen. Ein Tipp auf ein Gericht oben genügt —
             die Menge ist entweder normal oder übermäßig, mehr wird nicht gefragt.</p></div>`
        : t.entries.map(e => `
            <div class="v-row ern-zeile">
                <div class="ern-zeile-text">
                    <strong>${esc(e.name)}</strong>
                    <span class="ern-stufe is-${e.level}">${esc(e.level_label)}</span>
                    <div class="ern-klein">${esc(e.sub || '')}${
                        e.kcal_min != null ? ` · ${zahlKurz(e.kcal_min)}–${zahlKurz(e.kcal_max)} kcal` : ''}${
                        e.assumed_portion ? ' · Portion mit 100 g angenommen' : ''}</div>
                </div>
                <button type="button" class="v-btn v-btn--icon" data-eintrag="${e.id}"
                        aria-label="Eintrag entfernen" title="Entfernen">🗑️</button>
            </div>`).join('');
    document.querySelectorAll('[data-eintrag]').forEach(b =>
        b.addEventListener('click', () => eintragEntfernen(Number(b.dataset.eintrag))));
}

/* Schnelleintrag: je Gericht eine Zeile mit zwei Knoepfen. Ein Tipp, fertig --
   erst eine Auswahlliste zu oeffnen und dann die Menge zu waehlen, waere der
   Weg, den man nach einer Woche nicht mehr geht. */
function zeichneSchnell() {
    const ziel = document.getElementById('ernSchnell');
    const eigene = state.bestand.filter(p => p.portion_g);
    if (!state.gerichte.length && !eigene.length) {
        ziel.innerHTML = `<div class="empty"><span class="empty-mark">📖</span>
            <p class="empty-text">Noch nichts zum Eintragen da. Unter <strong>Gerichte</strong>
            stellst du aus deinem Bestand eines zusammen — danach steht es hier.</p></div>`;
        return;
    }
    const zeile = (name, sub, art, id) => `
        <div class="v-row ern-schnell">
            <div class="ern-zeile-text">
                <strong>${esc(name)}</strong>
                <div class="ern-klein">${esc(sub)}</div>
            </div>
            <div class="ern-schnell-tasten">
                <button type="button" class="v-btn v-btn--sm" data-art="${art}" data-id="${id}" data-stufe="normal">normal</button>
                <button type="button" class="v-btn v-btn--sm" data-art="${art}" data-id="${id}" data-stufe="viel">übermäßig</button>
            </div>
        </div>`;
    ziel.innerHTML = state.gerichte.map(g => zeile(
        g.name,
        g.portion.kcal != null ? `${zahlKurz(g.portion.kcal)} kcal je Portion` : 'Portion unvollständig',
        'dish', g.id)).join('')
        + eigene.slice(0, 8).map(p => zeile(
            p.name, `${p.portion_g} g je Portion`, 'item', p.id)).join('');
    ziel.querySelectorAll('[data-stufe]').forEach(b => b.addEventListener('click', () =>
        eintragen(b.dataset.art, Number(b.dataset.id), b.dataset.stufe, b)));
}

async function eintragen(art, id, stufe, knopf) {
    knopf.classList.add('is-loading');
    try {
        state.tag = await API.eintragen({
            [art === 'dish' ? 'dish_id' : 'item_id']: id,
            level: stufe, day: state.datum || heute(),
        });
        zeichneTag();
        melde('Eingetragen.', 'success');
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    } finally {
        knopf.classList.remove('is-loading');
    }
}

async function eintragEntfernen(id) {
    try {
        state.tag = await API.eintragWeg(id);
        zeichneTag();
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    }
}

function zeichneTag() {
    zeichneTagKopf();
    zeichneSumme();
    zeichneBaender();
    zeichneEintraege();
}

async function ladeTag(datum) {
    state.datum = datum || state.datum || heute();
    try {
        state.tag = await API.tag(state.datum);
    } catch (err) {
        melde(err.message || 'Der Tag konnte nicht geladen werden.', 'error');
        return;
    }
    zeichneTag();
}

/* ------------------------------------------------------------- Gerichte */

function zeichneEntwurf() {
    const e = state.entwurf;
    document.getElementById('ernGerichtTitel').textContent =
        e.id ? 'Gericht bearbeiten' : 'Neues Gericht';
    document.getElementById('ernGerichtNeu').hidden = !e.id;
    document.getElementById('ernZutaten').innerHTML = !e.items.length
        ? '<p class="ern-klein">Noch keine Zutat. Such unten etwas aus deinem Bestand.</p>'
        : e.items.map((z, i) => `
            <div class="v-row ern-zutat">
                <div class="ern-zeile-text"><strong>${esc(z.name)}</strong></div>
                <label class="ern-gramm">
                    <input type="number" min="0.25" step="0.25" value="${z.amount}" data-menge="${i}"
                           aria-label="Menge für ${esc(z.name)}">
                    <select class="v-select v-select--sm" data-einheit="${i}"
                            aria-label="Einheit für ${esc(z.name)}">
                        ${(z.units || [{ key: 'g', label: 'g' }]).map(u =>
                            `<option value="${u.key}"${u.key === z.unit ? ' selected' : ''}>${esc(u.label)}</option>`).join('')}
                    </select>
                </label>
                <button type="button" class="v-btn v-btn--icon" data-zutat-weg="${i}"
                        aria-label="Zutat entfernen" title="Entfernen">🗑️</button>
            </div>`).join('');
    document.querySelectorAll('[data-menge]').forEach(f => f.addEventListener('change', () => {
        const wert = Number(String(f.value).replace(',', '.'));
        if (wert > 0) state.entwurf.items[Number(f.dataset.menge)].amount = wert;
    }));
    document.querySelectorAll('[data-einheit]').forEach(f => f.addEventListener('change', () => {
        state.entwurf.items[Number(f.dataset.einheit)].unit = f.value;
    }));
    document.querySelectorAll('[data-zutat-weg]').forEach(b => b.addEventListener('click', () => {
        state.entwurf.items.splice(Number(b.dataset.zutatWeg), 1);
        zeichneEntwurf();
    }));
}

function zutatSuchen(text) {
    const ziel = document.getElementById('ernZutatTreffer');
    const begriff = text.trim().toLowerCase();
    if (!begriff) { ziel.innerHTML = ''; return; }
    const treffer = state.bestand.filter(p =>
        p.name.toLowerCase().includes(begriff)
        || (p.brand || '').toLowerCase().includes(begriff)).slice(0, 6);
    ziel.innerHTML = !treffer.length
        ? `<p class="ern-klein">Nichts im Bestand. Über den <strong>Scanner</strong> kommt es hinein.</p>`
        : treffer.map(p => `
            <button type="button" class="v-chip ern-zutat-treffer" data-zutat="${p.id}">
                ${esc(p.name)}${p.brand ? ' · ' + esc(p.brand) : ''}
            </button>`).join('');
    ziel.querySelectorAll('[data-zutat]').forEach(b => b.addEventListener('click', () => {
        const p = state.bestand.find(x => x.id === Number(b.dataset.zutat));
        if (!p) return;
        // Die eigene Einheit als Vorschlag, wenn es eine gibt: "1 Stueck"
        // trifft haeufiger als "62 g" und ist schneller zu pruefen.
        const eigene = (p.units || []).find(u => u.key === 'portion');
        state.entwurf.items.push({
            item_id: p.id, name: p.name,
            amount: eigene ? 1 : 100,
            unit: eigene ? 'portion' : (p.base_unit || 'g'),
            units: p.units || [{ key: p.base_unit || 'g', label: p.base_unit || 'g', grams: 1 }],
        });
        document.getElementById('ernZutatSuche').value = '';
        ziel.innerHTML = '';
        zeichneEntwurf();
    }));
}

async function gerichtSpeichern() {
    const name = document.getElementById('ernGerichtName').value.trim();
    if (!name) { melde('Das Gericht braucht einen Namen.', 'error'); return; }
    if (!state.entwurf.items.length) { melde('Mindestens eine Zutat.', 'error'); return; }
    const knopf = document.getElementById('ernGerichtSpeichern');
    knopf.classList.add('is-loading');
    try {
        const res = await API.gericht({
            id: state.entwurf.id, name,
            items: state.entwurf.items.map(z => ({
                item_id: z.item_id, amount: z.amount, unit: z.unit })),
        });
        state.gerichte = res.dishes;
        entwurfLeeren();
        zeichneGerichte();
        zeichneSchnell();
        melde('Gericht gespeichert.', 'success');
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    } finally {
        knopf.classList.remove('is-loading');
    }
}

function entwurfLeeren() {
    state.entwurf = { id: null, name: '', items: [] };
    document.getElementById('ernGerichtName').value = '';
    document.getElementById('ernZutatSuche').value = '';
    document.getElementById('ernZutatTreffer').innerHTML = '';
    zeichneEntwurf();
}

function gerichtBearbeiten(id) {
    const g = state.gerichte.find(x => x.id === id);
    if (!g) return;
    state.entwurf = {
        id: g.id, name: g.name,
        items: g.items.map(z => ({
            item_id: z.item_id, name: z.name,
            amount: z.amount, unit: z.unit, units: z.units })),
    };
    document.getElementById('ernGerichtName').value = g.name;
    zeichneEntwurf();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function gerichtLoeschen(id) {
    const g = state.gerichte.find(x => x.id === id);
    const ok = await askConfirm({
        title: 'Gericht löschen?',
        text: `„${g ? g.name : 'Das Gericht'}" verschwindet samt Rezept. Bereits eingetragene Tage verlieren diese Einträge.`,
        confirmText: 'Löschen', danger: true,
    });
    if (!ok) return;
    try {
        await API.gerichtWeg(id);
        await ladeGerichte();
        if (state.tag) await ladeTag(state.datum);
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    }
}

function zeichneGerichte() {
    const ziel = document.getElementById('ernGerichte');
    document.getElementById('ernGerichteZahl').textContent =
        state.gerichte.length ? state.gerichte.length + ' Gerichte' : '';
    ziel.innerHTML = !state.gerichte.length
        ? `<div class="empty"><span class="empty-mark">📖</span>
             <p class="empty-text">Noch keine Gerichte. Was du oft isst, legst du einmal an —
             danach reicht ein Tipp am Tag.</p></div>`
        : state.gerichte.map(g => `
            <div class="v-row ern-gericht">
                <div class="ern-zeile-text">
                    <strong>${esc(g.name)}</strong>
                    <div class="ern-klein">${g.items.map(z => {
                        const e = (z.units || []).find(u => u.key === z.unit);
                        return esc(z.name) + ' ' + z.amount + ' ' + esc(e ? e.label : z.unit);
                    }).join(' · ')}</div>
                    <div class="ern-klein">${g.portion.kcal != null
                        ? `${zahlKurz(g.portion.kcal)} kcal je Portion (${g.portion.grams} g)`
                        : 'Nährwerte unvollständig'}${g.portion.incomplete.length
                        ? ' · ohne Angabe: ' + g.portion.incomplete.length : ''}</div>
                </div>
                <div class="ern-schnell-tasten">
                    <button type="button" class="v-btn v-btn--sm" data-bearbeiten="${g.id}">Ändern</button>
                    <button type="button" class="v-btn v-btn--icon" data-gericht-weg="${g.id}"
                            aria-label="Gericht löschen" title="Löschen">🗑️</button>
                </div>
            </div>`).join('');
    ziel.querySelectorAll('[data-bearbeiten]').forEach(b =>
        b.addEventListener('click', () => gerichtBearbeiten(Number(b.dataset.bearbeiten))));
    ziel.querySelectorAll('[data-gericht-weg]').forEach(b =>
        b.addEventListener('click', () => gerichtLoeschen(Number(b.dataset.gerichtWeg))));
}

async function ladeGerichte() {
    try {
        const res = await API.gerichte();
        state.gerichte = res.dishes;
    } catch (e) {
        state.gerichte = [];
    }
    zeichneGerichte();
    zeichneSchnell();
}

/* ---------------------------------------------------------------- Kamera
 *
 * Zwei Wege, weil kein Browser beide hat:
 *
 *   1. ``BarcodeDetector`` steckt in Chrome und im Android-Browser fest
 *      eingebaut -- nichts nachzuladen, und es erkennt schneller.
 *   2. Safari kennt es nicht (Stand heute). Dort wird ZXing nachgeladen --
 *      erst dann, wenn es gebraucht wird: 300 KB beim Seitenaufruf fuer
 *      einen Knopf, den man selten drueckt, waeren verschenkt.
 *
 * Beide brauchen HTTPS. Auf einer Seite ueber http gibt der Browser die
 * Kamera gar nicht erst frei -- das sagt der Hinweis, statt es an einem
 * stummen Fehler scheitern zu lassen.
 */

const ZXING_CDN = 'https://cdn.jsdelivr.net/npm/@zxing/library@0.21.3/umd/index.min.js';
const FORMATE = ['ean_13', 'ean_8', 'upc_a', 'upc_e'];

const kamera = { stream: null, leser: null, laeuft: false };

function kameraHinweis(text) {
    const el = document.getElementById('ernKameraHinweis');
    if (el) el.textContent = text;
}

async function kameraStarten() {
    if (kamera.laeuft) { kameraStoppen(); return; }
    if (!window.isSecureContext) {
        melde('Die Kamera gibt der Browser nur über HTTPS frei.', 'error');
        return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        melde('Dieser Browser gibt keine Kamera frei.', 'error');
        return;
    }
    document.getElementById('ernKameraBereich').hidden = false;
    document.getElementById('ernKamera').textContent = '📷 Kamera schließen';
    kamera.laeuft = true;
    kameraHinweis('Kamera wird geöffnet …');
    try {
        if ('BarcodeDetector' in window) await mitBarcodeDetector();
        else await mitZXing();
    } catch (err) {
        kameraStoppen();
        // Der Browser sagt selbst, woran es lag (Erlaubnis verweigert, keine
        // Kamera da) -- das ist die bessere Meldung als eine eigene.
        melde(err && err.name === 'NotAllowedError'
            ? 'Der Zugriff auf die Kamera wurde abgelehnt.'
            : (err && err.message) || 'Die Kamera ließ sich nicht öffnen.', 'error');
    }
}

async function mitBarcodeDetector() {
    const video = document.getElementById('ernVideo');
    kamera.stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' } }, audio: false });
    video.srcObject = kamera.stream;
    await video.play();
    const detektor = new window.BarcodeDetector({ formats: FORMATE });
    kameraHinweis('Strichcode ins Bild halten');
    const takt = async () => {
        if (!kamera.laeuft) return;
        try {
            const treffer = await detektor.detect(video);
            if (treffer && treffer.length) return codeGefunden(treffer[0].rawValue);
        } catch (e) { /* einzelne Bilder duerfen misslingen */ }
        // Viermal je Sekunde reicht fuer einen Strichcode und laesst dem
        // Geraet Luft; jedes Bild zu pruefen heizt nur das Telefon.
        setTimeout(takt, 250);
    };
    takt();
}

function ladeZXing() {
    if (window.ZXing) return Promise.resolve(window.ZXing);
    return new Promise((fertig, fehler) => {
        const skript = document.createElement('script');
        skript.src = ZXING_CDN;
        skript.onload = () => fertig(window.ZXing);
        skript.onerror = () => fehler(new Error('Die Scanner-Bibliothek ließ sich nicht laden.'));
        document.head.appendChild(skript);
    });
}

async function mitZXing() {
    kameraHinweis('Scanner wird geladen …');
    const Z = await ladeZXing();
    if (!Z || !Z.BrowserMultiFormatReader) {
        throw new Error('Die Scanner-Bibliothek ließ sich nicht laden.');
    }
    const hinweise = new Map();
    hinweise.set(Z.DecodeHintType.POSSIBLE_FORMATS, [
        Z.BarcodeFormat.EAN_13, Z.BarcodeFormat.EAN_8,
        Z.BarcodeFormat.UPC_A, Z.BarcodeFormat.UPC_E]);
    kamera.leser = new Z.BrowserMultiFormatReader(hinweise, 300);
    kameraHinweis('Strichcode ins Bild halten');
    await kamera.leser.decodeFromVideoDevice(
        null, 'ernVideo', (ergebnis) => {
            if (ergebnis && kamera.laeuft) codeGefunden(ergebnis.getText());
        });
}

function codeGefunden(code) {
    const ziffern = String(code || '').replace(/\D/g, '');
    if (!ziffern) return;
    kameraStoppen();
    document.getElementById('ernBarcode').value = ziffern;
    // Direkt nachschlagen: wer gerade eine Packung vor die Kamera gehalten
    // hat, will das Ergebnis, nicht noch einen Knopf.
    nachschlagen();
}

function kameraStoppen() {
    kamera.laeuft = false;
    if (kamera.leser) {
        try { kamera.leser.reset(); } catch (e) {}
        kamera.leser = null;
    }
    if (kamera.stream) {
        kamera.stream.getTracks().forEach(spur => spur.stop());
        kamera.stream = null;
    }
    const video = document.getElementById('ernVideo');
    if (video) video.srcObject = null;
    document.getElementById('ernKameraBereich').hidden = true;
    document.getElementById('ernKamera').textContent = '📷 Kamera';
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

/* ------------------------------------------------- Anlegen und Aendern
 *
 * Dasselbe Formular fuer beides. Ein zweites Formular zum Bearbeiten waere
 * dieselbe Maske zweimal -- und zwei Stellen, an denen ein Feld fehlen kann.
 * Leere Felder bleiben leer: null heisst "keine Angabe" und ist etwas
 * anderes als 0.
 */

const FORM = {
    fName: 'name', fBrand: 'brand', fBase: 'base_unit',
    fKcal: 'kcal', fProtein: 'protein_g', fFiber: 'fiber_g',
    fCarbs: 'carbs_g', fFat: 'fat_g',
    fPortionLabel: 'portion_label', fPortion: 'portion_g', fPackage: 'package_g',
};
const ZAHLENFELDER = ['fKcal', 'fProtein', 'fFiber', 'fCarbs', 'fFat',
                      'fPortion', 'fPackage'];

let bearbeitet = null;   // id des Lebensmittels, das gerade geaendert wird

function formLeeren() {
    bearbeitet = null;
    Object.keys(FORM).forEach(id => {
        const feld = document.getElementById(id);
        if (feld) feld.value = id === 'fBase' ? 'g' : '';
    });
    document.getElementById('ernFormTitel').textContent = 'Von Hand anlegen';
    document.getElementById('fSpeichern').textContent = 'Aufnehmen';
    document.getElementById('fAbbrechen').hidden = true;
}

function formFuellen(p) {
    bearbeitet = p.id;
    Object.entries(FORM).forEach(([id, feld]) => {
        const el = document.getElementById(id);
        if (el) el.value = p[feld] == null ? '' : p[feld];
    });
    document.getElementById('fBase').value = p.base_unit || 'g';
    document.getElementById('ernFormTitel').textContent = 'Lebensmittel ändern';
    document.getElementById('fSpeichern').textContent = 'Änderung speichern';
    document.getElementById('fAbbrechen').hidden = false;
    activateTab('scanner');
    document.getElementById('ernFormTitel').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function formSpeichern() {
    const wert = (id) => {
        const roh = document.getElementById(id).value.trim();
        if (!roh) return null;
        return ZAHLENFELDER.includes(id) ? Number(roh.replace(',', '.')) : roh;
    };
    const daten = { source: 'eigen', user_edited: true };
    Object.entries(FORM).forEach(([id, feld]) => { daten[feld] = wert(id); });
    daten.base_unit = document.getElementById('fBase').value || 'g';
    if (!daten.name) { melde('Ohne Namen geht es nicht.', 'error'); return; }
    if (bearbeitet) daten.id = bearbeitet;

    const knopf = document.getElementById('fSpeichern');
    knopf.classList.add('is-loading');
    try {
        await API.aufnehmen(daten);
        formLeeren();
        await ladeBestand();
        await ladeGerichte();
        melde('Gespeichert.', 'success');
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    } finally {
        knopf.classList.remove('is-loading');
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
                    · ${zahl(p.fiber_g, ' g')} Ballaststoffe · je 100 ${esc(p.base_unit || 'g')}</div>
                <div class="ern-klein">${(p.units || []).map(e =>
                    e.grams === 1 ? esc(e.label) : `${esc(e.label)} = ${e.grams} ${esc(p.base_unit || 'g')}`
                ).join(' · ')}${p.user_edited ? ' · von Hand gepflegt' : ''}</div>
            </div>
            <div class="ern-schnell-tasten">
                <button type="button" class="v-btn v-btn--sm" data-aendern="${p.id}">Ändern</button>
                <button type="button" class="v-btn v-btn--icon" data-weg="${p.id}"
                        aria-label="Entfernen" title="Entfernen">🗑️</button>
            </div>
        </div>`).join('');
    ziel.querySelectorAll('[data-weg]').forEach(b =>
        b.addEventListener('click', () => entfernen(Number(b.dataset.weg))));
    ziel.querySelectorAll('[data-aendern]').forEach(b => b.addEventListener('click', () => {
        const p = state.bestand.find(x => x.id === Number(b.dataset.aendern));
        if (p) formFuellen(p);
    }));
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
    document.getElementById('ernKamera').addEventListener('click', kameraStarten);
    document.getElementById('ernKameraStop').addEventListener('click', kameraStoppen);
    // Beim Verlassen der Seite die Kamera freigeben -- sonst bleibt das
    // Lichtlein an, bis der Tab geschlossen wird.
    window.addEventListener('pagehide', kameraStoppen);
    let tippen = null;
    document.getElementById('ernSuche').addEventListener('input', (e) => {
        clearTimeout(tippen);
        const wert = e.target.value.trim();
        // Erst tippen lassen: Open Food Facts wird ehrenamtlich betrieben,
        // eine Abfrage je Tastenanschlag waere unhoeflich.
        tippen = setTimeout(() => suchen(wert), 400);
    });

    document.getElementById('ernTagZurueck').addEventListener('click', () => tagVerschieben(-1));
    document.getElementById('ernTagVor').addEventListener('click', () => tagVerschieben(1));
    document.getElementById('ernGerichtSpeichern').addEventListener('click', gerichtSpeichern);
    document.getElementById('ernGerichtNeu').addEventListener('click', entwurfLeeren);
    document.getElementById('ernZutatSuche').addEventListener('input',
        (e) => zutatSuchen(e.target.value));

    document.getElementById('fSpeichern').addEventListener('click', formSpeichern);
    document.getElementById('fAbbrechen').addEventListener('click', formLeeren);

    zeichneEntwurf();
    formLeeren();
    await ladeBestand();
    await ladeGerichte();
    await ladeTag(heute());
});
