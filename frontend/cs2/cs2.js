/* cs2.js — der CS2-Bestand.
 *
 * Vier Reiter, eine Frage je Reiter:
 *   Bestand     was ist da und was waere es wert
 *   Pflege      welcher Preis ist zu alt, um noch fuer sich zu sprechen
 *   Verlauf     wie hat sich das entwickelt
 *   Verwaltung  Lager und Gegenstaende
 *
 * Drei Regeln, die das Modul durchhaelt:
 *
 * 1. **Gerechnet wird im Server.** Die Kopfzahlen kommen aus /overview mit
 *    denselben Filterwerten wie die Liste, nicht aus den geladenen Zeilen.
 *    Sonst stuenden eine grosse Zahl und ein Ausschnitt nebeneinander, ohne
 *    dass man der Zahl ansieht, welche Menge sie meint.
 *
 * 2. **Ein gescheiterter Abruf ist kein leerer Bestand.** Jede Ladefunktion
 *    schreibt ihren Fehler DORTHIN, wo die Daten stuenden, mit dem Weg
 *    zurueck daneben -- nie in eine leere Liste und nie nur in einen Toast,
 *    der nach Sekunden weg ist.
 *
 * 3. **Kein eigener Dialog, kein eigener Zeitraum, kein eigener Export.**
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
    pflege:    ()            => apiCall('/api/cs2/pflege'),
    staende:   (tage)        => apiCall('/api/cs2/snapshots?tage=' + tage),
    festhalten:()            => apiCall('/api/cs2/snapshots', { method: 'POST', body: {} }),
    lagerNeu:  (n)           => apiCall('/api/cs2/storages', { method: 'POST', body: { name: n } }),
    lagerName: (id, n)       => apiCall('/api/cs2/storages/' + id, { method: 'PUT', body: { name: n } }),
    lagerWeg:  (id)          => apiCall('/api/cs2/storages/' + id, { method: 'DELETE' }),
    itemName:  (id, n)       => apiCall('/api/cs2/items/' + id, { method: 'PUT', body: { name: n } }),
    itemWeg:   (id)          => apiCall('/api/cs2/items/' + id, { method: 'DELETE' }),
};

const state = {
    katalog: null,
    filter: { suche: '', kategorien: [], lager: [], faellig: false, sortierung: 'wert' },
    aufteilung: 'kategorie',
    tage: 365,
    chart: null,
    itemSuche: '',
};

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
    if (f.lager.length) teile.push('lager=' + f.lager.join(','));
    if (f.faellig) teile.push('nur_faellig=true');
    return teile;
}

/* ------------------------------------------------------------------ Reiter */

const REITER = ['bestand', 'pflege', 'verlauf', 'verwaltung'];

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
    if (name === 'pflege') ladePflege();
    if (name === 'verwaltung') zeichneVerwaltung();
}

/* ----------------------------------------------------------------- Bestand */

