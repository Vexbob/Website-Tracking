/* musik.js — v1.67.0
 *
 * Das Hörregister: was aus dem Spotify-Datenexport importiert wurde, nach
 * Zeit, Interpret und Titel durchsuchbar.
 *
 * Zwei Dinge unterscheiden dieses Modul von den anderen:
 *
 *   1. **Ein Filter für zwei Ansichten.** Überblick und Register lesen
 *      denselben Zustand und dieselben Endpunkte. Zwei Filterleisten wären
 *      zwei Stände desselben Gedankens — man stellt etwas ein, wechselt den
 *      Reiter und sieht andere Zahlen.
 *   2. **Die Auflösung ist Teil der Daten.** Was importiert wurde, liegt je
 *      Zeitraum verschieden fein vor (2016 monatlich, dieses Jahr
 *      wöchentlich). Der Verlauf fasst deshalb nur nach OBEN zusammen und
 *      sagt darunter, wenn ein Teil der Zeilen gröber ist als die gewählte
 *      Stufe. Feiner aufteilen kann niemand — die Einzelwiedergaben stehen
 *      nur im Spotify-Export selbst.
 */

const API = {
    facets:   ()      => apiCall('/api/music/facets'),
    summary:  (qs)    => apiCall('/api/music/summary' + qs),
    series:   (qs)    => apiCall('/api/music/series' + qs),
    top:      (qs)    => apiCall('/api/music/top' + qs),
    entries:  (qs)    => apiCall('/api/music/entries' + qs),
    imports:  ()      => apiCall('/api/music/imports?limit=50'),
    delImport:(id)    => apiCall('/api/music/imports/' + id, { method: 'DELETE' }),
    clear:    ()      => apiCall('/api/music/entries', { method: 'DELETE' }),
    upload:   (file, dry) => {
        const fd = new FormData();
        fd.append('file', file);
        return apiCall('/api/music/import' + (dry ? '?dry_run=1' : ''),
                       { method: 'POST', body: fd });
    },
};

const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc = (v) => String(v == null ? '' : v)
    .replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const STEPS = [
    { key: 'tag',   label: 'täglich' },
    { key: 'woche', label: 'wöchentlich' },
    { key: 'monat', label: 'monatlich' },
    { key: 'jahr',  label: 'jährlich' },
];
const STEP_LABEL = Object.fromEntries(STEPS.map(s => [s.key, s.label]));

/* ---------------------------------------------------------- Musik ≠ Podcast
 *
 * Der Spotify-Export legt bei Podcasts die SHOW ins Feld „Interpret" und die
 * EPISODE in „Titel", bei Hörbüchern das Buch und das Kapitel. Dieselbe
 * Spalte bedeutet also je nach Art etwas anderes — „610 Titel" über beides
 * gerechnet vermischt zwei Dinge, und „Interpret: Lage der Nation" ist
 * schlicht falsch.
 *
 * Deshalb wechselt mit der Art das ganze Vokabular: Überschriften, Kennzahlen
 * und Spaltenköpfe. Der Ton ebenso — Musik trägt den Modulton (Spotify-Grün),
 * Podcast und Hörbuch je eine eigene Diagrammfarbe, damit sie im gestapelten
 * Verlauf auseinanderzuhalten sind.
 */
/* `whoMetric` / `whatMetric` sind der eigentliche Unterschied, nicht die
   Beschriftung: bei Musik zählt, wie OFT man etwas gehört hat, bei einem
   Podcast, WIE VIELE Folgen — eine Episode hört man einmal, „Top-Episode
   nach Wiedergaben“ wäre dort eine Liste von Einsen. Deshalb ranken Shows
   nach Folgenzahl, und die zweite Karte zeigt das zuletzt Gehörte. */
const VOCAB = {
    'Musik':   { who: 'Interpret', what: 'Titel',   whos: 'Interpreten', whats: 'Titel',
                 plays: 'Wiedergaben', unit: 'Wiedergaben',
                 whoMetric: 'plays', whatMetric: 'plays',
                 whoNote: 'nach Wiedergaben', whatNote: 'nach Wiedergaben',
                 countUnit: '',
                 tone: '--m-musik', mark: '🎵', whoMark: '🎤' },
    'Podcast': { who: 'Show',      what: 'Episode', whos: 'Shows',       whats: 'Episoden',
                 plays: 'Gehörte Folgen', unit: 'Folgen',
                 whoMetric: 'titles', whatMetric: 'last',
                 whoNote: 'nach Folgen', whatNote: 'zuletzt gehört',
                 countUnit: 'Folgen',
                 tone: '--chart-2', mark: '🎙️', whoMark: '🎙️' },
    'Hörbuch': { who: 'Buch',      what: 'Kapitel', whos: 'Bücher',      whats: 'Kapitel',
                 plays: 'Gehörte Kapitel', unit: 'Kapitel',
                 whoMetric: 'titles', whatMetric: 'last',
                 whoNote: 'nach Kapiteln', whatNote: 'zuletzt gehört',
                 countUnit: 'Kapitel',
                 tone: '--chart-5', mark: '📖', whoMark: '📚' },
};
// Ohne Spalte „Art" in der CSV lässt sich nichts unterscheiden — dann gilt
// die neutrale Fassung, und die Oberfläche behauptet keine Trennung, die die
// Daten nicht hergeben.
const VOCAB_ANY = {
    who: 'Interpret', what: 'Titel', whos: 'Interpreten', whats: 'Titel',
    plays: 'Wiedergaben', unit: 'Wiedergaben',
    whoMetric: 'plays', whatMetric: 'plays',
    whoNote: 'nach Wiedergaben', whatNote: 'nach Wiedergaben',
    countUnit: '',
    tone: '--m-musik', mark: '🎵', whoMark: '🎤',
};
const vocab = (kind) => VOCAB[kind] || VOCAB_ANY;

