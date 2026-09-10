/* Statistik — v1.64.0
 * Eine Seite fuer alles, was die Ausgaben in Zahlen beantwortet: ein
 * Zeitraum, eine Hauptzahl, ein Verlauf — und darunter vier
 * Aufschluesselungen DERSELBEN Summe (Kategorien, Laeden, Produkte, Zeiten)
 * unter einem Umschalter.
 *
 * Die Produkt-Tabelle war bis v1.63.x eine eigene Seite mit eigenem
 * Zeitraum-Filter. Man stellte denselben Zeitraum zweimal ein und bekam
 * trotzdem zwei verschiedene Zahlen zu sehen. Ihr Code lebt weiter in
 * produkte.js, wird von hier aber als Abschnitt eingehaengt.
 */

// --------- State ---------
const STAT = {
    from: null,     // ISO 'YYYY-MM-DD' oder null (=nur bis-heute Fallback)
    to:   null,
    preset: '30',   // '7' | '30' | '90' | '365' | 'all' | 'custom'
    granularity: 'daily',
    view: 'kategorien',   // welche Aufschluesselung offen ist
    charts: {},
    insightsCache: null,
    firstExpenseDate: null,
};

function escHtml(s){if(s==null)return'';return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
/* Diagrammfarben kommen aus den Tokens, nicht aus verstreuten Hex-Werten —
 * Regeln dazu in docs/DESIGN.md: kein senkrechtes Gitter, keine Rahmen, erste
 * Reihe im Modulton, Achsen in der sekundaeren Textrolle. */
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
/* Wie beim Sparziel: ohne Einstellung ist --figure nicht definiert, dann
   greift der Modulton. So bleibt Tuerkis der Standard fuer Ausgaben. */
const figureColor = () => cssVar('--figure') || cssVar('--m-ausgaben');
const gridColor = () => cssVar('--chart-grid');
const textColor = () => cssVar('--chart-axis');

/* Gemeinsame Grundeinstellungen: Tooltip sieht aus wie ein schwebendes Element
 * der App, Achsen ohne Rahmen, Gitter nur waagerecht. */
function chartBase(extra) {
    const base = {
        maintainAspectRatio: false,
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
            x: { ticks: { color: textColor(), font: { size: 11 } },
                 grid: { display: false }, border: { display: false } },
            y: { ticks: { color: textColor(), font: { size: 11 } },
                 grid: { color: gridColor() }, border: { display: false }, beginAtZero: true },
        },
    };
    return Object.assign(base, extra || {});
}

// --------- Init ---------
async function init(){
    const me = await ensureLoggedIn(); if(!me) return;
    renderSubnav();
    bindFilterUI();
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';
}

const VIEW_KEY = 'vexbob_stat_view';
const VIEWS = ['kategorien', 'laeden', 'produkte', 'zeiten'];

function panelOf(view){
    return document.getElementById('view' + view.charAt(0).toUpperCase() + view.slice(1));
}

/* Chart.js kann kein Diagramm in einem ausgeblendeten Container vermessen --
 * es kaeme mit Breite 0 heraus. Das Wochentags-Diagramm wird deshalb erst
 * gezeichnet, wenn sein Feld sichtbar ist, und beim Wechsel dorthin neu. */
function showBreakdown(view){
    if(VIEWS.indexOf(view) === -1) view = 'kategorien';
    STAT.view = view;
    try { localStorage.setItem(VIEW_KEY, view); } catch(e) {}
    document.querySelectorAll('#statBreakdown button').forEach(b => {
        b.classList.toggle('active', b.dataset.view === view);
    });
    VIEWS.forEach(v => { const el = panelOf(v); if(el) el.hidden = (v !== view); });
    if(view === 'zeiten' && STAT.insightsCache) renderWeekday(STAT.insightsCache);
    if(view === 'produkte' && typeof initProductsPanel === 'function') initProductsPanel();
}

