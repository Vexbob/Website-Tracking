/* depot.js — v2.38.0 (Modul im Bau)
 *
 * Der Trade-Republic-Kontoauszug, gelesen und geprueft (services/depot_import.py).
 * Die Seite zeigt, was der Auszug sicher hergibt: was verkaufte Wertpapiere
 * gebracht haben, was im Bestand ist, und jede Buchung. Kurse und den
 * heutigen Wert kennt der Auszug nicht -- die stehen hier deshalb auch nicht.
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
};

const esc = (v) => String(v == null ? '' : v)
    .replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const ikon = (n, g) => window.VexIkon ? VexIkon.svg(n, g || 18) : '';
const eur = (v) => (Number(v) || 0).toLocaleString('de-DE', { style: 'currency', currency: 'EUR' });
const eurVz = (v) => (Number(v) > 0 ? '+' : '') + eur(v);
const tag = (iso) => iso ? new Date(iso + (iso.length === 10 ? 'T12:00:00' : '')).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' }) : '–';
const monatJahr = (iso) => iso ? new Date(iso + 'T12:00:00').toLocaleDateString('de-DE', { month: 'long', year: 'numeric' }) : '';
const stueck = (v) => Number(v).toLocaleString('de-DE', { maximumFractionDigits: 6 });

function melde(text, fehler) {
    if (window.Toast) { fehler ? Toast.error(text) : Toast.success(text); return; }
    if (fehler) askAlert({ title: 'Das ging nicht', text });
}

const zustand = { filter: '', offset: 0, buchungen: [], statistikDa: false, buchungenDa: false };

/* ------------------------------------------------------------ Diagramme
 * Farben aus den Tokens (DESIGN 7): der Sparplan traegt den Modulton, die
 * uebrigen Reihen die Diagrammfarben. Kein senkrechtes Gitter, keine Rahmen. */
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const ton = {
    depot: () => cssVar('--figure') || cssVar('--m-depot'),
    kauf: () => cssVar('--chart-2'), verkauf: () => cssVar('--chart-1'),
    zinsen: () => cssVar('--chart-6'), ertrag: () => cssVar('--chart-1'),
    eingezahlt: () => cssVar('--chart-2'),
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

/* Der Verlauf in der Buehne: aufgelaufen seit der ersten Buchung. */
async function zeichneVerlauf(punkte) {
    try { await VexCharts.bereit(); } catch (e) { return; }
    const labels = punkte.map(p => monatKurz(p.monat));
    const o = chartBasis();
    VexCharts.applyFullDates(o, punkte.map(p => VexCharts.fullMonth(p.monat)));
    zeichne('verlauf', 'dpChartVerlauf', {
        type: 'line',
        data: { labels, datasets: [
            { label: 'In Wertpapieren', data: punkte.map(p => p.investiert), borderColor: ton.depot(),
              backgroundColor: tonAlpha(ton.depot(), 0.14), fill: 'origin', tension: 0.3, pointRadius: 0, borderWidth: 2,
              order: VexCharts.ORDER.VALUE },
            { label: 'Eingezahlt', data: punkte.map(p => p.eingezahlt), borderColor: ton.eingezahlt(),
              fill: false, tension: 0.3, pointRadius: 0, borderWidth: 2, borderDash: [5, 4],
              order: VexCharts.ORDER.CONTEXT },
        ] },
        options: o,
    });
    legende('dpVerlaufLegende', [['In Wertpapieren', 'var(--figure, var(--m-depot))'], ['Eingezahlt', 'var(--chart-2)']]);
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
    document.getElementById('dpKennzahlen').innerHTML = [
        kachel('Sparplan im Monat', esc(eur(k.sparplan_schnitt)), k.sparplan_monate ? `Ø über ${k.sparplan_monate} Monate` : 'kein Sparplan im Zeitraum'),
        kachel('Ausführungen', String(k.ausfuehrungen), 'Käufe, Sparpläne, Verkäufe'),
        kachel('Zinsen und Erträge', esc(eur(k.ertraege_zinsen)), ''),
        kachel('Realisiert', `<span class="${k.realisiert < 0 ? 'dp-minus' : 'dp-plus'}">${esc(eurVz(k.realisiert))}</span>`, 'mit Verkauf im Zeitraum'),
    ].join('');

    const labels = st.monate.map(m => monatKurz(m.monat));
    const voll = st.monate.map(m => VexCharts.fullMonth(m.monat));
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
        box.innerHTML = '<p class="dp-leer-satz">In diesem Zeitraum wurde nichts ganz verkauft.</p>';
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
        <span class="rank-sub">zuletzt verkauft ${esc(tag(x.letzte))}</span>
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
    document.getElementById('dpLaden').hidden = true;
    document.getElementById('dpLeer').hidden = !u.leer;
    document.getElementById('dpInhalt').hidden = !!u.leer;
    if (u.leer) return;
    zeichneBuehne(u);
    zeichneWertpapiere(u.wertpapiere);
    zeichneVerlauf(u.verlauf || []);
    // Nach einem neuen Auszug zeichnen die anderen Reiter beim naechsten
    // Oeffnen neu, statt alte Zahlen stehen zu lassen.
    zustand.offset = 0; zustand.buchungen = [];
    if (zustand.buchungenDa) { ladeBuchungen(); ladeAuszuege(); }
    if (zustand.statistikDa) { document.getElementById('dpRange').innerHTML = ''; zustand.statistikDa = false; }
    reiter(location.hash.slice(1));
}

function zeichneBuehne(u) {
    const a = u.arten || {};
    const summe = (...arten) => arten.reduce((s, k) => s + ((a[k] && a[k].summe) || 0), 0);
    const verkauft = u.wertpapiere.filter(w => !w.im_bestand);
    const realisiert = verkauft.reduce((s, w) => s + w.ergebnis, 0);
    // Ganze Euro gross, Cent und Zeichen klein -- wie jede Heldenzahl.
    const text = eurVz(realisiert);
    const m = text.match(/^(.*?)(,\d\d\s*€)$/);
    document.getElementById('dpHeld').innerHTML = m
        ? `${esc(m[1])}<span class="v-held-rest">${esc(m[2])}</span>` : esc(text);
    document.getElementById('dpHeld').classList.toggle('dp-minus', realisiert < 0);
    document.getElementById('dpMarke').textContent = 'Realisiert seit ' + monatJahr(u.von);
    document.getElementById('dpUnter').textContent =
        `aus ${verkauft.length} verkauften Wertpapieren · ${u.anzahl} Buchungen bis ${tag(u.bis)}`;
    const zahlen = [
        ['Eingezahlt', summe('einzahlung')],
        ['Ausgezahlt', -summe('auszahlung')],
        ['Gekauft', -summe('kauf', 'sparplan')],
        ['Verkauft', summe('verkauf')],
        ['Erträge und Zinsen', summe('ertrag', 'zinsen', 'praemie', 'geschenk', 'steuer')],
        ['Cash', u.saldo],
    ];
    document.getElementById('dpZahlen').innerHTML = zahlen.map(([l, v]) =>
        `<div><dt>${esc(l)}</dt><dd>${esc(eur(v))}</dd></div>`).join('');
}

function zeichneWertpapiere(liste) {
    const bestand = liste.filter(w => w.im_bestand);
    const verkauft = liste.filter(w => !w.im_bestand);
    const zeile = (w) => {
        const meta = [w.isin, `${w.ausfuehrungen} ${w.ausfuehrungen === 1 ? 'Ausführung' : 'Ausführungen'}`,
                      'zuletzt ' + tag(w.letzte)].join(' · ');
        const rechts = w.im_bestand
            ? (w.stueck_bekannt ? `${stueck(w.stueck)} Stück` : '<span class="dp-leise">Stück unbekannt</span>')
            : `<span class="${w.ergebnis < 0 ? 'dp-minus' : 'dp-plus'}">${esc(eurVz(w.ergebnis))}</span>`;
        return `<button type="button" class="rec-row" data-isin="${esc(w.isin)}">
            <span class="rec-mark">${ikon('depot', 16) || ikon('statistik', 16)}</span>
            <span class="rec-main"><span class="rec-title">${esc(w.name)}</span><span class="rec-meta">${esc(meta)}</span></span>
            <span class="rec-side"><span class="rec-val">${rechts}</span></span>
        </button>`;
    };
    const liste_ = (arr, leer) => arr.length ? '<div class="rec-list">' + arr.map(zeile).join('') + '</div>'
        : `<p class="dp-hinweis">${leer}</p>`;
    const unbekannt = bestand.some(w => !w.stueck_bekannt);
    document.getElementById('dpBestand').innerHTML =
        (unbekannt ? '<p class="dp-hinweis">Ältere Zeilen des Auszugs nennen keine Stückzahl – wo sie fehlt, steht „Stück unbekannt“.</p>' : '')
        + liste_(bestand, 'Nichts im Bestand.');
    document.getElementById('dpVerkauft').innerHTML = liste_(verkauft, 'Noch nichts verkauft.');
    document.getElementById('dpBestandSub').textContent = bestand.length ? bestand.length + ' Wertpapiere' : '';
    document.getElementById('dpVerkauftSub').textContent = verkauft.length ? verkauft.length + ' Wertpapiere' : '';
    document.querySelectorAll('[data-isin]').forEach(b => b.addEventListener('click', () =>
        dlgWertpapier(liste.find(w => w.isin === b.dataset.isin))));
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
        ['Gekauft', eur(w.gekauft)], ['Verkauft', eur(w.verkauft)],
        w.ertraege ? ['Erträge', eur(w.ertraege)] : null,
        w.im_bestand ? ['Stück', w.stueck_bekannt ? stueck(w.stueck) : 'unbekannt – ältere Zeilen nennen keine']
                     : ['Ergebnis', eurVz(w.ergebnis)],
    ].filter(Boolean);
    let r;
    try { r = await API.buchungen(new URLSearchParams({ isin: w.isin, limit: 500 }).toString()); }
    catch (e) { d.root.innerHTML = '<p class="dp-satz">Die Buchungen konnten nicht geladen werden.</p>'; return; }
    d.root.innerHTML = `<dl class="dp-fakten">${fakten.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>
        <div class="rec-list">${r.buchungen.map(x => buchungZeile(x, true)).join('')}</div>`;
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