/* Der gesamte Filterzustand an einer Stelle. Alles, was lädt, liest hier. */
const state = {
    tab: 'ueberblick',
    range: { from: null, to: null },
    q: '',
    kind: '',
    artist: '',
    grain: '',       // nur Zeilen dieser Auflösung
    group: '',       // titel | interpret | album
    minPlays: 0,
    step: 'auto',    // Zielstufe des Verlaufs
    sort: 'period',
    direction: 'desc',
    offset: 0,
    limit: 100,
    facets: null,
    file: null,
    plan: null,
    charts: {},
};

/* ------------------------------------------------------------- Abfragen */

function qs(extra) {
    const p = new URLSearchParams();
    if (state.range.from) p.set('from', state.range.from);
    if (state.range.to) p.set('to', state.range.to);
    if (state.q) p.set('q', state.q);
    if (state.kind) p.set('kind', state.kind);
    if (state.artist) p.set('artist', state.artist);
    if (state.grain) p.set('grain', state.grain);
    if (state.group) p.set('group_by', state.group);
    if (state.minPlays > 1) p.set('min_plays', state.minPlays);
    Object.entries(extra || {}).forEach(([k, v]) => {
        if (v !== '' && v != null) p.set(k, v);
    });
    const s = p.toString();
    return s ? '?' + s : '';
}

/* ------------------------------------------------------------- Formate */

const fmtInt = (n) => Number(n || 0).toLocaleString('de-DE');

function fmtDuration(ms) {
    if (ms == null) return null;
    const minutes = Math.round(ms / 60000);
    if (minutes < 90) return fmtInt(minutes) + ' min';
    const hours = minutes / 60;
    if (hours < 72) return fmtNum(hours, 1) + ' h';
    return fmtInt(Math.round(hours)) + ' h';
}

function fmtDay(iso) {
    if (!iso) return '—';
    const d = new Date(String(iso).slice(0, 10) + 'T00:00:00');
    return isNaN(d) ? iso : d.toLocaleDateString('de-DE',
        { day: '2-digit', month: '2-digit', year: 'numeric' });
}

/* Periodenschlüssel für die Achse: kurz. Im Tooltip steht die lange
   Fassung — dort ist Platz, und ohne Jahr ist ein „KW 01" wertlos. */
function shortPeriod(key, grain) {
    const s = String(key || '');
    if (grain === 'jahr') return s;
    if (grain === 'monat') {
        const d = new Date(s + '-01T00:00:00');
        return isNaN(d) ? s : d.toLocaleDateString('de-DE', { month: 'short', year: '2-digit' });
    }
    if (grain === 'woche') return s.replace(/^(\d{4})-KW/, 'KW ') + '';
    const d = new Date(s + 'T00:00:00');
    return isNaN(d) ? s : d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' });
}

function fullPeriod(key, grain) {
    if (grain === 'jahr') return String(key);
    if (grain === 'monat') return VexCharts.fullMonth(key);
    if (grain === 'woche') return VexCharts.fullWeek(key);
    return VexCharts.fullDay(key);
}

/* ------------------------------------------------- Lückenlose Zeitreihe */

/* Endpunkte liefern nur Perioden mit Daten. Ungefüllt stünden die Balken
   gleichmäßig verteilt und ein Jahr ohne Musik wäre unsichtbar (DESIGN.md 7). */
function fillGaps(points, grain) {
    if (points.length < 2) return points;
    const step = { tag: 1, woche: 7 }[grain];
    const out = [];
    const at = new Map(points.map(p => [p.period, p]));
    const first = new Date(points[0].start + 'T00:00:00');
    const last = new Date(points[points.length - 1].start + 'T00:00:00');
    const guard = 2000;   // eine Achse mit mehr Punkten ist keine mehr

    const push = (d) => {
        const key = keyFor(d, grain);
        out.push(at.get(key) || { period: key, start: isoOf(d), plays: 0, ms_played: null,
                                  titles: 0, artists: 0, coarser: 0, filled: true });
    };
    const cursor = new Date(first);
    while (cursor <= last && out.length < guard) {
        push(cursor);
        if (step) cursor.setDate(cursor.getDate() + step);
        else if (grain === 'monat') cursor.setMonth(cursor.getMonth() + 1);
        else cursor.setFullYear(cursor.getFullYear() + 1);
    }
    // Beim Abbruch durch die Notbremse lieber die echten Punkte zeigen als
    // eine halb gefüllte Achse, die am Ende einfach aufhört.
    return out.length < guard ? out : points;
}

function isoOf(d) {
    const p = (n) => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
}

function keyFor(d, grain) {
    const p = (n) => String(n).padStart(2, '0');
    if (grain === 'jahr') return String(d.getFullYear());
    if (grain === 'monat') return d.getFullYear() + '-' + p(d.getMonth() + 1);
    if (grain === 'tag') return isoOf(d);
    // ISO-Woche: der Donnerstag derselben Woche bestimmt das Jahr.
    const t = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    t.setDate(t.getDate() + 3 - ((t.getDay() + 6) % 7));
    const week1 = new Date(t.getFullYear(), 0, 4);
    const week = 1 + Math.round(((t - week1) / 86400000 - 3 + ((week1.getDay() + 6) % 7)) / 7);
    return t.getFullYear() + '-KW' + p(week);
}

/* --------------------------------------------------------------- Charts */

