/* cs2.js — der CS2-Bestand.
 *
 * Drei Reiter, eine Frage je Reiter:
 *   Bestand     was ist da, was waere es wert, und wie alt sind die Preise
 *   Verlauf     wie hat sich das entwickelt
 *   Verwaltung  einen Bestand aus einer Datei uebernehmen
 *
 * Vier Regeln, die das Modul durchhaelt:
 *
 * 1. **Gerechnet und sortiert wird im Server.** Die Kopfzahlen kommen aus
 *    /overview mit denselben Filterwerten wie die Liste, nicht aus den
 *    geladenen Zeilen. Und die Tabelle sortiert nicht das, was gerade da
 *    ist: bei 1000 Zeilen Obergrenze stuende oben sonst nicht das Groesste,
 *    sondern das Groesste der geladenen Haelfte.
 *
 * 2. **Ein gescheiterter Abruf ist kein leerer Bestand.** Jede Ladefunktion
 *    schreibt ihren Fehler DORTHIN, wo die Daten stuenden, mit dem Weg
 *    zurueck daneben -- nie in eine leere Liste und nie nur in einen Toast,
 *    der nach Sekunden weg ist.
 *
 * 3. **Was man aendert, aendert man an Ort und Stelle.** Anzahl und Preis
 *    sind Felder in der Zeile, kein Dialog. Der Preis geht dabei ueber
 *    ``PUT .../preis`` und bewegt damit den Preisstand -- "nachgesehen,
 *    stimmt noch" ist die haeufigste Auskunft bei Handpflege. Deshalb
 *    braucht es keine eigene Pflegeseite mehr: die Arbeit findet dort statt,
 *    wo die Zahl steht.
 *
 * 4. **Kein eigener Dialog, kein eigener Zeitraum, kein eigener Export.**
 *    VexModal, VexRange und der Gesamt-Export der Seite sind da.
 */
'use strict';

const API = {
    katalog:   ()            => apiCall('/api/cs2/catalog'),
    ueberblick:(q)           => apiCall('/api/cs2/overview' + q),
    liste:     (q)           => apiCall('/api/cs2/positions' + q),
    anlegen:   (b)           => apiCall('/api/cs2/positions', { method: 'POST', body: b }),
    aendern:   (id, b)       => apiCall('/api/cs2/positions/' + id, { method: 'PATCH', body: b }),
    preis:     (id, p)       => apiCall('/api/cs2/positions/' + id + '/preis',
                                        { method: 'PUT', body: { price_eur: p } }),
    entfernen: (id)          => apiCall('/api/cs2/positions/' + id, { method: 'DELETE' }),
    staende:   (tage)        => apiCall('/api/cs2/snapshots?tage=' + tage),
    festhalten:()            => apiCall('/api/cs2/snapshots', { method: 'POST', body: {} }),
    einlesen:  (daten, tun)  => apiCall('/api/cs2/import',
                                        { method: 'POST', body: { daten, uebernehmen: !!tun } }),
};

/* Die langen Namen der Abnutzung, fuer den Tooltip am Tag. Gefuellt aus dem
   Katalog, damit die Liste nur an einer Stelle steht (cs2_rechnung.py). */
const WEAR_LANG = {};

const state = {
    katalog: null,
    filter: { suche: '', kategorien: [], faellig: false },
    sortierung: 'wert',
    richtung: 'ab',
    tage: 365,
    chart: null,
    zeilen: [],
};

/* Die Spalten der Tabelle. ``zahl`` sagt, ob sie rechtsbuendig steht, und
   ``abwaerts`` welche Richtung beim ersten Klick gemeint ist: bei Geld und
   Mengen will man das Groesste zuerst, bei Namen das A. */
const SPALTEN = {
    name:  { abwaerts: false },
    preis: { abwaerts: true },
    wert:  { abwaerts: true },
    menge: { abwaerts: true },
    typ:   { abwaerts: false },
    alter: { abwaerts: false },   // aelteste zuerst -- das ist die offene Arbeit
};

/* Ein Zeichen je Art von Gegenstand. Bewusst hier und nicht in
   ``/js/ikon.js``: das sind die Zeichen dieses Moduls, so wie
   ``nav-switcher.js`` seine Modulzeichen bei sich fuehrt -- ein Kistensymbol
   hat in einem Rezeptmodul nichts zu suchen.

   Dieselbe Zeichenart wie ueberall in Vexbob: 24er-Raster, nur Linien,
   Strichstaerke 1.7. Keine Emoji -- ein Emoji ist auf jedem Geraet eine
   andere Zeichnung, in einer Farbe, die niemand gewaehlt hat, und faellt
   dort, wo die Schrift es nicht kennt, auf einen leeren Kasten zurueck.

   Gesucht wird ueber den kleingeschriebenen Kategorienamen; wer eine
   Kategorie umbenennt, bekommt das Ersatzzeichen und keine Luecke. Die
   deutschen Zweitnamen stehen dabei, weil die Kategorien umbenennbar sind. */
const TYP_ZEICHEN = {
    skin:              '<path d="M3 8.5h11.5l2 2.5H21v2.5h-3.5l-2 2.5h-2L12 21H8.5l1.5-5H5'
                     + 'a2 2 0 0 1-2-2z"/><path d="M10.5 13.5h4"/>',
    case:              '<rect x="3" y="6.5" width="18" height="13" rx="2"/>'
                     + '<path d="M3 11h18"/><path d="M10.5 11v2.5h3V11"/>',
    container:         '<path d="M12 3.2l8.2 4.4v8.8L12 20.8 3.8 16.4V7.6z"/>'
                     + '<path d="M3.8 7.6L12 12l8.2-4.4M12 12v8.8"/>',
    sticker:           '<path d="M4.5 5.5a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v8.5l-5.5 5.5h-7.5'
                     + 'a2 2 0 0 1-2-2z"/><path d="M19.5 14h-3.5a2 2 0 0 0-2 2v3.5"/>',
    'sticker capsule': '<rect x="7" y="3.5" width="10" height="17" rx="5"/><path d="M7 12h10"/>',
    agent:             '<circle cx="12" cy="8" r="3.5"/>'
                     + '<path d="M5 20c0-3.5 3.1-5.5 7-5.5s7 2 7 5.5"/>',
    'music kit':       '<path d="M9 18V5.5l10-2V16"/>'
                     + '<ellipse cx="6.5" cy="18" rx="2.5" ry="2.2"/>'
                     + '<ellipse cx="16.5" cy="16" rx="2.5" ry="2.2"/>',
    graffiti:          '<rect x="7.5" y="8.5" width="7" height="12" rx="1.2"/>'
                     + '<path d="M9.5 8.5V6h3v2.5"/><circle cx="17.5" cy="4.5" r=".9"/>'
                     + '<circle cx="20" cy="7" r=".9"/><circle cx="17.5" cy="9.5" r=".9"/>',
    patch:             '<path d="M12 3.2l7 2.8v5.6c0 4.2-2.9 7.6-7 9.2-4.1-1.6-7-5-7-9.2V6z"/>',
    charm:             '<circle cx="12" cy="5.5" r="2.5"/><path d="M12 8v2"/>'
                     + '<path d="M12 10l5 4-5 6-5-6z"/>',
    collectible:       '<circle cx="12" cy="15" r="5.2"/>'
                     + '<path d="M8.6 10.9L6 3.2h12l-2.6 7.7"/><path d="M12 3.2v3.8"/>',
    // Ohne Treffer: ein Anhaenger. Er sagt „irgendein Gegenstand“ und nicht
    // „hier fehlt etwas“.
    '': '<path d="M12.5 3.5H20v7.5l-8.8 8.8a1.6 1.6 0 0 1-2.3 0l-5.2-5.2a1.6 1.6 0 0 1 0-2.3z"/>'
      + '<circle cx="16.5" cy="7" r="1.1"/>',
};