function bindFilterUI(){
    // Der Zeitraum-Knopf zeichnet sich selbst und meldet den fertigen
    // Zeitraum zurück — diese Seite rechnet nichts mehr aus.
    VexRange.mount(document.getElementById('statRange'), { onChange: applyRange });
    document.querySelectorAll('#statBreakdown button').forEach(b => {
        b.addEventListener('click', () => showBreakdown(b.dataset.view));
    });
    let start = 'kategorien';
    try { start = localStorage.getItem(VIEW_KEY) || start; } catch(e) {}
    showBreakdown(start);
    document.querySelectorAll('#statGranularity button').forEach(b => {
        b.addEventListener('click', () => {
            document.querySelectorAll('#statGranularity button').forEach(x => x.classList.remove('active'));
            b.classList.add('active');
            STAT.granularity = b.dataset.gran;
            loadSeries();
        });
    });
}

/* Wie fein die Zeitreihe aufgelöst wird, hängt an der Länge des Zeitraums,
 * nicht am gewählten Preset — sonst hätte ein eigener Zeitraum keine Regel. */
function granularityFor(days){
    if(!days || days > 400) return 'monthly';
    if(days > 92) return 'monthly';
    if(days > 31) return 'weekly';
    return 'daily';
}

function applyRange(range){
    STAT.preset = range.preset;
    STAT.from = range.from;
    STAT.to = range.to;
    const info = document.getElementById('statRangeInfo');
    if(info) info.textContent = range.preset === 'all'
        ? 'seit dem ersten Bon'
        : `${range.days} Tage`;
    STAT.granularity = granularityFor(range.days);
    document.querySelectorAll('#statGranularity button').forEach(b => {
        b.classList.toggle('active', b.dataset.gran === STAT.granularity);
    });
    loadAll();
    // Die Produkt-Tabelle haengt am selben Zeitraum. Sie laedt nur nach, wenn
    // sie schon aufgebaut ist -- sonst holt sie ihre Daten ohnehin frisch,
    // sobald man sie das erste Mal ansieht.
    if(typeof refreshProductsPanel === 'function') refreshProductsPanel();
}

function rangeParams(){
    const p = {};
    if(STAT.from) p.from = STAT.from;
    if(STAT.to) p.to = STAT.to;
    return p;
}

// --------- Master-Loader ---------
async function loadAll(){
    updateSeriesRangeLabel();
    // Kategorien und Laeden kommen seit v1.62.0 aus den Insights mit --
    // dieselben Zahlen wie vorher, aber zwei Anfragen weniger.
    await Promise.all([
        loadInsights(),
        loadSeries(),
    ]);
}

function updateSeriesRangeLabel(){
    const el = document.getElementById('statSeriesRange');
    if(!el) return;
    const fmt = (iso) => iso ? new Date(iso).toLocaleDateString('de-DE',{day:'2-digit',month:'2-digit',year:'2-digit'}) : '?';
    el.textContent = `· ${fmt(STAT.from)} – ${fmt(STAT.to)}`;
}

// ========== INSIGHTS + KPI ==========
async function loadInsights(){
    try {
        const data = await AUSGABEN_API.statsInsights(rangeParams());
        STAT.insightsCache = data;
        renderKPI(data);
        renderInsights(data);
        renderWeekday(data);
        renderRanks(data);
    } catch(e) { console.error('insights failed:', e); }
}

/* Die Hauptzahl bekommt die Veraenderung als Pille daneben; sie ist die
 * Antwort auf "ist das viel?" und gehoert deshalb neben die Zahl, nicht in
 * eine eigene Kachel. */
function deltaPill(pct){
    if(pct == null) return '<span class="kpi-delta flat">neu</span>';
    const cls = Math.abs(pct) < 5 ? 'flat' : (pct > 0 ? 'up' : 'down');
    const sign = pct > 0 ? '+' : '';
    return `<span class="kpi-delta ${cls}">${sign}${pct.toFixed(0)} %</span>`;
}