function chartBase(fullLabels) {
    return VexCharts.applyFullDates({
        maintainAspectRatio: false,
        animation: { duration: 200 },
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: cssVar('--surface-3'),
                borderColor: cssVar('--line-strong'), borderWidth: 1,
                titleColor: cssVar('--text-1'), bodyColor: cssVar('--text-2'),
                cornerRadius: 12, padding: 10, displayColors: false,
            },
        },
        scales: {
            x: { ticks: { color: cssVar('--chart-axis'), font: { size: 11 }, maxRotation: 0,
                          autoSkipPadding: 12 },
                 grid: { display: false }, border: { display: false } },
            y: { ticks: { color: cssVar('--chart-axis'), font: { size: 11 } },
                 grid: { color: cssVar('--chart-grid') }, border: { display: false },
                 beginAtZero: true },
        },
    }, fullLabels);
}

/* Der Verlauf. Sind mehrere Arten im Spiel und keine davon ausgewählt, wird
   gestapelt — sonst sähe ein Podcast-Monat aus wie ein Musik-Monat. Bei einer
   einzelnen Art trägt die Reihe deren Ton. */
function drawSeries(data) {
    const canvas = document.getElementById('mChartSeries');
    if (state.charts.series) state.charts.series.destroy();
    const points = fillGaps(data.points || [], data.grain);
    const labels = points.map(p => shortPeriod(p.period, data.grain));
    const full = points.map(p => fullPeriod(p.period, data.grain));
    const byKind = (data.series || []).filter(s => s.plays > 0);
    const stacked = !state.kind && byKind.length > 1;

    // Die aufgeteilten Reihen sind an denselben Perioden ausgerichtet wie
    // `points` — nach dem Lückenfüllen muss die Ausrichtung mitwandern.
    const at = new Map((data.points || []).map((p, i) => [p.period, i]));
    const valuesOf = (s) => points.map(p => {
        const i = at.get(p.period);
        return i == null ? 0 : (s.values[i] || 0);
    });

    const datasets = stacked
        ? byKind.map(s => ({
            label: s.kind,
            data: valuesOf(s),
            backgroundColor: cssVar(vocab(s.kind).tone),
            borderRadius: 6,
            borderSkipped: false,
            order: VexCharts.ORDER.VALUE,
        }))
        : [{
            label: state.kind || 'Wiedergaben',
            data: points.map(p => p.plays),
            // Die erste Reihe trägt den Modulton, nicht den Akzent
            // (DESIGN.md 7) — hier ist das Spotify-Grün.
            backgroundColor: cssVar(vocab(state.kind).tone),
            borderRadius: 6,
            borderSkipped: false,
            order: VexCharts.ORDER.VALUE,
        }];

    const opts = chartBase(full);
    opts.plugins.tooltip.callbacks = {
        title: VexCharts.titleFrom(full),
        label: (item) => {
            if (stacked) {
                const v = vocab(item.dataset.label);
                return item.dataset.label + ': ' + fmtInt(item.parsed.y) + ' ' + v.unit;
            }
            const p = points[item.dataIndex];
            const v = vocab(state.kind);
            const parts = [fmtInt(p.plays) + ' ' + v.unit];
            if (p.titles) parts.push(fmtInt(p.titles) + ' ' + v.whats);
            const dur = fmtDuration(p.ms_played);
            if (dur) parts.push(dur);
            return parts;
        },
    };
    if (stacked) {
        opts.scales.x.stacked = true;
        opts.scales.y.stacked = true;
        // Direkt beschriftet wird über die eigene Legende unter der
        // Überschrift — Chart.js' eigene passt nicht zur Designsprache.
        opts.plugins.tooltip.mode = 'index';
        opts.plugins.tooltip.intersect = false;
    }

    state.charts.series = new Chart(canvas, {
        type: 'bar', data: { labels, datasets }, options: opts,
    });
    renderSeriesLegend(stacked ? byKind : []);
}

function renderSeriesLegend(kinds) {
    const box = document.getElementById('mSeriesLegend');
    if (!box) return;
    box.innerHTML = kinds.map(s =>
        '<span class="m-legend-item">' +
            '<i style="background:var(' + vocab(s.kind).tone + ')"></i>' +
            esc(s.kind) + '</span>').join('');
}

/* ------------------------------------------------------------ Überblick */

function kpiCard(label, value, sub, icon) {
    return '<div class="stat-kpi">' +
        '<div class="stat-kpi-icon" aria-hidden="true">' + icon + '</div>' +
        '<div class="stat-kpi-label">' + esc(label) + '</div>' +
        '<div class="stat-kpi-value">' + esc(value) + '</div>' +
        (sub ? '<div class="stat-kpi-sub">' + esc(sub) + '</div>' : '') +
    '</div>';
}

function renderKpis(sum) {
    const box = document.getElementById('mKpis');
    const v = vocab(state.kind);
    const span = (sum.from && sum.to)
        ? fmtDay(sum.from) + ' – ' + fmtDay(sum.to) : 'noch nichts importiert';
    const dur = fmtDuration(sum.ms_played);
    // Steht keine Art im Filter, aber mehrere im Register, sagt die Kachel
    // gleich die Aufteilung — sonst ist "4.320" eine Zahl über zwei Dinge.
    const kinds = (sum.by_kind || []).filter(k => k.plays > 0);
    const splitSub = (!state.kind && kinds.length > 1)
        ? kinds.map(k => k.kind + ' ' + fmtInt(k.plays)).join(' · ')
        : span;
    box.innerHTML =
        kpiCard(v.plays, fmtInt(sum.plays), splitSub, '🎧') +
        kpiCard(v.whats, fmtInt(sum.titles), fmtInt(sum.rows) + ' Registerzeilen', v.mark) +
        kpiCard(v.whos, fmtInt(sum.artists), null, v.whoMark) +
        (dur
            ? kpiCard('Hörzeit', dur, null, '⏱️')
            : kpiCard('Hörzeit', '—', 'die CSV enthielt keine Minuten', '⏱️'));
}