/* Deutsche Zweitnamen: die Kategorien lassen sich umbenennen. */
const TYP_ZWEITNAMEN = {
    kiste: 'case', kisten: 'case', waffe: 'skin', waffen: 'skin',
    aufkleber: 'sticker', kapsel: 'sticker capsule', anhänger: 'charm',
    behälter: 'container', sammlerstück: 'collectible', aufnäher: 'patch',
};

function typZeichen(name) {
    const k = String(name || '').trim().toLowerCase();
    const pfad = TYP_ZEICHEN[k] || TYP_ZEICHEN[TYP_ZWEITNAMEN[k]] || TYP_ZEICHEN[''];
    return `<svg viewBox="0 0 24 24" width="20" height="20" fill="none"
        stroke="currentColor" stroke-width="1.7" stroke-linecap="round"
        stroke-linejoin="round" aria-hidden="true">${pfad}</svg>`;
}

/* ---------------------------------------------------------------- Werkzeug */

const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const eur = (v) => (v == null ? '–'
    : Number(v).toLocaleString('de-DE', { style: 'currency', currency: 'EUR' }));

const zahl = (v) => Number(v || 0).toLocaleString('de-DE');

/* Ein Preis, wie man ihn eintippt: zwei Nachkommastellen, Komma, kein Euro.
   Nicht ``eur()`` -- das Zeichen im Feld stuende in der Eingabe mit drin. */
const preisFeld = (v) => (v == null ? '' : Number(v).toFixed(2).replace('.', ','));

const tagDatum = (iso) => {
    if (!iso) return '';
    try { return new Date(iso).toLocaleDateString('de-DE',
        { day: '2-digit', month: 'short', year: 'numeric' }); } catch (e) { return iso; }
};

const cssVar = (name) => getComputedStyle(document.documentElement)
    .getPropertyValue(name).trim();

/* Der Modulton folgt der Einstellung „Zahlen und Diagramme“; ohne sie bleibt
   es die Modul-Identitaet. Kein Hex in dieser Datei. */
const ton = () => cssVar('--figure') || cssVar('--m-cs2');

const melde = (art, text) => { if (window.Toast) Toast[art](text); };

/* Ein Fehler steht dort, wo die Daten stuenden -- und nimmt den Weg zurueck
   mit. Ein Toast allein reicht nicht: er ist nach Sekunden weg, der falsche
   Leerzustand bleibt. */
function zeigeFehler(el, text, nochmal) {
    if (!el) return;
    el.innerHTML = `<div class="empty is-error">
        <span class="empty-mark" aria-hidden="true">⚠️</span>
        <p class="empty-text">${esc(text)}</p>
        <button type="button" class="v-btn v-btn--sm" data-nochmal="1">Erneut versuchen</button>
    </div>`;
    const knopf = el.querySelector('[data-nochmal]');
    if (knopf) knopf.addEventListener('click', nochmal);
}

function zeigeLeer(el, text, handlung) {
    el.innerHTML = `<div class="empty">
        <span class="empty-mark" aria-hidden="true">📦</span>
        <p class="empty-text">${esc(text)}</p>
        ${handlung ? `<button type="button" class="v-btn v-btn--sm" data-handlung="1">${esc(handlung.text)}</button>` : ''}
    </div>`;
    if (handlung) {
        const k = el.querySelector('[data-handlung]');
        if (k) k.addEventListener('click', handlung.tun);
    }
}

function frageKette() {
    const f = state.filter;
    const teile = [];
    if (f.suche) teile.push('suche=' + encodeURIComponent(f.suche));
    if (f.kategorien.length) teile.push('kategorien=' + f.kategorien.join(','));
    if (f.faellig) teile.push('nur_faellig=true');
    return teile;
}

/* ------------------------------------------------------------------ Reiter */

const REITER = ['bestand', 'verlauf', 'verwaltung'];

function zeigeReiter(name, still) {
    if (!REITER.includes(name)) name = REITER[0];
    REITER.forEach((r) => {
        const feld = document.getElementById('tab-' + r);
        if (feld) feld.hidden = (r !== name);
    });
    document.querySelectorAll('.tab-btn').forEach((b) => {
        b.classList.toggle('active', b.dataset.tab === name);
    });
    if (!still) location.hash = name;
    if (name === 'verlauf') ladeVerlauf();
}

/* ----------------------------------------------------------------- Bestand */

async function ladeBestand() {
    const listeEl = document.getElementById('csListe');
    const q = frageKette();
    try {
        const [ueber, liste] = await Promise.all([
            API.ueberblick('?' + q.concat('tage=' + state.tage).join('&')),
            API.liste('?' + q.concat('sortierung=' + state.sortierung,
                                     'richtung=' + state.richtung).join('&')),
        ]);
        zeichneKpi(ueber);
        zeichneAufteilung(ueber);
        zeichneListe(liste);
    } catch (e) {
        listeEl.innerHTML = '';
        document.getElementById('csTabelle').hidden = true;
        zeigeFehler(document.getElementById('csListeLeer'),
                    'Der Bestand konnte nicht geladen werden: ' + e.message, ladeBestand);
        zeigeFehler(document.getElementById('csAufteilung'),
                    'Auch die Aufteilung fehlt dadurch.', ladeBestand);
    }
}