function renderKPI(data){
    const k = data.kpi, cp = data.compare_prev;
    const box = document.getElementById('statKpiGrid');
    const prev = Number(cp && cp.total) || 0;
    const pill = deltaPill(prev > 0 ? (k.total / prev - 1) * 100 : null);
    const sub = prev > 0
        ? `gegen\u00fcber ${fmtEur(prev)} in der Vorperiode`
        : 'keine Vorperiode zum Vergleich';

    const minis = [
        { lbl: `\u00d8 / Tag (${data.range.days} T.)`, val: fmtEur(k.avg_per_day) },
        { lbl: 'Bons', val: `${k.tx_count}` , note: `\u00d8 ${fmtEur(k.avg_tx)}` },
    ];
    if(k.biggest_tx){
        const b = k.biggest_tx;
        minis.push({ lbl: 'Gr\u00f6\u00dfter Bon', val: fmtEur(b.amount),
                     note: escHtml(b.store_name || '\u2014'),
                     href: `/ausgaben/bon.html?id=${b.id}` });
    }
    const wd = (data.by_weekday || []).filter(x => x.total > 0);
    if(wd.length){
        const days = ['Montag','Dienstag','Mittwoch','Donnerstag','Freitag','Samstag','Sonntag'];
        const top = wd.reduce((a,b) => a.total > b.total ? a : b);
        const share = k.total > 0 ? (top.total / k.total * 100) : 0;
        minis.push({ lbl: 'Teuerster Tag', val: days[top.dow] || '?',
                     note: `${share.toFixed(0)} % der Ausgaben` });
    }

    box.innerHTML = `
        <div class="kpi-hero">
            <div class="kpi-hero-main">
                <div class="lbl">Ausgaben im Zeitraum</div>
                <div class="val">${fmtEur(k.total)}</div>
                <div class="sub">${pill} ${sub}</div>
            </div>
        </div>
        <div class="kpi-mini-row">
            ${minis.map(m => {
                const inner = `<div class="lbl">${m.lbl}</div><div class="val">${m.val}</div>`
                    + (m.note ? `<div class="note">${m.note}</div>` : '');
                return m.href
                    ? `<a class="kpi-mini" href="${m.href}">${inner}</a>`
                    : `<div class="kpi-mini">${inner}</div>`;
            }).join('')}
        </div>`;
}

function renderInsights(data){
    const el = document.getElementById('statInsights');
    const out = [];
    const k = data.kpi, cp = data.compare_prev;
    if(cp.diff_pct != null && Math.abs(cp.diff_pct) >= 5){
        const dir = cp.diff_pct > 0 ? 'mehr' : 'weniger';
        const emoji = cp.diff_pct > 0 ? '📈' : '📉';
        out.push(`<div class="insight"><span class="icon">${emoji}</span><div>Du hast diese Periode <strong>${Math.abs(cp.diff_pct).toFixed(0)} % ${dir}</strong> ausgegeben als in der vorherigen (${fmtEur(cp.total)} → <strong>${fmtEur(k.total)}</strong>).</div></div>`);
    }
    if(data.top_categories && data.top_categories.length && k.total > 0){
        const top = data.top_categories[0];
        const share = (top.total / k.total * 100).toFixed(0);
        out.push(`<div class="insight"><span class="icon">${escHtml(top.icon)}</span><div>Top-Kategorie: <strong>${escHtml(top.name)}</strong> mit <strong>${fmtEur(top.total)}</strong> (${share} % der Ausgaben).</div></div>`);
    }
    if(data.top_stores && data.top_stores.length){
        const top = data.top_stores.reduce((a,b) => a.visits > b.visits ? a : b);
        if(top.visits >= 2){
            out.push(`<div class="insight"><span class="icon">${escHtml(top.icon)}</span><div>Du warst <strong>${top.visits}×</strong> bei <strong>${escHtml(top.name)}</strong> — Ø <strong>${fmtEur(top.avg_per_visit)}</strong> pro Besuch.</div></div>`);
        }
    }
    const wd = data.by_weekday;
    if(wd){
        const active = wd.filter(x => x.count > 0);
        if(active.length >= 3){
            const days = ['montags','dienstags','mittwochs','donnerstags','freitags','samstags','sonntags'];
            const avg = active.reduce((s,x) => s + x.total, 0) / active.length;
            const top = active.reduce((a,b) => a.total > b.total ? a : b);
            if(top.total > avg * 1.5){
                const pctOver = ((top.total/avg - 1) * 100).toFixed(0);
                out.push(`<div class="insight"><span class="icon">📊</span><div>Du gibst <strong>${days[top.dow]}</strong> im Schnitt <strong>${pctOver} %</strong> mehr aus als an anderen Tagen.</div></div>`);
            }
        }
    }
    if(data.top_categories){
        const risers = data.top_categories.filter(c => c.prev_total > 0 && c.total > c.prev_total * 1.3 && c.total > 5);
        if(risers.length){
            const top = risers[0];
            const pct = ((top.total/top.prev_total - 1)*100).toFixed(0);
            out.push(`<div class="insight"><span class="icon">⚠️</span><div>Kategorie <strong>${escHtml(top.name)}</strong> stieg um <strong>+${pct} %</strong> ggü. Vorperiode (${fmtEur(top.prev_total)} → ${fmtEur(top.total)}).</div></div>`);
        }
    }
    el.innerHTML = out.join('');
    // Die Karte drumherum nur zeigen, wenn wirklich etwas drinsteht --
    // eine leere Ueberschrift "Erkenntnisse" waere schlimmer als nichts.
    const card = document.getElementById('statInsightsCard');
    if (card) card.hidden = out.length === 0;
}