function rankList(items, opts) {
    if (!items.length) {
        return '<div class="empty"><span class="empty-mark" aria-hidden="true">' +
            vocab(state.kind).mark + '</span>' +
            '<p class="empty-text">Für diesen Filter stehen keine ' +
            esc(opts.empty || 'Einträge') + ' im Register. ' +
            'Ein weiterer Zeitraum oder eine leerere Suche bringt vermutlich etwas.</p></div>';
    }
    // Angezeigt wird die Zahl, nach der sortiert wurde -- eine Rangliste,
    // deren Balken zu einer anderen Größe gehören als ihre Reihenfolge,
    // ist eine Falle.
    const metric = opts.metric || 'plays';
    const valueOf = (i) => metric === 'titles' ? (i.titles || 0) : (i.plays || 0);
    const max = Math.max(1, ...items.map(valueOf));
    const tone = vocab(state.kind).tone;
    return '<div class="rank-list">' + items.map((i, n) => {
        const tag = opts.clickable ? 'button' : 'div';
        const attrs = opts.clickable
            ? ' type="button" data-artist="' + esc(i.label) + '"' : '';
        // Bei „zuletzt gehört“ ist die Reihenfolge die Aussage; ein Balken
        // nach Wiedergaben daneben würde eine zweite behaupten.
        const bar = metric === 'last' ? '' :
            '<span class="rank-bar"><i style="width:' +
                Math.round(valueOf(i) / max * 100) + '%"></i></span>';
        const val = metric === 'last'
            ? (i.to ? fmtDay(i.to) : '—')
            : fmtInt(valueOf(i)) + (opts.unit ? ' ' + opts.unit : '');
        return '<' + tag + ' class="rank-row"' + attrs + ' style="--tone:var(' + tone + ')">' +
            '<span class="rank-mark">' + (n + 1) + '</span>' +
            '<span class="rank-name">' + esc(i.label || '(ohne Namen)') + '</span>' +
            '<span class="rank-val">' + esc(val) + '</span>' +
            bar +
            (i.sub ? '<span class="rank-sub">' + esc(i.sub) + '</span>' : '') +
        '</' + tag + '>';
    }).join('') + '</div>';
}

async function loadOverview() {
    const box = { kpis: document.getElementById('mKpis') };
    try {
        const [sum, ser, artists, titles] = await Promise.all([
            API.summary(qs()),
            API.series(qs({ step: state.step, split: 'kind' })),
            API.top(qs({ by: 'interpret', limit: 12, metric: vocab(state.kind).whoMetric })),
            API.top(qs({ by: 'titel', limit: 12, metric: vocab(state.kind).whatMetric })),
        ]);
        renderKpis(sum);
        // Die Karten heißen, wie das heißt, was in ihnen steht.
        const v = vocab(state.kind);
        document.getElementById('mTopArtistsHead').textContent = v.whoMark + ' ' + v.whos;
        document.getElementById('mTopTitlesHead').textContent = v.mark + ' ' + v.whats;
        // Die Unterzeile sagt, WONACH sortiert ist -- sonst liest man eine
        // Show-Rangliste als Wiedergabezahl.
        const noteA = document.getElementById('mTopArtistsNote');
        const noteT = document.getElementById('mTopTitlesNote');
        if (noteA) noteA.textContent = v.whoNote + ' · Klick filtert';
        if (noteT) noteT.textContent = v.whatNote;
        document.getElementById('mSeriesLbl').textContent =
            '· ' + (ser.grain_label || '');
        drawSeries(ser);

        const coarser = (ser.points || []).reduce((n, p) => n + (p.coarser || 0), 0);
        document.getElementById('mSeriesNote').textContent = coarser
            ? coarser.toLocaleString('de-DE') + ' Zeilen liegen gröber vor als ' +
              (ser.grain_label || 'diese Stufe') + ' und zählen in die Periode ihres ' +
              'ersten Tages. Feiner als importiert lässt sich nicht aufteilen.'
            : '';

        document.getElementById('mTopArtists').innerHTML =
            rankList(artists.items || [], { clickable: true, empty: v.whos,
                                            metric: v.whoMetric, unit: v.countUnit });
        document.getElementById('mTopTitles').innerHTML =
            rankList(titles.items || [], { empty: v.whats, metric: v.whatMetric });
    } catch (e) {
        box.kpis.innerHTML = '<div class="empty is-error" style="grid-column:1/-1">' +
            '<span class="empty-mark" aria-hidden="true">⚠️</span>' +
            '<p class="empty-text">' + esc(e.message || e) + '</p></div>';
    }
}

/* -------------------------------------------------------------- Register */

/* Die Spalten heißen, was in ihnen steht — bei Podcasts also „Show" und
   „Episode". Ist eine Art gewählt, fällt die Art-Spalte weg: sie stünde in
   jeder Zeile gleich und kostete nur Breite. */
function columns() {
    const v = vocab(state.kind);
    const cols = [{ key: 'period', label: 'Periode', sort: 'period' }];
    if (!state.kind) cols.push({ key: 'kind', label: 'Art' });
    cols.push(
        { key: 'artist', label: v.who,  sort: 'artist' },
        { key: 'title',  label: v.what, sort: 'title' },
        { key: 'album',  label: 'Album', sort: 'album' },
        { key: 'plays',  label: v.unit, sort: 'plays', num: true },
        { key: 'ms',     label: 'Hörzeit', sort: 'ms', num: true });
    return cols;
}