function zeichneKpi(u) {
    const b = u.bestand;
    const v = u.veraenderung;
    const pfeil = v && v.brutto > 0 ? '▲' : (v && v.brutto < 0 ? '▼' : '±');
    // Hoch ist hier gut: mehr Wert. Deshalb --ok beim Plus, nicht --danger.
    const richtung = v && v.brutto > 0 ? 'down' : (v && v.brutto < 0 ? 'up' : 'neutral');
    const kacheln = [
        {
            label: 'Bestand brutto', wert: eur(b.brutto),
            sub: v ? `<span class="stat-kpi-delta ${richtung}">${pfeil} ${eur(Math.abs(v.brutto))}</span>
                      seit ${esc(tagDatum(v.seit))}`
                   : 'noch kein früherer Stand zum Vergleich',
        },
        {
            label: 'Nach Gebühr', wert: eur(b.netto),
            sub: `geschätzter Erlös, abzüglich ${Math.round((state.katalog?.gebuehr || 0.15) * 100)} % Gebühr`,
        },
        {
            label: 'Itemanzahl', wert: zahl(b.stueck),
            sub: b.positionen
                ? `Einzelstücke · Ø ${zahl(Math.round(b.stueck / b.positionen))} je Position`
                : 'Einzelstücke',
        },
        {
            // ``zeilen``, nicht ``positionen``: dieselbe Menge, die unten in
            // der Tabelle steht. ``positionen`` waere nur, was einen Wert
            // beitraegt -- eine andere Frage, und daneben steht ihre Antwort.
            label: 'Positionen', wert: zahl(b.zeilen),
            sub: [b.unvollstaendig ? `${zahl(b.unvollstaendig)} unvollständig` : '',
                  b.veraltet ? `${zahl(b.veraltet)} überfällig` : '']
                 .filter(Boolean).join(' · ') || 'alle vollständig und aktuell',
        },
    ];
    document.getElementById('csKpi').innerHTML = kacheln.map((k) => `
        <div class="stat-kpi">
            <div class="stat-kpi-label">${esc(k.label)}</div>
            <div class="stat-kpi-value">${esc(k.wert)}</div>
            <div class="stat-kpi-sub">${k.sub}</div>
        </div>`).join('');
}

function zeichneAufteilung(u) {
    const el = document.getElementById('csAufteilung');
    const daten = u.je_kategorie;
    if (!daten.length) {
        zeigeLeer(el, 'Noch nichts im Bestand, das sich aufteilen ließe.');
        return;
    }
    const groesste = daten[0].brutto || 1;
    const gesamt = daten.reduce((s, z) => s + z.brutto, 0) || 1;
    const zeilen = daten.slice(0, 8);
    el.innerHTML = `<div class="rank-list">${zeilen.map((z, i) => `
        <div class="rank-row" style="--tone:var(--cs2-ton)">
            <span class="rank-mark">${i + 1}</span>
            <span class="rank-name">${esc(z.name)}</span>
            <span class="rank-val">${esc(eur(z.brutto))}</span>
            <span class="rank-bar"><i style="width:${Math.max(2, (z.brutto / groesste) * 100).toFixed(1)}%"></i></span>
            <span class="rank-sub">${(z.brutto / gesamt * 100).toFixed(1).replace('.', ',')} % des Bestands</span>
        </div>`).join('')}</div>
        ${daten.length > zeilen.length
            ? `<div class="rank-rest">Top ${zeilen.length} · ${esc(eur(daten.slice(zeilen.length)
                  .reduce((s, z) => s + z.brutto, 0)))} übrige</div>` : ''}`;
}

/* ------------------------------------------------------------ Die Tabelle */

function markeFuer(p) {
    const stufe = { frisch: 'cs-frisch', alt: 'cs-alt', sehr_alt: 'cs-sehr-alt', ohne: 'cs-ohne' };
    return stufe[p.frische] || 'cs-frisch';
}

function alterText(p) {
    if (p.alter_tage == null) return 'nie bepreist';
    if (p.alter_tage === 0) return 'heute';
    if (p.alter_tage === 1) return 'gestern';
    return `vor ${zahl(p.alter_tage)} Tagen`;
}

/* Der Punkt neben dem Namen. Er erscheint, sobald ein Preis aelter ist als
   die Frist aus dem Katalog (30 Tage) -- gelb dafuer, rot ab der doppelten
   Frist, und grau, wenn nie ein Preis dastand. Das ist ausdruecklich eine
   eigene Stufe: kein Preis ist kein alter Preis.

   Frische Zeilen bekommen KEINEN Punkt. Ein Zeichen, das an jeder Zeile
   steht, sagt nichts mehr aus; es soll die Ausnahme markieren. */
function punktHtml(p) {
    if (p.frische === 'frisch') return '';
    const wort = {
        alt: `Preis ist ${p.alter_tage} Tage alt`,
        sehr_alt: `Preis ist ${p.alter_tage} Tage alt`,
        ohne: 'Für diese Position steht noch kein Preis',
    }[p.frische] || '';
    return `<span class="cs-punkt" role="img" aria-label="${esc(wort)}" title="${esc(wort)}"></span>`;
}

