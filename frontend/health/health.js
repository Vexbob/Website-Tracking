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
    // limit=500 (Server-Maximum): der Workouts-Tab filtert Sportart und
    // Zeitraum clientseitig -- mit dem Default 100 haette "Gesamt" bei
    // laengerer Historie stillschweigend Workouts unterschlagen.
    workouts:      (type) => apiCall('/api/health/workouts?limit=500'
                       + (type ? `&workout_type=${encodeURIComponent(type)}` : '')),
    workoutDetail: (id) => apiCall(`/api/health/workouts/${id}`),
    // v1.46.1: Reihenfolge der Vitalwerte-Karten (serverseitig, damit sie auf
    // allen Geraeten gleich ist — wie bei den Wochenzielen im Sparziel-Modul)
    metricOrder:    () => apiCall('/api/health/metric-order'),
    saveMetricOrder: (order) => apiCall('/api/health/metric-order', {
        method: 'PUT', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ order }),
    }),
    importFile:    (file) => { const fd = new FormData(); fd.append('file', file); return apiCall('/api/health/import-file', { method: 'POST', body: fd }); },
    importCsv:     (files) => { const fd = new FormData(); [...files].forEach(f => fd.append('files', f)); return apiCall('/api/health/import-csv', { method: 'POST', body: fd }); },
    apiKeys:       () => apiCall('/api/health/api-keys'),
    createKey:     (label) => apiCall('/api/health/api-keys', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ label }) }),
    revokeKey:     (id) => apiCall(`/api/health/api-keys/${id}`, { method: 'DELETE' }),
    // v1.28.0: Datensaetze loeschen
    deleteWorkout: (id) => apiCall(`/api/health/workouts/${id}`, { method: 'DELETE' }),
    deleteSleep:   (id) => apiCall(`/api/health/sleep/${id}`, { method: 'DELETE' }),
    deleteBp:      (id) => apiCall(`/api/health/blood-pressure/${id}`, { method: 'DELETE' }),
    deleteGlucose: (id) => apiCall(`/api/health/blood-glucose/${id}`, { method: 'DELETE' }),
    bulkDelete:    (body) => apiCall('/api/health/delete', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(body || {}),
    }),
    // v1.40.0: Import-Protokoll (Roh-Payloads der Sync-Aufrufe)
    imports:       (limit) => apiCall(`/api/health/imports?limit=${limit || 50}`),
    importRaw:     (id) => apiCall(`/api/health/imports/${id}/download`, { raw: true }),
    deleteImport:  (id) => apiCall(`/api/health/imports/${id}`, { method: 'DELETE' }),
    clearImports:  () => apiCall('/api/health/imports', { method: 'DELETE' }),
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
    blood_oxygen:    { label: 'Blutsauerstoff', unit: '%', icon: '🫧', color: '#06b6d4' },
    walking_distance:{ label: 'Geh-/Laufstrecke', unit: 'km', icon: '🛣️', color: '#84cc16', cumulative: true },
    walking_speed:   { label: 'Gehgeschwindigkeit', unit: 'km/h', icon: '💨', color: '#f97316' },
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
// Schwimmen wird anders gerechnet als Laufen/Radfahren: Distanz in Metern,
// Pace in min/100 m. Neben den bekannten Typen greift ein Namens-Fallback,
// damit auch kuenftige Apple-Bezeichnungen ("Freiwasserschwimmen") passen.
function isSwimWorkout(t) {
    if (wMeta(t).cls === 'swim') return true;
    return /schwimm|swim/i.test(t || '');
}

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

// v1.39.1: Durchschnitt ohne Messluecken.
// Tage, an denen kaum gemessen wurde (angebrochener heutiger Tag, Uhr nicht
// getragen, Sync abgebrochen), liefern bei kumulativen Metriken wie Schritten
// nur einen Bruchteil des ueblichen Werts und ziehen den Ø stark nach unten,
// obwohl an dem Tag gar nicht "wenig passiert" ist. Als Messluecke gilt daher
// alles unter 20 % des Medians der Reihe — der Median ist gegenueber genau
// solchen Ausreissern robust, ein Mittelwert waere es nicht.
// Bei nicht-kumulativen Metriken (Puls, Gewicht, HRV, …) greift die Regel
// praktisch nie, weil echte Messwerte dort nie auf 20 % des Medians fallen.
const GAP_FRACTION = 0.2;
function gapThreshold(values) {
    const vals = values.map(Number).filter(Number.isFinite);
    if (!vals.length) return 0;
    const sorted = [...vals].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    const median = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
    return median > 0 ? median * GAP_FRACTION : 0;
}
function cleanAverage(values) {
    const vals = values.map(Number).filter(Number.isFinite);
    if (!vals.length) return { avg: null, values: [], skipped: 0 };
    const used = vals.filter(v => v >= gapThreshold(vals));
    if (!used.length) return { avg: null, values: [], skipped: vals.length };
    return {
        avg: used.reduce((s, v) => s + v, 0) / used.length,
        values: used,
        skipped: vals.length - used.length,
    };
}

// Gleitender Durchschnitt als Trendlinie — zentriert, d. h. das Fenster liegt
// je zur Haelfte vor und hinter dem Punkt. Anders als bei einem nachlaufenden
// Fenster (wie in der Ausgaben-Statistik, wo die Reihe fortlaufend waechst)
// liegen hier alle Daten des Zeitraums schon vor, es gibt also keinen Grund
// fuer den Versatz. Messluecken (< threshold) fliessen nicht ein.
function rollingAverage(values, win, threshold) {
    const half = Math.floor(win / 2);
    return values.map((_, i) => {
        let sum = 0, n = 0;
        for (let j = Math.max(0, i - half); j <= Math.min(values.length - 1, i + half); j++) {
            const v = Number(values[j]);
            if (!Number.isFinite(v) || v < threshold) continue;
            sum += v; n++;
        }
        return n ? sum / n : null;
    });
}
// Fensterbreite passend zur Reihenlaenge: kurze Zeitraeume brauchen ein
// schmales Fenster, sonst buegelt die Linie den ganzen Verlauf platt.
function trendWindow(n) {
    const win = n <= 10 ? 3 : n <= 40 ? 7 : n <= 120 ? 14 : 30;
    return Math.max(2, Math.min(win, n));
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
// chartDefaults ersetzt bei einem `plugins`-Override den kompletten Block --
// wer nur die Legende abschaltet, verliert sonst das getunte Tooltip-Styling
// (und damit die Dark-Mode-Farben). Dieser Helfer liefert es zum Wiedereinsetzen.
function themedTooltip(extra) {
    const th = chartTheme();
    return Object.assign({
        backgroundColor: th.surface, borderColor: th.border, borderWidth: 1,
        titleColor: th.text, bodyColor: th.text, padding: 10, cornerRadius: 8,
        displayColors: true, boxPadding: 3,
    }, extra || {});
}

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
    vitalDays: 30, vitalInit: false,
    metricCards: null, metricChartMap: {},   // v1.46.0: Karten bleiben stehen,
                                             // nur die Daten werden getauscht
    metricOrder: null, sortableMetrics: null,

    chartBp: null, chartGlucose: null,
    sleepDays: 30, sleepInit: false, chartSleepTimes: null,
    sleepUsable: [], sleepWindows: [],   // Naechte hinter den Balken (Tooltip)
    workoutsLoaded: false, workoutsAll: [], workoutFilter: '', workoutRange: 0,
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
    // v1.39.1: Der frueher hier stehende Schlaf-Insight ist entfallen — er hat
    // die rohen `asleep_minutes` benutzt und damit (siehe renderSleepBlock)
    // regelmaessig zu wenig angezeigt, direkt neben der korrekten Karte
    // "Letzte Nacht". Doppelte, widerspruechliche Angabe statt Mehrwert.
    if (s.workouts_this_week >= 4) items.push({ icon:'🔥', txt:`<strong>${s.workouts_this_week}</strong> Workouts diese Woche — respektabel!` });
    box.innerHTML = items.map(i => `<div class="insight"><span class="icon">${i.icon}</span><span>${i.txt}</span></div>`).join('');
}