function renderHead() {
    document.getElementById('mRegHead').innerHTML = '<tr>' + columns().map(c => {
        if (!c.sort) return '<th' + (c.num ? ' class="num"' : '') + '>' + esc(c.label) + '</th>';
        const active = state.sort === c.sort;
        return '<th class="sort' + (c.num ? ' num' : '') + (active ? ' is-sorted' : '') + '">' +
            '<button type="button" class="sort-btn" data-sort="' + c.sort + '">' +
                esc(c.label) +
                '<span class="sort-arrow" aria-hidden="true">' +
                    (active && state.direction === 'asc' ? '▲' : '▼') + '</span>' +
            '</button></th>';
    }).join('') + '</tr>';
}

function renderRows(data) {
    const body = document.getElementById('mRegBody');
    const cols = columns();
    if (!data.items.length) {
        body.innerHTML = '<tr><td colspan="' + cols.length + '">' +
            '<div class="stat-empty">Für diesen Filter steht nichts im Register. ' +
            'Entweder war in dem Zeitraum nichts zu hören, oder er wurde noch nicht ' +
            'importiert.</div></td></tr>';
        return;
    }
    const kindCell = (kind) => kind
        ? '<span class="m-kind" style="--tone:var(' + vocab(kind).tone + ')">' +
          vocab(kind).mark + ' ' + esc(kind) + '</span>'
        : '<span class="m-grain-tag">ohne Angabe</span>';
    body.innerHTML = data.items.map(r =>
        '<tr>' +
            '<td>' + esc(r.period_key) +
                ' <span class="m-grain-tag">' + esc(STEP_LABEL[r.grain] || r.grain) + '</span></td>' +
            (state.kind ? '' : '<td>' + kindCell(r.kind) + '</td>') +
            '<td>' + esc(r.artist || '—') + '</td>' +
            '<td>' + esc(r.title || '—') + '</td>' +
            '<td>' + esc(r.album || '—') + '</td>' +
            '<td class="num">' + fmtInt(r.plays) + '</td>' +
            '<td class="num">' + esc(fmtDuration(r.ms_played) || '—') + '</td>' +
        '</tr>').join('');
}

function renderPager(data) {
    const box = document.getElementById('mRegPager');
    if (data.total <= data.limit) { box.innerHTML = ''; return; }
    const from = data.offset + 1;
    const to = Math.min(data.offset + data.limit, data.total);
    box.innerHTML =
        '<button type="button" class="v-btn v-btn--sm" data-page="prev"' +
            (data.offset ? '' : ' disabled') + '>Zurück</button>' +
        '<span class="m-pager-pos">' + fmtInt(from) + '–' + fmtInt(to) +
            ' von ' + fmtInt(data.total) + '</span>' +
        '<button type="button" class="v-btn v-btn--sm" data-page="next"' +
            (to < data.total ? '' : ' disabled') + '>Weiter</button>';
}

async function loadRegister() {
    renderHead();
    const body = document.getElementById('mRegBody');
    body.innerHTML = '<tr><td colspan="' + columns().length + '">' +
        '<span class="skel skel-block"></span></td></tr>';
    try {
        const data = await API.entries(qs({
            sort: state.sort, direction: state.direction,
            limit: state.limit, offset: state.offset,
        }));
        document.getElementById('mRegSummary').textContent =
            fmtInt(data.total) + ' Zeilen · ' + fmtInt(data.plays) + ' Wiedergaben';
        renderRows(data);
        renderPager(data);
    } catch (e) {
        body.innerHTML = '<tr><td colspan="' + columns().length + '">' +
            '<div class="stat-empty">' + esc(e.message || e) + '</div></td></tr>';
    }
}

/* ---------------------------------------------------------------- Import */

function planHtml(plan, applied) {
    const blocks = plan.blocks || [];
    const rows = blocks.map(b =>
        '<div class="v-row">' +
            '<div class="m-block-name">' + esc(b.label) + '</div>' +
            '<div class="m-block-meta">' +
                esc((b.grains || []).map(g => STEP_LABEL[g] || g).join(', ')) + ' · ' +
                fmtDay(b.replace_from) + ' – ' + fmtDay(b.replace_to) + ' · ' +
                fmtInt(b.rows) + ' Zeilen · ' + fmtInt(b.plays) + ' Wiedergaben' +
            '</div>' +
        '</div>').join('');

    const head =
        '<div class="m-plan-head">' +
            '<span class="m-plan-title">' + (applied ? 'Übernommen' : 'Das würde passieren') + '</span>' +
            '<span class="m-plan-sub">' + fmtInt(plan.rows_read) + ' Zeilen gelesen · ' +
                fmtInt(plan.rows_written) + ' übernommen' +
                (plan.rows_skipped ? ' · ' + fmtInt(plan.rows_skipped) + ' ohne Periode übersprungen' : '') +
            '</span>' +
        '</div>';

    const replace = plan.rows_replaced
        ? '<p class="m-note">Jeder Block ersetzt seinen Zeitraum vollständig: ' +
          '<span class="m-block-replace">' + fmtInt(plan.rows_replaced) + ' vorhandene Zeilen</span> ' +
          (applied ? 'sind dabei entfernt worden.' : 'werden dabei entfernt.') +
          ' Dadurch ist derselbe Upload zweimal hintereinander folgenlos.</p>'
        : '<p class="m-note">Es liegt noch nichts in diesen Zeiträumen — es wird nichts ersetzt.</p>';

    const actions = applied ? '' :
        '<div class="m-plan-actions">' +
            '<button type="button" class="v-btn v-btn--primary" id="mApply">Übernehmen</button>' +
            '<button type="button" class="v-btn v-btn--ghost" id="mCancel">Verwerfen</button>' +
        '</div>';

    return head + '<div class="m-stack">' + rows + '</div>' + replace + actions;
}

