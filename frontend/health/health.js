/* Gesundheit-Modul (v1.22.0) — Frontend-Logik.
 * Nutzt apiCall()/API_BASE aus /js/api.js. Chart.js fuer alle Diagramme. */

const HEALTH_API = {
    summary:      () => apiCall('/api/health/summary'),
    metricSeries: (type, days) => apiCall(`/api/health/metrics/${type}?days=${days}`),
    bloodPressure:(days) => apiCall(`/api/health/blood-pressure?days=${days}`),
    bloodGlucose: (days) => apiCall(`/api/health/blood-glucose?days=${days}`),
    sleep:        (days) => apiCall(`/api/health/sleep?days=${days}`),
    workouts:     (type) => apiCall('/api/health/workouts' + (type ? `?workout_type=${encodeURIComponent(type)}` : '')),
    workoutDetail:(id) => apiCall(`/api/health/workouts/${id}`),
    importFile:   (file) => { const fd = new FormData(); fd.append('file', file); return apiCall('/api/health/import-file', { method: 'POST', body: fd }); },
    importCsv:    (files) => { const fd = new FormData(); [...files].forEach(f => fd.append('files', f)); return apiCall('/api/health/import-csv', { method: 'POST', body: fd }); },
    apiKeys:      () => apiCall('/api/health/api-keys'),
    createKey:    (label) => apiCall('/api/health/api-keys', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ label }) }),
    revokeKey:    (id) => apiCall(`/api/health/api-keys/${id}`, { method: 'DELETE' }),
};

const METRIC_LABELS = {
    active_energy:     { label: 'Aktive Energie', unit: 'kcal', icon: '🔥' },
    heart_rate:        { label: 'Herzfrequenz', unit: 'bpm', icon: '❤️' },
    walking_hr_avg:    { label: 'Ø-HF beim Gehen', unit: 'bpm', icon: '🚶' },
    weight:            { label: 'Gewicht', unit: 'kg', icon: '⚖️' },
    hrv:               { label: 'Herzfrequenzvariabilität', unit: 'ms', icon: '📈' },
    cardio_recovery:   { label: 'Kardio-Erholung', unit: 'bpm', icon: '💪' },
    resting_hr:        { label: 'Ruhepuls', unit: 'bpm', icon: '🛋️' },
    steps:             { label: 'Schritte', unit: '', icon: '👟' },
    swim_distance:     { label: 'Schwimmdistanz', unit: 'm', icon: '🏊' },
    vo2_max:           { label: 'VO2max', unit: 'ml/kg/min', icon: '🫁' },
};

let toastTimer = null;
function showToast(msg, isErr) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.toggle('err', !!isErr);
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 2500);
}

function fmt1(n) { return (n == null) ? '–' : Number(n).toFixed(1).replace('.', ','); }
function fmt0(n) { return (n == null) ? '–' : Math.round(Number(n)).toLocaleString('de-DE'); }
function fmtDate(iso) { return iso ? new Date(iso).toLocaleDateString('de-DE') : '–'; }
function fmtDateTime(iso) { return iso ? new Date(iso).toLocaleString('de-DE', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' }) : '–'; }

// ---------- Tabs ----------
function activateTab(t) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === t));
    ['dashboard', 'vitalwerte', 'schlaf', 'workouts', 'einstellungen'].forEach(id => {
        const el = document.getElementById('tab-' + id);
        if (el) el.style.display = (id === t) ? '' : 'none';
    });
    if (t === 'vitalwerte' && !chartMetric) initVitalwerte();
    if (t === 'schlaf' && !chartSleep) initSchlaf();
    if (t === 'workouts' && !workoutsLoaded) initWorkouts();
    if (t === 'einstellungen' && !keysLoaded) initEinstellungen();
}

