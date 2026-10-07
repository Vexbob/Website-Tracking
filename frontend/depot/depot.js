/* depot.js — v2.39.0 (Modul im Bau)
 *
 * Der Trade-Republic-Kontoauszug, gelesen und geprueft (services/depot_import.py),
 * dazu Tagesschlusskurse (services/depot_kurse.py). Gerechnet wird im Server
 * (services/depot_rechnung.py): Depotwert, Einstand, Ergebnis seit Beginn,
 * Realisiert. Die Seite zeichnet nur.
 *
 * Kurse holt die Seite selbst nach, wenn der Server sagt, dass welche offen
 * sind (``kurse_offen``) -- in kleinen Schritten, bis ``more`` falsch ist.
 *
 * Ein neuer Auszug geht immer erst durch die Vorschau: Zeitraum, Summen,
 * Pruefung und wie viele vorhandene Buchungen er ersetzen wuerde.
 */
const API = {
    uebersicht: () => apiCall('/api/depot/uebersicht'),
    statistik:  (q) => apiCall('/api/depot/statistik?' + q),
    buchungen:  (q) => apiCall('/api/depot/buchungen?' + q),
    auszuege:   () => apiCall('/api/depot/imports'),
    lesen:      (f, speichern) => { const fd = new FormData(); fd.append('file', f);
                    return apiCall('/api/depot/import' + (speichern ? '?speichern=true' : ''), { method: 'POST', body: fd }); },
    weg:        (id) => apiCall('/api/depot/imports/' + id, { method: 'DELETE' }),
    kurse:      () => apiCall('/api/depot/kurse', { method: 'POST' }),
    papier:     (isin) => apiCall('/api/depot/wertpapier/' + encodeURIComponent(isin)),
    stueck:     (isin, body) => apiCall('/api/depot/stueck/' + encodeURIComponent(isin),
                    { method: 'PUT', body: JSON.stringify(body) }),
    stueckWeg:  (isin) => apiCall('/api/depot/stueck/' + encodeURIComponent(isin), { method: 'DELETE' }),
};

const esc = (v) => String(v == null ? '' : v)
    .replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const ikon = (n, g) => window.VexIkon ? VexIkon.svg(n, g || 18) : '';
const eur = (v) => (Number(v) || 0).toLocaleString('de-DE', { style: 'currency', currency: 'EUR' });
const eurVz = (v) => (Number(v) > 0 ? '+' : '') + eur(v);
const tag = (iso) => iso ? new Date(iso + (iso.length === 10 ? 'T12:00:00' : '')).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' }) : '–';
const monatJahr = (iso) => iso ? new Date(iso + 'T12:00:00').toLocaleDateString('de-DE', { month: 'long', year: 'numeric' }) : '';
const stueck = (v) => Number(v).toLocaleString('de-DE', { maximumFractionDigits: 6 });
const kursText = (v) => Number(v).toLocaleString('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: v < 10 ? 3 : 2 });
const prozent = (v) => (v > 0 ? '+' : '') + (v * 100).toLocaleString('de-DE', { maximumFractionDigits: 1, minimumFractionDigits: 1 }) + ' %';
const vzKlasse = (v) => v < 0 ? 'dp-minus' : (v > 0 ? 'dp-plus' : '');

function melde(text, fehler) {
    if (window.Toast) { fehler ? Toast.error(text) : Toast.success(text); return; }
    if (fehler) askAlert({ title: 'Das ging nicht', text });
}

const zustand = { filter: '', offset: 0, buchungen: [], statistikDa: false, buchungenDa: false,
                  u: null, kurseLaufen: false, kurseVersucht: false, kursFehler: null };

/* ------------------------------------------------------------ Diagramme
 * Farben aus den Tokens (DESIGN 7): der Sparplan traegt den Modulton, die
 * uebrigen Reihen die Diagrammfarben. Kein senkrechtes Gitter, keine Rahmen. */
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const ton = {
    depot: () => cssVar('--figure') || cssVar('--m-depot'),
    kauf: () => cssVar('--chart-2'), verkauf: () => cssVar('--chart-1'),
    zinsen: () => cssVar('--chart-6'), ertrag: () => cssVar('--chart-1'),
    einstand: () => cssVar('--chart-2'),
    // Gewinn und Verlust tragen die Statusfarben -- Farbe mit Bedeutung.
    gut: () => cssVar('--ok'), schlecht: () => cssVar('--warn'),
};
const RING_TOENE = ['--m-depot', '--chart-2', '--chart-1', '--chart-3', '--chart-5', '--chart-6'];
const charts = {};
/* Ein Ton mit Deckkraft fuer Diagrammflaechen. color-mix() kennt die
   Leinwand nicht -- deshalb aus dem Hexwert, wie in Sparziel und Gesundheit. */
function tonAlpha(farbe, a) {
    const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(farbe || '').trim());
    if (!m) return farbe;
    let h = m[1];
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
}
const MONATE_KURZ = ['Jan.', 'Feb.', 'März', 'Apr.', 'Mai', 'Juni', 'Juli', 'Aug.', 'Sept.', 'Okt.', 'Nov.', 'Dez.'];
const monatKurz = (ym) => { const [j, m] = ym.split('-'); return MONATE_KURZ[Number(m) - 1] + ' ' + j.slice(2); };
// Achsen: ganze Euro mit Tausenderpunkt, ohne Cent.
const eurKurz = (v) => Math.round(v).toLocaleString('de-DE') + ' €';

function chartBasis(extra) {
    const o = {
        maintainAspectRatio: false, responsive: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: cssVar('--surface-3'), borderColor: cssVar('--line-strong'), borderWidth: 1,
                titleColor: cssVar('--text-1'), bodyColor: cssVar('--text-2'),
                cornerRadius: 12, padding: 10, boxPadding: 4,
                callbacks: { label: (c) => ` ${c.dataset.label}: ${eur(c.parsed.y)}` },
            },
        },
        scales: {
            x: { ticks: { color: cssVar('--chart-axis'), font: { size: 11 }, maxRotation: 0, autoSkip: true, autoSkipPadding: 14 },
                 grid: { display: false }, border: { display: false } },
            y: { ticks: { color: cssVar('--chart-axis'), font: { size: 11 }, maxTicksLimit: 5, callback: (v) => eurKurz(v) },
                 // Die Nulllinie traegt, alle anderen Linien treten zurueck.
                 grid: { color: (c) => c.tick && c.tick.value === 0 ? cssVar('--line-strong') : cssVar('--chart-grid') },
                 border: { display: false } },
        },
    };
    return Object.assign(o, extra || {});
}
function zeichne(key, id, config) {
    if (charts[key]) charts[key].destroy();
    const el = document.getElementById(id);
    if (el) charts[key] = new Chart(el, config);
}
function legende(id, eintraege) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = eintraege.map(([l, t]) => `<span><i style="--ton:${t}"></i>${esc(l)}</span>`).join('');
}