async function previewFile(file) {
    const box = document.getElementById('mPlan');
    box.innerHTML = '<span class="skel skel-block"></span>';
    try {
        state.plan = await API.upload(file, true);
        box.innerHTML = planHtml(state.plan, false);
    } catch (e) {
        state.plan = null;
        box.innerHTML = '<div class="empty is-error">' +
            '<span class="empty-mark" aria-hidden="true">⚠️</span>' +
            '<p class="empty-text">' + esc(e.message || e) + '</p></div>';
    }
}

async function applyImport() {
    const btn = document.getElementById('mApply');
    if (btn) { btn.disabled = true; btn.classList.add('is-loading'); }
    try {
        const result = await API.upload(state.file, false);
        document.getElementById('mPlan').innerHTML = planHtml(result, true);
        resetDropzone();
        if (window.Toast) {
            Toast.success(fmtInt(result.rows_written) + ' Zeilen übernommen');
        }
        haptic('success');
        await Promise.all([loadFacets(), loadImportLog(), reload()]);
    } catch (e) {
        if (btn) { btn.disabled = false; btn.classList.remove('is-loading'); }
        if (window.Toast) Toast.error('Import fehlgeschlagen: ' + (e.message || e));
    }
}

function resetDropzone() {
    state.file = null;
    document.getElementById('mFile').value = '';
    document.getElementById('mDropzone').classList.remove('has-files');
    document.getElementById('mDropzoneSub').textContent =
        'Eine Datei, Semikolon oder Tabulator getrennt';
}

function importSummary(r) {
    const parts = [fmtInt(r.rows_written) + ' übernommen'];
    if (r.rows_replaced) parts.push(fmtInt(r.rows_replaced) + ' ersetzt');
    if (r.rows_skipped) parts.push(fmtInt(r.rows_skipped) + ' übersprungen');
    return parts.join(' · ');
}

async function loadImportLog() {
    const box = document.getElementById('mImportLog');
    try {
        const rows = await API.imports();
        if (!rows.length) {
            box.innerHTML = '<div class="empty">' +
                '<span class="empty-mark" aria-hidden="true">🧾</span>' +
                '<p class="empty-text">Noch keine CSV hochgeladen. Sobald eine drin ist, ' +
                'steht hier, welchen Zeitraum sie mitgebracht und welchen sie ersetzt hat.</p>' +
                '</div>';
            return;
        }
        box.innerHTML = '<div class="m-stack">' + rows.map(r =>
            '<div class="v-row m-imp-row">' +
                '<div>' +
                    '<div class="m-imp-name">' + esc(r.filename || 'ohne Dateiname') + '</div>' +
                    '<div class="m-imp-meta">' + fmtDay(r.uploaded_at) + ' · ' +
                        importSummary(r) +
                        (r.rows_alive != null ? ' · ' + fmtInt(r.rows_alive) + ' davon noch im Register' : '') +
                    '</div>' +
                '</div>' +
                '<button type="button" class="v-btn v-btn--sm v-btn--danger" ' +
                        'data-del-import="' + r.id + '">Eintrag löschen</button>' +
            '</div>').join('') + '</div>';
    } catch (e) {
        box.innerHTML = '<div class="empty is-error">' +
            '<span class="empty-mark" aria-hidden="true">⚠️</span>' +
            '<p class="empty-text">' + esc(e.message || e) + '</p></div>';
    }
}

/* --------------------------------------------------------------- Filter */

/* Die selteneren Filter liegen hinter einem Knopf, der seinen Stand nennt —
   dauerhaft auf der Seite kosteten sie auf dem Handy zwei Zeilen
   (DESIGN.md 6b). */