async function ladeBestand() {
    const q = frageKette();
    const listeEl = document.getElementById('csListe');
    try {
        const [ueber, liste] = await Promise.all([
            API.ueberblick('?' + q.concat('tage=' + state.tage).join('&')),
            API.liste('?' + q.concat('sortierung=' + state.filter.sortierung).join('&')),
        ]);
        zeichneKpi(ueber);
        zeichneAufteilung(ueber);
        zeichneListe(liste);
    } catch (e) {
        zeigeFehler(listeEl, 'Der Bestand konnte nicht geladen werden: ' + e.message, ladeBestand);
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
                   : `${zahl(b.stueck)} Einzelstücke`,
        },
        {
            label: 'Nach Gebühr', wert: eur(b.netto),
            sub: `geschätzter Erlös, abzüglich ${Math.round((state.katalog?.gebuehr || 0.15) * 100)} % Gebühr`,
        },
        {
            label: 'Selbst gespielt', wert: eur(b.playskin_brutto),
            sub: `Rest als Anlage: ${eur(b.invest_brutto)}`,
        },
        {
            label: 'Positionen', wert: zahl(b.positionen),
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

    const zaehler = document.getElementById('csPflegeZahl');
    zaehler.hidden = !b.veraltet;
    zaehler.textContent = b.veraltet || '';
}

function zeichneAufteilung(u) {
    const el = document.getElementById('csAufteilung');
    const daten = state.aufteilung === 'lager' ? u.je_lager : u.je_kategorie;
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

function markeFuer(p) {
    const stufe = { frisch: 'cs-frisch', alt: 'cs-alt', sehr_alt: 'cs-sehr-alt', ohne: 'cs-ohne' };
    return stufe[p.frische] || 'cs-frisch';
}

function alterText(p) {
    if (p.alter_tage == null) return 'nie bepreist';
    if (p.alter_tage === 0) return 'heute gepflegt';
    if (p.alter_tage === 1) return 'gestern gepflegt';
    return `vor ${zahl(p.alter_tage)} Tagen gepflegt`;
}

function zeileHtml(p) {
    const marken = [
        p.stattrak ? '<span class="cs-marke cs-marke--st">StatTrak™</span>' : '',
        p.playskin ? '<span class="cs-marke cs-marke--ps">gespielt</span>' : '',
    ].filter(Boolean).join(' ');
    const meta = [
        esc(p.category_name),
        p.wear ? esc(p.wear) : '',
        esc(p.storage_name),
        `<span class="cs-alter">${esc(alterText(p))}</span>`,
    ].filter(Boolean).join('<span class="sep">·</span>');
    return `<button type="button" class="rec-row ${markeFuer(p)}${p.unvollstaendig ? ' cs-unvollstaendig' : ''}"
                    data-position="${p.id}">
        <span class="rec-mark">${esc((p.item_name || '?').slice(0, 1).toUpperCase())}</span>
        <span class="rec-main">
            <span class="rec-title">${esc(p.item_name)} ${marken}</span>
            <span class="rec-meta">${meta}</span>
        </span>
        <span class="rec-side">
            <span class="rec-val">${p.brutto == null ? 'unvollständig' : esc(eur(p.brutto))}</span>
            <span class="rec-sub">${p.quantity == null ? '– Stück' : zahl(p.quantity) + ' ×'} ${p.price_eur == null ? '–' : esc(eur(p.price_eur))}</span>
        </span>
        <span class="rec-go" aria-hidden="true">›</span>
    </button>`;
}

function zeichneListe(d) {
    const el = document.getElementById('csListe');
    const kopf = document.getElementById('csListeKopf');
    kopf.textContent = d.gekuerzt
        ? `${zahl(d.gezeigt)} von ${zahl(d.gesamt)} gezeigt`
        : `${zahl(d.gesamt)} ${d.gesamt === 1 ? 'Position' : 'Positionen'}`;
    if (!d.positionen.length) {
        const gefiltert = frageKette().length > 0;
        zeigeLeer(el,
            gefiltert ? 'Kein Gegenstand passt auf diesen Filter.'
                      : 'Noch nichts erfasst. Die erste Position legst du oben rechts an.',
            gefiltert ? { text: 'Filter zurücksetzen', tun: filterLeeren }
                      : { text: '+ Position', tun: () => formular() });
        return;
    }
    el.innerHTML = `<div class="rec-list">${d.positionen.map(zeileHtml).join('')}</div>`;
}

function filterLeeren() {
    state.filter = { suche: '', kategorien: [], lager: [], faellig: false,
                     sortierung: state.filter.sortierung };
    document.getElementById('csSuche').value = '';
    document.getElementById('csFaellig').classList.remove('active');
    zeichneFilterKnoepfe();
    ladeBestand();
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
    const paare = [
        ['csKatBadge', state.filter.kategorien.length],
        ['csLagBadge', state.filter.lager.length],
    ];
    paare.forEach(([id, n]) => {
        const b = document.getElementById(id);
        b.hidden = !n;
        b.textContent = n || '';
        b.closest('.filter-popover-wrap').querySelector('.filter-toggle-btn')
            .classList.toggle('has-active', !!n);
    });
    baueFilterPopover('csKatPop', state.katalog.kategorien, state.filter.kategorien,
        (ids) => { state.filter.kategorien = ids; zeichneFilterKnoepfe(); ladeBestand(); });
    baueFilterPopover('csLagPop', state.katalog.lager, state.filter.lager,
        (ids) => { state.filter.lager = ids; zeichneFilterKnoepfe(); ladeBestand(); });
}

/* ------------------------------------------------------------------ Pflege */

async function ladePflege() {
    const el = document.getElementById('csPflege');
    try {
        const d = await API.pflege();
        zeichnePflege(d);
    } catch (e) {
        zeigeFehler(el, 'Die Pflegeliste konnte nicht geladen werden: ' + e.message, ladePflege);
    }
}

function zeichnePflege(d) {
    const el = document.getElementById('csPflege');
    const sub = document.getElementById('csPflegeSub');
    const stand = document.getElementById('csPflegeStand');
    const erledigt = d.bestand - d.offen;

    sub.textContent = `Älteste zuerst · überfällig ab ${d.alt_ab_tagen} Tagen`;
    document.getElementById('csFortschritt').style.width =
        (d.bestand ? (erledigt / d.bestand) * 100 : 100).toFixed(1) + '%';
    stand.textContent = d.offen
        ? `${zahl(d.offen)} von ${zahl(d.bestand)} Positionen brauchen einen neuen Preis.`
        : `Alle ${zahl(d.bestand)} Positionen sind aktuell.`;

    if (!d.faellig.length) {
        zeigeLeer(el, d.bestand
            ? 'Nichts überfällig — jeder Preis ist jünger als ' + d.alt_ab_tagen + ' Tage.'
            : 'Noch nichts erfasst, also auch nichts zu pflegen.');
        return;
    }
    el.innerHTML = `<div class="v-card">${d.faellig.map((p) => `
        <div class="cs-pflege-zeile ${markeFuer(p)}" data-pflege="${p.id}">
            <span class="rec-mark">${esc((p.item_name || '?').slice(0, 1).toUpperCase())}</span>
            <span class="cs-pflege-name">${esc(p.item_name)}${p.wear ? ' · ' + esc(p.wear) : ''}
                <span class="cs-pflege-meta">${p.price_eur == null ? 'noch kein Preis'
                    : 'zuletzt ' + esc(eur(p.price_eur))}<span class="sep">·</span><span class="cs-alter">${esc(alterText(p))}</span><span class="sep">·</span>${zahl(p.quantity || 0)} ×</span>
            </span>
            <span class="cs-pflege-feld">
                <input type="text" inputmode="decimal" aria-label="Neuer Preis für ${esc(p.item_name)}"
                       placeholder="${p.price_eur == null ? '0,00' : preisFeld(p.price_eur)}">
                <span aria-hidden="true">€</span>
            </span>
        </div>`).join('')}</div>`;
}

async function preisSpeichern(zeile, wert) {
    const id = Number(zeile.dataset.pflege);
    const feld = zeile.querySelector('input');
    try {
        await API.preis(id, wert);
        zeile.classList.add('is-erledigt');
        feld.disabled = true;
        melde('success', 'Preis bestätigt');
        // Zum naechsten offenen Feld weiter -- das ist der Takt dieser Ansicht.
        const offen = [...document.querySelectorAll('.cs-pflege-zeile:not(.is-erledigt) input')];
        if (offen.length) offen[0].focus();
        else ladePflege();
        ladeBestandStill();
    } catch (e) {
        melde('error', e.message);
        feld.focus();
        feld.select();
    }
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

/* -------------------------------------------------------------- Verwaltung */

function zeichneVerwaltung() {
    const lagerEl = document.getElementById('csLagerListe');
    lagerEl.innerHTML = `<div class="rec-list">${state.katalog.lager.map((l) => `
        <button type="button" class="rec-row" data-lager="${l.id}">
            <span class="rec-mark" style="--tone:var(--cs2-ton)">${esc(l.name.slice(0, 1).toUpperCase())}</span>
            <span class="rec-main">
                <span class="rec-title">${esc(l.name)}</span>
                <span class="rec-meta">${l.is_default ? 'Auffanglager<span class="sep">·</span>' : ''}${zahl(l.positionen)} Positionen</span>
            </span>
            <span class="rec-go" aria-hidden="true">›</span>
        </button>`).join('')}</div>`;

    const suche = state.itemSuche.toLowerCase();
    const items = state.katalog.items.filter((i) => !suche || i.name.toLowerCase().includes(suche));
    const katName = Object.fromEntries(state.katalog.kategorien.map((k) => [k.id, k.name]));
    document.getElementById('csItemKopf').textContent =
        `${zahl(items.length)} von ${zahl(state.katalog.items.length)}`;
    const itemEl = document.getElementById('csItemListe');
    if (!items.length) {
        zeigeLeer(itemEl, suche ? 'Kein Gegenstand mit diesem Namen.'
                                : 'Noch keine Gegenstände. Sie entstehen beim Anlegen einer Position.');
        return;
    }
    itemEl.innerHTML = `<div class="rec-list">${items.slice(0, 300).map((i) => `
        <button type="button" class="rec-row" data-item="${i.id}">
            <span class="rec-mark" style="--tone:var(--cs2-ton)">${esc(i.name.slice(0, 1).toUpperCase())}</span>
            <span class="rec-main">
                <span class="rec-title">${esc(i.name)}</span>
                <span class="rec-meta">${esc(katName[i.category_id] || '?')}<span class="sep">·</span>${zahl(i.positionen)} Positionen</span>
            </span>
            <span class="rec-go" aria-hidden="true">›</span>
        </button>`).join('')}</div>`;
}

async function lagerDialog(id) {
    const lager = state.katalog.lager.find((l) => l.id === id);
    if (!lager) return;
    const neu = await askPrompt({
        title: 'Lager umbenennen', text: 'Wie soll es heißen?', value: lager.name,
        ok: 'Umbenennen',
    });
    if (neu && neu.trim() && neu.trim() !== lager.name) {
        try { await API.lagerName(id, neu.trim()); melde('success', 'Umbenannt'); await neuLaden(); }
        catch (e) { melde('error', e.message); }
        return;
    }
    if (neu !== null) return;
    if (lager.is_default) return;
    const weg = await askConfirm({
        title: 'Lager löschen?',
        text: `„${lager.name}“ entfernen. Die ${lager.positionen} Position(en) darin ziehen ins Auffanglager — gelöscht wird nichts davon.`,
        confirmText: 'Löschen', danger: true,
    });
    if (!weg) return;
    try {
        const r = await API.lagerWeg(id);
        melde('success', r.umgezogen ? `${r.umgezogen} Position(en) umgezogen` : 'Lager gelöscht');
        await neuLaden();
    } catch (e) { melde('error', e.message); }
}

async function itemDialog(id) {
    const item = state.katalog.items.find((i) => i.id === id);
    if (!item) return;
    const neu = await askPrompt({
        title: 'Gegenstand umbenennen',
        text: item.positionen
            ? `Der neue Name gilt sofort für alle ${item.positionen} Position(en).`
            : 'Zu diesem Gegenstand gibt es noch keine Position.',
        value: item.name, ok: 'Umbenennen',
    });
    if (neu && neu.trim() && neu.trim() !== item.name) {
        try { await API.itemName(id, neu.trim()); melde('success', 'Umbenannt'); await neuLaden(); }
        catch (e) { melde('error', e.message); }
        return;
    }
    if (neu !== null || item.positionen) return;
    const weg = await askConfirm({
        title: 'Gegenstand löschen?', text: `„${item.name}“ aus der Liste nehmen.`,
        confirmText: 'Löschen', danger: true,
    });
    if (!weg) return;
    try { await API.itemWeg(id); melde('success', 'Gelöscht'); await neuLaden(); }
    catch (e) { melde('error', e.message); }
}

/* ---------------------------------------------------------------- Formular */

function formular(position) {
    const k = state.katalog;
    const istNeu = !position;
    const gewaehlteKat = position ? position.category_id : k.kategorien[0]?.id;

    const optionen = (liste, aktiv) => liste.map((e) =>
        `<option value="${e.id}"${String(e.id) === String(aktiv) ? ' selected' : ''}>${esc(e.name)}</option>`).join('');

    const html = `<form class="cs-form" id="csForm">
        <div class="cs-form-reihe">
            <label><span class="cs-label">Kategorie</span>
                <select name="category_id"${istNeu ? '' : ' disabled'}>${optionen(k.kategorien, gewaehlteKat)}</select>
            </label>
            <label><span class="cs-label">Lager</span>
                <select name="storage_id">${optionen(k.lager, position ? position.storage_id : k.lager[0]?.id)}</select>
            </label>
        </div>
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
            <label><input type="checkbox" name="playskin"${position && position.playskin ? ' checked' : ''}> Wird selbst gespielt</label>
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
       Case hat keine Abnutzung — das Feld dafuer stehen zu lassen und die
       Eingabe hinterher zu verwerfen, waere eine Frage ohne Antwort. */
    const regelnAnwenden = () => {
        const kat = k.kategorien.find((x) => String(x.id) === String(katFeld.value));
        if (!kat) return;
        form.querySelector('[name=wear]').closest('label').hidden = !kat.supports_wear;
        form.querySelector('[name=stattrak]').closest('label').hidden = !kat.supports_stattrak;
        form.querySelector('[name=playskin]').closest('label').hidden = !kat.supports_playskin;
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
            storage_id: Number(f.get('storage_id')) || null,
            wear: f.get('wear') || null,
            stattrak: form.querySelector('[name=stattrak]').checked,
            playskin: form.querySelector('[name=playskin]').checked,
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

async function oeffnePosition(id) {
    try {
        const d = await API.liste('?' + frageKette().concat(
            'sortierung=' + state.filter.sortierung).join('&'));
        const p = d.positionen.find((x) => x.id === id);
        if (p) formular(p);
    } catch (e) { melde('error', e.message); }
}

/* ------------------------------------------------------------------- Start */

async function neuLaden() {
    state.katalog = await API.katalog();
    zeichneFilterKnoepfe();
    await ladeBestand();
    if (!document.getElementById('tab-verwaltung').hidden) zeichneVerwaltung();
    if (!document.getElementById('tab-pflege').hidden) ladePflege();
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
    document.getElementById('csSort').addEventListener('change', (ev) => {
        state.filter.sortierung = ev.target.value;
        ladeBestand();
    });
    document.getElementById('csFaellig').addEventListener('click', (ev) => {
        state.filter.faellig = !state.filter.faellig;
        ev.target.classList.toggle('active', state.filter.faellig);
        ladeBestand();
    });
    document.getElementById('csNeu').addEventListener('click', () => formular());
    document.getElementById('csSnapshot').addEventListener('click', standFesthalten);
    document.getElementById('csLagerNeu').addEventListener('click', async () => {
        const name = await askPrompt({ title: 'Lager anlegen', text: 'Wie soll es heißen?', ok: 'Anlegen' });
        if (!name || !name.trim()) return;
        try { await API.lagerNeu(name.trim()); melde('success', 'Angelegt'); await neuLaden(); }
        catch (e) { melde('error', e.message); }
    });
    document.getElementById('csItemSuche').addEventListener('input', (ev) => {
        state.itemSuche = ev.target.value.trim();
        zeichneVerwaltung();
    });

    document.getElementById('csAufteilungWahl').addEventListener('click', (ev) => {
        const knopf = ev.target.closest('[data-dim]');
        if (!knopf) return;
        state.aufteilung = knopf.dataset.dim;
        document.querySelectorAll('#csAufteilungWahl button').forEach(
            (b) => b.classList.toggle('active', b === knopf));
        ladeBestandStill();
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

    // Eine Zeile oeffnet ihren Vorgang. Kein Papierkorb an jeder Zeile: er
    // waere das groesste Ziel fuer den seltensten Handgriff.
    document.addEventListener('click', (ev) => {
        const pos = ev.target.closest('[data-position]');
        if (pos) { oeffnePosition(Number(pos.dataset.position)); return; }
        const lag = ev.target.closest('[data-lager]');
        if (lag) { lagerDialog(Number(lag.dataset.lager)); return; }
        const item = ev.target.closest('[data-item]');
        if (item) { itemDialog(Number(item.dataset.item)); }
    });

    // Pflege: Eingabe bestaetigen und weiter zur naechsten Zeile.
    document.addEventListener('keydown', (ev) => {
        if (ev.key !== 'Enter') return;
        const zeile = ev.target.closest('.cs-pflege-zeile');
        if (!zeile) return;
        ev.preventDefault();
        const wert = ev.target.value.trim();
        if (!wert) {
            const offen = [...document.querySelectorAll('.cs-pflege-zeile:not(.is-erledigt) input')];
            const i = offen.indexOf(ev.target);
            if (i >= 0 && offen[i + 1]) offen[i + 1].focus();
            return;
        }
        preisSpeichern(zeile, wert);
    });

    if (window.VexRange) {
        VexRange.mount(document.getElementById('csRange'), {
            onChange: (r) => { state.tage = r.fetchDays || r.days || 365; ladeVerlauf(); },
        });
    }

    try {
        state.katalog = await API.katalog();
    } catch (e) {
        zeigeFehler(document.getElementById('csListe'),
            'Die Stammdaten konnten nicht geladen werden: ' + e.message,
            () => location.reload());
        return;
    }
    zeichneFilterKnoepfe();
    zeigeReiter((location.hash || '').replace('#', '') || 'bestand', true);
    await ladeBestand();
});