function renderWeekday(data){
    const canvas = document.getElementById('chartWeekday');
    if(!canvas) return;
    // Ausgeblendet hat der Canvas die Breite 0 -- Chart.js wuerde ein
    // Diagramm bauen, das beim Aufklappen leer aussieht. showBreakdown()
    // holt das Zeichnen nach, sobald das Feld offen ist.
    const panel = panelOf('zeiten');
    if(panel && panel.hidden) return;
    if(STAT.charts.weekday) STAT.charts.weekday.destroy();
    const days = ['Mo','Di','Mi','Do','Fr','Sa','So'];
    const totals = data.by_weekday.map(x => x.total);
    const counts = data.by_weekday.map(x => x.count);
    STAT.charts.weekday = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: days,
            datasets: [{ label: 'Ausgaben (€)', data: totals,
                backgroundColor: figureColor(), hoverBackgroundColor: cssVar('--chart-2'),
                borderRadius: 6, borderSkipped: false, barPercentage: 0.72 }],
        },
        options: (() => {
            const o = chartBase();
            o.plugins.tooltip.callbacks = { label: (c) => `${fmtEur(c.parsed.y)} · ${counts[c.dataIndex]} Bons` };
            o.scales.y.ticks.callback = v => fmtEur(v);
            return o;
        })(),
    });
}


/* Eine Zeile je Posten: Marke, Name, Betrag, darunter der Anteil als Balken
 * und die Veraenderung. Die Entitaetsfarbe faerbt nur Marke und Balken --
 * sie ist Nutzerdatum, ihren Kontrast gegen Text garantiert niemand. */
function safeColor(v){
    return /^#[0-9a-fA-F]{3,8}$/.test(String(v || '')) ? v : '';
}

function renderRankList(boxId, noteId, items, total, subOf){
    const box = document.getElementById(boxId);
    if(!box) return;
    if(!items || !items.length){
        box.innerHTML = `<div class="empty"><span class="empty-mark">\u{1f4ad}</span>
            <p class="empty-text">In diesem Zeitraum wurde nichts erfasst.</p></div>`;
        const n = document.getElementById(noteId); if(n) n.textContent = '';
        return;
    }
    const max = Math.max(...items.map(x => Number(x.total) || 0), 0.01);
    box.innerHTML = items.map(x => {
        const val = Number(x.total) || 0;
        const tone = safeColor(x.color);
        const delta = Number(x.prev_total) > 0 ? (val / x.prev_total - 1) * 100 : null;
        const pill = (delta != null && Math.abs(delta) >= 10)
            ? `<span class="delta-pill ${delta > 0 ? 'up' : 'down'}">${delta > 0 ? '+' : ''}${delta.toFixed(0)} %</span>`
            : '';
        return `<div class="rank-row"${tone ? ` style="--tone:${tone}"` : ''}>
            <span class="rank-mark">${escHtml(x.icon || '')}</span>
            <span class="rank-name">${escHtml(x.name)}</span>
            <span class="rank-val">${fmtEur(val)}</span>
            <span class="rank-bar"><i style="width:${Math.max(2, val / max * 100).toFixed(1)}%"></i></span>
            <span class="rank-sub">${subOf(x, val)}${pill}</span>
        </div>`;
    }).join('');

    // Die Liste zeigt nur die vordersten Posten. Was fehlt, gehoert dazu --
    // sonst liest man die Balken als Aufteilung des Ganzen.
    const listed = items.reduce((sum, x) => sum + (Number(x.total) || 0), 0);
    const rest = (Number(total) || 0) - listed;
    const note = document.getElementById(noteId);
    if(note) note.textContent = rest > 0.005
        ? `Top ${items.length} \u00b7 ${fmtEur(rest)} \u00fcbrige`
        : `${items.length} von ${items.length}`;
}