/* Der Verlauf in der Buehne: Depotwert und Einstand je Handelstag. Der
   Abstand der beiden ist, was nicht verkauft im Depot liegt (unrealisiert). */
const MONATE_LANG_KURZ = (iso) => monatKurz(iso.slice(0, 7));
async function zeichneVerlauf(punkte) {
    try { await VexCharts.bereit(); } catch (e) { return; }
    const labels = punkte.map(p => MONATE_LANG_KURZ(p.datum));
    const o = chartBasis();
    o.scales.x.ticks.maxTicksLimit = 6;
    VexCharts.applyFullDates(o, punkte.map(p => VexCharts.fullDay(p.datum)));
    zeichne('verlauf', 'dpChartVerlauf', {
        type: 'line',
        data: { labels, datasets: [
            { label: 'Depotwert', data: punkte.map(p => p.wert), borderColor: ton.depot(),
              backgroundColor: tonAlpha(ton.depot(), 0.14), fill: 'origin', tension: 0.25, pointRadius: 0, borderWidth: 2,
              order: VexCharts.ORDER.VALUE },
            { label: 'Einstand', data: punkte.map(p => p.einstand), borderColor: ton.einstand(),
              fill: false, tension: 0, stepped: true, pointRadius: 0, borderWidth: 1.5, borderDash: [5, 4],
              order: VexCharts.ORDER.CONTEXT },
        ] },
        options: o,
    });
    legende('dpVerlaufLegende', [['Depotwert', 'var(--figure, var(--m-depot))'], ['Einstand', 'var(--chart-2)']]);
}

/* Balken in Gewinn- und Verlustfarbe: je Wert seine eigene. */
function plusMinusBalken(label, daten) {
    return Object.assign({ type: 'bar', label, data: daten, order: VexCharts.ORDER.VALUE, maxBarThickness: 32,
        backgroundColor: daten.map(v => (v || 0) < 0 ? ton.schlecht() : ton.gut()) }, VexCharts.balken(4));
}

/* -------------------------------------------------------------- Statistik */
function initStatistik() {
    zustand.statistikDa = true;
    // Ein Jahr, nicht die Kontoeinstellung: 30 Tage zeigten beim Depot
    // einen einzigen Sparplan-Termin.
    VexRange.mount(document.getElementById('dpRange'), {
        preset: '365', onChange: (r) => ladeStatistik(r),
    });
}

async function ladeStatistik(r) {
    const q = new URLSearchParams();
    if (r.from) q.set('von', r.from);
    if (r.to) q.set('bis', r.to);
    let st;
    try { st = await API.statistik(q.toString()); await VexCharts.bereit(); }
    catch (e) {
        document.getElementById('dpKennzahlen').innerHTML =
            '<p class="dp-leer-satz">Die Statistik konnte nicht geladen werden.</p>';
        return;
    }
    if (st.leer) return;
    document.getElementById('dpStatInfo').textContent = `${tag(st.von)} – ${tag(st.bis)}`;
    const k = st.kennzahlen;
    const kachel = (l, v, klein) => `<div class="dp-kz-kachel"><span>${esc(l)}</span><strong>${v}</strong>${klein ? `<small>${esc(klein)}</small>` : ''}</div>`;
    // Beginnt der Zeitraum vor dem Verlauf, zaehlt das Ergebnis ab dessen
    // Beginn -- die Kachel sagt das, statt eine kleinere Zahl zu behaupten.
    const ergebnisKlein = k.ergebnis == null ? 'kein Verlauf in diesem Zeitraum'
        : (k.ergebnis_ab && k.ergebnis_ab >= st.von ? 'ab ' + tag(k.ergebnis_ab) : 'Wert, Cash und Verkäufe');
    document.getElementById('dpKennzahlen').innerHTML = [
        kachel('Ergebnis', k.ergebnis == null ? '–' : `<span class="${vzKlasse(k.ergebnis)}">${esc(eurVz(k.ergebnis))}</span>`, ergebnisKlein),
        kachel('Sparplan im Monat', esc(eur(k.sparplan_schnitt)), k.sparplan_monate ? `Ø über ${k.sparplan_monate} Monate` : 'kein Sparplan im Zeitraum'),
        kachel('Realisiert', `<span class="${vzKlasse(k.realisiert)}">${esc(eurVz(k.realisiert))}</span>`, 'Verkäufe im Zeitraum'),
        kachel('Zinsen und Erträge', esc(eur(k.ertraege_zinsen)), ''),
    ].join('');

    const labels = st.monate.map(m => monatKurz(m.monat));
    const voll = st.monate.map(m => VexCharts.fullMonth(m.monat));

    // Ergebnis je Monat: was das ganze Depot im Monat gewonnen oder verloren
    // hat, Ein- und Auszahlungen herausgerechnet. Vor dem Verlauf bleibt leer.
    let oe = chartBasis();
    VexCharts.applyFullDates(oe, voll);
    oe.plugins.tooltip.callbacks.label = (c) => c.parsed.y == null ? ' kein Verlauf' : ` Ergebnis: ${eurVz(c.parsed.y)}`;
    zeichne('ergebnis', 'dpChartErgebnis', { data: { labels, datasets: [
        plusMinusBalken('Ergebnis', st.monate.map(m => m.ergebnis)),
    ] }, options: oe });
    const mitWert = st.monate.filter(m => m.ergebnis != null);
    const plus = mitWert.filter(m => m.ergebnis > 0).length;
    document.getElementById('dpErgMonSub').textContent = mitWert.length
        ? `${plus} von ${mitWert.length} Monaten im Plus` : 'Verlauf erst ab ' + tag(st.verlauf_ab);
    const balken = (label, daten, farbe, stapel) => Object.assign(
        { type: 'bar', label, data: daten, backgroundColor: farbe, stack: stapel,
          order: VexCharts.ORDER.VALUE, maxBarThickness: 28 }, VexCharts.balken(4));
    let o = chartBasis();
    o.scales.x.stacked = true; o.scales.y.stacked = true;
    VexCharts.applyFullDates(o, voll);
    zeichne('monate', 'dpChartMonate', { data: { labels, datasets: [
        balken('Sparplan', st.monate.map(m => m.sparplan), ton.depot(), 'kauf'),
        balken('Einzelkauf', st.monate.map(m => m.kauf), ton.kauf(), 'kauf'),
        balken('Verkauf', st.monate.map(m => m.verkauf), ton.verkauf(), 'verkauf'),
    ] }, options: o });
    legende('dpMonateLegende', [['Sparplan', 'var(--figure, var(--m-depot))'], ['Einzelkauf', 'var(--chart-2)'], ['Verkauf', 'var(--chart-1)']]);

    o = chartBasis();
    o.scales.x.stacked = true; o.scales.y.stacked = true;
    o.scales.y.ticks.callback = (v) => eur(v).replace(/,00\s/, ' ');
    VexCharts.applyFullDates(o, voll);
    zeichne('zinsen', 'dpChartZinsen', { data: { labels, datasets: [
        balken('Zinsen', st.monate.map(m => m.zinsen), ton.zinsen(), 'z'),
        balken('Erträge', st.monate.map(m => m.ertraege), ton.ertrag(), 'z'),
    ] }, options: o });
    // Die Legende traegt die Summen: welche Farbe was ist und wie viel es war.
    const summe = (k) => st.monate.reduce((s, m) => s + m[k], 0);
    legende('dpZinsLegende', [['Zinsen ' + eur(summe('zinsen')), 'var(--chart-6)'],
                              ['Erträge ' + eur(summe('ertraege')), 'var(--chart-1)']]);

    zeichneSparplan(st.sparplan);
    zeichneErgebnisse(st.ergebnisse);
}