function mountMoreFilter(host) {
    const wrap = document.createElement('div');
    wrap.className = 'filter-popover-wrap';
    wrap.innerHTML =
        '<button type="button" class="filter-toggle-btn" aria-expanded="false" ' +
                'aria-haspopup="dialog"><span data-role="label">Feineres</span>' +
            '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" ' +
                'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
                'aria-hidden="true"><path d="M6 9.5l6 6 6-6"/></svg></button>' +
        '<div class="filter-popover" role="dialog" aria-label="Weitere Filter" hidden>' +
            '<div class="fp-row"><label class="fp-label" for="mGrain">Auflösung der Zeilen</label>' +
                '<select id="mGrain"><option value="">alle</option>' +
                    STEPS.map(s => '<option value="' + s.key + '">nur ' + s.label + '</option>').join('') +
                '</select></div>' +
            '<div class="fp-row"><label class="fp-label" for="mGroup">Zeilenart</label>' +
                '<select id="mGroup"><option value="">alle</option>' +
                    '<option value="titel">nach Titel</option>' +
                    '<option value="interpret">nach Interpret</option>' +
                    '<option value="album">nach Album</option>' +
                '</select></div>' +
            '<div class="fp-row"><label class="fp-label" for="mMinPlays">Mindestens Wiedergaben</label>' +
                '<input type="number" id="mMinPlays" min="0" step="1" placeholder="0"></div>' +
            '<div class="fp-actions">' +
                '<button type="button" class="fp-btn fp-btn-ghost" data-act="reset">Zurücksetzen</button>' +
                '<button type="button" class="fp-btn fp-btn-primary" data-act="apply">Übernehmen</button>' +
            '</div>' +
        '</div>';
    host.appendChild(wrap);

    const btn = wrap.querySelector('.filter-toggle-btn');
    const pop = wrap.querySelector('.filter-popover');
    const label = wrap.querySelector('[data-role="label"]');
    const grainEl = wrap.querySelector('#mGrain');
    const groupEl = wrap.querySelector('#mGroup');
    const minEl = wrap.querySelector('#mMinPlays');

    function paint() {
        const active = !!(state.grain || state.group || state.minPlays > 1);
        btn.classList.toggle('has-active', active);
        // Der Knopf nennt seinen Stand, nicht seine Möglichkeiten.
        label.textContent = active
            ? [state.grain ? 'nur ' + STEP_LABEL[state.grain] : '',
               state.group ? 'nach ' + state.group : '',
               state.minPlays > 1 ? '≥ ' + state.minPlays : '']
                .filter(Boolean).join(' · ')
            : 'Feineres';
        grainEl.value = state.grain;
        groupEl.value = state.group;
        minEl.value = state.minPlays > 1 ? state.minPlays : '';
    }

    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        pop.hidden = !pop.hidden;
        btn.setAttribute('aria-expanded', String(!pop.hidden));
    });
    document.addEventListener('click', (e) => {
        if (!wrap.contains(e.target)) { pop.hidden = true; btn.setAttribute('aria-expanded', 'false'); }
    });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') pop.hidden = true; });

    wrap.querySelector('.fp-actions').addEventListener('click', (e) => {
        const b = e.target.closest('button');
        if (!b) return;
        if (b.dataset.act === 'reset') {
            state.grain = ''; state.group = ''; state.minPlays = 0;
        } else {
            state.grain = grainEl.value;
            state.group = groupEl.value;
            state.minPlays = parseInt(minEl.value, 10) || 0;
        }
        pop.hidden = true;
        btn.setAttribute('aria-expanded', 'false');
        paint();
        state.offset = 0;
        reload();
    });

    paint();
    return { paint };
}

let moreFilter = null;

function paintVocab() {
    const v = vocab(state.kind);
    const input = document.getElementById('mSearch');
    if (input) {
        input.placeholder = v.who + ', ' + v.what + ' oder Album';
        input.setAttribute('aria-label', 'Im Hörregister suchen');
    }
}

function renderKindChips() {
    const box = document.getElementById('mKindChips');
    const kinds = (state.facets && state.facets.kinds) || [];
    // Ohne die Spalte "Art" in der CSV gibt es nichts zu unterscheiden —
    // dann steht hier auch keine Reihe aus einem einzigen Chip.
    if (kinds.length < 2) { box.innerHTML = ''; return; }
    box.innerHTML = '<button type="button" class="stat-chip' +
            (state.kind ? '' : ' active') + '" data-kind="">Alle</button>' +
        kinds.map(k => '<button type="button" class="stat-chip' +
            (state.kind === k.key ? ' active' : '') + '" data-kind="' + esc(k.key) + '">' +
            esc(k.key) + '</button>').join('');
}

function renderActiveFilters() {
    const box = document.getElementById('mActiveFilters');
    const chips = [];
    if (state.artist) chips.push({ key: 'artist', text: 'Interpret: ' + state.artist });
    if (state.q) chips.push({ key: 'q', text: 'Suche: ' + state.q });
    box.innerHTML = chips.map(c =>
        '<button type="button" class="m-chip" data-clear="' + c.key + '">' +
            esc(c.text) + '<span class="m-chip-x" aria-hidden="true">✕</span></button>').join('');
}

/* ----------------------------------------------------------------- Laden */

function reload() {
    paintVocab();
    renderActiveFilters();
    if (state.tab === 'ueberblick') return loadOverview();
    if (state.tab === 'register') return loadRegister();
    return Promise.resolve();
}

async function loadFacets() {
    try {
        state.facets = await API.facets();
        renderKindChips();
    } catch (e) { /* Filter bleiben dann eben schmaler */ }
}