function renderRanks(data){
    const total = data.kpi.total;
    renderRankList('rankCategory', 'catNote', data.top_categories, total,
        (x, val) => total > 0 ? `${(val / total * 100).toFixed(0)} % der Ausgaben` : '');
    renderRankList('rankStore', 'storeNote', data.top_stores, total,
        (x) => `${x.visits}\u00d7 \u00b7 \u00d8 ${fmtEur(x.avg_per_visit)}`);
}

// ========== ZEITREIHE ==========

const isoDay = (d) => {
    const p = (n) => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
};

/* ISO-Kalenderwoche (Montag ist Tag 1). JavaScript kennt keine, deshalb das
 * Standardrezept ueber den Donnerstag derselben Woche. */
function isoWeekOf(d){
    const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    t.setUTCDate(t.getUTCDate() + 4 - (t.getUTCDay() || 7));
    const jan1 = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
    return { week: Math.ceil(((t - jan1) / 86400000 + 1) / 7), year: t.getUTCFullYear() };
}
function mondayOf(d){
    const t = new Date(d.getTime());
    t.setDate(t.getDate() - ((t.getDay() + 6) % 7));
    t.setHours(0, 0, 0, 0);
    return t;
}

/* Die Endpunkte liefern nur Perioden MIT Ausgaben. Ungefuellt stuenden die
 * Balken gleichmaessig verteilt nebeneinander, die Luecken waeren unsichtbar,
 * und der gleitende Durchschnitt mittelte ueber sieben EINKAUFSTAGE statt
 * ueber sieben Kalendertage. Deshalb wird die Reihe hier dicht gemacht. */
function densify(rows, gran, from, to){
    rows = rows || [];
    const firstOf = () => {
        if(!rows.length) return null;
        if(gran === 'daily') return rows[0].date;
        if(gran === 'weekly') return rows[0].week_start;
        return rows[0].month + '-01';
    };
    const first = from || firstOf();
    const last = to || isoDay(new Date());
    if(!first) return [];
    const out = [];
    const end = new Date(last + 'T00:00:00');

    if(gran === 'daily'){
        const by = new Map(rows.map(r => [r.date, Number(r.total) || 0]));
        for(let d = new Date(first + 'T00:00:00'); d <= end; d.setDate(d.getDate() + 1)){
            const key = isoDay(d);
            out.push({ key, value: by.get(key) || 0,
                       label: d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' }),
                       full: VexCharts.fullDay(key) });
        }
    } else if(gran === 'weekly'){
        const by = new Map(rows.map(r => [r.week_start, Number(r.total) || 0]));
        for(let d = mondayOf(new Date(first + 'T00:00:00')); d <= end; d.setDate(d.getDate() + 7)){
            const key = isoDay(d);
            const w = isoWeekOf(d);
            out.push({ key, value: by.get(key) || 0,
                       label: 'KW ' + w.week,
                       full: `KW ${w.week} \u00b7 ${w.year}` });
        }
    } else {
        const by = new Map(rows.map(r => [r.month, Number(r.total) || 0]));
        const s0 = new Date(first + 'T00:00:00');
        let y = s0.getFullYear(), m = s0.getMonth();
        while(y < end.getFullYear() || (y === end.getFullYear() && m <= end.getMonth())){
            const key = y + '-' + String(m + 1).padStart(2, '0');
            out.push({ key, value: by.get(key) || 0,
                       label: new Date(y, m, 1).toLocaleDateString('de-DE', { month: 'short', year: '2-digit' }),
                       full: VexCharts.fullMonth(key) });
            if(++m > 11){ m = 0; y++; }
        }
    }
    return out;
}