/* Wohin der Sparplan geht: ein Ring bis sechs Wertpapiere, darueber nur
   die Rangliste (DESIGN: ein Ring ist ab etwa sechs Posten nicht lesbar). */
function zeichneSparplan(liste) {
    const summe = liste.reduce((s, x) => s + x.summe, 0);
    document.getElementById('dpSparSub').textContent = summe ? 'zusammen ' + eur(summe) : '';
    const ring = document.querySelector('.dp-ring');
    const box = document.getElementById('dpSparListe');
    if (!liste.length) {
        ring.hidden = true;
        box.innerHTML = '<p class="dp-leer-satz">Kein Sparplan in diesem Zeitraum.</p>';
        return;
    }
    const mitRing = liste.length <= 6;
    ring.hidden = !mitRing;
    const toene = liste.map((_, i) => RING_TOENE[i % RING_TOENE.length]);
    const max = liste[0].summe;
    box.innerHTML = liste.map((x, i) => `<div class="rank-row" style="--tone:var(${toene[i]})">
        <span class="rank-mark"></span>
        <span class="rank-name">${esc(x.name)}</span>
        <span class="rank-val">${esc(eur(x.summe))}</span>
        <span class="rank-bar"><i style="width:${(x.summe / max * 100).toFixed(1)}%"></i></span>
        <span class="rank-sub">${(x.summe / summe * 100).toLocaleString('de-DE', { maximumFractionDigits: 0 })} % des Sparplans</span>
    </div>`).join('');
    if (!mitRing) { if (charts.sparplan) { charts.sparplan.destroy(); delete charts.sparplan; } return; }
    zeichne('sparplan', 'dpChartSparplan', {
        type: 'doughnut',
        data: { labels: liste.map(x => x.name), datasets: [{
            data: liste.map(x => x.summe), backgroundColor: toene.map(t => cssVar(t)),
            borderColor: cssVar('--surface-1'), borderWidth: 2, hoverOffset: 4,
        }] },
        options: { maintainAspectRatio: false, cutout: '68%',
                   plugins: { legend: { display: false }, tooltip: Object.assign(chartBasis().plugins.tooltip,
                       { callbacks: { label: (c) => ` ${eur(c.parsed)} · ${(c.parsed / summe * 100).toFixed(0)} %` } }) } },
    });
}

function zeichneErgebnisse(liste) {
    const box = document.getElementById('dpErgebnisse');
    if (!liste.length) {
        box.innerHTML = '<p class="dp-leer-satz">In diesem Zeitraum wurde nichts verkauft.</p>';
        document.getElementById('dpErgSub').textContent = '';
        return;
    }
    const summe = liste.reduce((s, x) => s + x.ergebnis, 0);
    document.getElementById('dpErgSub').textContent = `${liste.length} Wertpapiere · zusammen ${eurVz(summe)}`;
    const max = Math.max(...liste.map(x => Math.abs(x.ergebnis))) || 1;
    box.innerHTML = liste.map(x => `<div class="rank-row" style="--tone:var(${x.ergebnis < 0 ? '--warn' : '--ok'})">
        <span class="rank-mark"></span>
        <span class="rank-name">${esc(x.name)}</span>
        <span class="rank-val ${x.ergebnis < 0 ? 'dp-minus' : 'dp-plus'}">${esc(eurVz(x.ergebnis))}</span>
        <span class="rank-bar"><i style="width:${(Math.abs(x.ergebnis) / max * 100).toFixed(1)}%"></i></span>
        <span class="rank-sub">${x.im_bestand ? 'teilweise verkauft, ' : ''}zuletzt ${esc(tag(x.letzte))}</span>
    </div>`).join('');
}

