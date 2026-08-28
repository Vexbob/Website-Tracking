/* Gesundheit-Modul (v1.25.0) — Frontend-Logik.
 * Nutzt apiCall()/API_BASE aus /js/api.js. Chart.js fuer alle Diagramme.
 *
 * Architektur:
 *   - HEALTH_API                : API-Bindings (unveraendert kompatibel)
 *   - Chart-Theme (chartTheme)  : reagiert auf Dark/Light-Wechsel und liefert
 *                                  konsistente Achsen-/Tooltip-Farben
 *   - Bootstrap                 : setzt Tabs auf, laedt Dashboard
 *   - Pro Tab: initX() + loadX()
 */

const HEALTH_API = {
    summary:       () => apiCall('/api/health/summary'),
    metricSeries:  (type, days) => apiCall(`/api/health/metrics/${type}?days=${days}`),
    bloodPressure: (days) => apiCall(`/api/health/blood-pressure?days=${days}`),
    bloodGlucose:  (days) => apiCall(`/api/health/blood-glucose?days=${days}`),
    sleep:         (days) => apiCall(`/api/health/sleep?days=${days}`),
    workouts:      (type) => apiCall('/api/health/workouts' + (type ? `?workout_type=${encodeURIComponent(type)}` : '')),
    workoutDetail: (id) => apiCall(`/api/health/workouts/${id}`),
    importFile:    (file) => { const fd = new FormData(); fd.append('file', file); return apiCall('/api/health/import-file', { method: 'POST', body: fd }); },
    importCsv:     (files) => { const fd = new FormData(); [...files].forEach(f => fd.append('files', f)); return apiCall('/api/health/import-csv', { method: 'POST', body: fd }); },
    apiKeys:       () => apiCall('/api/health/api-keys'),
    createKey:     (label) => apiCall('/api/health/api-keys', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ label }) }),
    revokeKey:     (id) => apiCall(`/api/health/api-keys/${id}`, { method: 'DELETE' }),
};

const METRIC_LABELS = {
    steps:           { label: 'Schritte', unit: '', icon: '👟', color: '#3b82f6', cumulative: true },
    active_energy:   { label: 'Aktive Energie', unit: 'kcal', icon: '🔥', color: '#f59e0b', cumulative: true },
    resting_hr:      { label: 'Ruhepuls', unit: 'bpm', icon: '🛋️', color: '#ec4899' },
    heart_rate:      { label: 'Herzfrequenz', unit: 'bpm', icon: '❤️', color: '#ef4444' },
    walking_hr_avg:  { label: 'Ø-HF Gehen', unit: 'bpm', icon: '🚶', color: '#14b8a6' },
    hrv:             { label: 'HRV', unit: 'ms', icon: '📈', color: '#8b5cf6' },
    cardio_recovery: { label: 'Kardio-Erholung', unit: 'bpm', icon: '💪', color: '#22c55e' },
    weight:          { label: 'Gewicht', unit: 'kg', icon: '⚖️', color: '#0d9488' },
    vo2_max:         { label: 'VO2max', unit: 'ml/kg/min', icon: '🫁', color: '#2563eb' },
    swim_distance:   { label: 'Schwimmdistanz', unit: 'm', icon: '🏊', color: '#3b82f6', cumulative: true },
};

const WORKOUT_META = {
    'Running':          { icon: '🏃', cls: 'run',      de: 'Laufen' },
    'Cycling':          { icon: '🚴', cls: 'bike',     de: 'Radfahren' },
    'Swimming':         { icon: '🏊', cls: 'swim',     de: 'Schwimmen' },
    'Walking':          { icon: '🚶', cls: 'walk',     de: 'Gehen' },
    'StrengthTraining': { icon: '🏋️', cls: 'strength', de: 'Krafttraining' },
    'HIKE':             { icon: '🥾', cls: 'hike',     de: 'Wandern' },
    'Outdoor Spaziergang':{icon: '🚶', cls: 'walk',    de: 'Outdoor Spaziergang' },
    'Schwimmbad Schwimmen':{icon:'🏊', cls: 'swim',    de: 'Schwimmen (Pool)' },
    'Outdoor Laufen':   { icon: '🏃', cls: 'run',      de: 'Outdoor Laufen' },
};
function wMeta(t) { return WORKOUT_META[t] || { icon: '🏋️', cls: '', de: t || 'Workout' }; }

// ---------- Helpers ----------
let toastTimer = null;
function showToast(msg, isErr) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.toggle('err', !!isErr);
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 2500);
}
function fmt1(n) { return (n == null || Number.isNaN(+n)) ? '–' : Number(n).toFixed(1).replace('.', ','); }
function fmt0(n) { return (n == null || Number.isNaN(+n)) ? '–' : Math.round(Number(n)).toLocaleString('de-DE'); }
function fmtDate(iso) { return iso ? new Date(iso).toLocaleDateString('de-DE', { day:'2-digit', month:'2-digit' }) : '–'; }
function fmtDateFull(iso) { return iso ? new Date(iso).toLocaleDateString('de-DE') : '–'; }
function fmtDateTime(iso) { return iso ? new Date(iso).toLocaleString('de-DE', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' }) : '–'; }
function fmtHM(iso) { return iso ? new Date(iso).toLocaleTimeString('de-DE', { hour:'2-digit', minute:'2-digit' }) : '–'; }
function fmtDuration(min) {
    if (min == null) return '–';
    const h = Math.floor(min / 60), m = Math.round(min % 60);
    return h > 0 ? `${h}h ${m}min` : `${m} min`;
}
function escHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function pctDelta(cur, prev) {
    if (!prev || !cur) return null;
    return ((cur - prev) / prev) * 100;
}

// ---------- Chart-Theme (reagiert auf data-theme-Wechsel) ----------
function chartTheme() {
    const dark = document.documentElement.getAttribute('data-theme') === 'dark';
    return {
        text:    dark ? '#f0f0f0' : '#1a1a1a',
        muted:   dark ? '#a0a5b0' : '#666',
        grid:    dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
        border:  dark ? '#2a2e37' : '#e8e8e8',
        surface: dark ? '#1a1d24' : '#fff',
    };
}
function chartDefaults(overrides) {
    const th = chartTheme();
    return Object.assign({
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
            legend: { labels: { color: th.text, boxWidth: 12, font: { size: 11 } } },
            tooltip: {
                backgroundColor: th.surface, borderColor: th.border, borderWidth: 1,
                titleColor: th.text, bodyColor: th.text, padding: 10, cornerRadius: 8,
                displayColors: true, boxPadding: 3,
            },
        },
        scales: {
            x: { ticks: { color: th.muted, maxRotation: 0, autoSkipPadding: 12 }, grid: { color: th.grid } },
            y: { ticks: { color: th.muted }, grid: { color: th.grid }, beginAtZero: false },
        },
    }, overrides || {});
}
// Sparklines: minimales Achsen-loses Setup
function sparkOptions(color) {
    return {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: { x: { display: false }, y: { display: false } },
        elements: { point: { radius: 0 }, line: { tension: 0.35, borderColor: color, borderWidth: 2 } },
    };
}

// ---------- Tabs ----------
function activateTab(t) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === t));
    ['dashboard', 'vitalwerte', 'schlaf', 'workouts', 'einstellungen'].forEach(id => {
        const el = document.getElementById('tab-' + id);
        if (el) el.style.display = (id === t) ? '' : 'none';
    });
    if (t === 'vitalwerte' && !state.vitalInit) initVitalwerte();
    if (t === 'schlaf' && !state.sleepInit) initSchlaf();
    if (t === 'workouts' && !state.workoutsLoaded) initWorkouts();
    if (t === 'einstellungen' && !state.keysLoaded) initEinstellungen();
}