/* Die gleich lange Spanne unmittelbar davor. "Gesamt" hat keine Vorperiode --
 * davor liegt nichts. */
function prevRange(){
    if(!STAT.from) return null;
    const from = new Date(STAT.from + 'T00:00:00');
    const to = new Date((STAT.to || isoDay(new Date())) + 'T00:00:00');
    const days = Math.round((to - from) / 86400000) + 1;
    const pTo = new Date(from.getTime() - 86400000);
    const pFrom = new Date(pTo.getTime() - (days - 1) * 86400000);
    return { from: isoDay(pFrom), to: isoDay(pTo) };
}

async function loadSeries(){
    try {
        const gran = STAT.granularity;
        const fetchFor = (p) => gran === 'daily' ? AUSGABEN_API.statsDaily(p)
                              : gran === 'weekly' ? AUSGABEN_API.statsWeekly(p)
                              : AUSGABEN_API.statsMonthly(p);
        const pr = prevRange();
        const [rows, prevRows] = await Promise.all([
            fetchFor(rangeParams()),
            pr ? fetchFor({ from: pr.from, to: pr.to }).catch(() => []) : Promise.resolve(null),
        ]);
        renderSeriesChart(
            densify(rows, gran, STAT.from, STAT.to),
            pr ? densify(prevRows, gran, pr.from, pr.to) : null,
            gran);
    } catch(e) { console.error('series failed:', e); }
}

function renderSeriesChart(points, prevPoints, gran){
    const canvas = document.getElementById('chartSeries');
    if(!canvas) return;
    if(STAT.charts.series) STAT.charts.series.destroy();

    const labels = points.map(p => p.label);
    const fullLabels = points.map(p => p.full);
    const values = points.map(p => p.value);

    // Gleitender Durchschnitt. Seit die Reihe lueckenlos ist, sind das
    // wirklich sieben Tage bzw. vier Wochen und nicht sieben Eintraege.
    const win = gran === 'daily' ? 7 : (gran === 'weekly' ? 4 : 3);
    const trend = values.map((_, i) => {
        const slice = values.slice(Math.max(0, i - win + 1), i + 1);
        return slice.reduce((a, b) => a + b, 0) / slice.length;
    });

    // Die Vorperiode liegt Position fuer Position hinter der aktuellen. Sie
    // beantwortet die Frage, die ein Balken allein nicht beantwortet: ist das
    // viel? Ungleiche Laengen (Monate) werden hinten abgeschnitten.
    const datasets = [
        { type: 'bar', label: 'Ausgaben', data: values,
          backgroundColor: figureColor(),
          borderRadius: 4, borderSkipped: false, order: VexCharts.ORDER.VALUE },
    ];
    if(prevPoints && prevPoints.length){
        datasets.push({
            type: 'line', label: 'Vorperiode',
            data: points.map((_, i) => prevPoints[i] ? prevPoints[i].value : null),
            borderColor: cssVar('--text-3'), borderWidth: 1.5, borderDash: [2, 3],
            pointRadius: 0, tension: 0.35, fill: false, spanGaps: true,
            order: VexCharts.ORDER.CONTEXT,
        });
    }
    datasets.push({
        type: 'line', label: `\u00d8 (${win} Perioden)`, data: trend,
        borderColor: cssVar('--text-2'), borderWidth: 2, borderDash: [6, 4],
        pointRadius: 0, tension: 0.35, fill: false, order: VexCharts.ORDER.TREND,
    });

    STAT.charts.series = new Chart(canvas, {
        data: { labels, datasets },
        options: (() => {
            const o = chartBase({ interaction: { mode: 'index', intersect: false } });
            o.plugins.legend = { display: true, position: 'top',
                labels: { color: textColor(), font: { size: 11 }, boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: 'circle' } };
            o.plugins.tooltip.callbacks = { label: (c) => `${c.dataset.label}: ${fmtEur(c.parsed.y)}` };
            VexCharts.applyFullDates(o, fullLabels);
            o.scales.x.ticks = Object.assign(o.scales.x.ticks, { maxRotation: 0, autoSkip: true, autoSkipPadding: 10 });
            o.scales.y.ticks.callback = v => fmtEur(v);
            return o;
        })(),
    });
}

// ========== BOOT ==========
init();