function zeileHtml(p) {
    // StatTrak zuerst, dann die Abnutzung -- dieselbe Reihenfolge, in der sie
    // im Marktnamen stehen: „StatTrak™ AK-47 | Ice Coaled (Minimal Wear)“.
    const marken = [
        p.stattrak ? '<span class="cs-tag cs-tag--st">StatTrak™</span>' : '',
        p.wear ? `<span class="cs-tag cs-tag--wear" title="${esc(WEAR_LANG[p.wear] || p.wear)}">${esc(p.wear)}</span>` : '',
    ].filter(Boolean).join(' ');
    return `<tr class="${markeFuer(p)}${p.unvollstaendig ? ' cs-unvollstaendig' : ''}"
                data-zeile="${p.id}">
        <td class="cs-sp-name">
            <button type="button" class="cs-name" data-kopieren="${esc(p.markt_name)}"
                    title="Anklicken kopiert „${esc(p.markt_name)}“">
                ${punktHtml(p)}<span class="cs-name-text">${esc(p.item_name)}</span>
            </button>${marken ? ' ' + marken : ''}
        </td>
        <td class="num cs-sp-preis" data-label="Je Stück">
            <span class="cs-feld-huelle">
                <input type="text" inputmode="decimal" class="cs-feld" data-feld="preis"
                       data-id="${p.id}" data-wert="${esc(preisFeld(p.price_eur))}"
                       value="${esc(preisFeld(p.price_eur))}" placeholder="0,00"
                       aria-label="Preis je Stück für ${esc(p.item_name)}"><i aria-hidden="true">€</i>
            </span>
        </td>
        <td class="num cs-gesamt" data-label="Gesamt">${p.brutto == null ? '–' : esc(eur(p.brutto))}</td>
        <td class="num cs-sp-menge" data-label="Anzahl">
            <span class="cs-feld-huelle">
                <input type="text" inputmode="numeric" class="cs-feld cs-feld--menge" data-feld="menge"
                       data-id="${p.id}" data-wert="${p.quantity == null ? '' : p.quantity}"
                       value="${p.quantity == null ? '' : p.quantity}" placeholder="–"
                       aria-label="Anzahl für ${esc(p.item_name)}">
            </span>
        </td>
        <td class="cs-sp-typ" data-label="Typ">
            <span class="cs-typ" role="img" aria-label="${esc(p.category_name)}"
                  title="${esc(p.category_name)}">${typZeichen(p.category_name)}</span>
        </td>
        <td class="cs-alter" title="${p.priced_at ? esc(tagDatum(p.priced_at)) : 'nie'}">${esc(alterText(p))}</td>
        <td class="cs-sp-tun">
            <button type="button" class="cs-stift" data-position="${p.id}"
                    aria-label="${esc(p.item_name)} ändern">${
                window.VexIkon ? VexIkon.svg('stift', 16) : ''}</button>
        </td>
    </tr>`;
}

/* Auf dem Telefon gibt es keine Kopfzeile zum Anklicken -- dort steht
   dieselbe Wahl als Auswahlfeld in der Filterleiste. Beide schreiben in
   dieselbe Zustandsgroesse; zwei Sortierungen nebeneinander waeren zwei
   Antworten auf dieselbe Frage. */
function zeichneSortWahl() {
    const wahl = document.getElementById('csSort');
    if (wahl) wahl.value = state.sortierung;
    const knopf = document.getElementById('csRichtung');
    if (knopf) {
        const auf = state.richtung === 'auf';
        knopf.textContent = auf ? '\u25b2' : '\u25bc';
        knopf.setAttribute('aria-label',
            auf ? 'Aufsteigend sortiert, umschalten' : 'Absteigend sortiert, umschalten');
    }
}

function zeichneKopfzeile() {
    const kopf = document.getElementById('csKopfzeile');
    kopf.querySelectorAll('th.sort').forEach((th) => {
        const aktiv = th.dataset.sort === state.sortierung;
        th.classList.toggle('is-sorted', aktiv);
        const pfeil = aktiv ? (state.richtung === 'auf' ? '▲' : '▼') : '';
        const text = th.dataset.label || (th.dataset.label = th.textContent.trim());
        th.setAttribute('aria-sort',
            aktiv ? (state.richtung === 'auf' ? 'ascending' : 'descending') : 'none');
        th.innerHTML = `<button type="button" class="sort-btn"
            aria-label="Nach ${esc(text)} sortieren">${esc(text)}<span
            class="sort-arrow" aria-hidden="true">${pfeil}</span></button>`;
    });
    zeichneSortWahl();
}

function zeichneListe(d) {
    const koerper = document.getElementById('csListe');
    const leer = document.getElementById('csListeLeer');
    const tabelle = document.getElementById('csTabelle');
    const kopf = document.getElementById('csListeKopf');
    state.zeilen = d.positionen;
    kopf.textContent = d.gekuerzt
        ? `${zahl(d.gezeigt)} von ${zahl(d.gesamt)} gezeigt`
        : `${zahl(d.gesamt)} ${d.gesamt === 1 ? 'Position' : 'Positionen'}`;
    zeichneKopfzeile();

    if (!d.positionen.length) {
        koerper.innerHTML = '';
        tabelle.hidden = true;
        const gefiltert = frageKette().length > 0;
        zeigeLeer(leer,
            gefiltert ? 'Kein Gegenstand passt auf diesen Filter.'
                      : 'Noch nichts erfasst. Die erste Position legst du oben rechts an.',
            gefiltert ? { text: 'Filter zurücksetzen', tun: filterLeeren }
                      : { text: '+ Position', tun: () => formular() });
        return;
    }
    leer.innerHTML = '';
    tabelle.hidden = false;
    koerper.innerHTML = d.positionen.map(zeileHtml).join('');
}

function filterLeeren() {
    state.filter = { suche: '', kategorien: [], faellig: false };
    document.getElementById('csSuche').value = '';
    document.getElementById('csFaellig').classList.remove('active');
    zeichneFilterKnoepfe();
    ladeBestand();
}

function sortiereNach(spalte) {
    if (!SPALTEN[spalte]) return;
    if (state.sortierung === spalte) {
        state.richtung = state.richtung === 'auf' ? 'ab' : 'auf';
    } else {
        state.sortierung = spalte;
        state.richtung = SPALTEN[spalte].abwaerts ? 'ab' : 'auf';
    }
    ladeBestand();
}

/* ------------------------------------------------- Kopieren und Bearbeiten */

/* Kopiert wird der MARKTNAME, nicht bloss der angezeigte: er traegt StatTrak
   und Abnutzung mit und ist damit das, was man drueben ins Suchfeld legt.
   Der Toast sagt wortwoertlich, was in der Zwischenablage liegt -- sonst
   koennte man es nur durch Einfuegen herausfinden. */
async function kopiere(text) {
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
        } else {
            // Ohne sicheren Kontext gibt es die Zwischenablage-API nicht.
            const hilf = document.createElement('textarea');
            hilf.value = text;
            hilf.setAttribute('readonly', '');
            hilf.style.position = 'fixed';
            hilf.style.opacity = '0';
            document.body.appendChild(hilf);
            hilf.select();
            const ging = document.execCommand('copy');
            document.body.removeChild(hilf);
            if (!ging) throw new Error('Der Browser hat das Kopieren abgelehnt.');
        }
        melde('success', `Kopiert: ${text}`);
    } catch (e) {
        melde('error', 'Kopieren ging nicht: ' + e.message);
    }
}

/* Eine geaenderte Zelle speichern.

   Der Preis geht ueber den Preis-Endpunkt und bewegt damit den Preisstand,
   die Menge ueber PATCH und laesst ihn in Ruhe. Das ist der ganze Unterschied
   zwischen "ich habe nachgesehen" und "es sind jetzt mehr". */