// ---------- Zentraler State ----------
const state = {
    summary: null,
    metricsCache: {},
    activityMode: 'steps',
    activityChart: null,
    vitalDays: 30, vitalMetric: 'heart_rate', vitalInit: false,
    chartMetric: null, chartBp: null, chartGlucose: null,
    sleepDays: 30, sleepInit: false, chartSleep: null, chartSleepTimes: null,
    workoutsLoaded: false, workoutsAll: [], workoutFilter: '',
    keysLoaded: false,
    sparkCharts: [],
};

// ---------- Dashboard ----------
async function loadDashboard() {
    const grid = document.getElementById('hDashKpis');
    try {
        const [summary, stepsRows, energyRows, hrRows, restRows] = await Promise.all([
            HEALTH_API.summary(),
            HEALTH_API.metricSeries('steps', 14).catch(() => []),
            HEALTH_API.metricSeries('active_energy', 14).catch(() => []),
            HEALTH_API.metricSeries('heart_rate', 14).catch(() => []),
            HEALTH_API.metricSeries('resting_hr', 14).catch(() => []),
        ]);
        state.summary = summary;
        state.dashSeries = { steps: stepsRows, active_energy: energyRows, heart_rate: hrRows, resting_hr: restRows };

        const sum7 = (arr) => arr.slice(-7).reduce((s, r) => s + (Number(r.qty) || 0), 0);
        const sumPrev7 = (arr) => arr.slice(-14, -7).reduce((s, r) => s + (Number(r.qty) || 0), 0);
        const avg7 = (arr) => { const s = arr.slice(-7); if (!s.length) return null;
            return s.reduce((a, r) => a + (Number(r.qty) || 0), 0) / s.length; };
        const avgPrev7 = (arr) => { const s = arr.slice(-14, -7); if (!s.length) return null;
            return s.reduce((a, r) => a + (Number(r.qty) || 0), 0) / s.length; };

        const stepsSum = sum7(stepsRows), stepsPrev = sumPrev7(stepsRows);
        const enSum = sum7(energyRows), enPrev = sumPrev7(energyRows);
        const restAvg = avg7(restRows), restPrev = avgPrev7(restRows);

        const tiles = [
            { icon: '👟', label: 'Schritte (7 Tage)', value: fmt0(stepsSum),
              delta: pctDelta(stepsSum, stepsPrev), higherIsBetter: true,
              spark: stepsRows.slice(-14).map(r => Number(r.qty) || 0), color: '#3b82f6' },
            { icon: '🔥', label: 'Aktive Energie (7 Tage)', value: fmt0(enSum) + ' kcal',
              delta: pctDelta(enSum, enPrev), higherIsBetter: true,
              spark: energyRows.slice(-14).map(r => Number(r.qty) || 0), color: '#f59e0b' },
            { icon: '🛋️', label: 'Ø Ruhepuls (7 Tage)',
              value: restAvg != null ? fmt0(restAvg) + ' bpm' : '–',
              delta: pctDelta(restAvg, restPrev), higherIsBetter: false,
              spark: restRows.slice(-14).map(r => Number(r.qty) || 0), color: '#ec4899' },
            { icon: '🏋️', label: 'Workouts diese Woche',
              value: fmt0(summary.workouts_this_week), delta: null, spark: null, color: '#14b8a6' },
        ];

        state.sparkCharts.forEach(c => c && c.destroy());
        state.sparkCharts = [];

        grid.innerHTML = tiles.map((t, i) => {
            let deltaHtml = '';
            if (t.delta != null && Number.isFinite(t.delta) && Math.abs(t.delta) >= 1) {
                const up = t.delta > 0;
                const good = (up && t.higherIsBetter) || (!up && !t.higherIsBetter);
                const cls = good ? 'down' : 'up';
                deltaHtml = `<span class="stat-kpi-delta ${cls}">${up ? '▲' : '▼'} ${Math.abs(t.delta).toFixed(0)}%</span>`;
            }
            const sparkHtml = t.spark && t.spark.some(v => v > 0)
                ? `<div class="h-kpi-spark"><canvas id="hDashSpark${i}"></canvas></div>` : '';
            return `<div class="stat-kpi">
                <div class="stat-kpi-icon">${t.icon}</div>
                <div class="stat-kpi-label">${t.label}</div>
                <div class="stat-kpi-value">${t.value}</div>
                ${deltaHtml ? `<div class="stat-kpi-sub">${deltaHtml}<span>vs. Vorwoche</span></div>` : ''}
                ${sparkHtml}
            </div>`;
        }).join('');

        tiles.forEach((t, i) => {
            if (!t.spark || !t.spark.some(v => v > 0)) return;
            const canvas = document.getElementById('hDashSpark' + i);
            if (!canvas) return;
            const ch = new Chart(canvas.getContext('2d'), {
                type: 'line',
                data: { labels: t.spark.map((_, j) => j), datasets: [{
                    data: t.spark, fill: true,
                    backgroundColor: t.color + '22', borderColor: t.color,
                }] },
                options: sparkOptions(t.color),
            });
            state.sparkCharts.push(ch);
        });

        renderSleepBlock('hDashSleep', summary.sleep_last);
        renderBpBlock('hDashBp', summary.blood_pressure_last);
        renderHeartOverview(summary, hrRows, restRows);
        renderInsights(summary, { stepsSum, stepsPrev, enSum, enPrev, restAvg, restPrev });
        renderActivityChart();
    } catch (e) {
        grid.innerHTML = `<div class="stat-empty">Fehler beim Laden: ${escHtml(e.message)}</div>`;
    }
}