function renderSleepBlock(elId, sl) {
    const el = document.getElementById(elId);
    if (!sl) { el.className = 'h-empty'; el.textContent = 'Noch keine Daten synchronisiert.'; return; }
    el.className = '';
    const num = (v) => { const n = Number(v); return Number.isFinite(n) ? n : 0; };
    // Fallback: fehlt asleep_minutes, nutze die Summe der Phasen
    const phases = num(sl.core_minutes) + num(sl.deep_minutes) + num(sl.rem_minutes);
    const rawAsleep = num(sl.asleep_minutes);
    // v1.36.1 Bugfix: Apple's `asleep_minutes` zaehlt oft nur den
    // "asleep unspecified"-Anteil und ignoriert Core/Deep/REM. Wenn Phasen
    // vorhanden sind, ist deren Summe die verlaessliche geschlafene Zeit.
    // Vorher hat der Header teils weniger angezeigt als die einzelne
    // Phasen-Legende (z. B. Core 4 h + Tief 1,5 h + REM 1 h = 6,5 h, Header
    // aber "5 h") -- genau das ist der vom User gemeldete Fall.
    const asleepMin = phases > 0 ? Math.max(phases, rawAsleep) : rawAsleep;
    // Fallback fuer in_bed: sleep + awake oder Zeitspanne
    let inBedMin = num(sl.in_bed_minutes);
    if (inBedMin <= 0) {
        const awake = num(sl.awake_minutes);
        if (asleepMin + awake > 0) inBedMin = asleepMin + awake;
        else if (sl.sleep_start && sl.sleep_end) {
            const diff = (new Date(sl.sleep_end) - new Date(sl.sleep_start)) / 60000;
            if (diff > 0) inBedMin = diff;
        }
    }
    const total = phases + num(sl.awake_minutes);
    const pct = (v) => total ? (100 * (v||0) / total).toFixed(1) : 0;
    const pctInt = (v) => total ? Math.round(100 * (v||0) / total) : 0;
    const asleepH = asleepMin / 60;
    const inBedH  = inBedMin  / 60;
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
                <span><span class="h-phase-dot" style="background:var(--blue)"></span>Core <strong>${fmt1((sl.core_minutes||0)/60)} h</strong> <em>${pctInt(sl.core_minutes)} %</em></span>
                <span><span class="h-phase-dot" style="background:var(--purple)"></span>Tief <strong>${fmt1((sl.deep_minutes||0)/60)} h</strong> <em>${pctInt(sl.deep_minutes)} %</em></span>
                <span><span class="h-phase-dot" style="background:var(--teal)"></span>REM <strong>${fmt1((sl.rem_minutes||0)/60)} h</strong> <em>${pctInt(sl.rem_minutes)} %</em></span>
                <span><span class="h-phase-dot" style="background:var(--orange)"></span>Wach <strong>${fmt1((sl.awake_minutes||0)/60)} h</strong> <em>${pctInt(sl.awake_minutes)} %</em></span>
            </div>` : ''}
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
            loadMetricCharts(); loadBpGlucoseCharts();
        });
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
        options: chartDefaults({
            plugins: { legend: { display: false }, tooltip: themedTooltip() },
        }),
    });
    loadMetricCharts(); loadBpGlucoseCharts();
}

// v1.45.0: Jede Metrik bekommt ihr eigenes Diagramm. Vorher gab es eine
// Kachelreihe als Auswahl plus EIN grosses Diagramm — fuer den Vergleich
// zweier Metriken musste man hin- und herklicken, waehrend Blutdruck und
// Blutzucker (mit deutlich weniger Datenpunkten) dauerhaft sichtbar waren.
//
// v1.46.0: Beim Wechsel des Zeitraums werden Karten und Chart-Instanzen NICHT
// mehr neu gebaut. Vorher flog das Raster raus und wurde durch "Lade …"
// ersetzt — sichtbares Flackern und jedes Mal ein Aufbau von null. Jetzt
// bleiben die Diagramme stehen, bekommen die neuen Daten zugewiesen und
// animieren per Chart.js von den alten Werten auf die neuen.
// Gespeicherte Reihenfolge auf die bekannten Metriken anwenden: erst die
// sortierten, dann alles, was der Nutzer noch nie in der Hand hatte (neue
// Metriken landen so hinten statt zu verschwinden).
function orderedMetricKeys() {
    const all = Object.keys(METRIC_LABELS);
    const saved = (state.metricOrder || []).filter(k => all.includes(k));
    return saved.concat(all.filter(k => !saved.includes(k)));
}

async function loadMetricCharts() {
    const box = document.getElementById('hMetricCharts');
    if (!box) return;

    if (!state.metricCards) {
        // Reihenfolge einmalig holen; scheitert das, bleibt die Default-Folge.
        try {
            const r = await HEALTH_API.metricOrder();
            state.metricOrder = (r && r.order) || [];
        } catch (e) { state.metricOrder = []; }
        state.metricCards = {};
        box.innerHTML = '';
        orderedMetricKeys().forEach(k => {
            const card = buildMetricShell(k);
            box.appendChild(card);
            state.metricCards[k] = card;
        });
        initMetricSortable(box);
    }
    const keys = orderedMetricKeys();

    const days = state.vitalDays;
    box.classList.add('is-loading');
    const rowsList = await Promise.all(
        keys.map(k => HEALTH_API.metricSeries(k, days).catch(() => [])));
    // Zwischenzeitlicher Zeitraum-Wechsel: das spaetere Ergebnis gewinnt,
    // ein veraltetes ueberschreibt die frischeren Daten nicht mehr.
    if (state.vitalDays !== days) return;
    box.classList.remove('is-loading');
    keys.forEach((k, i) => updateMetricCard(k, rowsList[i], days));
}

// Gleiche Wert-Ermittlung wie fuer die Chart-Linie (qty, sonst avg_value),
// damit Kopfzahl, Statistik und Kurve nicht auf verschiedenen Zahlen basieren.
function metricValueOf(r) {
    const v = Number(r.qty);
    return Number.isFinite(v) ? v : Number(r.avg_value);
}

// Leere Karte samt Canvas — Inhalt kommt aus updateMetricCard().
function buildMetricShell(key) {
    const meta = METRIC_LABELS[key];
    const card = document.createElement('div');
    card.className = 'stat-card h-metric-card';
    card.dataset.metric = key;
    card.innerHTML = `
        <div class="h-metric-head">
            <div class="h-metric-name"><span class="drag-handle" title="Ziehen zum Sortieren">⠿</span><span class="h-metric-ico">${meta.icon}</span>${escHtml(meta.label)}</div>
            <div class="h-metric-big" data-role="big">–</div>
        </div>
        <div class="h-metric-stats" data-role="stats"></div>
        <div class="chart-wrap mini">
            <canvas id="hMc_${key}"></canvas>
            <div class="h-metric-empty" data-role="empty" hidden>Keine Messwerte</div>
        </div>`;
    return card;
}

function updateMetricCard(key, rows, days) {
    const card = state.metricCards[key];
    if (!card) return;
    const meta = METRIC_LABELS[key];
    const data = rows.map(metricValueOf);
    const vals = data.filter(Number.isFinite);

    let headline = '–', stats = 'Keine Daten in diesem Zeitraum';
    if (vals.length) {
        // Ø, Min und Max beziehen sich auf die echten Messtage — Messluecken
        // wuerden sonst als Rekord-Tief in der Statistik landen.
        const { avg, values: solid, skipped } = cleanAverage(vals);
        const fmtV = (v) => v >= 100 ? fmt0(v) : fmt1(v);
        const base = solid.length ? solid : vals;
        const mn = Math.min(...base), mx = Math.max(...base);
        const span = days > 0 ? `${days} T.` : 'gesamt';
        if (meta.cumulative) {
            headline = fmt0(vals.reduce((a, v) => a + v, 0));
            stats = `Σ ${span} · Ø ${avg != null ? fmt0(avg) : '–'}/Tag · Max ${fmt0(mx)}`;
        } else {
            headline = avg != null ? fmtV(avg) : '–';
            stats = `Ø ${span} · Min ${fmtV(mn)} · Max ${fmtV(mx)}`;
        }
        if (skipped) stats += ` · ${skipped} Messlücke${skipped === 1 ? '' : 'n'} raus`;
    }
    card.classList.toggle('is-empty', vals.length === 0);
    card.querySelector('[data-role="big"]').innerHTML =
        headline + (meta.unit ? `<small>${escHtml(meta.unit)}</small>` : '');
    card.querySelector('[data-role="stats"]').textContent = stats;
    card.querySelector('[data-role="empty"]').hidden = vals.length > 0;

    const labels = rows.map(r => fmtDate(r.sample_date || r.recorded_at));
    const win = trendWindow(data.length);
    const trend = vals.length ? rollingAverage(data, win, gapThreshold(vals)) : [];

    let ch = state.metricChartMap[key];
    if (!ch) {
        ch = mountMetricChart(key, labels, data, trend, win);
        if (!ch) return;
        state.metricChartMap[key] = ch;
        return;
    }
    ch.data.labels = labels;
    ch.data.datasets[0].data = data;
    ch.data.datasets[1].data = trend;
    ch.data.datasets[1].label = `Ø gleitend (${win})`;
    ch.update();
}

// Drag & Drop wie bei Achievements/Wochenzielen: Anfassen nur am Griff, auf
// dem Touchscreen mit kurzer Verzoegerung, damit Scrollen weiter funktioniert.
function initMetricSortable(box) {
    if (state.sortableMetrics) return;
    if (typeof Sortable === 'undefined') {
        // Sortable.min.js laedt mit `defer` und ist beim ersten Rendern unter
        // Umstaenden noch nicht da (health.js selbst laeuft undeferred am
        // Body-Ende). Dann einmal nach dem load-Event nachziehen, statt das
        // Sortieren still gar nicht zu aktivieren.
        window.addEventListener('load', () => initMetricSortable(box), { once: true });
        return;
    }
    state.sortableMetrics = Sortable.create(box, {
        handle: '.drag-handle', animation: 150, delay: 120, delayOnTouchOnly: true,
        onEnd: async () => {
            const order = Array.from(box.children)
                .map(el => el.dataset.metric)
                .filter(Boolean);
            if (!order.length) return;
            const previous = state.metricOrder;
            state.metricOrder = order;
            try {
                await HEALTH_API.saveMetricOrder(order);
                showToast('Reihenfolge gespeichert');
            } catch (e) {
                // Serverstand gilt: zuruecksetzen statt eine Reihenfolge zu
                // zeigen, die beim naechsten Laden wieder anders waere.
                state.metricOrder = previous;
                showToast('Reihenfolge speichern fehlgeschlagen', true);
                orderedMetricKeys().forEach(k => {
                    const card = state.metricCards[k];
                    if (card) box.appendChild(card);
                });
            }
        },
    });
}

function mountMetricChart(key, labels, data, trend, win) {
    const canvas = document.getElementById('hMc_' + key);
    if (!canvas) return null;
    const meta = METRIC_LABELS[key];
    const th = chartTheme();
    return new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: `${meta.label}${meta.unit ? ' (' + meta.unit + ')' : ''}`,
                    data, borderColor: meta.color, backgroundColor: meta.color + '1f',
                    tension: 0.3, fill: true, pointRadius: 0, borderWidth: 2,
                },
                // Gleitende Ø-/Trendlinie (ohne Messluecken, siehe rollingAverage)
                {
                    label: `Ø gleitend (${win})`, data: trend,
                    borderColor: th.muted, borderWidth: 1.5, borderDash: [5, 4],
                    tension: 0.35, fill: false, pointRadius: 0, spanGaps: true,
                },
            ],
        },
        options: chartDefaults({
            plugins: { legend: { display: false }, tooltip: themedTooltip() },
            scales: {
                x: { ticks: { color: th.muted, maxRotation: 0, autoSkipPadding: 20,
                              font: { size: 10 } }, grid: { display: false } },
                y: { ticks: { color: th.muted, font: { size: 10 }, maxTicksLimit: 5 },
                     grid: { color: th.grid }, beginAtZero: false },
            },
        }),
    });
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
// Stunden-Offset ab 18:00 -> "HH:MM". Werte ueber 24 sind erlaubt (eine Nacht
// darf ueber die 18:00-Grenze des Folgetags hinausreichen) und wrappen sauber.
function sleepOffsetToClock(v) {
    let h = (18 + Number(v)) % 24;
    if (h < 0) h += 24;
    let hh = Math.floor(h);
    let mm = Math.round((h - hh) * 60);
    if (mm === 60) { mm = 0; hh = (hh + 1) % 24; }
    return String(hh).padStart(2, '0') + ':' + String(mm).padStart(2, '0');
}

// v1.46.0: Phasen und Schlaffenster stecken in EINEM Diagramm. Die y-Achse ist
// die Uhrzeit, jede Nacht ein Balken von der Zubettgeh- bis zur Aufstehzeit,
// und die Phasen kacheln diesen Balken mit ihrer ECHTEN Dauer (keine Normierung
// auf eine gemeinsame Grundlinie). Technisch sind das mehrere Floating-Bar-
// Datasets im selben x-Slot (`x.stacked` gruppiert sie uebereinander,
// `y.stacked` bleibt aus, damit Chart.js die Werte nicht zusaetzlich addiert) --
// die Segmentgrenzen rechnen wir selbst aus.
//
// Was die Daten NICHT hergeben: die zeitliche Lage der Phasen. Apple liefert je
// Nacht nur Summen. Die Laenge jedes Abschnitts stimmt daher, seine Position im
// Balken ist eine feste Reihenfolge und keine Messung -- kein Hypnogramm.
const SLEEP_SEGMENTS = [
    { key: 'deep',   label: 'Tief',              color: '#4338ca' },
    { key: 'core',   label: 'Kern',              color: '#6366f1' },
    { key: 'rem',    label: 'REM',               color: '#a5b4fc' },
    { key: 'rest',   label: 'ohne Phasendetail', color: '#c7d2fe' },
    { key: 'awake',  label: 'Wach',              color: '#f59e0b' },
];

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
    const th = chartTheme();
    state.chartSleepTimes = new Chart(document.getElementById('hChartSleepTimes').getContext('2d'), {
        type: 'bar',
        data: { labels: [], datasets: [
            // Dataset 0 ist der helle Rahmen "Zeit im Bett". Er liegt unter den
            // Phasen und bleibt dort sichtbar, wo die Summe der Phasen die
            // Bettzeit nicht ganz ausfuellt.
            { label: 'Im Bett', data: [], backgroundColor: th.grid,
              borderColor: th.border, borderWidth: 1, borderSkipped: false,
              borderRadius: 4, barPercentage: 0.8, categoryPercentage: 0.9 },
            ...SLEEP_SEGMENTS.map(seg => ({
                label: seg.label, data: [], backgroundColor: seg.color,
                borderSkipped: false, barPercentage: 0.8, categoryPercentage: 0.9,
            })),
            // v1.46.5: Was hinter der 18:00-Kante liegt, wird in DERSELBEN
            // Spalte ab der Oberkante weitergezeichnet — die Achse ist ein
            // 24-h-Kreis, oben und unten sind dieselbe Uhrzeit. Diese Datasets
            // sind die Fortsetzung: gleicher Aufbau, gleiche Farben.
            //
            // Vorher lief der Rest in der FOLGESPALTE weiter (v1.46.4). Das
            // war falsch: die naechste Spalte ist die naechste aufgezeichnete
            // Nacht und oft nicht der naechste Tag — bei einer Luecke von zwei
            // Wochen behauptete der Balken einen Schlaf, den es dort nie gab.
            // Und die betroffenen Naechte enden gar nicht spaet, sie BEGINNEN
            // vor 18:00 (z.B. 16:30 bis 01:30); ihr Rest gehoert derselben Nacht.
            { label: 'Im Bett (Fortsetzung)', data: [], backgroundColor: th.grid,
              borderColor: th.border, borderWidth: 1, borderSkipped: false,
              borderRadius: 4, wrap: true, barPercentage: 0.8, categoryPercentage: 0.9 },
            ...SLEEP_SEGMENTS.map(seg => ({
                label: seg.label + ' (nach 18:00)', data: [], backgroundColor: seg.color,
                wrap: true, borderSkipped: false, barPercentage: 0.8, categoryPercentage: 0.9,
            })),
            // Die beiden duennen gruenen Kanten: unten, wo der Balken die
            // 18:00-Grenze reisst, und oben, wo er wieder einsetzt.
            { label: 'über 18:00 hinaus', data: [], backgroundColor: '#22c55e',
              marker: true, borderSkipped: false,
              barPercentage: 0.8, categoryPercentage: 0.9 },
            { label: 'über 18:00 hinaus (oben)', data: [], backgroundColor: '#22c55e',
              marker: true, wrap: true, borderSkipped: false,
              barPercentage: 0.8, categoryPercentage: 0.9 },
        ] },
        options: chartDefaults({
            plugins: {
                legend: { labels: { color: th.text, boxWidth: 12, font: { size: 11 },
                    // Die Fortsetzung benutzt dieselben Farben wie der
                    // Hauptteil und bekommt deshalb keinen zweiten Eintrag.
                    // Der gruene Eintrag taucht nur auf, wenn wirklich eine
                    // Nacht ueber die Kante laeuft.
                    filter: (item, data) => {
                        const ds = data.datasets[item.datasetIndex];
                        if (ds.wrap) return false;
                        return !ds.marker || (ds.data || []).some(v => Array.isArray(v));
                    } } },
                tooltip: themedTooltip({
                    // Segmente ohne Dauer wuerden den Tooltip nur zumuellen.
                    // Segmente ohne Dauer wuerden den Tooltip nur zumuellen, und
                    // die obere Bruchkante teilt sich die Zeile mit der unteren.
                    filter: (item) => Array.isArray(item.raw) && (item.raw[1] - item.raw[0]) > 0.01
                        && !(item.dataset.marker && item.dataset.wrap),
                    callbacks: {
                        label: (ctx) => {
                            if (ctx.dataset.marker) {
                                const w = (state.sleepWindows || [])[ctx.dataIndex];
                                return w ? `Über 18:00 hinaus — läuft oben in derselben Spalte weiter bis ${sleepOffsetToClock(w[1])}`
                                         : 'Über 18:00 hinaus';
                            }
                            return `${ctx.dataset.label}: ${fmt1(ctx.raw[1] - ctx.raw[0])} h`;
                        },
                        footer: (items) => {
                            const first = items && items[0];
                            const w = first ? (state.sleepWindows || [])[first.dataIndex] : null;
                            return w ? `${sleepOffsetToClock(w[0])} → ${sleepOffsetToClock(w[1])}` : '';
                        },
                    },
                }),
            },
            scales: {
                x: { stacked: true, ticks: { color: th.muted, maxRotation: 0, autoSkipPadding: 12 },
                     grid: { display: false } },
                y: { stacked: false, reverse: true, min: 0, max: 24,
                     ticks: { color: th.muted, stepSize: 3, callback: (v) => sleepOffsetToClock(v) },
                     grid: { color: th.grid },
                     title: { display: true, text: 'Uhrzeit', color: th.muted } },
            },
        }),
    });
    loadSleepChart();
}

async function loadSleepChart() {
    try {
        const rows = await HEALTH_API.sleep(state.sleepDays);
        const kpiBox = document.getElementById('hSleepKpis');
        if (!rows.length) {
            kpiBox.innerHTML = `<div class="stat-empty" style="grid-column:1/-1">
                Keine Schlaf-Daten für diesen Zeitraum. Auto Health Export exportiert
                Schlaf nur, wenn Apple Watch getragen wurde (oder ein anderer Tracker
                die Schlafphasen liefert).
            </div>`;
            const emptyNote = document.getElementById('hSleepNote');
            if (emptyNote) emptyNote.textContent = '';
            state.sleepUsable = []; state.sleepWindows = [];
            renderSleepRhythm([]);
            state.chartSleepTimes.data.labels = [];
            state.chartSleepTimes.data.datasets.forEach(d => d.data = []);
            state.chartSleepTimes.update();
            return;
        }
        // Ø nur ueber Naechte mit tatsaechlichem Wert; sonst verwaessern Null-
        // Naechte (z.B. Tage ohne Apple-Watch) den Schnitt komplett. Zusaetzlich
        // fallen wir auf die Phasen zurueck, wenn das Feld selbst leer ist,
        // damit die KPIs mit dem Balken-Chart konsistent bleiben.
        const num = (v) => { const n = Number(v); return Number.isFinite(n) ? n : null; };
        const asleepMin = (r) => {
            const v = num(r.asleep_minutes);
            if (v != null && v > 0) return v;
            const phases = (num(r.core_minutes)||0) + (num(r.deep_minutes)||0) + (num(r.rem_minutes)||0);
            return phases > 0 ? phases : null;
        };
        const inBedMin = (r) => {
            const v = num(r.in_bed_minutes);
            if (v != null && v > 0) return v;
            const sleep = asleepMin(r) || 0;
            const awake = num(r.awake_minutes) || 0;
            if (sleep + awake > 0) return sleep + awake;
            if (r.sleep_start && r.sleep_end) {
                const diff = (new Date(r.sleep_end) - new Date(r.sleep_start)) / 60000;
                return diff > 0 ? diff : null;
            }
            return null;
        };
        // Uhrzeit -> Stunden-Offset ab 18:00 (0 = 18:00, 24 = 18:00 Folgetag)
        const toOffset = (iso) => {
            if (!iso) return null;
            const d = new Date(iso);
            if (Number.isNaN(d.getTime())) return null;
            let h = d.getHours() + d.getMinutes() / 60;
            let off = h - 18; if (off < 0) off += 24;
            return off;
        };

        // v1.40.2: Naechte mit unter 1 h Gesamtschlaf sind praktisch immer
        // Tage ohne getragene Apple Watch (kurz zum Laden abgelegt, spaet
        // angelegt, Mittagsschlaf-Fragment). Sie zaehlten bisher voll mit und
        // haben alle Ø-Werte nach unten gezogen.
        // Das Gate ist bewusst die GESAMTE Schlafdauer der Nacht und nicht die
        // jeweilige Phase: sonst wuerde eine Nacht nur aus einzelnen Kacheln
        // fallen (z.B. ohne Tiefschlaf-Anteil) und die vier Kacheln bezoegen
        // sich auf unterschiedliche Naechte -- Ø-Effizienz und Ø-Dauer waeren
        // dann nicht mehr miteinander vergleichbar.
        const MIN_SLEEP_MIN = 60;
        const usable = rows.filter(r => (asleepMin(r) || 0) >= MIN_SLEEP_MIN);
        const skippedNights = rows.length - usable.length;

        // v1.46.2: Ohne Zubettgeh- UND Aufstehzeit laesst sich eine Nacht auf
        // der Uhrzeit-Achse nicht platzieren -- sie stand bisher als leere
        // Spalte mit Datum im Diagramm. Solche Naechte kommen z.B. aus der
        // alten Tages-CSV, die die Schlafphasen ohne Zeitstempel liefert.
        // Sie fliegen aus dem Diagramm, bleiben aber in den Ø-Kacheln: ihre
        // Dauer ist echt gemessen, nur eben ohne Uhrzeit. Die Notiz unter den
        // Kacheln benennt beide Faelle, damit nichts still verschwindet.
        const plotted = usable.filter(r => r.sleep_start && r.sleep_end
            && toOffset(r.sleep_start) != null && toOffset(r.sleep_end) != null);
        const undatedNights = usable.length - plotted.length;
        state.sleepUsable = plotted;
        // Ein Balken je Nacht: [Zubettgehen, Aufstehen] als Offset ab 18:00.
        // Endet eine Nacht rechnerisch vor ihrem Start (Einschlafen vor 18:00),
        // laeuft sie ueber die Tagesgrenze — dann +24 und die Achse waechst mit,
        // statt den Balken verkehrt herum zu zeichnen.
        const windows = plotted.map(r => {
            const a = toOffset(r.sleep_start), b = toOffset(r.sleep_end);
            if (a == null || b == null) return null;
            return [a, b <= a ? b + 24 : b];
        });
        // `sleepWindows` behaelt die UNGEKAPPTEN Zeiten — Tooltip und Fusszeile
        // sollen die echte Aufstehzeit nennen, auch wenn der Balken gekappt ist.
        state.sleepWindows = windows;
        const AXIS_END = 24;   // 18:00 des Folgetags
        // Der Balken bis zur 18:00-Kante ...
        const clipped = windows.map(w => w ? [w[0], Math.min(w[1], AXIS_END)] : null);
        // ... und der Rest, der oben in DERSELBEN Spalte weiterlaeuft. Er hoert
        // spaetestens am eigenen Zubettgeh-Zeitpunkt auf: laenger als 24 h ist
        // keine Nacht, und der Balken darf sich nicht selbst ueberlappen.
        const wrapped = windows.map(w => (w && w[1] > AXIS_END + 1e-6)
            ? [0, Math.min(w[1] - AXIS_END, w[0])] : null);
        // Duenne gruene Kanten an der Bruchstelle: unten am Achsenende, oben
        // dort, wo die Nacht wieder einsetzt.
        const cutLow  = wrapped.map(x => x ? [AXIS_END - 0.2, AXIS_END] : null);
        const cutHigh = wrapped.map(x => x ? [0, 0.2] : null);

        // Phasen kacheln das Fenster ab der Zubettgeh-Kante mit ihrer echten
        // Dauer. Ueberschiesst die Summe das Fenster (Rundung in der Quelle),
        // wird am Fensterende abgeschnitten statt darueber hinaus gemalt.
        const segH = (r) => {
            const h = (v) => (num(v) || 0) / 60;
            const phases = h(r.deep_minutes) + h(r.core_minutes) + h(r.rem_minutes);
            return {
                deep: h(r.deep_minutes), core: h(r.core_minutes), rem: h(r.rem_minutes),
                rest: Math.max(0, ((asleepMin(r) || 0) / 60) - phases),
                awake: h(r.awake_minutes),
            };
        };
        // Gekachelt wird ueber das GANZE Fenster, auch ueber die 18:00-Kante
        // hinweg; jedes Segment wird an der Kante geteilt. Der Teil davor
        // landet im Hauptbalken, der Teil dahinter oben in derselben Spalte --
        // eine Phase, die genau auf der Kante liegt, erscheint dadurch in
        // beiden Stuecken mit ihrer jeweils richtigen Laenge.
        const segData = SLEEP_SEGMENTS.map(() => []);
        const segWrap = SLEEP_SEGMENTS.map(() => []);
        plotted.forEach((r, i) => {
            const w = windows[i];
            if (!w) { segData.forEach(d => d.push(null)); segWrap.forEach(d => d.push(null)); return; }
            const parts = segH(r);
            const endLow  = Math.min(w[1], AXIS_END);
            const endHigh = wrapped[i] ? wrapped[i][1] : 0;
            let cursor = w[0];
            SLEEP_SEGMENTS.forEach((seg, si) => {
                const len = parts[seg.key] || 0;
                const from = cursor, to = cursor + len;
                const lowFrom = Math.min(from, endLow), lowTo = Math.min(to, endLow);
                segData[si].push(lowTo - lowFrom > 0.01 ? [lowFrom, lowTo] : null);
                const hiFrom = Math.min(Math.max(from - AXIS_END, 0), endHigh);
                const hiTo   = Math.min(Math.max(to   - AXIS_END, 0), endHigh);
                segWrap[si].push(hiTo - hiFrom > 0.01 ? [hiFrom, hiTo] : null);
                cursor = to;
            });
        });

        const ds = state.chartSleepTimes.data.datasets;
        const N = SLEEP_SEGMENTS.length;
        state.chartSleepTimes.data.labels = plotted.map(r => fmtDate(r.sleep_date));
        ds[0].data = clipped;
        segData.forEach((d, si) => { ds[si + 1].data = d; });
        ds[N + 1].data = wrapped;
        segWrap.forEach((d, si) => { ds[N + 2 + si].data = d; });
        ds[2 * N + 2].data = cutLow;
        ds[2 * N + 3].data = cutHigh;
        state.chartSleepTimes.update();
        renderSleepRhythm(windows);

        const meanOf = (extract) => {
            const arr = usable.map(extract).filter(v => v != null && v > 0);
            return arr.length ? arr.reduce((s,v)=>s+v,0) / arr.length : null;
        };
        const meanAsleepMin = meanOf(asleepMin);
        const meanInBedMin  = meanOf(inBedMin);
        const meanDeepMin   = meanOf(r => num(r.deep_minutes));
        const effList = usable.map(r => {
            const a = asleepMin(r), b = inBedMin(r);
            return (a != null && b != null && b > 0) ? (a / b) * 100 : null;
        }).filter(v => v != null);
        const avgEff = effList.length ? effList.reduce((s,v)=>s+v,0) / effList.length : null;

        const fmtH = (min) => min == null ? '–' : fmt1(min / 60) + ' h';
        const kpis = [
            { icon: '😴', label: 'Ø Schlafdauer', value: fmtH(meanAsleepMin) },
            { icon: '🛏️', label: 'Ø Im Bett',    value: fmtH(meanInBedMin) },
            { icon: '🌊', label: 'Ø Tiefschlaf', value: fmtH(meanDeepMin) },
            { icon: '✨', label: 'Ø Effizienz',  value: avgEff != null ? fmt0(avgEff) + ' %' : '–' },
        ];
        kpiBox.innerHTML = kpis.map(k => `
            <div class="stat-kpi"><div class="stat-kpi-icon">${k.icon}</div>
                <div class="stat-kpi-label">${k.label}</div>
                <div class="stat-kpi-value">${k.value}</div></div>`).join('');

        // Transparenz statt stiller Filterung: Kacheln und Diagramme zeigen
        // dieselben Naechte, die Zeile darunter nennt die Zahl der weggelassenen.
        const note = document.getElementById('hSleepNote');
        if (note) {
            const nights = (n) => n === 1 ? '1 Nacht' : n + ' Nächte';
            const parts = [];
            if (skippedNights) {
                parts.push(`${nights(skippedNights)} unter 1 h Schlaf – als Messlücke `
                    + `gewertet und aus Ø-Werten und Diagramm ausgenommen.`);
            }
            if (undatedNights) {
                parts.push(`${nights(undatedNights)} ohne Zubettgeh-/Aufstehzeit aufgezeichnet – `
                    + `zählen in die Ø-Werte, lassen sich im Diagramm aber nicht auf der Uhr `
                    + `platzieren.`);
            }
            note.textContent = parts.join(' ');
        }
    } catch (e) { showToast('Fehler: ' + e.message, true); }
}

// v1.46.2: Typische Zubettgeh-/Aufstehzeit mit Streuung.
//
// Gerechnet wird auf den 18:00-Offsets, nicht auf der Uhrzeit selbst: sonst
// waere der Mittelwert aus 23:30 und 00:30 die Mittagszeit statt Mitternacht.
// Innerhalb des 18:00-Fensters sind die Werte linear, Mittelwert und
// Standardabweichung sind dort also unproblematisch.
//
// Streuung = Standardabweichung der Stichprobe (n-1), in Minuten. Sie ist die
// eigentliche Aussage: Ein Mittelwert aus einem Nachtschlaf und einem
// Tagschlaf ist fuer sich genommen wenig wert, die grosse Streuung daneben
// macht genau das sichtbar.
function meanAndSd(values) {
    const arr = values.filter(v => Number.isFinite(v));
    if (!arr.length) return null;
    const mean = arr.reduce((s, v) => s + v, 0) / arr.length;
    if (arr.length < 2) return { mean, sd: null, n: 1 };
    const varSample = arr.reduce((s, v) => s + (v - mean) * (v - mean), 0) / (arr.length - 1);
    return { mean, sd: Math.sqrt(varSample), n: arr.length };
}

function renderSleepRhythm(windows) {
    const box = document.getElementById('hSleepRhythm');
    if (!box) return;
    const valid = (windows || []).filter(Boolean);
    if (!valid.length) { box.innerHTML = ''; return; }

    const bed = meanAndSd(valid.map(w => w[0]));
    const wake = meanAndSd(valid.map(w => w[1]));
    const span = meanAndSd(valid.map(w => w[1] - w[0]));
    const spread = (st) => st && st.sd != null
        ? `<small>± ${fmt0(st.sd * 60)} min</small>` : '';
    const items = [
        { lbl: '🌙 Zubettgehen', val: sleepOffsetToClock(bed.mean), st: bed },
        { lbl: '☀️ Aufstehen',   val: sleepOffsetToClock(wake.mean), st: wake },
        { lbl: '🛏️ Zeit im Bett', val: fmt1(span.mean) + ' h', st: span, minutes: true },
    ];
    // Bei einer Streuung von mehreren Stunden liegt der Mittelwert womoeglich
    // in einer Zeit, zu der nie jemand ins Bett geht (Nacht- und Tagschlaf
    // gemischt). Das dazuzuschreiben ist ehrlicher, als die Zahl fuer sich
    // stehen zu lassen.
    const WOBBLY_MIN = 120;
    box.innerHTML = items.map(i => {
        const wobbly = i.st && i.st.sd != null && i.st.sd * 60 > WOBBLY_MIN;
        const sub = `Ø aus ${valid.length === 1 ? '1 Nacht' : valid.length + ' Nächten'}`
            + (wobbly ? ' · stark schwankend' : '');
        return `
        <div class="h-rhythm-item">
            <div class="h-rhythm-lbl">${i.lbl}</div>
            <div class="h-rhythm-val">${i.val} ${spread(i.st)}</div>
            <div class="h-rhythm-sub">${sub}</div>
        </div>`;
    }).join('');
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
    // v1.43.1: Zeitraum-Chips — die Kennzahlen darueber beziehen sich auf den
    // gewaehlten Zeitraum, nicht mehr zwangslaeufig auf die gesamte Historie.
    const rangeBox = document.getElementById('hWorkoutRangeChips');
    if (rangeBox) {
        rangeBox.querySelectorAll('.stat-chip').forEach(btn => {
            btn.addEventListener('click', () => {
                rangeBox.querySelectorAll('.stat-chip').forEach(c => c.classList.remove('active'));
                btn.classList.add('active');
                state.workoutRange = Number(btn.dataset.range) || 0;
                renderWorkouts();
            });
        });
    }
    renderWorkouts();
}

const WORKOUT_RANGE_LBL = { 0: 'Gesamter Zeitraum', 7: 'Letzte 7 Tage',
                            30: 'Letzte 30 Tage', 90: 'Letzte 90 Tage',
                            365: 'Letztes Jahr' };

function renderWorkouts() {
    const days = Number(state.workoutRange) || 0;
    const since = days ? Date.now() - days * 86400000 : null;
    const rows = state.workoutsAll.filter(w => {
        if (state.workoutFilter && w.workout_type !== state.workoutFilter) return false;
        if (since == null) return true;
        const t = Date.parse(w.start_at);
        return Number.isFinite(t) && t >= since;
    });
    const kpiBox = document.getElementById('hWorkoutKpis');
    const rangeEl = document.getElementById('hWorkoutRangeLbl');
    const list = document.getElementById('hWorkoutList');
    if (rangeEl) rangeEl.textContent = WORKOUT_RANGE_LBL[days] || 'Gesamter Zeitraum';
    if (!rows.length) {
        kpiBox.innerHTML = '';
        list.className = 'h-empty';
        list.innerHTML = state.workoutsAll.length
            ? 'Keine Workouts in diesem Zeitraum.'
            : 'Noch keine Workouts synchronisiert.';
        return;
    }
    const totalMin = rows.reduce((s, w) => s + (Number(w.duration_min) || 0), 0);
    // Durchschnitte nur ueber die Workouts bilden, die den Wert wirklich
    // mitbringen — sonst zieht jedes Workout ohne Kalorienwert den Schnitt
    // nach unten.
    const durArr = rows.map(w => Number(w.duration_min)).filter(v => Number.isFinite(v) && v > 0);
    const kcalArr = rows.map(w => Number(w.active_energy_kcal)).filter(Number.isFinite);
    const avgOf = arr => arr.length ? arr.reduce((s, v) => s + v, 0) / arr.length : null;
    const avgDur = avgOf(durArr);
    const avgKcal = avgOf(kcalArr);
    // Puls: nur plausible Werte mitteln. Bis v1.43.0 hat der CSV-Import bei
    // manchen Exporten die HRV-Spalte (ms) als Puls gespeichert; Migration 029
    // raeumt die Altlasten weg, dieser Filter faengt alles ab, was trotzdem
    // noch danebenliegt.
    const hrArr = rows.map(w => Number(w.avg_heart_rate))
                      .filter(v => Number.isFinite(v) && v >= 30 && v <= 240);
    const avgHr = avgOf(hrArr);
    const kpis = [
        { icon:'⏱️', lbl:'Gesamtzeit', val: fmtDuration(totalMin) },
        { icon:'⌛', lbl:'Ø Dauer', val: avgDur != null ? fmtDuration(avgDur) : '–' },
        { icon:'🔥', lbl:'Ø Kalorien (aktiv)', val: avgKcal != null ? fmt0(avgKcal) + ' kcal' : '–' },
        { icon:'❤️', lbl:'Ø Puls', val: avgHr != null ? fmt0(avgHr) + ' bpm' : '–',
          sub: avgHr != null
              ? `aus ${hrArr.length} von ${rows.length} Workout${rows.length === 1 ? '' : 's'}`
              : 'kein Pulswert importiert' },
    ];
    kpiBox.innerHTML = kpis.map(k => `
        <div class="stat-kpi"><div class="stat-kpi-icon">${k.icon}</div>
            <div class="stat-kpi-label">${k.lbl}</div>
            <div class="stat-kpi-value">${k.val}</div>
            ${k.sub ? `<div class="stat-kpi-sub">${k.sub}</div>` : ''}</div>`).join('');
    list.className = '';
    list.innerHTML = rows.map(w => renderWorkoutCard(w)).join('');
}

function renderWorkoutCard(w) {
    const m = wMeta(w.workout_type);
    const swim = isSwimWorkout(w.workout_type);
    const dist = Number(w.distance_m);
    const hasDist = Number.isFinite(dist) && dist > 0;
    const distStr = hasDist
        ? ((dist >= 1000 && !swim) ? fmt1(dist/1000) + ' <small>km</small>'
                                   : fmt0(dist) + ' <small>m</small>')
        : null;
    // Pace nur fuer Distanz-Sportarten. Beim Schwimmen ist die uebliche (und
    // von der Uhr angezeigte) Einheit min/100 m — dieselbe Einheit in min/km
    // waere zwar rechnerisch dasselbe, aber als "38:00" nicht lesbar.
    let paceStr = null;
    if (hasDist && (w.duration_min > 0)) {
        const refM = swim ? 100 : 1000;
        const pace = w.duration_min / (dist / refM);
        const paceMax = swim ? 20 : 60;
        if (Number.isFinite(pace) && pace > 0 && pace < paceMax) {
            let mm = Math.floor(pace);
            let ss = Math.round((pace - mm) * 60);
            if (ss === 60) { mm += 1; ss = 0; }
            paceStr = `${mm}:${String(ss).padStart(2,'0')} `
                + `<small>min/${swim ? '100 m' : 'km'}</small>`;
        }
    }
    const tiles = [
        { lbl:'Dauer', val: fmtDuration(w.duration_min) },
        w.active_energy_kcal != null ? { lbl:'Aktive Energie', val: fmt0(w.active_energy_kcal) + ' <small>kcal</small>' } : null,
        w.total_energy_kcal != null && w.total_energy_kcal !== w.active_energy_kcal
            ? { lbl:'Gesamt-Energie', val: fmt0(w.total_energy_kcal) + ' <small>kcal</small>' } : null,
        hasDist ? { lbl:'Distanz', val: distStr } : null,
        paceStr ? { lbl:'Pace', val: paceStr } : null,
        w.avg_heart_rate != null ? { lbl:'Ø Puls', val: fmt0(w.avg_heart_rate) + ' <small>bpm</small>' } : null,
        w.max_heart_rate != null ? { lbl:'Max Puls', val: fmt0(w.max_heart_rate) + ' <small>bpm</small>' } : null,
        w.elevation_m != null && w.elevation_m > 0
            ? { lbl:'Aufstieg', val: fmt0(w.elevation_m) + ' <small>m</small>' } : null,
    ].filter(Boolean);
    return `
        <div class="h-workout-card" data-wid="${w.id}">
            <div class="h-workout-head">
                <div class="h-workout-icon ${m.cls}">${m.icon}</div>
                <div class="h-workout-main">
                    <div class="h-workout-title">${escHtml(m.de)}</div>
                    <div class="h-workout-sub">${fmtDateTime(w.start_at)}</div>
                </div>
                <button class="h-workout-more" onclick="toggleWorkoutExtras(${w.id})"
                        aria-expanded="false" title="Zusatzdaten">＋</button>
                <button class="h-workout-del" onclick="deleteWorkout(${w.id})"
                        title="Workout löschen">✕</button>
            </div>
            <div class="h-workout-detail-grid">
                ${tiles.map(t => `<div class="h-workout-detail-tile">
                    <div class="h-workout-detail-lbl">${t.lbl}</div>
                    <div class="h-workout-detail-val">${t.val}</div>
                </div>`).join('')}
            </div>
            <div class="h-workout-extras-wrap" id="hwx-${w.id}" style="display:none"></div>
        </div>`;
}

async function toggleWorkoutExtras(id) {
    const card = document.querySelector(`.h-workout-card[data-wid="${id}"]`);
    if (!card) return;
    const wrap = document.getElementById('hwx-' + id);
    const btn = card.querySelector('.h-workout-more');
    if (wrap.style.display !== 'none') {
        wrap.style.display = 'none';
        btn.textContent = '＋'; btn.setAttribute('aria-expanded', 'false');
        return;
    }
    if (!wrap.dataset.loaded) {
        wrap.innerHTML = '<div class="stat-loading">Lade Zusatzdaten …</div>';
        wrap.style.display = '';
        try {
            const w = await HEALTH_API.workoutDetail(id);
            const extras = (w.extra_metrics || []).filter(x => x.value != null && Math.abs(x.value) > 0.0001);
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
            wrap.innerHTML = extras.length ? `
                <div class="h-workout-extras"><table>${extras.map(x => `
                    <tr><td>${escHtml(extraLabels[x.metric_key] || x.metric_key)}</td>
                        <td>${fmt1(x.value)}${x.unit ? ' ' + escHtml(x.unit) : ''}</td></tr>`).join('')}
                </table></div>` : '<div class="h-empty" style="padding:0.75rem">Keine Zusatzdaten.</div>';
            wrap.dataset.loaded = '1';
        } catch (e) {
            wrap.innerHTML = `<div class="stat-empty">Fehler: ${escHtml(e.message)}</div>`;
        }
    } else {
        wrap.style.display = '';
    }
    btn.textContent = '−'; btn.setAttribute('aria-expanded', 'true');
}

function closeWorkoutModal() { /* legacy no-op, Modal entfernt in v1.25.1 */ }

// v1.28.0: einzelnes Workout löschen (nutzt confirm() — leichtgewichtig,
// analog zu deleteSavingsGoal im Sparziel-Tracker)
async function deleteWorkout(id) {
    const w = state.workoutsAll.find(x => x.id === id);
    const label = w ? wMeta(w.workout_type).de + ' vom ' + fmtDateTime(w.start_at) : 'Workout';
    if (!confirm(`${label} wirklich löschen? Zusatzdaten (Kadenz, SWOLF, ...) werden mit entfernt.`))
        return;
    try {
        await HEALTH_API.deleteWorkout(id);
        state.workoutsAll = state.workoutsAll.filter(x => x.id !== id);
        renderWorkouts();
        showToast('Workout gelöscht ✓');
    } catch (e) {
        showToast('Löschen fehlgeschlagen: ' + e.message, true);
    }
}

// ---------- Einstellungen / API-Keys ----------
function initEinstellungen() {
    state.keysLoaded = true;
    document.getElementById('hImportUrl').textContent = `${API_BASE}/api/health/import`;
    loadApiKeys();
    loadImportLog();
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



// v1.27.0: CSV-Export der kompletten Gesundheitsdaten
async function exportHealthCsv() {
    try {
        const res = await apiCall('/api/health/export', { raw: true });
        if (!res || !res.ok) { showToast('Export fehlgeschlagen', true); return; }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        const dt = new Date().toISOString().slice(0, 10);
        a.href = url; a.download = `vexbob-health-export_${dt}.csv`;
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
        showToast('Export heruntergeladen ✓');
    } catch (e) {
        showToast('Export fehlgeschlagen: ' + e.message, true);
    }
}

// ---------- Import-Protokoll (v1.40.0) ----------
// Zeigt die letzten Sync-Aufrufe der iPhone-App inkl. Ingest-Ergebnis und
// macht den Roh-Payload herunterladbar -- Grundlage fuer den Abgleich
// "was hat die App geliefert" vs. "was steht in der Datenbank".
const IMPORT_KIND_LABELS = {
    'multipart':        'Multipart-Datei',
    'multipart-manual': 'Multipart (manuell geparst)',
    'multipart-raw':    'Multipart (Rohbody)',
    'json':             'JSON',
    'csv':              'CSV',
    'csv-fallback':     'CSV (ohne Content-Type)',
    'empty':            'leerer Aufruf',
};

function fmtBytes(n) {
    const b = Number(n || 0);
    if (b < 1024) return `${b} B`;
    if (b < 1024 * 1024) return `${(b / 1024).toFixed(1).replace('.', ',')} KB`;
    return `${(b / 1024 / 1024).toFixed(1).replace('.', ',')} MB`;
}

function importStatsSummary(s) {
    if (!s) return 'kein Ergebnis gespeichert';
    const parts = [];
    if (s.metrics_imported)  parts.push(`${s.metrics_imported} Vitalwerte`);
    if (s.workouts_imported) parts.push(`${s.workouts_imported} Workouts`);
    if (s.sleep_imported)    parts.push(`${s.sleep_imported} Schlaf`);
    if (s.bp_imported)       parts.push(`${s.bp_imported} Blutdruck`);
    if (s.glucose_imported)  parts.push(`${s.glucose_imported} Blutzucker`);
    const skipped = Array.isArray(s.skipped) ? s.skipped.length : 0;
    if (!parts.length) return skipped ? `nichts importiert (${skipped}× übersprungen)` : 'nichts importiert';
    return parts.join(' · ') + (skipped ? ` · ${skipped}× übersprungen` : '');
}

async function loadImportLog() {
    const box = document.getElementById('hImportLog');
    if (!box) return;
    box.className = 'h-empty'; box.innerHTML = '<div class="stat-loading">Lade …</div>';
    try {
        const rows = await HEALTH_API.imports(50);
        if (!rows.length) {
            box.className = 'h-empty';
            box.innerHTML = 'Noch kein Sync über die API eingegangen.';
            return;
        }
        box.className = '';
        box.innerHTML = rows.map(r => `
            <div class="h-imp-row">
                <div class="h-imp-main">
                    <div class="h-imp-head">${fmtDateTime(r.created_at)}
                        <span class="h-imp-kind">${escHtml(IMPORT_KIND_LABELS[r.kind] || r.kind || '?')}</span>
                        ${r.truncated ? '<span class="h-imp-trunc">gekürzt</span>' : ''}
                    </div>
                    <div class="h-imp-meta">${escHtml(r.filename || 'ohne Dateiname')} · ${fmtBytes(r.size_bytes)} · ${escHtml(importStatsSummary(r.stats))}</div>
                    ${r.preview ? `<div class="h-imp-preview">${escHtml(r.preview)}</div>` : ''}
                </div>
                <div class="h-imp-actions">
                    <button onclick="downloadImportPayload(${r.id})" ${r.size_bytes ? '' : 'disabled'}>⬇ Payload</button>
                    <button class="danger" onclick="deleteImportEntry(${r.id})">✕</button>
                </div>
            </div>`).join('');
    } catch (e) {
        box.className = '';
        box.innerHTML = `<div class="stat-empty">Fehler: ${escHtml(e.message)}</div>`;
    }
}

async function downloadImportPayload(id) {
    try {
        const res = await HEALTH_API.importRaw(id);
        if (!res || !res.ok) { showToast('Download fehlgeschlagen', true); return; }
        // Dateiname kommt aus dem Content-Disposition-Header des Backends.
        const cd = res.headers.get('content-disposition') || '';
        const m = /filename="?([^";]+)"?/i.exec(cd);
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = m ? m[1] : `health-sync_${id}.bin`;
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
        showToast('Payload heruntergeladen ✓');
    } catch (e) {
        showToast('Download fehlgeschlagen: ' + e.message, true);
    }
}

async function deleteImportEntry(id) {
    try {
        await HEALTH_API.deleteImport(id);
        loadImportLog();
    } catch (e) { showToast('Löschen fehlgeschlagen: ' + e.message, true); }
}

async function clearImportLog() {
    if (!confirm('Das komplette Import-Protokoll löschen? Die importierten Gesundheitsdaten bleiben erhalten.')) return;
    try {
        const res = await HEALTH_API.clearImports();
        showToast(`${res.deleted} Einträge gelöscht ✓`);
        loadImportLog();
    } catch (e) { showToast('Löschen fehlgeschlagen: ' + e.message, true); }
}

// v1.28.0: Bulk-Delete
const DELETE_SCOPE_LABELS = {
    all: 'ALLE Gesundheitsdaten',
    metrics: 'Vitalwerte',
    blood_pressure: 'Blutdruck',
    blood_glucose: 'Blutzucker',
    sleep: 'Schlaf-Nächte',
    workouts: 'Workouts',
};
async function bulkDeleteHealth() {
    const scope = document.getElementById('hDelScope').value;
    const from  = document.getElementById('hDelFrom').value || null;
    const to    = document.getElementById('hDelTo').value || null;
    const resultEl = document.getElementById('hDelResult');
    const range = (from || to) ? ` (${from||'Anfang'} – ${to||'heute'})` : ' für ALLE Zeit';
    const label = DELETE_SCOPE_LABELS[scope] || scope;
    if (!confirm(`${label}${range} unwiderruflich löschen?\n\nDas kann nicht rückgängig gemacht werden. Falls noch nicht geschehen: vorher den CSV-Export nutzen!`))
        return;
    resultEl.innerHTML = '<div class="stat-loading">Lösche …</div>';
    try {
        const res = await HEALTH_API.bulkDelete({
            scope,
            from_date: from,
            to_date: to,
        });
        const d = res.deleted || {};
        const parts = Object.keys(d).filter(k => d[k] > 0).map(k =>
            `${DELETE_SCOPE_LABELS[k] || k}: ${fmt0(d[k])}`);
        resultEl.innerHTML = `
            <div class="h-hint" style="margin:0">
                ✅ <strong>${fmt0(res.total)}</strong> Einträge gelöscht${parts.length ? ' — ' + parts.join(', ') : ''}.
            </div>`;
        showToast(res.total > 0 ? `${fmt0(res.total)} Einträge gelöscht ✓` : 'Keine passenden Einträge');
        // Alles neu laden
        state.workoutsLoaded = false; state.sleepInit = false; state.vitalInit = false;
        loadDashboard();
        // Aktiven Tab neu laden, falls betroffen
        const activeTab = document.querySelector('.tab-btn.active');
        if (activeTab) activateTab(activeTab.dataset.tab);
    } catch (e) {
        resultEl.innerHTML = `<div class="stat-empty">Fehler: ${escHtml(e.message)}</div>`;
        showToast('Löschen fehlgeschlagen', true);
    }
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
        [state.chartBp, state.chartGlucose,
         state.chartSleepTimes, state.activityChart,
         ...Object.values(state.metricChartMap)].forEach(c => {
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
    // ESC schließt Modals
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeKeyModal();
    });

    loadDashboard();
})();

