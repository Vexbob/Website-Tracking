/* Statistik — v1.18.0 Redesign
 * Modularer Aufbau: State (Datumsbereich + Granularity) → loadAll()
 * lädt Insights + Serie + Verteilung parallel. Alle Charts re-rendern
 * bei Filter-Aenderung.
 */

// --------- State ---------
const STAT = {
    from: null,     // ISO 'YYYY-MM-DD' oder null (=nur bis-heute Fallback)
    to:   null,
    preset: '30',   // '7' | '30' | '90' | '365' | 'all' | 'custom'
    granularity: 'daily',
    charts: {},
    insightsCache: null,
    firstExpenseDate: null,
};

function escHtml(s){if(s==null)return'';return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
/* Diagrammfarben kommen aus den Tokens, nicht aus verstreuten Hex-Werten —
 * Regeln dazu in docs/DESIGN.md: kein senkrechtes Gitter, keine Rahmen, erste
 * Reihe im Modulton, Achsen in der sekundaeren Textrolle. */
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const gridColor = () => cssVar('--chart-grid');
const textColor = () => cssVar('--chart-axis');
const chartSeriesColors = () => ['--chart-1','--chart-2','--chart-3','--chart-4','--chart-5','--chart-6'].map(cssVar);

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
    applyPreset('30');
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';
}

function bindFilterUI(){
    document.querySelectorAll('.stat-chip').forEach(btn => {
        btn.addEventListener('click', () => {
            const p = btn.dataset.preset;
            applyPreset(p);
        });
    });
    const fromEl = document.getElementById('statFrom');
    const toEl = document.getElementById('statTo');
    const onCustomChange = () => {
        if(!fromEl.value && !toEl.value) return;
        STAT.preset = 'custom';
        STAT.from = fromEl.value || null;
        STAT.to = toEl.value || null;
        document.querySelectorAll('.stat-chip').forEach(b => b.classList.remove('active'));
        loadAll();
    };
    fromEl.addEventListener('change', onCustomChange);
    toEl.addEventListener('change', onCustomChange);
    document.querySelectorAll('#statGranularity button').forEach(b => {
        b.addEventListener('click', () => {
            document.querySelectorAll('#statGranularity button').forEach(x => x.classList.remove('active'));
            b.classList.add('active');
            STAT.granularity = b.dataset.gran;
            loadSeries();
        });
    });
}