function renderInsights(s, extras) {
    const box = document.getElementById('hDashInsights');
    const items = [];
    if (extras.stepsSum >= 70000) items.push({ icon:'🎯', txt:`Starke Woche — <strong>${fmt0(extras.stepsSum)}</strong> Schritte in 7 Tagen.` });
    else if (extras.stepsSum > 0 && extras.stepsSum < 20000) items.push({ icon:'💡', txt:`Wenig Aktivität diese Woche (<strong>${fmt0(extras.stepsSum)}</strong> Schritte).` });
    if (extras.restAvg != null && extras.restPrev != null && (extras.restAvg - extras.restPrev) <= -2)
        items.push({ icon:'💚', txt:`Ruhepuls <strong>${fmt0(extras.restAvg)}</strong> bpm — ${fmt0(extras.restPrev - extras.restAvg)} bpm besser als Vorwoche.` });
    if (extras.restAvg != null && extras.restAvg >= 80)
        items.push({ icon:'⚠️', txt:`Erhöhter Ruhepuls (<strong>${fmt0(extras.restAvg)}</strong> bpm) — evtl. Erholung einplanen.` });
    if (s.sleep_last && s.sleep_last.asleep_minutes != null) {
        const h = s.sleep_last.asleep_minutes / 60;
        if (h < 6) items.push({ icon:'😴', txt:`Letzte Nacht nur <strong>${fmt1(h)} h</strong> Schlaf.` });
        else if (h >= 7.5) items.push({ icon:'✨', txt:`Guter Schlaf: <strong>${fmt1(h)} h</strong> letzte Nacht.` });
    }
    if (s.workouts_this_week >= 4) items.push({ icon:'🔥', txt:`<strong>${s.workouts_this_week}</strong> Workouts diese Woche — respektabel!` });
    box.innerHTML = items.map(i => `<div class="insight"><span class="icon">${i.icon}</span><span>${i.txt}</span></div>`).join('');
}

function renderSleepBlock(elId, sl) {
    const el = document.getElementById(elId);
    if (!sl) { el.className = 'h-empty'; el.textContent = 'Noch keine Daten synchronisiert.'; return; }
    el.className = '';
    const total = (sl.core_minutes||0) + (sl.deep_minutes||0) + (sl.rem_minutes||0) + (sl.awake_minutes||0);
    const pct = (v) => total ? (100 * (v||0) / total).toFixed(1) : 0;
    const asleepH = (sl.asleep_minutes || 0) / 60;
    const inBedH = (sl.in_bed_minutes || 0) / 60;
    const eff = inBedH > 0 ? (asleepH / inBedH) * 100 : null;
    const effCls = eff == null ? '' : eff >= 90 ? 'good' : eff >= 80 ? 'mid' : 'low';
    const effHtml = eff != null ? `<span class="h-sleep-eff ${effCls}">Effizienz ${fmt0(eff)} %</span>` : '';
    const timeRange = (sl.sleep_start && sl.sleep_end) ? `${fmtHM(sl.sleep_start)} → ${fmtHM(sl.sleep_end)}` : '';
    el.innerHTML = `
        <div class="h-sleep-block">
            <div class="h-sleep-head">
                <span class="h-big">${fmt1(asleepH)} h</span>
                <span class="h-sub">geschlafen · ${fmtDateFull(sl.sleep_date)}${timeRange ? ' · ' + timeRange : ''}</span>
                ${effHtml}
            </div>
            ${total ? `<div class="h-phase-bars">
                <span class="h-phase-core" style="width:${pct(sl.core_minutes)}%"></span>
                <span class="h-phase-deep" style="width:${pct(sl.deep_minutes)}%"></span>
                <span class="h-phase-rem" style="width:${pct(sl.rem_minutes)}%"></span>
                <span class="h-phase-awake" style="width:${pct(sl.awake_minutes)}%"></span>
            </div>
            <div class="h-phase-legend">
                <span><span class="h-phase-dot" style="background:var(--blue)"></span>Core <strong>${fmt1((sl.core_minutes||0)/60)} h</strong></span>
                <span><span class="h-phase-dot" style="background:var(--purple)"></span>Tief <strong>${fmt1((sl.deep_minutes||0)/60)} h</strong></span>
                <span><span class="h-phase-dot" style="background:var(--teal)"></span>REM <strong>${fmt1((sl.rem_minutes||0)/60)} h</strong></span>
                <span><span class="h-phase-dot" style="background:var(--orange)"></span>Wach <strong>${fmt1((sl.awake_minutes||0)/60)} h</strong></span>
            </div>` : ''}
        </div>`;
}

function bpCategory(sys, dia) {
    if (sys == null || dia == null) return { cls: 'normal', label: '—' };
    if (sys >= 180 || dia >= 120) return { cls: 'crisis', label: 'Krise' };
    if (sys >= 140 || dia >= 90) return { cls: 'stage2', label: 'Hypertonie' };
    if (sys >= 130 || dia >= 80) return { cls: 'stage1', label: 'Erhöht' };
    if (sys >= 120) return { cls: 'elevated', label: 'Leicht erhöht' };
    if (sys < 120 && dia < 80) return { cls: 'optimal', label: 'Optimal' };
    return { cls: 'normal', label: 'Normal' };
}