/* Ein abgelehnter Wert wird zurueckgenommen, nicht stehen gelassen.

   Sonst steht in der Zelle „drei“, waehrend gespeichert 6 ist -- und nichts
   an der Zeile sagt, welche der beiden Zahlen gilt. Die Regel dieser Tabelle
   ist, dass ein Feld zeigt, was gespeichert ist; eine abgelehnte Eingabe ist
   keine Ausnahme davon. Der alte Wert bleibt markiert, damit Tippen ihn
   sofort ersetzt. */
function zurueck(feld, satz) {
    feld.value = feld.dataset.wert;
    melde('error', satz);
    feld.focus();
    feld.select();
    return false;
}

async function feldSpeichern(feld) {
    const roh = feld.value.trim();
    if (roh === feld.dataset.wert) return false;
    const id = Number(feld.dataset.id);
    const menge = feld.dataset.feld === 'menge';

    // Leeren ist kein Loeschen: beide Endpunkte lesen "nichts" als "nichts
    // aendern". Das stillschweigend zurueckzusetzen waere eine Aenderung, die
    // verschwindet -- also wird es gesagt.
    if (!roh) {
        return zurueck(feld, menge ? 'Die Anzahl lässt sich hier nicht leeren.'
                                   : 'Der Preis lässt sich hier nicht leeren.');
    }
    if (menge && !/^\d+$/.test(roh)) {
        return zurueck(feld, `„${roh}“ ist keine Stückzahl.`);
    }

    feld.classList.add('is-laeuft');
    try {
        const p = menge ? await API.aendern(id, { quantity: Number(roh) })
                        : await API.preis(id, roh);
        zeileNachziehen(feld.closest('tr'), p);
        feld.dataset.wert = menge ? String(p.quantity)
                                  : preisFeld(p.price_eur);
        feld.value = feld.dataset.wert;
        feld.classList.remove('is-laeuft');
        feld.classList.add('is-gesichert');
        setTimeout(() => feld.classList.remove('is-gesichert'), 900);
        ladeBestandStill();
        return true;
    } catch (e) {
        feld.classList.remove('is-laeuft');
        return zurueck(feld, e.message);
    }
}

/* Nur die Zelle nachziehen, die sich mitaendert -- nicht die ganze Liste.
   Ein Neuaufbau waehrend des Tippens wuerde die Zeile unter dem Finger
   wegsortieren, sobald nach Preis oder Wert sortiert ist. */
function zeileNachziehen(tr, p) {
    if (!tr || !p) return;
    tr.className = markeFuer(p) + (p.unvollstaendig ? ' cs-unvollstaendig' : '');
    tr.dataset.zeile = p.id;
    const gesamt = tr.querySelector('.cs-gesamt');
    if (gesamt) gesamt.textContent = p.brutto == null ? '–' : eur(p.brutto);
    const alter = tr.querySelector('.cs-alter');
    if (alter) {
        alter.textContent = alterText(p);
        alter.title = p.priced_at ? tagDatum(p.priced_at) : 'nie';
    }
    const punkt = tr.querySelector('.cs-name');
    if (punkt) {
        const alt = punkt.querySelector('.cs-punkt');
        if (alt) alt.remove();
        punkt.insertAdjacentHTML('afterbegin', punktHtml(p));
    }
}

/* Weiter zum naechsten Feld derselben Spalte -- der Takt, in dem man eine
   Preisrunde abarbeitet. */
function naechstesFeld(feld, schritt) {
    const alle = [...document.querySelectorAll(
        `#csListe .cs-feld[data-feld="${feld.dataset.feld}"]`)];
    const i = alle.indexOf(feld);
    const ziel = alle[i + (schritt || 1)];
    if (ziel) { ziel.focus(); ziel.select(); }
    else feld.blur();
}

/* Der Bestand im Hintergrund nachziehen: was dasteht, bleibt stehen, falls es
   schiefgeht. Eine Fehlerseite ueber gueltigen Zahlen waere ein Rueckschritt. */
async function ladeBestandStill() {
    try {
        const q = frageKette();
        const ueber = await API.ueberblick('?' + q.concat('tage=' + state.tage).join('&'));
        zeichneKpi(ueber);
        zeichneAufteilung(ueber);
    } catch (e) { /* der sichtbare Stand bleibt */ }
}

/* ------------------------------------------------------- Filter-Aufklapper */

function baueFilterPopover(id, eintraege, gewaehlt, beiAenderung) {
    const pop = document.getElementById(id);
    pop.innerHTML = eintraege.map((e) => `
        <label class="fp-row">
            <input type="checkbox" value="${e.id}"${gewaehlt.includes(e.id) ? ' checked' : ''}>
            <span class="fp-label">${esc(e.name)}</span>
        </label>`).join('')
        + `<div class="fp-actions">
             <button type="button" class="fp-btn fp-btn-ghost" data-alle="0">Keine</button>
             <button type="button" class="fp-btn fp-btn-primary" data-alle="1">Alle</button>
           </div>`;
    pop.querySelectorAll('input[type=checkbox]').forEach((c) => {
        c.addEventListener('change', () => beiAenderung(
            [...pop.querySelectorAll('input:checked')].map((x) => Number(x.value))));
    });
    pop.querySelectorAll('[data-alle]').forEach((b) => {
        b.addEventListener('click', () => {
            const an = b.dataset.alle === '1';
            pop.querySelectorAll('input[type=checkbox]').forEach((c) => { c.checked = an; });
            beiAenderung(an ? eintraege.map((e) => e.id) : []);
        });
    });
}

function zeichneFilterKnoepfe() {
    const b = document.getElementById('csKatBadge');
    const n = state.filter.kategorien.length;
    b.hidden = !n;
    b.textContent = n || '';
    b.closest('.filter-popover-wrap').querySelector('.filter-toggle-btn')
        .classList.toggle('has-active', !!n);
    baueFilterPopover('csKatPop', state.katalog.kategorien, state.filter.kategorien,
        (ids) => { state.filter.kategorien = ids; zeichneFilterKnoepfe(); ladeBestand(); });
}

/* ----------------------------------------------------------------- Verlauf */

async function ladeVerlauf() {
    const el = document.getElementById('csStaende');
    try {
        const staende = await API.staende(state.tage);
        zeichneKurve(staende);
        zeichneStaende(staende);
    } catch (e) {
        zeigeFehler(el, 'Der Verlauf konnte nicht geladen werden: ' + e.message, ladeVerlauf);
    }
}