// ---------- Dashboard ----------
async function loadDashboard() {
    const grid = document.getElementById('hDashKpis');
    try {
        const s = await HEALTH_API.summary();
        const tiles = [
            { icon: '👟', label: 'Schritte (7 Tage)', value: fmt0(s.steps?.week_sum) },
            { icon: '🔥', label: 'Aktive Energie (7 Tage)', value: fmt0(s.active_energy?.week_sum) + ' kcal' },
            { icon: '🛋️', label: 'Ruhepuls (letzter Wert)', value: fmt0(s.resting_hr?.last?.qty) + ' bpm' },
            { icon: '🏋️', label: 'Workouts diese Woche', value: fmt0(s.workouts_this_week) },
        ];
        grid.innerHTML = tiles.map(t => `
            <div class="stat-kpi">
                <div class="stat-kpi-icon">${t.icon}</div>
                <div class="stat-kpi-label">${t.label}</div>
                <div class="stat-kpi-value">${t.value}</div>
            </div>`).join('');

        const sleepEl = document.getElementById('hDashSleep');
        if (s.sleep_last) {
            const sl = s.sleep_last;
            sleepEl.innerHTML = `
                <div class="h-sleep-summary"><span class="h-big">${fmt1((sl.asleep_minutes||0)/60)} h</span> <span>geschlafen · ${fmtDate(sl.sleep_date)}</span></div>
                ${renderPhaseBars(sl)}`;
        } else {
            sleepEl.textContent = 'Noch keine Daten synchronisiert.';
        }

        const bpEl = document.getElementById('hDashBp');
        if (s.blood_pressure_last) {
            const bp = s.blood_pressure_last;
            bpEl.innerHTML = `<div class="h-bp-summary"><span class="h-big">${fmt0(bp.systolic)}/${fmt0(bp.diastolic)}</span> <span>mmHg · ${fmtDateTime(bp.recorded_at)}</span></div>`;
        } else {
            bpEl.textContent = 'Noch keine Daten synchronisiert.';
        }
    } catch (e) {
        grid.innerHTML = `<div class="stat-empty">Fehler beim Laden: ${e.message}</div>`;
    }
}

function renderPhaseBars(sl) {
    const total = (sl.core_minutes||0) + (sl.deep_minutes||0) + (sl.rem_minutes||0) + (sl.awake_minutes||0);
    if (!total) return '';
    const pct = (v) => (100 * (v||0) / total).toFixed(1);
    return `
        <div class="h-phase-bars">
            <span class="h-phase-core" style="width:${pct(sl.core_minutes)}%"></span>
            <span class="h-phase-deep" style="width:${pct(sl.deep_minutes)}%"></span>
            <span class="h-phase-rem" style="width:${pct(sl.rem_minutes)}%"></span>
            <span class="h-phase-awake" style="width:${pct(sl.awake_minutes)}%"></span>
        </div>
        <div class="h-phase-legend">
            <span><span class="h-phase-dot" style="background:var(--blue)"></span>Core ${fmt1(sl.core_minutes/60)}h</span>
            <span><span class="h-phase-dot" style="background:var(--purple)"></span>Deep ${fmt1(sl.deep_minutes/60)}h</span>
            <span><span class="h-phase-dot" style="background:var(--teal)"></span>REM ${fmt1(sl.rem_minutes/60)}h</span>
            <span><span class="h-phase-dot" style="background:var(--orange)"></span>Wach ${fmt1(sl.awake_minutes/60)}h</span>
        </div>`;
}

// ---------- Vitalwerte ----------
let chartMetric = null, chartBp = null, chartGlucose = null;
let currentMetricDays = 30;