function renderBpBlock(elId, bp) {
    const el = document.getElementById(elId);
    if (!bp) { el.className = 'h-empty'; el.textContent = 'Noch keine Daten synchronisiert.'; return; }
    el.className = '';
    const cat = bpCategory(bp.systolic, bp.diastolic);
    el.innerHTML = `
        <div class="h-bp-block">
            <div class="h-bp-head">
                <span class="h-big">${fmt0(bp.systolic)}/${fmt0(bp.diastolic)}</span>
                <span class="h-sub">mmHg · ${fmtDateTime(bp.recorded_at)}</span>
                <span class="h-bp-badge ${cat.cls}">${cat.label}</span>
            </div>
        </div>`;
}

function renderHeartOverview(s, hrRows, restRows) {
    const el = document.getElementById('hDashHeart');
    const hr7 = hrRows.slice(-7);
    const rest7 = restRows.slice(-7);
    const avg = (arr) => arr.length ? arr.reduce((a, r) => a + (Number(r.qty)||0), 0) / arr.length : null;
    const hrvLast = s.hrv && s.hrv.last ? s.hrv.last.qty : null;
    const vo2Last = s.vo2_max && s.vo2_max.last ? s.vo2_max.last.qty : null;
    const items = [
        { lbl: 'Ø Ruhepuls', val: avg(rest7) != null ? fmt0(avg(rest7)) : '–', sub: 'bpm' },
        { lbl: 'Ø Herzfrequenz', val: avg(hr7) != null ? fmt0(avg(hr7)) : '–', sub: 'bpm' },
        { lbl: 'HRV (letzt.)', val: hrvLast != null ? fmt0(hrvLast) : '–', sub: 'ms' },
        { lbl: 'VO2max', val: vo2Last != null ? fmt1(vo2Last) : '–', sub: 'ml/kg/min' },
    ];
    el.className = '';
    el.innerHTML = `<div class="h-heart-grid">${items.map(i => `
        <div class="h-heart-item">
            <div class="h-heart-lbl">${i.lbl}</div>
            <div class="h-heart-val">${i.val} <small>${i.sub}</small></div>
        </div>`).join('')}</div>`;
}

function renderActivityChart() {
    const canvas = document.getElementById('hDashActivity');
    const rows = (state.dashSeries && state.dashSeries[state.activityMode]) || [];
    const data = rows.slice(-14);
    const meta = METRIC_LABELS[state.activityMode];
    if (state.activityChart) state.activityChart.destroy();
    state.activityChart = new Chart(canvas.getContext('2d'), {
        type: 'bar',
        data: {
            labels: data.map(r => fmtDate(r.sample_date || r.recorded_at)),
            datasets: [{
                label: `${meta.label} (${meta.unit || '–'})`,
                data: data.map(r => Number(r.qty) || 0),
                backgroundColor: meta.color + 'cc',
                borderRadius: 6,
            }],
        },
        options: chartDefaults({
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: chartTheme().surface, borderColor: chartTheme().border,
                    borderWidth: 1, titleColor: chartTheme().text, bodyColor: chartTheme().text,
                    padding: 10, cornerRadius: 8,
                    callbacks: { label: (ctx) => ` ${fmt0(ctx.raw)} ${meta.unit || ''}`.trim() },
                },
            },
            scales: {
                x: { ticks: { color: chartTheme().muted }, grid: { display: false } },
                y: { ticks: { color: chartTheme().muted }, grid: { color: chartTheme().grid }, beginAtZero: true },
            },
        }),
    });
}

// ---------- Vitalwerte ----------
function initVitalwerte() {
    state.vitalInit = true;
    document.querySelectorAll('#hMetricPresets .stat-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            document.querySelectorAll('#hMetricPresets .stat-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            state.vitalDays = parseInt(chip.dataset.preset, 10);
            loadVitalTiles(); loadMetricChart(); loadBpGlucoseCharts();
        });
    });
    const th = chartTheme();
    state.chartMetric = new Chart(document.getElementById('hChartMetric').getContext('2d'), {
        type: 'line',
        data: { labels: [], datasets: [{
            label: '', data: [], borderColor: '#3b82f6',
            backgroundColor: 'rgba(59,130,246,0.12)', tension: 0.3, fill: true, pointRadius: 0,
        }] },
        options: chartDefaults({ plugins: { legend: { display: false } } }),
    });
    state.chartBp = new Chart(document.getElementById('hChartBp').getContext('2d'), {
        type: 'line',
        data: { labels: [], datasets: [
            { label: 'Systolisch', data: [], borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,0.1)', tension: 0.3, pointRadius: 2, fill: false },
            { label: 'Diastolisch', data: [], borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.1)', tension: 0.3, pointRadius: 2, fill: false },
        ] },
        options: chartDefaults(),
    });
    state.chartGlucose = new Chart(document.getElementById('hChartGlucose').getContext('2d'), {
        type: 'line',
        data: { labels: [], datasets: [{
            label: 'Blutzucker', data: [], borderColor: '#f59e0b',
            backgroundColor: 'rgba(245,158,11,0.12)', tension: 0.3, pointRadius: 2, fill: true,
        }] },
        options: chartDefaults({ plugins: { legend: { display: false } } }),
    });
    loadVitalTiles(); loadMetricChart(); loadBpGlucoseCharts();
}

async function loadVitalTiles() {
    const grid = document.getElementById('hMetricTiles');
    grid.innerHTML = Object.keys(METRIC_LABELS).slice(0, 8).map(() =>
        '<div class="stat-kpi"><div class="stat-loading">Lade …</div></div>').join('');
    const days = state.vitalDays;
    const keys = Object.keys(METRIC_LABELS).slice(0, 8);
    const rowsList = await Promise.all(keys.map(k => HEALTH_API.metricSeries(k, days).catch(() => [])));
    grid.innerHTML = '';
    keys.forEach((k, i) => {
        const meta = METRIC_LABELS[k];
        const rows = rowsList[i];
        const vals = rows.map(r => Number(r.qty)).filter(Number.isFinite);
        let display = '–';
        if (vals.length) {
            if (meta.cumulative) {
                const sum = vals.reduce((s,v)=>s+v,0);
                display = fmt0(sum) + (meta.unit ? ' ' + meta.unit : '');
            } else {
                const avg = vals.reduce((s,v)=>s+v,0) / vals.length;
                display = (avg >= 100 ? fmt0(avg) : fmt1(avg)) + (meta.unit ? ' ' + meta.unit : '');
            }
        }
        const isActive = k === state.vitalMetric;
        const tile = document.createElement('div');
        tile.className = 'stat-kpi clickable' + (isActive ? ' active-tile' : '');
        tile.innerHTML = `
            <div class="stat-kpi-icon">${meta.icon}</div>
            <div class="stat-kpi-label">${meta.label}</div>
            <div class="stat-kpi-value">${display}</div>
            <div class="stat-kpi-sub"><span>${meta.cumulative ? 'Summe' : 'Ø'} · ${days} T.</span></div>`;
        tile.addEventListener('click', () => {
            state.vitalMetric = k;
            grid.querySelectorAll('.stat-kpi').forEach(t => t.classList.remove('active-tile'));
            tile.classList.add('active-tile');
            loadMetricChart();
        });
        grid.appendChild(tile);
    });
}