function zeichneKurve(staende) {
    const leinwand = document.getElementById('csChart');
    if (!leinwand || typeof Chart === 'undefined') return;
    const reihe = [...staende].reverse();
    const achse = reihe.map((s) => s.taken_on);
    if (state.chart) { state.chart.destroy(); state.chart = null; }
    if (!reihe.length) return;

    const optionen = {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { labels: { color: cssVar('--text-3') } } },
        scales: {
            x: { grid: { color: cssVar('--chart-grid') }, ticks: { color: cssVar('--chart-axis') } },
            y: { grid: { color: cssVar('--chart-grid') }, ticks: { color: cssVar('--chart-axis') } },
        },
    };
    if (window.VexCharts) VexCharts.applyFullDates(optionen, achse);

    state.chart = new Chart(leinwand, {
        type: 'line',
        data: {
            labels: achse.map((d) => tagDatum(d)),
            datasets: [
                { label: 'Brutto', data: reihe.map((s) => s.total_gross),
                  borderColor: ton(), backgroundColor: 'transparent',
                  tension: 0.25, pointRadius: 2,
                  order: window.VexCharts ? VexCharts.ORDER.VALUE : 1 },
                { label: 'Nach Gebühr', data: reihe.map((s) => s.total_net),
                  borderColor: cssVar('--text-4'), borderDash: [5, 4],
                  backgroundColor: 'transparent', tension: 0.25, pointRadius: 0,
                  order: window.VexCharts ? VexCharts.ORDER.TREND : 0 },
            ],
        },
        options: optionen,
    });
}

function zeichneStaende(staende) {
    const el = document.getElementById('csStaende');
    if (!staende.length) {
        zeigeLeer(el, 'Noch kein Stand festgehalten. Der erste macht aus dem Bestand einen Verlauf.',
            { text: 'Stand festhalten', tun: standFesthalten });
        return;
    }
    el.innerHTML = `<div class="rec-list">${staende.map((s) => `
        <div class="rec-row">
            <span class="rec-mark" style="--tone:var(--cs2-ton)">${esc(String(s.taken_on).slice(8, 10))}</span>
            <span class="rec-main">
                <span class="rec-title">${esc(tagDatum(s.taken_on))}</span>
                <span class="rec-meta">${zahl(s.rows_valid)} Positionen${
                    s.rows_incomplete ? '<span class="sep">·</span>' + zahl(s.rows_incomplete) + ' unvollständig' : ''}${
                    s.stale_rows ? '<span class="sep">·</span><span class="cs-alter">' + zahl(s.stale_rows) + ' überfällige Preise</span>' : ''}${
                    s.note ? '<span class="sep">·</span>' + esc(s.note) : ''}</span>
            </span>
            <span class="rec-side">
                <span class="rec-val">${esc(eur(s.total_gross))}</span>
                <span class="rec-sub">${esc(eur(s.total_net))} netto</span>
            </span>
        </div>`).join('')}</div>`;
}

async function standFesthalten() {
    try {
        const s = await API.festhalten();
        melde('success', `Stand vom ${tagDatum(s.taken_on)} festgehalten`);
        await ladeVerlauf();
        ladeBestandStill();
    } catch (e) {
        melde('error', e.message);
    }
}

/* ------------------------------------------------------------ Übernahme */

/* Erst zeigen, dann tun. Ein Import, der beim Loslassen der Datei 116 Zeilen
   umschreibt, ist nicht überprüfbar — und die Regel dazu steht in DESIGN:
   wer etwas ersetzt, zeigt vorher, was er ersetzen würde. */
async function dateiGelesen(datei) {
    const el = document.getElementById('csImport');
    el.innerHTML = '<span class="skel skel-line"></span><span class="skel skel-line short"></span>';
    let dok;
    try {
        dok = JSON.parse(await datei.text());
    } catch (e) {
        zeigeFehler(el, `„${datei.name}“ ist keine lesbare JSON-Datei.`, () => { el.innerHTML = ''; });
        return;
    }
    try {
        const { vorschau } = await API.einlesen(dok, false);
        zeigeVorschau(dok, vorschau, datei.name);
    } catch (e) {
        zeigeFehler(el, e.message, () => { el.innerHTML = ''; });
    }
}

function zeigeVorschau(dok, v, dateiname) {
    const el = document.getElementById('csImport');
    const zeile = (p, mitAlt) => `<div class="rec-row">
        <span class="rec-mark" style="--tone:var(--cs2-ton)">${esc((p.gegenstand || '?').slice(0, 1).toUpperCase())}</span>
        <span class="rec-main">
            <span class="rec-title">${esc(p.gegenstand)}</span>
            <span class="rec-meta">${esc(p.kategorie)}${p.wear ? '<span class="sep">·</span>' + esc(p.wear) : ''}</span>
        </span>
        <span class="rec-side">
            <span class="rec-val">${zahl(p.menge)} × ${esc(eur(p.preis))}</span>
            ${mitAlt ? `<span class="rec-sub">bisher ${zahl(p.menge_alt)} × ${esc(eur(p.preis_alt))}</span>` : ''}
        </span></div>`;

    const teile = [];
    if (v.neu) teile.push(`<strong>${zahl(v.neu)}</strong> neu`);
    if (v.geaendert) teile.push(`<strong>${zahl(v.geaendert)}</strong> geändert`);
    if (v.gleich) teile.push(`${zahl(v.gleich)} unverändert`);

    el.innerHTML = `
        <div class="cs-vorschau">
            <p class="cs-hinweis"><strong>${esc(dateiname)}</strong> enthält
               ${zahl(v.positionen)} ${v.positionen === 1 ? 'Position' : 'Positionen'}${
                 v.erzeugt_am ? ` vom ${esc(tagDatum(v.erzeugt_am))}` : ''}:
               ${teile.join(' · ') || 'nichts davon ist neu'}.</p>
            ${v.bleibt_stehen ? `<p class="cs-hinweis">${zahl(v.bleibt_stehen)} Position(en)
               im Bestand kommen in der Datei nicht vor. Sie bleiben stehen —
               eine Übernahme löscht nichts.</p>` : ''}
            ${v.zusammengefuehrt ? `<p class="cs-hinweis">${zahl(v.zusammengefuehrt)} Zeile(n)
               der Datei unterschieden sich nur im Lager, das es nicht mehr gibt.
               Sie wurden zu einer zusammengefasst — die Stückzahlen addiert.</p>` : ''}
            ${v.neue_kategorien.length ? `<p class="cs-hinweis">Neue Kategorien:
               ${v.neue_kategorien.map(esc).join(', ')}</p>` : ''}
            ${v.staende ? `<p class="cs-hinweis">Dazu ${zahl(v.staende)} festgehaltene Stände
               für den Verlauf.</p>` : ''}
            ${v.beispiele_neu.length ? `<div class="cs-beispiele">
               <span class="cs-label">Neu, zum Beispiel</span>
               <div class="rec-list">${v.beispiele_neu.map(p => zeile(p, false)).join('')}</div></div>` : ''}
            ${v.beispiele_geaendert.length ? `<div class="cs-beispiele">
               <span class="cs-label">Geändert, zum Beispiel</span>
               <div class="rec-list">${v.beispiele_geaendert.map(p => zeile(p, true)).join('')}</div></div>` : ''}
            <div class="cs-form-fuss">
                <button type="button" class="v-btn" data-abbruch="1">Verwerfen</button>
                <button type="button" class="v-btn v-btn--primary" data-uebernehmen="1"
                        ${v.neu + v.geaendert + v.staende ? '' : 'disabled'}>Übernehmen</button>
            </div>
        </div>`;
    el.querySelector('[data-abbruch]').addEventListener('click', () => { el.innerHTML = ''; });
    el.querySelector('[data-uebernehmen]').addEventListener('click', async (ev) => {
        const knopf = ev.currentTarget;
        knopf.disabled = true;
        knopf.classList.add('is-loading');
        try {
            const { uebernommen } = await API.einlesen(dok, true);
            melde('success', `${uebernommen.neu} neu, ${uebernommen.geaendert} aktualisiert`
                + (uebernommen.staende ? `, ${uebernommen.staende} Stände` : ''));
            el.innerHTML = '';
            document.getElementById('csDatei').value = '';
            await neuLaden();
        } catch (e) {
            melde('error', e.message);
            knopf.disabled = false;
            knopf.classList.remove('is-loading');
        }
    });
}