/* ---------------------------------------------------------------- Reiter */
const REITER = ['ueberblick', 'statistik', 'buchungen'];
function reiter(t) {
    if (REITER.indexOf(t) < 0) t = REITER[0];
    document.querySelectorAll('#dpInhalt .tabs .tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === t));
    REITER.forEach(id => { document.getElementById('tab-' + id).hidden = id !== t; });
    history.replaceState(null, '', t === REITER[0] ? location.pathname : '#' + t);
    if (t === 'statistik' && !zustand.statistikDa) initStatistik();
    if (t === 'buchungen' && !zustand.buchungenDa) { zustand.buchungenDa = true; ladeBuchungen(); ladeAuszuege(); }
}

/* ---------------------------------------------------------------- Laden */
async function laden() {
    let u;
    try { u = await API.uebersicht(); }
    catch (e) {
        // Ein gescheiterter Abruf ist kein leeres Depot.
        document.getElementById('dpLaden').hidden = true;
        const f = document.getElementById('dpFehler');
        f.hidden = false;
        f.innerHTML = `<div class="v-card"><div class="empty is-error"><p class="empty-text">Das Depot konnte nicht geladen werden.</p>
            <button type="button" class="v-btn" id="dpNochmal">Erneut versuchen</button></div></div>`;
        document.getElementById('dpNochmal').onclick = () => { f.hidden = true; laden(); };
        return;
    }
    zustand.u = u;
    document.getElementById('dpLaden').hidden = true;
    document.getElementById('dpLeer').hidden = !u.leer;
    document.getElementById('dpInhalt').hidden = !!u.leer;
    if (u.leer) return;
    zeichneBuehne(u);
    zeichneWertpapiere(u.wertpapiere);
    zeichneVerlauf(u.verlauf || []);
    zeichneJahre(u.realisiert_jahre || []);
    // Nach einem neuen Auszug zeichnen die anderen Reiter beim naechsten
    // Oeffnen neu, statt alte Zahlen stehen zu lassen.
    zustand.offset = 0; zustand.buchungen = [];
    if (zustand.buchungenDa) { ladeBuchungen(); ladeAuszuege(); }
    if (zustand.statistikDa) { document.getElementById('dpRange').innerHTML = ''; zustand.statistikDa = false; }
    reiter(location.hash.slice(1));
    if (u.kurse_offen && !zustand.kurseLaufen && !zustand.kurseVersucht) kurseHolen();
}

/* Kurse in kleinen Schritten nachholen (der Server deckelt je Aufruf), dann
   einmal neu laden. Hoechstens einmal je Seitenaufruf -- eine Quelle, die
   heute nichts hergibt, gibt beim zweiten Versuch auch nichts her. */
async function kurseHolen() {
    zustand.kurseLaufen = true; zustand.kursFehler = null;
    zeichneStand();
    for (let i = 0; i < 20; i++) {
        let r;
        try { r = await API.kurse(); }
        catch (e) { zustand.kursFehler = e.message || 'Die Kurse konnten nicht geholt werden.'; break; }
        if (r.fehler) zustand.kursFehler = r.fehler;
        if (!r.more) break;
        await new Promise(ok => setTimeout(ok, 800));
    }
    zustand.kurseLaufen = false; zustand.kurseVersucht = true;
    await laden();
}

function heldText(wert) {
    // Ganze Euro gross, Cent und Zeichen klein -- wie jede Heldenzahl.
    const text = eur(wert);
    const m = text.match(/^(.*?)(,\d\d\s*€)$/);
    return m ? `${esc(m[1])}<span class="v-held-rest">${esc(m[2])}</span>` : esc(text);
}

function zeichneStand() {
    const u = zustand.u, el = document.getElementById('dpStand');
    if (!u || !el) return;
    const d = u.depot;
    if (zustand.kurseLaufen) { el.innerHTML = `<span class="dp-laeuft"></span>Kurse werden geholt …`; return; }
    const teile = [];
    if (d.kurse_stand) teile.push('Kurse vom ' + tag(d.kurse_stand));
    if (zustand.kursFehler) teile.push(`<span class="dp-warn-text">${esc(zustand.kursFehler)}</span>`);
    el.innerHTML = teile.join(' · ');
}

function zeichneBuehne(u) {
    const d = u.depot;
    const wartet = !d.kurse_stand && u.kurse_offen && !zustand.kurseVersucht;
    const held = document.getElementById('dpHeld');
    held.innerHTML = wartet ? '<span class="skel skel-line dp-held-skel"></span>' : heldText(d.wert);
    document.getElementById('dpMarke').textContent = 'Depotwert';
    document.getElementById('dpUnter').innerHTML = wartet ? '' :
        `<span class="${vzKlasse(d.ergebnis)}">${esc(eurVz(d.ergebnis))}</span> Ergebnis seit ${esc(monatJahr(u.von))}`;
    zeichneStand();
    document.getElementById('dpVerlaufTitel').textContent = 'Seit ' + monatJahr(d.verlauf_ab);

    // Was nicht zum Kurs gerechnet ist, steht beim Wert -- nicht weiter unten.
    const bestand = u.wertpapiere.filter(w => w.im_bestand);
    const ohneStueck = bestand.filter(w => w.stueck == null);
    const ohneKurs = bestand.filter(w => w.stueck != null && w.kurs == null);
    const hinweise = [];
    ohneStueck.forEach(w => hinweise.push(`<div class="dp-b-hinweis">
        <span><strong>${esc(w.name)}</strong>: ${w.stueck_fehler ? esc(w.stueck_fehler) : 'Stückzahl fehlt'} – zum Einstand gerechnet.</span>
        <button type="button" class="v-btn v-btn--sm" data-stueck="${esc(w.isin)}">Stück eintragen</button></div>`));
    if (ohneKurs.length && !wartet) hinweise.push(`<div class="dp-b-hinweis"><span>Ohne Kurs, zum Einstand gerechnet: ${esc(ohneKurs.map(w => w.name).join(', '))}.</span></div>`);
    const box = document.getElementById('dpHinweise');
    box.innerHTML = hinweise.join('');
    box.querySelectorAll('[data-stueck]').forEach(b => b.addEventListener('click', () =>
        dlgStueck(u.wertpapiere.find(w => w.isin === b.dataset.stueck))));

    const a = u.arten || {};
    const summe = (...arten) => arten.reduce((s, k) => s + ((a[k] && a[k].summe) || 0), 0);
    const zahl = (l, v, klasse) => `<div><dt>${esc(l)}</dt><dd class="${klasse || ''}">${esc(klasse ? eurVz(v) : eur(v))}</dd></div>`;
    document.getElementById('dpZahlen').innerHTML = [
        zahl('Einstand', d.einstand),
        zahl('Unrealisiert', d.unrealisiert, vzKlasse(d.unrealisiert) || ' '),
        zahl('Realisiert', d.realisiert, vzKlasse(d.realisiert) || ' '),
        zahl('Erträge und Zinsen', summe('ertrag', 'zinsen', 'praemie', 'geschenk', 'steuer')),
        zahl('Cash', d.cash),
        // Wer mehr entnommen als eingezahlt hat, liest sonst ein Minus vor
        // „eingezahlt“ -- dieselbe Zahl, richtig benannt.
        d.netto_eingezahlt < 0 ? zahl('Netto entnommen', -d.netto_eingezahlt) : zahl('Netto eingezahlt', d.netto_eingezahlt),
    ].join('');
}

function zeichneWertpapiere(liste) {
    const bestand = liste.filter(w => w.im_bestand);
    const verkauft = liste.filter(w => !w.im_bestand);
    const wertVon = (w) => w.wert != null ? w.wert : w.einstand;
    const gesamt = bestand.reduce((s, w) => s + (wertVon(w) || 0), 0) || 1;
    const mitRing = bestand.length > 1 && bestand.length <= 6;
    const toene = bestand.map((_, i) => RING_TOENE[i % RING_TOENE.length]);

    const bestandZeile = (w, i) => {
        const meta = w.stueck != null
            ? `${stueck(w.stueck)} Stück${w.stueck_quelle === 'kurse' ? ' (berechnet)' : ''}${w.kurs != null ? ' · ' + kursText(w.kurs) : ''}`
            : 'Stückzahl fehlt';
        const anteil = (wertVon(w) / gesamt * 100).toLocaleString('de-DE', { maximumFractionDigits: 0 }) + ' %';
        const unter = w.unrealisiert != null && w.einstand
            ? `<span class="rec-sub ${vzKlasse(w.unrealisiert)}">${esc(eurVz(w.unrealisiert))} · ${esc(prozent(w.unrealisiert / w.einstand))}</span>`
            : `<span class="rec-sub">zum Einstand</span>`;
        return `<button type="button" class="rec-row" data-isin="${esc(w.isin)}" style="--tone:var(${toene[i]})">
            <span class="rec-mark dp-farbmarke"></span>
            <span class="rec-main"><span class="rec-title">${esc(w.name)}</span><span class="rec-meta">${esc(meta)} · ${esc(anteil)}</span></span>
            <span class="rec-side"><span class="rec-val">${esc(eur(wertVon(w)))}</span>${unter}</span>
        </button>`;
    };
    document.getElementById('dpBestand').innerHTML = bestand.length
        ? '<div class="rec-list">' + bestand.map(bestandZeile).join('') + '</div>'
        : '<p class="dp-hinweis">Nichts im Bestand.</p>';
    document.getElementById('dpRingBestand').hidden = !mitRing;
    document.getElementById('dpAufteilung').classList.toggle('dp-ohne-ring', !mitRing);
    // Die Summe vom Server, nicht aus gerundeten Zeilen -- sonst stuende ein
    // Cent neben dem Depotwert darueber.
    const depotwert = zustand.u && zustand.u.depot ? zustand.u.depot.wert : gesamt;
    document.getElementById('dpBestandSub').textContent = bestand.length ? `${bestand.length} Wertpapiere · ${eur(depotwert)}` : '';
    if (mitRing) zeichneBestandRing(bestand.map(wertVon), bestand.map(w => w.name), toene, gesamt);

    const verkauftZeile = (w) => `<button type="button" class="rec-row" data-isin="${esc(w.isin)}">
            <span class="rec-mark">${ikon('depot', 16) || ikon('statistik', 16)}</span>
            <span class="rec-main"><span class="rec-title">${esc(w.name)}</span>
                <span class="rec-meta">${esc(w.ausfuehrungen)} ${w.ausfuehrungen === 1 ? 'Ausführung' : 'Ausführungen'} · zuletzt ${esc(tag(w.letzte))}</span></span>
            <span class="rec-side"><span class="rec-val ${vzKlasse(w.ergebnis)}">${esc(eurVz(w.ergebnis))}</span></span>
        </button>`;
    document.getElementById('dpVerkauft').innerHTML = verkauft.length
        ? '<div class="rec-list">' + verkauft.map(verkauftZeile).join('') + '</div>'
        : '<p class="dp-hinweis">Noch nichts ganz verkauft.</p>';
    document.getElementById('dpVerkauftSub').textContent = verkauft.length ? `· ${verkauft.length} Wertpapiere` : '';
    document.querySelectorAll('#tab-ueberblick [data-isin]').forEach(b => b.addEventListener('click', () =>
        dlgWertpapier(liste.find(w => w.isin === b.dataset.isin))));
}

async function zeichneBestandRing(werte, namen, toene, gesamt) {
    try { await VexCharts.bereit(); } catch (e) { return; }
    zeichne('bestand', 'dpChartBestand', {
        type: 'doughnut',
        data: { labels: namen, datasets: [{ data: werte, backgroundColor: toene.map(t => cssVar(t)),
            borderColor: cssVar('--surface-1'), borderWidth: 2, hoverOffset: 4 }] },
        options: { maintainAspectRatio: false, cutout: '68%',
                   plugins: { legend: { display: false }, tooltip: Object.assign(chartBasis().plugins.tooltip,
                       { callbacks: { label: (c) => ` ${eur(c.parsed)} · ${(c.parsed / gesamt * 100).toFixed(0)} %` } }) } },
    });
}

/* Realisiert je Kalenderjahr: Gewinn gruen, Verlust in der Warnfarbe. */
async function zeichneJahre(jahre) {
    const summe = jahre.reduce((s, j) => s + j.realisiert, 0);
    document.getElementById('dpRealSub').textContent = jahre.length ? 'zusammen ' + eurVz(summe) : '';
    const bestes = jahre.slice().sort((a, b) => b.realisiert - a.realisiert)[0];
    document.getElementById('dpJahreSub').textContent = bestes && bestes.realisiert > 0 ? `am meisten ${bestes.jahr}` : '';
    try { await VexCharts.bereit(); } catch (e) { return; }
    const o = chartBasis();
    o.plugins.tooltip.callbacks.label = (c) => ` Realisiert: ${eurVz(c.parsed.y)}`;
    zeichne('jahre', 'dpChartJahre', { data: { labels: jahre.map(j => String(j.jahr)), datasets: [
        plusMinusBalken('Realisiert', jahre.map(j => j.realisiert)),
    ] }, options: o });
}

/* Eine Buchung: das Wertpapier als Titel, sonst die Art („Einzahlung“) --
   die Rohbeschreibung („Your interest payment“, zwei IBANs) sagt nichts, was
   die Art nicht schon sagt. Im Dialog eines Wertpapiers steht dessen Name
   schon oben, dort traegt die Zeile die Art. */
function buchungZeile(b, imWertpapier) {
    const titel = imWertpapier ? b.art_label : (b.name || b.art_label);
    const meta = [tag(b.datum), (imWertpapier || !b.name) ? '' : b.art_label,
                  b.stueck != null ? stueck(b.stueck) + ' Stück' : ''].filter(Boolean).join(' · ');
    return `<div class="rec-row">
        <span class="rec-main"><span class="rec-title">${esc(titel)}</span><span class="rec-meta">${esc(meta)}</span></span>
        <span class="rec-side"><span class="rec-val ${b.betrag < 0 ? '' : 'dp-plus'}">${esc(eurVz(b.betrag))}</span></span>
    </div>`;
}

async function ladeBuchungen() {
    const box = document.getElementById('dpBuchungen');
    const q = new URLSearchParams({ limit: 50, offset: zustand.offset });
    if (zustand.filter) q.set('art', zustand.filter);
    let r;
    try { r = await API.buchungen(q.toString()); }
    catch (e) { box.innerHTML = '<p class="dp-hinweis">Die Buchungen konnten nicht geladen werden.</p>'; return; }
    zustand.buchungen = zustand.buchungen.concat(r.buchungen);
    zustand.offset += r.buchungen.length;
    box.innerHTML = zustand.buchungen.length
        ? '<div class="rec-list">' + zustand.buchungen.map(x => buchungZeile(x, false)).join('') + '</div>'
        : '<p class="dp-hinweis">Keine Buchungen dieser Art.</p>';
    document.getElementById('dpBuchSub').textContent = `${zustand.buchungen.length} von ${r.gesamt}`;
    document.getElementById('dpMehr').hidden = zustand.buchungen.length >= r.gesamt;
}

async function ladeAuszuege() {
    const box = document.getElementById('dpAuszuege');
    let liste;
    try { liste = await API.auszuege(); }
    catch (e) { box.innerHTML = '<p class="dp-hinweis">Die Auszüge konnten nicht geladen werden.</p>'; return; }
    box.innerHTML = '<div class="rec-list">' + liste.map(a => `
        <button type="button" class="rec-row" data-auszug="${a.id}">
            <span class="rec-mark">${ikon('ablage', 16)}</span>
            <span class="rec-main"><span class="rec-title">${esc(a.dateiname)}</span>
                <span class="rec-meta">${esc(tag(a.zeitraum_von))} – ${esc(tag(a.zeitraum_bis))} · ${a.buchungen} Buchungen · abgelegt ${esc(tag(a.hochgeladen_at.slice(0, 10)))}</span></span>
            <span class="rec-go">${ikon('pfeil', 16)}</span>
        </button>`).join('') + '</div>';
    box.querySelectorAll('[data-auszug]').forEach(b => b.addEventListener('click', () =>
        dlgAuszug(liste.find(a => a.id === Number(b.dataset.auszug)))));
}

/* -------------------------------------------------------------- Dialoge */
async function dlgWertpapier(w) {
    if (!w) return;
    const d = VexModal.open(esc(w.name), '<span class="skel skel-block"></span>', { breit: true });
    const fakten = [
        ['ISIN', w.isin],
        w.im_bestand ? ['Stück', w.stueck == null ? 'fehlt'
            : stueck(w.stueck) + ({ app: ' (laut App)', kurse: ' (berechnet)' }[w.stueck_quelle] || '')] : null,
        w.kurs != null ? ['Kurs', `${kursText(w.kurs)} am ${tag(w.kurs_datum)}`] : null,
        w.im_bestand && w.wert != null ? ['Wert', eur(w.wert)] : null,
        w.im_bestand ? ['Einstand', eur(w.einstand) + (w.kaufkurs ? ` · Ø ${kursText(w.kaufkurs)}` : '')] : null,
        w.im_bestand && w.unrealisiert != null ? ['Unrealisiert', `${eurVz(w.unrealisiert)} · ${prozent(w.unrealisiert / (w.einstand || 1))}`] : null,
        w.realisiert ? ['Realisiert', eurVz(w.realisiert)] : null,
        w.ertraege ? ['Erträge', eur(w.ertraege)] : null,
        ['Gekauft', eur(w.gekauft)], ['Verkauft', eur(w.verkauft)],
    ].filter(Boolean);
    let r, p;
    try {
        [r, p] = await Promise.all([
            API.buchungen(new URLSearchParams({ isin: w.isin, limit: 500 }).toString()),
            API.papier(w.isin).catch(() => null),
        ]);
    } catch (e) { d.root.innerHTML = '<p class="dp-satz">Die Buchungen konnten nicht geladen werden.</p>'; return; }
    const stueckKnopf = w.im_bestand
        ? `<button type="button" class="v-btn v-btn--sm v-btn--ghost" data-stueck>${w.stueck_quelle === 'app' ? 'Stück ändern' : (w.stueck == null ? 'Stück eintragen' : (w.stueck_quelle === 'kurse' ? 'Stück aus der App eintragen' : 'Stück korrigieren'))}</button>` : '';
    const mitKurs = p && p.kurse && p.kurse.length > 1;
    // Woher eine berechnete Stueckzahl kommt, steht direkt dabei.
    const berechnet = w.im_bestand && w.stueck_quelle === 'kurse'
        ? `<p class="dp-hinweis">${w.stueck_geschaetzt} ältere Käufe nennen keine Stückzahl. Für sie gilt Betrag ÷ Schlusskurs am Kauftag, das liegt meist innerhalb von 1&nbsp;% an der App. Genau wird es mit der Zahl aus der App.</p>` : '';
    d.root.innerHTML = `<dl class="dp-fakten">${fakten.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>${berechnet}
        ${stueckKnopf ? `<div class="dp-knopfzeile">${stueckKnopf}</div>` : ''}
        ${mitKurs ? `<div class="dp-papier-kopf"><h4>Kurs und deine Ausführungen</h4><span class="dp-legende" id="dpPapierLegende"></span></div>
            <div class="dp-flaeche dp-flaeche--klein"><canvas id="dpChartPapier" aria-label="Kursverlauf mit Käufen und Verkäufen"></canvas></div>
            <p class="dp-hinweis">Kurse${p.markt ? ' von ' + esc(p.markt) : ''}, Schlusskurs je Tag. Punkte: Ausführungskurs, bei Einzelkäufen samt Gebühr.</p>` : ''}
        <div class="rec-list">${r.buchungen.map(x => buchungZeile(x, true)).join('')}</div>`;
    const knopf = d.root.querySelector('[data-stueck]');
    if (knopf) knopf.onclick = () => { d.close(); dlgStueck(w); };
    if (mitKurs) zeichnePapier(p, w);
}

/* Der Kurs eines Wertpapiers mit den eigenen Ausfuehrungen als Punkte und
   dem Durchschnittskurs als Linie -- daran sieht man, wann man guenstig war. */
async function zeichnePapier(p, w) {
    try { await VexCharts.bereit(); } catch (e) { return; }
    // Ab dem Monat der ersten eigenen Ausfuehrung, soweit es Kurse gibt.
    const ab = (p.ausfuehrungen.length ? p.ausfuehrungen[0].datum : p.kurse[0].datum).slice(0, 7) + '-01';
    let kurse = p.kurse.filter(k => k.datum >= ab);
    if (kurse.length < 2) kurse = p.kurse;
    const index = new Map(kurse.map((k, i) => [k.datum, i]));
    // Eine Ausfuehrung am Wochenende landet auf dem naechsten Handelstag.
    const naechster = (datum) => { const i = kurse.findIndex(k => k.datum >= datum); return i < 0 ? kurse.length - 1 : i; };
    const leer = () => kurse.map(() => null);
    const kauf = leer(), verkauf = leer();
    p.ausfuehrungen.forEach(a => {
        if (a.datum < kurse[0].datum) return;
        const i = index.has(a.datum) ? index.get(a.datum) : naechster(a.datum);
        (a.art === 'verkauf' ? verkauf : kauf)[i] = a.kurs;
    });
    const o = chartBasis();
    o.scales.x.ticks.maxTicksLimit = 5;
    o.scales.y.ticks.callback = (v) => kursText(v);
    o.plugins.tooltip.callbacks.label = (c) => c.parsed.y == null ? null : ` ${c.dataset.label}: ${kursText(c.parsed.y)}`;
    VexCharts.applyFullDates(o, kurse.map(k => VexCharts.fullDay(k.datum)));
    const reihen = [
        { type: 'line', label: 'Kurs', data: kurse.map(k => k.kurs), borderColor: ton.depot(), pointRadius: 0,
          borderWidth: 2, tension: 0.2, order: VexCharts.ORDER.VALUE },
        { type: 'line', label: 'Kauf', data: kauf, showLine: false, pointRadius: 3.5, pointHoverRadius: 5,
          pointBackgroundColor: ton.kauf(), pointBorderColor: ton.kauf(), order: VexCharts.ORDER.TREND },
        { type: 'line', label: 'Verkauf', data: verkauf, showLine: false, pointRadius: 4, pointHoverRadius: 6,
          pointStyle: 'rectRot', pointBackgroundColor: ton.verkauf(), pointBorderColor: ton.verkauf(), order: VexCharts.ORDER.TREND },
    ];
    const leg = [['Kurs', 'var(--figure, var(--m-depot))'], ['Kauf', 'var(--chart-2)'], ['Verkauf', 'var(--chart-1)']];
    if (w.im_bestand && w.kaufkurs) {
        reihen.push({ type: 'line', label: 'Ø Kaufkurs', data: kurse.map(() => w.kaufkurs), borderColor: cssVar('--text-3'),
                      borderDash: [4, 4], borderWidth: 1.5, pointRadius: 0, order: VexCharts.ORDER.CONTEXT });
        leg.push(['Ø Kaufkurs', 'var(--text-3)']);
    }
    zeichne('papier', 'dpChartPapier', { data: { labels: kurse.map(k => MONATE_LANG_KURZ(k.datum)), datasets: reihen }, options: o });
    legende('dpPapierLegende', leg);
}

/* Die Stueckzahl laut App. Der Auszug nennt sie erst ab Juni 2024; fuer eine
   Position von davor rechnet der Server von dieser Zahl aus zurueck. */
function dlgStueck(w) {
    if (!w) return;
    const d = VexModal.open('Stück laut App', `
        <p class="dp-satz">${esc(w.name)}: In der Trade-Republic-App beim Wertpapier unter „Anteile“ ablesen.</p>
        <label class="dp-feld"><span>Stück</span>
            <input type="text" inputmode="decimal" autocomplete="off" id="dpStueckFeld" value="${w.stueck != null ? esc(String(w.stueck).replace('.', ',')) : ''}" placeholder="z. B. 1,234567"></label>
        <p class="dp-warn" id="dpStueckFehler" hidden></p>
        <div class="modal-fuss">
            ${w.stueck_quelle === 'app' ? '<button type="button" class="v-btn v-btn--ghost" data-weg>Zurücksetzen</button>' : ''}
            <button type="button" class="v-btn" data-zu>Abbrechen</button>
            <button type="button" class="v-btn v-btn--primary" data-ok>Speichern</button>
        </div>`, { voll: true });
    const feld = d.root.querySelector('#dpStueckFeld');
    const fehler = d.root.querySelector('#dpStueckFehler');
    if (window.innerWidth > 720) feld.focus();
    d.root.querySelector('[data-zu]').onclick = () => d.close();
    const weg = d.root.querySelector('[data-weg]');
    if (weg) weg.onclick = async () => {
        try { await API.stueckWeg(w.isin); d.close(); melde('Zurückgesetzt'); laden(); }
        catch (e) { fehler.hidden = false; fehler.textContent = e.message || 'Das ging nicht.'; }
    };
    const speichern = async () => {
        // Komma ist das Dezimalzeichen; steht keins da, gilt ein Punkt als solches
        // („1.5“ heisst anderthalb, nicht fuenfzehn).
        const t = String(feld.value).trim();
        const wert = Number(t.includes(',') ? t.replace(/\./g, '').replace(',', '.') : t);
        if (!(wert >= 0) || feld.value.trim() === '') { fehler.hidden = false; fehler.textContent = 'Bitte eine Stückzahl eintragen.'; return; }
        try {
            const r = await API.stueck(w.isin, { stueck: wert });
            if (r.fehler) { fehler.hidden = false; fehler.textContent = r.fehler; return; }
            d.close(); melde('Gespeichert'); laden();
        } catch (e) { fehler.hidden = false; fehler.textContent = e.message || 'Speichern fehlgeschlagen'; }
    };
    d.root.querySelector('[data-ok]').onclick = speichern;
    feld.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); speichern(); } });
}