function initVitalwerte() {
    const sel = document.getElementById('hMetricSelect');
    sel.innerHTML = Object.entries(METRIC_LABELS)
        .map(([k, m]) => `<option value="${k}">${m.icon} ${m.label}</option>`).join('');
    sel.value = 'heart_rate';
    sel.addEventListener('change', () => loadMetricChart());
    document.querySelectorAll('#hMetricPresets .stat-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            document.querySelectorAll('#hMetricPresets .stat-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            currentMetricDays = parseInt(chip.dataset.preset, 10);
            loadMetricChart(); loadBpGlucoseCharts();
        });
    });
    const ctx = document.getElementById('hChartMetric').getContext('2d');
    chartMetric = new Chart(ctx, {
        type: 'line',
        data: { labels: [], datasets: [{ label: '', data: [], borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.12)', tension: 0.3, fill: true, pointRadius: 0 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
    });
    chartBp = new Chart(document.getElementById('hChartBp').getContext('2d'), {
        type: 'line',
        data: { labels: [], datasets: [
            { label: 'Systolisch', data: [], borderColor: '#ef4444', tension: 0.3, pointRadius: 0 },
            { label: 'Diastolisch', data: [], borderColor: '#3b82f6', tension: 0.3, pointRadius: 0 },
        ] },
        options: { responsive: true, maintainAspectRatio: false }
    });
    chartGlucose = new Chart(document.getElementById('hChartGlucose').getContext('2d'), {
        type: 'line',
        data: { labels: [], datasets: [{ label: 'Blutzucker', data: [], borderColor: '#f59e0b', tension: 0.3, pointRadius: 0 }] },
        options: { responsive: true, maintainAspectRatio: false }
    });
    loadMetricChart(); loadBpGlucoseCharts();
}

async function loadMetricChart() {
    const type = document.getElementById('hMetricSelect').value;
    const meta = METRIC_LABELS[type] || { label: type, unit: '' };
    document.getElementById('hMetricTitle').textContent = `${meta.icon || '📈'} ${meta.label}`;
    try {
        const rows = await HEALTH_API.metricSeries(type, currentMetricDays);
        chartMetric.data.labels = rows.map(r => fmtDate(r.sample_date));
        chartMetric.data.datasets[0].label = `${meta.label} (${meta.unit})`;
        chartMetric.data.datasets[0].data = rows.map(r => r.qty ?? r.avg_value);
        chartMetric.update();
    } catch (e) { showToast('Fehler: ' + e.message, true); }
}

async function loadBpGlucoseCharts() {
    try {
        const bp = await HEALTH_API.bloodPressure(currentMetricDays);
        chartBp.data.labels = bp.map(r => fmtDateTime(r.recorded_at));
        chartBp.data.datasets[0].data = bp.map(r => r.systolic);
        chartBp.data.datasets[1].data = bp.map(r => r.diastolic);
        chartBp.update();
    } catch (e) {}
    try {
        const gl = await HEALTH_API.bloodGlucose(currentMetricDays);
        chartGlucose.data.labels = gl.map(r => fmtDateTime(r.recorded_at));
        chartGlucose.data.datasets[0].data = gl.map(r => r.value);
        chartGlucose.update();
    } catch (e) {}
}

// ---------- Schlaf ----------
let chartSleep = null;

function initSchlaf() {
    chartSleep = new Chart(document.getElementById('hChartSleep').getContext('2d'), {
        type: 'bar',
        data: { labels: [], datasets: [
            { label: 'Core', data: [], backgroundColor: '#3b82f6', stack: 's' },
            { label: 'Deep', data: [], backgroundColor: '#8b5cf6', stack: 's' },
            { label: 'REM', data: [], backgroundColor: '#14b8a6', stack: 's' },
            { label: 'Wach', data: [], backgroundColor: '#f59e0b', stack: 's' },
        ] },
        options: {
            responsive: true, maintainAspectRatio: false,
            scales: { x: { stacked: true }, y: { stacked: true, title: { display: true, text: 'Stunden' } } }
        }
    });
    loadSleepChart();
}

async function loadSleepChart() {
    try {
        const rows = await HEALTH_API.sleep(30);
        chartSleep.data.labels = rows.map(r => fmtDate(r.sleep_date));
        chartSleep.data.datasets[0].data = rows.map(r => (r.core_minutes || 0) / 60);
        chartSleep.data.datasets[1].data = rows.map(r => (r.deep_minutes || 0) / 60);
        chartSleep.data.datasets[2].data = rows.map(r => (r.rem_minutes || 0) / 60);
        chartSleep.data.datasets[3].data = rows.map(r => (r.awake_minutes || 0) / 60);
        chartSleep.update();

        const n = rows.length || 1;
        const avg = (key) => rows.reduce((s, r) => s + (r[key] || 0), 0) / n / 60;
        const kpis = [
            { icon: '😴', label: 'Ø Schlafdauer', value: fmt1(rows.reduce((s,r)=>s+(r.asleep_minutes||0),0)/n/60) + ' h' },
            { icon: '🛏️', label: 'Ø Im Bett', value: fmt1(rows.reduce((s,r)=>s+(r.in_bed_minutes||0),0)/n/60) + ' h' },
            { icon: '🌊', label: 'Ø Deep-Sleep', value: fmt1(avg('deep_minutes')) + ' h' },
            { icon: '💭', label: 'Ø REM', value: fmt1(avg('rem_minutes')) + ' h' },
        ];
        document.getElementById('hSleepKpis').innerHTML = kpis.map(k => `
            <div class="stat-kpi"><div class="stat-kpi-icon">${k.icon}</div>
                <div class="stat-kpi-label">${k.label}</div>
                <div class="stat-kpi-value">${k.value}</div></div>`).join('');
    } catch (e) { showToast('Fehler: ' + e.message, true); }
}

// ---------- Workouts ----------
let workoutsLoaded = false;

function initWorkouts() {
    workoutsLoaded = true;
    document.getElementById('hWorkoutTypeFilter').addEventListener('change', (e) => loadWorkouts(e.target.value));
    loadWorkouts();
}

const WORKOUT_ICONS = { Running: '🏃', Cycling: '🚴', Swimming: '🏊', Walking: '🚶', StrengthTraining: '🏋️', HIKE: '🥾' };

async function loadWorkouts(type) {
    const list = document.getElementById('hWorkoutList');
    list.innerHTML = '<div class="stat-loading">Lade …</div>';
    try {
        const rows = await HEALTH_API.workouts(type);
        if (!rows.length) { list.innerHTML = '<div class="h-empty">Noch keine Workouts synchronisiert.</div>'; return; }

        const typeSel = document.getElementById('hWorkoutTypeFilter');
        if (typeSel.options.length <= 1) {
            const types = [...new Set(rows.map(r => r.workout_type).filter(Boolean))];
            types.forEach(t => typeSel.insertAdjacentHTML('beforeend', `<option value="${t}">${t}</option>`));
        }

        list.innerHTML = rows.map(w => `
            <div class="h-workout-row" onclick="openWorkoutDetail(${w.id})">
                <div class="h-workout-icon">${WORKOUT_ICONS[w.workout_type] || '🏋️'}</div>
                <div class="h-workout-main">
                    <div class="h-workout-title">${w.workout_type || 'Workout'}</div>
                    <div class="h-workout-sub">${fmtDateTime(w.start_at)} · ${fmt0(w.duration_min)} min</div>
                </div>
                <div class="h-workout-stats">
                    <div>${fmt0(w.active_energy_kcal)} kcal<br><strong>${fmt0(w.avg_heart_rate)} bpm</strong></div>
                </div>
            </div>`).join('');
    } catch (e) {
        list.innerHTML = `<div class="stat-empty">Fehler: ${e.message}</div>`;
    }
}

async function openWorkoutDetail(id) {
    try {
        const w = await HEALTH_API.workoutDetail(id);
        const extra = (w.extra_metrics || []).map(m => `<li>${m.metric_key}: ${m.value}${m.unit ? ' ' + m.unit : ''}</li>`).join('');
        alert(
            `${w.workout_type || 'Workout'}\n` +
            `Start: ${fmtDateTime(w.start_at)}\n` +
            `Dauer: ${fmt0(w.duration_min)} min\n` +
            `Aktive Energie: ${fmt0(w.active_energy_kcal)} kcal\n` +
            `Gesamt-Energie: ${fmt0(w.total_energy_kcal)} kcal\n` +
            `Distanz: ${fmt0(w.distance_m)} m\n` +
            `Ø/Max HF: ${fmt0(w.avg_heart_rate)}/${fmt0(w.max_heart_rate)} bpm` +
            (extra ? `\nZusatz: ${(w.extra_metrics||[]).map(m=>`${m.metric_key}=${m.value}`).join(', ')}` : '')
        );
    } catch (e) { showToast('Fehler: ' + e.message, true); }
}
// ---------- Einstellungen / API-Keys ----------
let keysLoaded = false;

function initEinstellungen() {
    keysLoaded = true;
    document.getElementById('hImportUrl').textContent = `${API_BASE}/api/health/import`;
    loadApiKeys();
}

async function loadApiKeys() {
    const list = document.getElementById('hApiKeyList');
    list.innerHTML = '<div class="stat-loading">Lade …</div>';
    try {
        const keys = await HEALTH_API.apiKeys();
        if (!keys.length) { list.innerHTML = '<div class="h-empty">Noch kein API-Key erzeugt.</div>'; return; }
        list.innerHTML = keys.map(k => `
            <div class="h-key-row ${k.revoked_at ? 'h-key-revoked' : ''}">
                <div>
                    <div class="h-key-label">${escHtmlHealth(k.label || 'Key')} ${k.revoked_at ? '(widerrufen)' : ''}</div>
                    <div class="h-key-meta">Erstellt: ${fmtDateTime(k.created_at)} · Zuletzt genutzt: ${k.last_used_at ? fmtDateTime(k.last_used_at) : 'nie'}</div>
                </div>
                ${k.revoked_at ? '' : `<button class="danger" onclick="revokeApiKey(${k.id})">Widerrufen</button>`}
            </div>`).join('');
    } catch (e) {
        list.innerHTML = `<div class="stat-empty">Fehler: ${e.message}</div>`;
    }
}

function escHtmlHealth(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
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
    navigator.clipboard?.writeText(input.value).then(() => showToast('Key kopiert ✓'));
}

async function revokeApiKey(id) {
    if (!confirm('Diesen Key wirklich widerrufen? Der Sync in Auto Health Export funktioniert danach nicht mehr.')) return;
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
                ${fmt0(stats.metrics_imported)} Vitalwerte,
                ${fmt0(stats.bp_imported)} Blutdruck,
                ${fmt0(stats.glucose_imported)} Blutzucker,
                ${fmt0(stats.sleep_imported)} Nächte,
                ${fmt0(stats.workouts_imported)} Workouts importiert.
                ${skipped.length ? `${skipped.length} Punkte/Dateien übersprungen (z.B. unbekannte Einzelmetrik-CSVs).` : ''}
            </div>`;
        showToast('CSV-Import abgeschlossen ✓');
        input.value = '';
        loadDashboard();
    } catch (e) {
        resultEl.innerHTML = `<div class="stat-empty">Import fehlgeschlagen: ${e.message}</div>`;
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
                ✅ Import abgeschlossen —
                ${fmt0(stats.metrics_imported)} Vitalwerte,
                ${fmt0(stats.bp_imported)} Blutdruck,
                ${fmt0(stats.glucose_imported)} Blutzucker,
                ${fmt0(stats.sleep_imported)} Nächte,
                ${fmt0(stats.workouts_imported)} Workouts importiert.
                ${skipped.length ? `${skipped.length} Punkte übersprungen (z.B. unbekanntes Format).` : ''}
            </div>`;
        showToast('Import abgeschlossen ✓');
        input.value = '';
        loadDashboard();
    } catch (e) {
        resultEl.innerHTML = `<div class="stat-empty">Import fehlgeschlagen: ${e.message}</div>`;
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
    document.getElementById('logoutBtn').addEventListener('click', () => { clearToken(); location.href = '/private/login.html'; });
    document.getElementById('themeBtn').addEventListener('click', toggleTheme);
    document.querySelectorAll('.tab-btn').forEach(b => b.addEventListener('click', () => activateTab(b.dataset.tab)));
    document.getElementById('hKeyModal').addEventListener('click', (e) => { if (e.target.id === 'hKeyModal') closeKeyModal(); });
    loadDashboard();
})();