async function loadMetricChart() {
    const type = state.vitalMetric;
    const meta = METRIC_LABELS[type] || { label: type, unit: '', icon: '📈', color: '#3b82f6' };
    document.getElementById('hMetricTitle').innerHTML = `${meta.icon || '📈'} ${meta.label}`;
    try {
        const rows = await HEALTH_API.metricSeries(type, state.vitalDays);
        const vals = rows.map(r => Number(r.qty)).filter(Number.isFinite);
        let stats = '';
        if (vals.length) {
            const mn = Math.min(...vals), mx = Math.max(...vals);
            const av = vals.reduce((s,v)=>s+v,0) / vals.length;
            const sum = vals.reduce((s,v)=>s+v,0);
            stats = meta.cumulative
                ? `Σ ${fmt0(sum)} · Ø ${fmt0(av)} · Max ${fmt0(mx)}`
                : `Ø ${(av>=100?fmt0(av):fmt1(av))} · Min ${(mn>=100?fmt0(mn):fmt1(mn))} · Max ${(mx>=100?fmt0(mx):fmt1(mx))} ${meta.unit || ''}`;
        }
        document.getElementById('hMetricStats').textContent = stats;
        state.chartMetric.data.labels = rows.map(r => fmtDate(r.sample_date || r.recorded_at));
        const ds = state.chartMetric.data.datasets[0];
        ds.label = `${meta.label} (${meta.unit || '–'})`;
        ds.data = rows.map(r => { const v = Number(r.qty); return Number.isFinite(v) ? v : Number(r.avg_value); });
        ds.borderColor = meta.color;
        ds.backgroundColor = meta.color + '1f';
        state.chartMetric.update();
    } catch (e) { showToast('Fehler: ' + e.message, true); }
}

async function loadBpGlucoseCharts() {
    try {
        const bp = await HEALTH_API.bloodPressure(state.vitalDays);
        state.chartBp.data.labels = bp.map(r => fmtDate(r.recorded_at));
        state.chartBp.data.datasets[0].data = bp.map(r => r.systolic);
        state.chartBp.data.datasets[1].data = bp.map(r => r.diastolic);
        state.chartBp.update();
    } catch (e) {}
    try {
        const gl = await HEALTH_API.bloodGlucose(state.vitalDays);
        state.chartGlucose.data.labels = gl.map(r => fmtDate(r.recorded_at));
        state.chartGlucose.data.datasets[0].data = gl.map(r => r.value);
        state.chartGlucose.update();
    } catch (e) {}
}

// ---------- Schlaf ----------
function initSchlaf() {
    state.sleepInit = true;
    document.querySelectorAll('#hSleepPresets .stat-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            document.querySelectorAll('#hSleepPresets .stat-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            state.sleepDays = parseInt(chip.dataset.preset, 10);
            loadSleepChart();
        });
    });
    state.chartSleep = new Chart(document.getElementById('hChartSleep').getContext('2d'), {
        type: 'bar',
        data: { labels: [], datasets: [
            { label: 'Core', data: [], backgroundColor: '#3b82f6', stack: 's', borderRadius: 3 },
            { label: 'Tief', data: [], backgroundColor: '#8b5cf6', stack: 's', borderRadius: 3 },
            { label: 'REM', data: [], backgroundColor: '#14b8a6', stack: 's', borderRadius: 3 },
            { label: 'Wach', data: [], backgroundColor: '#f59e0b', stack: 's', borderRadius: 3 },
        ] },
        options: chartDefaults({
            scales: {
                x: { stacked: true, ticks: { color: chartTheme().muted }, grid: { display: false } },
                y: { stacked: true, ticks: { color: chartTheme().muted }, grid: { color: chartTheme().grid },
                     title: { display: true, text: 'Stunden', color: chartTheme().muted } },
            },
        }),
    });
    state.chartSleepTimes = new Chart(document.getElementById('hChartSleepTimes').getContext('2d'), {
        type: 'line',
        data: { labels: [], datasets: [
            { label: 'Zubettgehen', data: [], borderColor: '#8b5cf6', backgroundColor: '#8b5cf6', pointRadius: 4, showLine: false },
            { label: 'Aufstehen',  data: [], borderColor: '#f59e0b', backgroundColor: '#f59e0b', pointRadius: 4, showLine: false },
        ] },
        options: chartDefaults({
            scales: {
                x: { ticks: { color: chartTheme().muted }, grid: { display: false } },
                y: { ticks: { color: chartTheme().muted,
                        callback: (v) => {
                            // v ist Stunden-Offset ab 18:00 (0 = 18:00, 24 = 18:00 nächster Tag)
                            let h = (18 + v) % 24; if (h < 0) h += 24;
                            return String(Math.floor(h)).padStart(2,'0') + ':00';
                        }
                    }, grid: { color: chartTheme().grid }, min: 0, max: 24 },
            },
        }),
    });
    loadSleepChart();
}