function dlgAuszug(a) {
    if (!a) return;
    const d = VexModal.open(esc(a.dateiname), `
        <dl class="dp-fakten">
            <dt>Zeitraum</dt><dd>${esc(tag(a.zeitraum_von))} – ${esc(tag(a.zeitraum_bis))}</dd>
            <dt>Buchungen</dt><dd>${a.buchungen}</dd>
            <dt>Endsaldo</dt><dd>${esc(eur(a.endsaldo))}</dd>
            <dt>Abgelegt</dt><dd>${esc(new Date(a.hochgeladen_at).toLocaleString('de-DE'))}</dd>
        </dl>
        <div class="modal-fuss">
            <button type="button" class="v-btn v-btn--danger" data-weg>${ikon('muell', 16)} Löschen</button>
            <button type="button" class="v-btn" data-zu>Schließen</button>
        </div>`);
    d.root.querySelector('[data-zu]').onclick = () => d.close();
    d.root.querySelector('[data-weg]').onclick = async () => {
        if (!await askConfirm({ title: 'Auszug löschen?',
                                text: 'Seine Buchungen verschwinden mit. Was ein späterer Auszug schon ersetzt hat, bleibt.',
                                ok: 'Löschen', danger: true })) return;
        try { await API.weg(a.id); d.close(); melde('Gelöscht'); laden(); }
        catch (e) { melde(e.message || 'Löschen fehlgeschlagen', true); }
    };
}