function applyPreset(preset){
    STAT.preset = preset;
    document.querySelectorAll('.stat-chip').forEach(b => {
        b.classList.toggle('active', b.dataset.preset === preset);
    });
    const today = new Date();
    const iso = (d) => d.toISOString().slice(0,10);
    if(preset === 'all'){
        STAT.from = null; STAT.to = iso(today);
    } else {
        const days = parseInt(preset, 10);
        const from = new Date(today.getTime() - (days-1)*86400000);
        STAT.from = iso(from); STAT.to = iso(today);
    }
    // Custom-Inputs mit aktuellen Werten synchronisieren
    document.getElementById('statFrom').value = STAT.from || '';
    document.getElementById('statTo').value = STAT.to || '';
    // Granularity smart wählen
    if(preset === '7') { STAT.granularity = 'daily'; }
    else if(preset === '30') { STAT.granularity = 'daily'; }
    else if(preset === '90') { STAT.granularity = 'weekly'; }
    else if(preset === '365') { STAT.granularity = 'monthly'; }
    else if(preset === 'all') { STAT.granularity = 'monthly'; }
    document.querySelectorAll('#statGranularity button').forEach(b => {
        b.classList.toggle('active', b.dataset.gran === STAT.granularity);
    });
    loadAll();
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
    await Promise.all([
        loadInsights(),
        loadSeries(),
        loadDistribution(),
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
        renderTopItems(data);
        renderDistributionTables(data);
    } catch(e) { console.error('insights failed:', e); }
}

function fmtDelta(pct){
    if(pct == null) return '<span class="stat-kpi-delta neutral">neu</span>';
    if(Math.abs(pct) < 0.5) return `<span class="stat-kpi-delta neutral">≈ 0 %</span>`;
    const cls = pct > 0 ? 'up' : 'down';
    const arr = pct > 0 ? '▲' : '▼';
    return `<span class="stat-kpi-delta ${cls}">${arr} ${Math.abs(pct).toFixed(0)} %</span>`;
}

function renderKPI(data){
    const k = data.kpi, cp = data.compare_prev;
    const grid = document.getElementById('statKpiGrid');
    const tiles = [];
    tiles.push({
        label: 'Ausgaben (Zeitraum)',
        value: fmtEur(k.total),
        icon: '💶',
        sub: `${fmtDelta(cp.diff_pct)} vs. Vorperiode (${fmtEur(cp.total)})`,
    });
    tiles.push({
        label: `Ø / Tag (${data.range.days} T.)`,
        value: fmtEur(k.avg_per_day),
        icon: '📆',
        sub: `${k.tx_count} Bons · Ø ${fmtEur(k.avg_tx)} / Bon`,
    });
    if(k.biggest_tx){
        const b = k.biggest_tx;
        const d = new Date(b.date).toLocaleDateString('de-DE',{day:'2-digit',month:'2-digit'});
        tiles.push({
            label: 'Größter Bon',
            value: fmtEur(b.amount),
            icon: '🏆',
            sub: `${escHtml(b.store_name||'—')} · ${d}`,
            href: `/ausgaben/bon.html?id=${b.id}`,
        });
    } else {
        tiles.push({label:'Größter Bon', value:'–', icon:'🏆', sub:'Keine Daten'});
    }
    const wd = data.by_weekday;
    if(wd && wd.length){
        const days = ['Mo','Di','Mi','Do','Fr','Sa','So'];
        const withData = wd.filter(x => x.total > 0);
        if(withData.length){
            const top = withData.reduce((a,b) => a.total > b.total ? a : b);
            const share = k.total > 0 ? (top.total / k.total * 100) : 0;
            tiles.push({
                label: 'Teuerster Wochentag',
                value: days[top.dow] || '?',
                icon: '🗓',
                sub: `${fmtEur(top.total)} · ${share.toFixed(0)} % der Ausgaben`,
            });
        } else {
            tiles.push({label:'Teuerster Wochentag', value:'–', icon:'🗓', sub:'Keine Daten'});
        }
    }
    grid.innerHTML = tiles.map(t => {
        const inner = `
            <div class="stat-kpi-icon">${t.icon}</div>
            <div class="stat-kpi-label">${escHtml(t.label)}</div>
            <div class="stat-kpi-value">${t.value}</div>
            <div class="stat-kpi-sub">${t.sub}</div>`;
        if(t.href) return `<a class="stat-kpi clickable" href="${t.href}" style="text-decoration:none;color:inherit;display:block">${inner}</a>`;
        return `<div class="stat-kpi">${inner}</div>`;
    }).join('');
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
    if(STAT.charts.weekday) STAT.charts.weekday.destroy();
    const days = ['Mo','Di','Mi','Do','Fr','Sa','So'];
    const totals = data.by_weekday.map(x => x.total);
    const counts = data.by_weekday.map(x => x.count);
    STAT.charts.weekday = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: days,
            datasets: [{ label: 'Ausgaben (€)', data: totals,
                backgroundColor: cssVar('--chart-1'), hoverBackgroundColor: cssVar('--chart-2'),
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


function renderTopItems(data){
    const box = document.getElementById('tableItems');
    if(!data.top_items || !data.top_items.length){
        box.innerHTML = '<div class="stat-empty">Keine Artikel-Daten</div>';
        return;
    }
    let html = `<table class="stat-table"><thead><tr>
        <th>Artikel</th><th style="text-align:right">×</th><th style="text-align:right">Ø</th><th style="text-align:right">Total</th>
    </tr></thead><tbody>`;
    data.top_items.forEach(it => {
        html += `<tr><td>${escHtml(it.name)}</td><td class="num">${it.count}</td><td class="num">${fmtEur(it.avg)}</td><td class="num">${fmtEur(it.total)}</td></tr>`;
    });
    html += `</tbody></table>`;
    box.innerHTML = html;
}

function renderDistributionTables(data){
    const catBox = document.getElementById('tableCategory');
    const total = data.kpi.total;
    if(data.top_categories && data.top_categories.length){
        let html = `<table class="stat-table"><thead><tr>
            <th>Kategorie</th><th style="text-align:right">Anteil</th><th style="text-align:right">Total</th>
        </tr></thead><tbody>`;
        data.top_categories.forEach(c => {
            const share = total > 0 ? (c.total/total*100).toFixed(0) : 0;
            const delta = c.prev_total > 0 ? ((c.total/c.prev_total - 1)*100) : null;
            const deltaPill = delta != null && Math.abs(delta) >= 10
                ? `<span class="delta-pill ${delta > 0 ? 'up' : 'down'}">${delta > 0 ? '+' : ''}${delta.toFixed(0)}%</span>` : '';
            html += `<tr><td><span class="name"><span class="stat-color-dot" style="background:${c.color}"></span>${escHtml(c.icon)} ${escHtml(c.name)}</span></td><td class="num">${share} %</td><td class="num">${fmtEur(c.total)}${deltaPill}</td></tr>`;
        });
        html += `</tbody></table>`;
        catBox.innerHTML = html;
    } else { catBox.innerHTML = '<div class="stat-empty">Keine Daten</div>'; }

    const storeBox = document.getElementById('tableStore');
    if(data.top_stores && data.top_stores.length){
        let html = `<table class="stat-table"><thead><tr>
            <th>Laden</th><th style="text-align:right">Besuche</th><th style="text-align:right">Ø / Besuch</th><th style="text-align:right">Total</th>
        </tr></thead><tbody>`;
        data.top_stores.forEach(s => {
            const delta = s.prev_total > 0 ? ((s.total/s.prev_total - 1)*100) : null;
            const deltaPill = delta != null && Math.abs(delta) >= 10
                ? `<span class="delta-pill ${delta > 0 ? 'up' : 'down'}">${delta > 0 ? '+' : ''}${delta.toFixed(0)}%</span>` : '';
            html += `<tr><td><span class="name"><span class="stat-color-dot" style="background:${s.color}"></span>${escHtml(s.icon)} ${escHtml(s.name)}</span></td><td class="num">${s.visits}</td><td class="num">${fmtEur(s.avg_per_visit)}</td><td class="num">${fmtEur(s.total)}${deltaPill}</td></tr>`;
        });
        html += `</tbody></table>`;
        storeBox.innerHTML = html;
    } else { storeBox.innerHTML = '<div class="stat-empty">Keine Daten</div>'; }
}


// ========== ZEITREIHE ==========
async function loadSeries(){
    try {
        const gran = STAT.granularity;
        let data;
        if(gran === 'daily') data = await AUSGABEN_API.statsDaily(rangeParams());
        else if(gran === 'weekly') data = await AUSGABEN_API.statsWeekly(rangeParams());
        else data = await AUSGABEN_API.statsMonthly(rangeParams());
        renderSeriesChart(data, gran);
    } catch(e) { console.error('series failed:', e); }
}

function renderSeriesChart(data, gran){
    const canvas = document.getElementById('chartSeries');
    if(STAT.charts.series) STAT.charts.series.destroy();
    // Achse bleibt kurz, der Tooltip bekommt die ausgeschriebene Fassung mit
    // Jahr -- in einer Jahresansicht ist ein blosses "05.09." wertlos.
    let labels, fullLabels, values;
    if(gran === 'daily'){
        labels = data.map(d => new Date(d.date + 'T00:00:00').toLocaleDateString('de-DE',{day:'2-digit',month:'2-digit'}));
        fullLabels = data.map(d => VexCharts.fullDay(d.date));
        values = data.map(d => d.total);
    } else if(gran === 'weekly'){
        labels = data.map(d => 'KW ' + (d.week ? d.week.split('KW').pop() : '?'));
        fullLabels = data.map(d => VexCharts.fullWeek(d.week));
        values = data.map(d => d.total);
    } else {
        labels = data.map(d => {
            const [y,m] = d.month.split('-');
            const dt = new Date(parseInt(y),parseInt(m)-1,1);
            return dt.toLocaleDateString('de-DE',{month:'short',year:'2-digit'});
        });
        fullLabels = data.map(d => VexCharts.fullMonth(d.month));
        values = data.map(d => d.total);
    }
    const win = gran === 'daily' ? 7 : (gran === 'weekly' ? 4 : 3);
    const trend = values.map((_, i) => {
        const s = Math.max(0, i - win + 1);
        const slice = values.slice(s, i + 1);
        return slice.reduce((a,b) => a+b, 0) / slice.length;
    });
    STAT.charts.series = new Chart(canvas, {
        data: {
            labels,
            datasets: [
                // Die Balken sind die Daten und tragen deshalb den Modulton;
                // die Trendlinie ist eine Anmerkung und bleibt zurueckhaltend.
                { type: 'bar', label: 'Ausgaben', data: values,
                  backgroundColor: cssVar('--chart-1'),
                  borderRadius: 4, borderSkipped: false, order: VexCharts.ORDER.VALUE },
                // Die Ø-Linie liegt oben, damit sie auch bei sprunghaften
                // Balken lesbar bleibt (kleinere `order` = weiter vorn).
                { type: 'line', label: `Ø (${win} Perioden)`, data: trend,
                  borderColor: cssVar('--text-2'), borderWidth: 2, borderDash: [4, 4],
                  pointRadius: 0, tension: 0.35, fill: false, order: VexCharts.ORDER.TREND },
            ],
        },
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


// ========== VERTEILUNGS-CHARTS ==========
async function loadDistribution(){
    try {
        const params = rangeParams();
        const [cats, stores] = await Promise.all([
            AUSGABEN_API.statsCategory(params),
            AUSGABEN_API.statsStore(params),
        ]);
        renderCategoryChart(cats);
        renderStoreChart(stores);
    } catch(e) { console.error('distribution failed:', e); }
}

function renderCategoryChart(data){
    const canvas = document.getElementById('chartCategory');
    if(!canvas) return;
    if(STAT.charts.category) STAT.charts.category.destroy();
    if(!data.length){
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        return;
    }
    STAT.charts.category = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: data.map(d => d.name),
            datasets: [{ data: data.map(d => Number(d.total||0)),
                backgroundColor: data.map(d => d.color),
                borderWidth: 2, borderColor: cssVar('--surface-1') }],
        },
        options: (() => {
            const o = chartBase();
            delete o.scales;
            o.cutout = '68%';
            o.plugins.legend = { position: 'right',
                labels: { color: textColor(), font: { size: 11 }, boxWidth: 8, boxHeight: 8, padding: 8, usePointStyle: true, pointStyle: 'circle' } };
            o.plugins.tooltip.callbacks = { label: (c) => `${c.label}: ${fmtEur(c.parsed)}` };
            return o;
        })(),
    });
}

function renderStoreChart(data){
    const canvas = document.getElementById('chartStore');
    if(!canvas) return;
    if(STAT.charts.store) STAT.charts.store.destroy();
    if(!data.length){
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        return;
    }
    // Nur top 8 im Chart, Rest ist in der Tabelle
    const top = data.slice(0, 8);
    STAT.charts.store = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: top.map(d => d.name),
            datasets: [{ label: 'Ausgaben (€)', data: top.map(d => Number(d.total||0)),
                backgroundColor: top.map(d => d.color), borderRadius: 6, borderSkipped: false }],
        },
        options: (() => {
            const o = chartBase({ indexAxis: 'y' });
            o.plugins.tooltip.callbacks = { label: (c) => fmtEur(c.parsed.x) };
            o.scales.x = { ticks: { color: textColor(), font: { size: 11 }, callback: v => fmtEur(v) },
                           grid: { color: gridColor() }, border: { display: false }, beginAtZero: true };
            o.scales.y = { ticks: { color: textColor(), font: { size: 11 } },
                           grid: { display: false }, border: { display: false } };
            return o;
        })(),
    });
}

// ========== BOOT ==========
init();