/* ---------------------------------------------------------------- Formular */

function formular(position) {
    const k = state.katalog;
    const istNeu = !position;
    const gewaehlteKat = position ? position.category_id : k.kategorien[0]?.id;

    const optionen = (liste, aktiv) => liste.map((e) =>
        `<option value="${e.id}"${String(e.id) === String(aktiv) ? ' selected' : ''}>${esc(e.name)}</option>`).join('');

    const html = `<form class="cs-form" id="csForm">
        <label><span class="cs-label">Kategorie</span>
            <select name="category_id"${istNeu ? '' : ' disabled'}>${optionen(k.kategorien, gewaehlteKat)}</select>
        </label>
        <label><span class="cs-label">Gegenstand</span>
            <input type="text" name="item_name" list="csItemVorschlag" autocomplete="off"
                   value="${esc(position ? position.item_name : '')}" placeholder="AK-47 | Frontside Misty">
        </label>
        <datalist id="csItemVorschlag"></datalist>
        <div class="cs-form-reihe">
            <label><span class="cs-label">Abnutzung</span>
                <select name="wear"><option value="">— keine —</option>${
                    k.wear.map((w) => `<option value="${w.wert}"${position && position.wear === w.wert ? ' selected' : ''}>${esc(w.wert)} · ${esc(w.label)}</option>`).join('')}</select>
            </label>
            <label><span class="cs-label">Stückzahl</span>
                <input type="number" name="quantity" min="0" step="1" inputmode="numeric"
                       value="${position && position.quantity != null ? position.quantity : ''}">
            </label>
        </div>
        <label><span class="cs-label">Preis je Stück</span>
            <input type="text" name="price_eur" inputmode="decimal" placeholder="0,00"
                   value="${position ? preisFeld(position.price_eur) : ''}">
        </label>
        <div class="cs-schalter">
            <label><input type="checkbox" name="stattrak"${position && position.stattrak ? ' checked' : ''}> StatTrak™</label>
        </div>
        <div class="cs-form-fuss">
            ${istNeu ? '' : '<button type="button" class="v-btn" data-weg="1">Löschen</button>'}
            <button type="submit" class="v-btn v-btn--primary">${istNeu ? 'Anlegen' : 'Speichern'}</button>
        </div>
    </form>`;

    const fenster = VexModal.open(istNeu ? 'Position anlegen' : 'Position ändern', html);
    const form = fenster.el.querySelector('#csForm');
    const katFeld = form.querySelector('[name=category_id]');
    const liste = form.querySelector('#csItemVorschlag');

    /* Was die Kategorie nicht kennt, wird ausgeblendet statt abgelehnt. Ein
       Case hat keine Abnutzung -- das Feld dafuer stehen zu lassen und die
       Eingabe hinterher zu verwerfen, waere eine Frage ohne Antwort. */
    const regelnAnwenden = () => {
        const kat = k.kategorien.find((x) => String(x.id) === String(katFeld.value));
        if (!kat) return;
        form.querySelector('[name=wear]').closest('label').hidden = !kat.supports_wear;
        form.querySelector('[name=stattrak]').closest('label').hidden = !kat.supports_stattrak;
        liste.innerHTML = k.items.filter((i) => String(i.category_id) === String(katFeld.value))
            .map((i) => `<option value="${esc(i.name)}"></option>`).join('');
    };
    katFeld.addEventListener('change', regelnAnwenden);
    regelnAnwenden();

    const wegKnopf = form.querySelector('[data-weg]');
    if (wegKnopf) {
        wegKnopf.addEventListener('click', async () => {
            const sicher = await askConfirm({
                title: 'Position löschen?',
                text: `„${position.item_name}“ aus dem Bestand nehmen.`,
                confirmText: 'Löschen', danger: true,
            });
            if (!sicher) return;
            try {
                await API.entfernen(position.id);
                fenster.close();
                melde('success', 'Gelöscht');
                await neuLaden();
            } catch (e) { melde('error', e.message); }
        });
    }

    form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const f = new FormData(form);
        const koerper = {
            item_name: (f.get('item_name') || '').trim(),
            wear: f.get('wear') || null,
            stattrak: form.querySelector('[name=stattrak]').checked,
            quantity: f.get('quantity') === '' ? null : Number(f.get('quantity')),
            price_eur: (f.get('price_eur') || '').trim() || null,
        };
        if (!koerper.item_name) { melde('error', 'Der Gegenstand braucht einen Namen.'); return; }
        try {
            if (istNeu) {
                koerper.category_id = Number(f.get('category_id'));
                await API.anlegen(koerper);
            } else {
                await API.aendern(position.id, koerper);
            }
            fenster.close();
            melde('success', istNeu ? 'Angelegt' : 'Gespeichert');
            await neuLaden();
        } catch (e) { melde('error', e.message); }
    });
}