async function loadSleepChart() {
    try {
        const rows = await HEALTH_API.sleep(state.sleepDays);
        state.chartSleep.data.labels = rows.map(r => fmtDate(r.sleep_date));
        state.chartSleep.data.datasets[0].data = rows.map(r => (r.core_minutes || 0) / 60);
        state.chartSleep.data.datasets[1].data = rows.map(r => (r.deep_minutes || 0) / 60);
        state.chartSleep.data.datasets[2].data = rows.map(r => (r.rem_minutes || 0) / 60);
        state.chartSleep.data.datasets[3].data = rows.map(r => (r.awake_minutes || 0) / 60);
        state.chartSleep.update();

        // Regelmäßigkeits-Chart: Offset ab 18:00
        const toOffset = (iso) => {
            if (!iso) return null;
            const d = new Date(iso);
            let h = d.getHours() + d.getMinutes() / 60;
            let off = h - 18; if (off < 0) off += 24;
            return off;
        };
        state.chartSleepTimes.data.labels = rows.map(r => fmtDate(r.sleep_date));
        state.chartSleepTimes.data.datasets[0].data = rows.map(r => toOffset(r.sleep_start));
        state.chartSleepTimes.data.datasets[1].data = rows.map(r => toOffset(r.sleep_end));
        state.chartSleepTimes.update();

        const n = rows.length || 1;
        const avg = (key) => rows.reduce((s, r) => s + (r[key] || 0), 0) / n / 60;
        const avgEff = (() => {
            const arr = rows.filter(r => (r.in_bed_minutes||0) > 0)
                            .map(r => (r.asleep_minutes||0) / r.in_bed_minutes * 100);
            return arr.length ? arr.reduce((s,v)=>s+v,0) / arr.length : null;
        })();
        const kpis = [
            { icon: '😴', label: 'Ø Schlafdauer', value: fmt1(rows.reduce((s,r)=>s+(r.asleep_minutes||0),0)/n/60) + ' h' },
            { icon: '🛏️', label: 'Ø Im Bett', value: fmt1(rows.reduce((s,r)=>s+(r.in_bed_minutes||0),0)/n/60) + ' h' },
            { icon: '🌊', label: 'Ø Tiefschlaf', value: fmt1(avg('deep_minutes')) + ' h' },
            { icon: '✨', label: 'Ø Effizienz', value: avgEff != null ? fmt0(avgEff) + ' %' : '–' },
        ];
        document.getElementById('hSleepKpis').innerHTML = kpis.map(k => `
            <div class="stat-kpi"><div class="stat-kpi-icon">${k.icon}</div>
                <div class="stat-kpi-label">${k.label}</div>
                <div class="stat-kpi-value">${k.value}</div></div>`).join('');
    } catch (e) { showToast('Fehler: ' + e.message, true); }
}

// ---------- Workouts ----------
async function initWorkouts() {
    state.workoutsLoaded = true;
    try {
        state.workoutsAll = await HEALTH_API.workouts();
    } catch (e) {
        document.getElementById('hWorkoutList').innerHTML = `<div class="stat-empty">Fehler: ${escHtml(e.message)}</div>`;
        return;
    }
    const chipsBox = document.getElementById('hWorkoutTypeChips');
    const types = [...new Set(state.workoutsAll.map(w => w.workout_type).filter(Boolean))];
    types.forEach(t => {
        const btn = document.createElement('button');
        btn.className = 'stat-chip';
        btn.dataset.type = t;
        btn.innerHTML = `${wMeta(t).icon} ${escHtml(wMeta(t).de)}`;
        chipsBox.appendChild(btn);
    });
    chipsBox.querySelectorAll('.stat-chip').forEach(btn => {
        btn.addEventListener('click', () => {
            chipsBox.querySelectorAll('.stat-chip').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            state.workoutFilter = btn.dataset.type || '';
            renderWorkouts();
        });
    });
    renderWorkouts();
}

function renderWorkouts() {
    const rows = state.workoutFilter
        ? state.workoutsAll.filter(w => w.workout_type === state.workoutFilter)
        : state.workoutsAll;
    const kpiBox = document.getElementById('hWorkoutKpis');
    const countEl = document.getElementById('hWorkoutCount');
    const list = document.getElementById('hWorkoutList');
    if (!rows.length) {
        kpiBox.innerHTML = ''; countEl.textContent = '';
        list.className = 'h-empty'; list.innerHTML = 'Noch keine Workouts synchronisiert.';
        return;
    }
    countEl.textContent = `${rows.length} Workout${rows.length === 1 ? '' : 's'}`;
    const totalMin = rows.reduce((s, w) => s + (Number(w.duration_min) || 0), 0);
    const totalKcal = rows.reduce((s, w) => s + (Number(w.active_energy_kcal) || 0), 0);
    const hrArr = rows.map(w => Number(w.avg_heart_rate)).filter(Number.isFinite);
    const avgHr = hrArr.length ? hrArr.reduce((s,v)=>s+v,0) / hrArr.length : null;
    const kpis = [
        { icon:'🏋️', lbl:'Anzahl', val: fmt0(rows.length) },
        { icon:'⏱️', lbl:'Gesamtzeit', val: fmtDuration(totalMin) },
        { icon:'🔥', lbl:'Ø Kalorien', val: fmt0(totalKcal / rows.length) + ' kcal' },
        { icon:'❤️', lbl:'Ø Puls', val: avgHr != null ? fmt0(avgHr) + ' bpm' : '–' },
    ];
    kpiBox.innerHTML = kpis.map(k => `
        <div class="stat-kpi"><div class="stat-kpi-icon">${k.icon}</div>
            <div class="stat-kpi-label">${k.lbl}</div>
            <div class="stat-kpi-value">${k.val}</div></div>`).join('');
    list.className = '';
    list.innerHTML = rows.map(w => {
        const m = wMeta(w.workout_type);
        const dist = Number(w.distance_m);
        const distStr = Number.isFinite(dist) && dist > 0
            ? (dist >= 1000 ? fmt1(dist/1000) + ' km' : fmt0(dist) + ' m') : null;
        return `
        <div class="h-workout-row" onclick="openWorkoutDetail(${w.id})">
            <div class="h-workout-icon ${m.cls}">${m.icon}</div>
            <div class="h-workout-main">
                <div class="h-workout-title">${escHtml(m.de)}</div>
                <div class="h-workout-sub">${fmtDateTime(w.start_at)} · ${fmtDuration(w.duration_min)}${distStr ? ' · ' + distStr : ''}</div>
            </div>
            <div class="h-workout-stats">
                <div><span>Kcal</span><strong>${fmt0(w.active_energy_kcal)}</strong></div>
                <div><span>Puls</span><strong>${fmt0(w.avg_heart_rate)}</strong></div>
            </div>
        </div>`;
    }).join('');
}