/* Erst lesen und pruefen, dann uebernehmen. Die Vorschau sagt, was der
   Auszug ersetzen wuerde -- ein Import, der etwas ersetzt, zeigt das vorher. */
async function vorschau(datei) {
    if (!datei) return;
    const d = VexModal.open('Kontoauszug lesen', '<span class="skel skel-block"></span><span class="skel skel-line long"></span>', {});
    let v;
    try { v = await API.lesen(datei, false); }
    catch (e) {
        d.root.innerHTML = `<p class="dp-warn">${esc(e.message || 'Der Auszug ließ sich nicht lesen.')}</p>
            <div class="modal-fuss"><button type="button" class="v-btn" data-zu>Schließen</button></div>`;
        d.root.querySelector('[data-zu]').onclick = () => d.close();
        return;
    }
    const arten = Object.values(v.arten).sort((a, b) => b.anzahl - a.anzahl)
        .map(a => `<dt>${esc(a.label)}</dt><dd>${a.anzahl} · ${esc(eur(a.summe))}</dd>`).join('');
    d.root.innerHTML = `
        <p class="dp-pruef">${ikon('haken', 16)} Jede Buchung gegen den Saldo geprüft, Summen passen zur Kontoübersicht.</p>
        <dl class="dp-fakten">
            <dt>Zeitraum</dt><dd>${esc(tag(v.von))} – ${esc(tag(v.bis))}</dd>
            <dt>Buchungen</dt><dd>${v.anzahl}, ${v.wertpapiere} Wertpapiere</dd>
            <dt>Eingang</dt><dd>${esc(eur(v.summe_ein))}</dd>
            <dt>Ausgang</dt><dd>${esc(eur(v.summe_aus))}</dd>
            <dt>Endsaldo</dt><dd>${esc(eur(v.endsaldo))}</dd>
        </dl>
        <dl class="dp-fakten">${arten}</dl>
        ${v.schon_da ? `<p class="dp-warn">Genau dieser Auszug ist schon übernommen (${esc(tag(v.schon_da.slice(0, 10)))}).</p>`
          : v.ersetzt ? `<p class="dp-warn">Ersetzt ${v.ersetzt} vorhandene Buchungen aus diesem Zeitraum.</p>` : ''}
        <div class="modal-fuss">
            <button type="button" class="v-btn" data-zu>Abbrechen</button>
            ${v.schon_da ? '' : `<button type="button" class="v-btn v-btn--primary" data-ok>Übernehmen</button>`}
        </div>`;
    d.root.querySelector('[data-zu]').onclick = () => d.close();
    const ok = d.root.querySelector('[data-ok]');
    if (ok) ok.onclick = async () => {
        ok.disabled = true;
        try {
            const r = await API.lesen(datei, true);
            d.close();
            melde(`${r.anzahl} Buchungen übernommen`);
            laden();
        } catch (e) { ok.disabled = false; melde(e.message || 'Übernehmen fehlgeschlagen', true); }
    };
}