/* ------------------------------------------------------------------- Start */

async function neuLaden() {
    state.katalog = await API.katalog();
    zeichneFilterKnoepfe();
    await ladeBestand();
}

document.addEventListener('DOMContentLoaded', async () => {
    if (!isLoggedIn()) { location.href = '/private/login.html'; return; }
    // Freigabe direkt nach dem synchronen Login-Check und VOR jedem await:
    // css/statistics.css haelt den Body bis dahin unsichtbar.
    document.body.classList.add('ready');

    document.getElementById('logoutBtn').addEventListener('click', () => {
        clearToken(); location.href = '/private/login.html';
    });
    try {
        const me = await fetchMe();
        document.getElementById('userLabel').textContent = '👤 ' + me.username;
    } catch (e) { /* der Name ist Beiwerk */ }

    document.querySelectorAll('.tab-btn').forEach((b) => {
        b.addEventListener('click', () => zeigeReiter(b.dataset.tab));
    });

    let tippTakt = null;
    document.getElementById('csSuche').addEventListener('input', (ev) => {
        clearTimeout(tippTakt);
        tippTakt = setTimeout(() => {
            state.filter.suche = ev.target.value.trim();
            ladeBestand();
        }, 250);
    });
    document.getElementById('csFaellig').addEventListener('click', (ev) => {
        state.filter.faellig = !state.filter.faellig;
        ev.target.classList.toggle('active', state.filter.faellig);
        ladeBestand();
    });
    document.getElementById('csNeu').addEventListener('click', () => formular());
    document.getElementById('csSnapshot').addEventListener('click', standFesthalten);

    document.getElementById('csKopfzeile').addEventListener('click', (ev) => {
        const th = ev.target.closest('th.sort');
        if (th) sortiereNach(th.dataset.sort);
    });
    document.getElementById('csSort').addEventListener('change', (ev) => {
        state.sortierung = ev.target.value;
        state.richtung = SPALTEN[state.sortierung].abwaerts ? 'ab' : 'auf';
        ladeBestand();
    });
    document.getElementById('csRichtung').addEventListener('click', () => {
        state.richtung = state.richtung === 'auf' ? 'ab' : 'auf';
        ladeBestand();
    });

    const drop = document.getElementById('csDrop');
    const feld = document.getElementById('csDatei');
    drop.addEventListener('click', () => feld.click());
    drop.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); feld.click(); }
    });
    feld.addEventListener('change', () => {
        if (feld.files && feld.files[0]) dateiGelesen(feld.files[0]);
    });
    ['dragenter', 'dragover'].forEach((art) => drop.addEventListener(art, (ev) => {
        ev.preventDefault(); drop.classList.add('drag');
    }));
    ['dragleave', 'drop'].forEach((art) => drop.addEventListener(art, (ev) => {
        ev.preventDefault(); drop.classList.remove('drag');
    }));
    drop.addEventListener('drop', (ev) => {
        const d = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];
        if (d) dateiGelesen(d);
    });

    // Aufklapper: der Knopf schaltet, ein Klick daneben schliesst.
    document.querySelectorAll('.filter-popover-wrap').forEach((wrap) => {
        const knopf = wrap.querySelector('.filter-toggle-btn');
        const pop = wrap.querySelector('.filter-popover');
        knopf.addEventListener('click', () => {
            const auf = pop.hidden;
            document.querySelectorAll('.filter-popover').forEach((p) => { p.hidden = true; });
            pop.hidden = !auf;
            knopf.setAttribute('aria-expanded', String(auf));
        });
    });
    document.addEventListener('click', (ev) => {
        if (!ev.target.closest('.filter-popover-wrap')) {
            document.querySelectorAll('.filter-popover').forEach((p) => { p.hidden = true; });
            document.querySelectorAll('.filter-toggle-btn').forEach(
                (b) => b.setAttribute('aria-expanded', 'false'));
        }
    });

    // Der Name kopiert, der Stift oeffnet. Zwei Ziele in einer Zeile, und
    // beide sind angeschrieben -- der Name ueber sein title, der Stift ueber
    // sein aria-label.
    document.addEventListener('click', (ev) => {
        const name = ev.target.closest('[data-kopieren]');
        if (name) { kopiere(name.dataset.kopieren); return; }
        const stift = ev.target.closest('[data-position]');
        if (stift) {
            const p = state.zeilen.find((x) => x.id === Number(stift.dataset.position));
            if (p) formular(p);
        }
    });

    // Die Felder in der Tabelle: Enter bestaetigt und geht weiter, Tab und
    // Klick daneben bestaetigen auch (change), Escape nimmt zurueck.
    const liste = document.getElementById('csListe');
    liste.addEventListener('keydown', (ev) => {
        const f = ev.target.closest('.cs-feld');
        if (!f) return;
        if (ev.key === 'Enter') {
            ev.preventDefault();
            feldSpeichern(f).then(() => naechstesFeld(f, 1));
        } else if (ev.key === 'Escape') {
            ev.preventDefault();
            f.value = f.dataset.wert;
            f.blur();
        }
    });
    liste.addEventListener('change', (ev) => {
        const f = ev.target.closest('.cs-feld');
        if (f) feldSpeichern(f);
    });
    liste.addEventListener('focusin', (ev) => {
        const f = ev.target.closest('.cs-feld');
        if (f) f.select();
    });

    if (window.VexRange) {
        VexRange.mount(document.getElementById('csRange'), {
            onChange: (r) => { state.tage = r.fetchDays || r.days || 365; ladeVerlauf(); },
        });
    }

    try {
        state.katalog = await API.katalog();
    } catch (e) {
        document.getElementById('csTabelle').hidden = true;
        zeigeFehler(document.getElementById('csListeLeer'),
            'Die Stammdaten konnten nicht geladen werden: ' + e.message,
            () => location.reload());
        return;
    }
    (state.katalog.wear || []).forEach((w) => { WEAR_LANG[w.wert] = w.label; });
    zeichneFilterKnoepfe();
    zeigeReiter((location.hash || '').replace('#', '') || 'bestand', true);
    await ladeBestand();
});