async function openWorkoutDetail(id) {
    const modal = document.getElementById('hWorkoutModal');
    const body = document.getElementById('hWorkoutModalBody');
    const titleEl = document.getElementById('hWorkoutModalTitle');
    body.innerHTML = '<div class="stat-loading">Lade …</div>';
    modal.classList.add('show');
    try {
        const w = await HEALTH_API.workoutDetail(id);
        const m = wMeta(w.workout_type);
        titleEl.innerHTML = `${m.icon} ${escHtml(m.de)}`;
        const dist = Number(w.distance_m);
        const distStr = Number.isFinite(dist) && dist > 0
            ? (dist >= 1000 ? fmt1(dist/1000) + ' <small>km</small>' : fmt0(dist) + ' <small>m</small>') : '–';
        const tiles = [
            { lbl:'Start', val: fmtDateTime(w.start_at) },
            { lbl:'Dauer', val: fmtDuration(w.duration_min) },
            { lbl:'Aktive Energie', val: fmt0(w.active_energy_kcal) + ' <small>kcal</small>' },
            { lbl:'Gesamt-Energie', val: fmt0(w.total_energy_kcal) + ' <small>kcal</small>' },
            { lbl:'Distanz', val: distStr },
            { lbl:'Ø Puls', val: fmt0(w.avg_heart_rate) + ' <small>bpm</small>' },
            { lbl:'Max Puls', val: fmt0(w.max_heart_rate) + ' <small>bpm</small>' },
            { lbl:'Höhenmeter', val: fmt0(w.elevation_m) + ' <small>m</small>' },
        ];
        const extraLabels = {
            resting_energy_kcal: 'Ruhe-Energie (kcal)',
            intensity_kcal_h_kg: 'Intensität (kcal/h·kg)',
            max_speed_kmh: 'Max. Geschwindigkeit (km/h)',
            avg_speed_kmh: 'Ø Geschwindigkeit (km/h)',
            flights_climbed: 'Etagen gestiegen',
            elevation_descended_m: 'Abstieg (m)',
            step_count: 'Schritte', cadence_spm: 'Schrittfrequenz (spm)',
            swim_stroke_count: 'Schwimmzüge', swim_cadence_spm: 'Schwimmkadenz (spm)',
            lap_length_m: 'Rundenlänge (m)', swolf: 'SWOLF',
            temperature_c: 'Temperatur (°C)', humidity_pct: 'Luftfeuchtigkeit (%)',
        };
        const extras = (w.extra_metrics || []).filter(x => x.value != null);
        const extrasHtml = extras.length ? `
            <h4 style="margin:0.5rem 0 0.5rem;font-size:0.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;font-weight:600">Zusatzdaten</h4>
            <div class="h-workout-extras"><table>${extras.map(x => `
                <tr><td>${escHtml(extraLabels[x.metric_key] || x.metric_key)}</td>
                    <td>${fmt1(x.value)}${x.unit ? ' ' + escHtml(x.unit) : ''}</td></tr>`).join('')}
            </table></div>` : '';
        body.innerHTML = `
            <div class="h-workout-detail-grid">
                ${tiles.map(t => `<div class="h-workout-detail-tile">
                    <div class="h-workout-detail-lbl">${t.lbl}</div>
                    <div class="h-workout-detail-val">${t.val}</div>
                </div>`).join('')}
            </div>
            ${extrasHtml}`;
    } catch (e) {
        body.innerHTML = `<div class="stat-empty">Fehler: ${escHtml(e.message)}</div>`;
    }
}
function closeWorkoutModal() { document.getElementById('hWorkoutModal').classList.remove('show'); }

// ---------- Einstellungen / API-Keys ----------
function initEinstellungen() {
    state.keysLoaded = true;
    document.getElementById('hImportUrl').textContent = `${API_BASE}/api/health/import`;
    loadApiKeys();
    setupDropzone('hDropzoneCsv', 'hImportCsvFiles', 'hDropzoneCsvSub', true);
    setupDropzone('hDropzoneJson', 'hImportFile', 'hDropzoneJsonSub', false);

    document.querySelectorAll('#hImportModeToggle button').forEach(b => {
        b.addEventListener('click', () => {
            document.querySelectorAll('#hImportModeToggle button').forEach(x => x.classList.remove('active'));
            b.classList.add('active');
            const csv = b.dataset.mode === 'csv';
            document.getElementById('hImportCsvBox').style.display = csv ? '' : 'none';
            document.getElementById('hImportJsonBox').style.display = csv ? 'none' : '';
        });
    });
}