/* ---------------------------------------------------------------- Start */
document.addEventListener('DOMContentLoaded', () => {
    if (!isLoggedIn()) { location.href = '/private/login.html'; return; }
    document.body.classList.add('ready');
    fetchMe().then(me => { document.getElementById('userLabel').textContent = me.username; }).catch(() => {});
    document.getElementById('logoutBtn').addEventListener('click',
        () => { clearToken(); location.href = '/private/login.html'; });

    const feld = document.getElementById('dpDatei');
    feld.addEventListener('change', () => { const f = feld.files[0]; feld.value = ''; vorschau(f); });
    const zone = document.getElementById('dpDrop');
    zone.addEventListener('click', (e) => { e.preventDefault(); feld.click(); });
    zone.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); feld.click(); } });
    ['dragenter', 'dragover'].forEach(t => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.add('drag'); }));
    ['dragleave', 'drop'].forEach(t => zone.addEventListener(t, () => zone.classList.remove('drag')));
    zone.addEventListener('drop', (e) => { e.preventDefault(); vorschau(e.dataTransfer.files[0]); });
    document.getElementById('dpNeu').addEventListener('click', () => feld.click());

    document.getElementById('dpFilter').addEventListener('click', (e) => {
        const b = e.target.closest('[data-art]');
        if (!b) return;
        document.querySelectorAll('#dpFilter .v-chip').forEach(x => x.classList.toggle('is-active', x === b));
        zustand.filter = b.dataset.art; zustand.offset = 0; zustand.buchungen = [];
        ladeBuchungen();
    });
    document.getElementById('dpMehr').addEventListener('click', () => ladeBuchungen());
    document.querySelector('#dpInhalt .tabs').addEventListener('click', (e) => {
        const b = e.target.closest('.tab-btn');
        if (b) reiter(b.dataset.tab);
    });

    laden();
});