function activateTab(tab) {
    state.tab = tab;
    document.querySelectorAll('.tab-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.tab === tab));
    ['ueberblick', 'register', 'import'].forEach(t => {
        document.getElementById('tab-' + t).style.display = t === tab ? '' : 'none';
    });
    // Der Import kennt keinen Zeitraum: eine Filterleiste ohne Wirkung wäre
    // eine Behauptung.
    document.getElementById('mFilterbar').style.display = tab === 'import' ? 'none' : '';
    document.getElementById('mActiveFilters').style.display = tab === 'import' ? 'none' : '';
    if (tab === 'import') loadImportLog();
    else reload();
}

/* ------------------------------------------------------------------ Boot */

document.addEventListener('DOMContentLoaded', async () => {
    if (!isLoggedIn()) { location.href = '/private/login.html'; return; }
    // css/statistics.css versteckt den Body (`body{visibility:hidden}`), bis
    // die Seite sich freigibt — sonst blitzt vor einer Weiterleitung zum Login
    // kurz die fertige Oberfläche auf. Jede Modulseite muss diesen Schalter
    // umlegen; fehlt er, sieht man dauerhaft nur den Seitenhintergrund.
    //
    // Und zwar HIER, direkt nach dem synchronen Login-Check: ab hier steht
    // fest, dass diese Seite bleibt. Erst nach dem Warten auf fetchMe
    // freizugeben hiesse, dass eine hängende oder fehlschlagende Antwort die
    // Seite unsichtbar lässt.
    document.body.classList.add('ready');
    try {
        const me = await fetchMe();
        document.getElementById('userLabel').textContent = '👤 ' + me.username;
    } catch (e) { /* Name ist Beiwerk */ }
    document.getElementById('logoutBtn').addEventListener('click',
        () => { clearToken(); location.href = '/private/login.html'; });

    document.querySelectorAll('.tab-btn').forEach(b =>
        b.addEventListener('click', () => activateTab(b.dataset.tab)));

    moreFilter = mountMoreFilter(document.getElementById('mMoreFilter'));

    // „Gesamt" ist hier der richtige Standard: das Register reicht über zehn
    // Jahre zurück, und 30 Tage wären bei einem Import alle paar Monate meist
    // eine leere Seite.
    VexRange.mount(document.getElementById('mRange'), {
        preset: 'all',
        onChange: (r) => {
            state.range = { from: r.from, to: r.to };
            state.offset = 0;
            reload();
        },
        fire: false,
    });

    // Suche: erst tippen lassen, dann laden.
    let searchTimer = null;
    document.getElementById('mSearch').addEventListener('input', (e) => {
        clearTimeout(searchTimer);
        const value = e.target.value.trim();
        searchTimer = setTimeout(() => {
            state.q = value;
            state.offset = 0;
            reload();
        }, 350);
    });

    document.getElementById('mKindChips').addEventListener('click', (e) => {
        const b = e.target.closest('[data-kind]');
        if (!b) return;
        state.kind = b.dataset.kind;
        state.offset = 0;
        renderKindChips();
        reload();
    });

    document.getElementById('mActiveFilters').addEventListener('click', (e) => {
        const b = e.target.closest('[data-clear]');
        if (!b) return;
        if (b.dataset.clear === 'artist') state.artist = '';
        if (b.dataset.clear === 'q') {
            state.q = '';
            document.getElementById('mSearch').value = '';
        }
        state.offset = 0;
        reload();
    });

    document.getElementById('mStepToggle').addEventListener('click', (e) => {
        const b = e.target.closest('button');
        if (!b) return;
        document.querySelectorAll('#mStepToggle button').forEach(x => x.classList.remove('active'));
        b.classList.add('active');
        state.step = b.dataset.step;
        loadOverview();
    });

    // Ein Klick auf einen Interpreten filtert alles darauf — der Chip
    // darüber zeigt, dass er greift, und nimmt ihn auch wieder weg.
    document.getElementById('mTopArtists').addEventListener('click', (e) => {
        const b = e.target.closest('[data-artist]');
        if (!b) return;
        state.artist = state.artist === b.dataset.artist ? '' : b.dataset.artist;
        state.offset = 0;
        reload();
    });

    document.getElementById('mRegHead').addEventListener('click', (e) => {
        const b = e.target.closest('[data-sort]');
        if (!b) return;
        if (state.sort === b.dataset.sort) {
            state.direction = state.direction === 'asc' ? 'desc' : 'asc';
        } else {
            state.sort = b.dataset.sort;
            state.direction = 'desc';
        }
        state.offset = 0;
        loadRegister();
    });

    document.getElementById('mRegPager').addEventListener('click', (e) => {
        const b = e.target.closest('[data-page]');
        if (!b || b.disabled) return;
        state.offset = Math.max(0, state.offset +
            (b.dataset.page === 'next' ? state.limit : -state.limit));
        loadRegister();
        document.getElementById('mRegTable').scrollIntoView({ block: 'nearest' });
    });

    // ---- Import
    const zone = document.getElementById('mDropzone');
    const input = document.getElementById('mFile');
    const sub = document.getElementById('mDropzoneSub');

    const takeFile = (file) => {
        if (!file) return;
        state.file = file;
        zone.classList.add('has-files');
        sub.textContent = file.name;
        previewFile(file);
    };

    zone.addEventListener('click', () => input.click());
    zone.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
    });
    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('drag'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag'));
    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('drag');
        takeFile(e.dataTransfer.files && e.dataTransfer.files[0]);
    });
    input.addEventListener('change', () => takeFile(input.files && input.files[0]));

    document.getElementById('mPlan').addEventListener('click', (e) => {
        if (e.target.closest('#mApply')) applyImport();
        if (e.target.closest('#mCancel')) {
            resetDropzone();
            document.getElementById('mPlan').innerHTML = '';
        }
    });

    document.getElementById('mImportLog').addEventListener('click', async (e) => {
        const b = e.target.closest('[data-del-import]');
        if (!b) return;
        const ok = await askConfirm({
            title: 'Protokolleintrag löschen?',
            text: 'Die importierten Zeilen bleiben im Register — nur der Herkunftsnachweis verschwindet.',
            ok: 'Löschen',
            danger: true,
        });
        if (!ok) return;
        try {
            await API.delImport(b.dataset.delImport);
            loadImportLog();
        } catch (err) {
            if (window.Toast) Toast.error(err.message || String(err));
        }
    });

    document.getElementById('mClearBtn').addEventListener('click', async () => {
        const ok = await askConfirm({
            title: 'Register wirklich leeren?',
            text: 'Alle Zeilen des Hörregisters werden gelöscht. Zurück holt sie nur ein neuer Import.',
            ok: 'Leeren',
            danger: true,
        });
        if (!ok) return;
        try {
            const res = await API.clear();
            if (window.Toast) Toast.success(fmtInt(res.deleted) + ' Zeilen gelöscht');
            await Promise.all([loadFacets(), loadImportLog(), reload()]);
        } catch (err) {
            if (window.Toast) Toast.error(err.message || String(err));
        }
    });

    await loadFacets();
    reload();
});