function setupDropzone(dropId, inputId, subId, multiple) {
    const zone = document.getElementById(dropId);
    const input = document.getElementById(inputId);
    const sub = document.getElementById(subId);
    zone.addEventListener('click', () => input.click());
    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('drag'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag'));
    zone.addEventListener('drop', (e) => {
        e.preventDefault(); zone.classList.remove('drag');
        const files = e.dataTransfer.files;
        if (!files.length) return;
        try {
            const dt = new DataTransfer();
            [...files].forEach(f => dt.items.add(f));
            input.files = dt.files;
        } catch (_e) { /* Safari-Fallback: einfach ignorieren, User muss Klicken */ }
        updateDropzoneLabel();
    });
    input.addEventListener('change', updateDropzoneLabel);
    function updateDropzoneLabel() {
        const files = input.files;
        if (!files || !files.length) {
            zone.classList.remove('has-files');
            sub.textContent = multiple ? 'Mehrfachauswahl unterstützt' : 'Eine Datei';
            return;
        }
        zone.classList.add('has-files');
        sub.textContent = files.length === 1 ? files[0].name : `${files.length} Dateien ausgewählt`;
    }
}

async function loadApiKeys() {
    const list = document.getElementById('hApiKeyList');
    list.className = 'h-empty'; list.innerHTML = '<div class="stat-loading">Lade …</div>';
    try {
        const keys = await HEALTH_API.apiKeys();
        if (!keys.length) { list.className = 'h-empty'; list.innerHTML = 'Noch kein API-Key erzeugt.'; return; }
        list.className = '';
        list.innerHTML = keys.map(k => `
            <div class="h-key-row ${k.revoked_at ? 'h-key-revoked' : ''}">
                <div>
                    <div class="h-key-label">${escHtml(k.label || 'Key')} ${k.revoked_at ? '<span style="color:var(--red)">(widerrufen)</span>' : ''}</div>
                    <div class="h-key-meta">Erstellt: ${fmtDateTime(k.created_at)} · Zuletzt genutzt: ${k.last_used_at ? fmtDateTime(k.last_used_at) : 'nie'}</div>
                </div>
                ${k.revoked_at ? '' : `<button class="danger" onclick="revokeApiKey(${k.id})">Widerrufen</button>`}
            </div>`).join('');
    } catch (e) {
        list.className = ''; list.innerHTML = `<div class="stat-empty">Fehler: ${escHtml(e.message)}</div>`;
    }
}

async function createApiKey() {
    const label = document.getElementById('hNewKeyLabel').value.trim() || 'Auto Health Export';
    try {
        const res = await HEALTH_API.createKey(label);
        document.getElementById('hNewKeyLabel').value = '';
        document.getElementById('hKeyModalValue').value = res.api_key;
        document.getElementById('hKeyModal').classList.add('show');
        loadApiKeys();
    } catch (e) { showToast('Fehler: ' + e.message, true); }
}
function closeKeyModal() { document.getElementById('hKeyModal').classList.remove('show'); }
function copyNewKey() {
    const input = document.getElementById('hKeyModalValue');
    input.select();
    if (navigator.clipboard) navigator.clipboard.writeText(input.value).then(() => showToast('Key kopiert ✓'));
}
async function revokeApiKey(id) {
    if (!confirm('Diesen Key wirklich widerrufen?')) return;
    try {
        await HEALTH_API.revokeKey(id);
        showToast('Key widerrufen');
        loadApiKeys();
    } catch (e) { showToast('Fehler: ' + e.message, true); }
}



async function uploadHealthCsv() {
    const input = document.getElementById('hImportCsvFiles');
    const resultEl = document.getElementById('hImportCsvResult');
    const files = input.files;
    if (!files || !files.length) { showToast('Bitte zuerst CSV-Dateien auswählen', true); return; }
    resultEl.innerHTML = `<div class="stat-loading">Importiere ${files.length} Datei(en) …</div>`;
    try {
        const stats = await HEALTH_API.importCsv(files);
        const skipped = stats.skipped || [];
        resultEl.innerHTML = `
            <div class="h-hint" style="margin:0">
                ✅ ${fmt0(stats.files_processed)} Dateien verarbeitet —
                ${fmt0(stats.metrics_imported)} Vitalwerte, ${fmt0(stats.bp_imported)} Blutdruck,
                ${fmt0(stats.glucose_imported)} Blutzucker, ${fmt0(stats.sleep_imported)} Nächte,
                ${fmt0(stats.workouts_imported)} Workouts importiert.
                ${skipped.length ? `${skipped.length} Punkte übersprungen.` : ''}
            </div>`;
        showToast('CSV-Import abgeschlossen ✓');
        input.value = ''; document.getElementById('hDropzoneCsv').classList.remove('has-files');
        document.getElementById('hDropzoneCsvSub').textContent = 'Mehrfachauswahl unterstützt';
        loadDashboard();
    } catch (e) {
        resultEl.innerHTML = `<div class="stat-empty">Import fehlgeschlagen: ${escHtml(e.message)}</div>`;
        showToast('Import fehlgeschlagen', true);
    }
}

async function uploadHealthFile() {
    const input = document.getElementById('hImportFile');
    const resultEl = document.getElementById('hImportFileResult');
    const file = input.files && input.files[0];
    if (!file) { showToast('Bitte zuerst eine Datei auswählen', true); return; }
    resultEl.innerHTML = '<div class="stat-loading">Importiere …</div>';
    try {
        const stats = await HEALTH_API.importFile(file);
        const skipped = stats.skipped || [];
        resultEl.innerHTML = `
            <div class="h-hint" style="margin:0">
                ✅ Import abgeschlossen — ${fmt0(stats.metrics_imported)} Vitalwerte,
                ${fmt0(stats.bp_imported)} Blutdruck, ${fmt0(stats.glucose_imported)} Blutzucker,
                ${fmt0(stats.sleep_imported)} Nächte, ${fmt0(stats.workouts_imported)} Workouts.
                ${skipped.length ? `${skipped.length} Punkte übersprungen.` : ''}
            </div>`;
        showToast('Import abgeschlossen ✓');
        input.value = ''; document.getElementById('hDropzoneJson').classList.remove('has-files');
        document.getElementById('hDropzoneJsonSub').textContent = 'Eine Datei';
        loadDashboard();
    } catch (e) {
        resultEl.innerHTML = `<div class="stat-empty">Import fehlgeschlagen: ${escHtml(e.message)}</div>`;
        showToast('Import fehlgeschlagen', true);
    }
}

// ---------- Bootstrap ----------
(async function () {
    if (!isLoggedIn()) { window.location.href = '/private/login.html'; return; }
    try {
        const me = await fetchMe(true);
        document.getElementById('userLabel').textContent = '👤 ' + me.username;
    } catch (e) { window.location.href = '/private/login.html'; return; }
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';

    document.getElementById('logoutBtn').addEventListener('click',
        () => { clearToken(); location.href = '/private/login.html'; });
    document.getElementById('themeBtn').addEventListener('click', () => {
        toggleTheme();
        // Charts neu einfärben
        [state.chartMetric, state.chartBp, state.chartGlucose, state.chartSleep,
         state.chartSleepTimes, state.activityChart].forEach(c => {
            if (c) { Object.assign(c.options, chartDefaults(c.options)); c.update(); }
        });
    });
    document.querySelectorAll('.tab-btn').forEach(b =>
        b.addEventListener('click', () => activateTab(b.dataset.tab)));

    // Activity-Chart Toggle
    document.querySelectorAll('#hActivityToggle button').forEach(b => {
        b.addEventListener('click', () => {
            document.querySelectorAll('#hActivityToggle button').forEach(x => x.classList.remove('active'));
            b.classList.add('active');
            state.activityMode = b.dataset.mode;
            renderActivityChart();
        });
    });

    // Modal-Overlay-Click schließt
    document.getElementById('hKeyModal').addEventListener('click',
        (e) => { if (e.target.id === 'hKeyModal') closeKeyModal(); });
    document.getElementById('hWorkoutModal').addEventListener('click',
        (e) => { if (e.target.id === 'hWorkoutModal') closeWorkoutModal(); });

    // ESC schließt Modals
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { closeKeyModal(); closeWorkoutModal(); }
    });

    loadDashboard();
})();

