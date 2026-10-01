/* Gesundheit-Modul — Frontend-Logik (neu gebaut in v2.20.0).
 * Nutzt apiCall()/API_BASE aus /js/api.js. Chart.js fuer alle Diagramme.
 *
 * Was sich in v2.20.0 geaendert hat, und warum:
 *
 *   - Vier Reiter statt fuenf. Der „Überblick“ ersetzt das Dashboard; die
 *     Einstellungen (Schluessel, Protokoll, Import, Loeschen) braucht man
 *     selten und stehen als Zeilen unten im Überblick, jede oeffnet einen
 *     Dialog (DESIGN 6d). Alte Anker (#dashboard, #einstellungen) fuehren
 *     weiter an die richtige Stelle.
 *   - Oben die Buehne: der letzte VOLLE Tag gegen den eigenen Schnitt der
 *     dreissig Tage davor. Die Daten kommen per taeglichem Upload, der
 *     juengste Tag ist gestern; ein angebrochener heutiger Tag zaehlt auf dem
 *     Überblick nirgends mit (abgeschlossen()). Ein Ring sagt „wie viel von
 *     einem Ziel“ (DESIGN 7a); ein fremdes Ziel wie „10.000 Schritte“ waere
 *     eine Behauptung, die in keiner Einstellung steht -- der eigene Schnitt
 *     ist eine Zahl aus den Daten.
 *   - Keine Emoji mehr an Kacheln und Knoepfen: sie ueberlappten die
 *     Beschriftung (🔥 ueber „Aktive Energie (7 Tage)“). Eine Messgroesse
 *     traegt ihren Farbpunkt -- dieselbe Farbe wie ihre Kurve.
 *   - Workouts sind eine Liste; Details, Pulsverlauf und Loeschen stehen im
 *     Dialog statt als zwei Knoepfe an jeder Karte.
 *   - Eine Messgroesse ohne Werte im Zeitraum steht nicht als leere Karte da,
 *     sondern ist in einer Zeile darunter genannt.
 *
 * Die Rechnungen (Mittel ohne Messluecken, gleitender Durchschnitt, Schlaf
 * auf der Uhrzeit-Achse, Median statt Mittel bei Zubettgehzeiten) sind
 * unveraendert -- sie standen richtig und haben jede ihre Begruendung
 * weiter unten.
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
    // allen Geraeten gleich ist)
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

// Farben kommen aus den Tokens (css/style.css, --h-*) -- der Helfer steht
// deshalb vor den Tabellen, die ihn brauchen.
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

// ``ton`` ist der Name des Tokens: im HTML steht er als var(), im Diagramm
// wird er zur Farbe aufgeloest.
const METRIC_LABELS = {
    steps:           { label: 'Schritte', unit: '', ton: '--h-steps', cumulative: true },
    active_energy:   { label: 'Aktive Energie', unit: 'kcal', ton: '--h-energy', cumulative: true },
    resting_hr:      { label: 'Ruhepuls', unit: 'bpm', ton: '--h-resthr' },
    heart_rate:      { label: 'Herzfrequenz', unit: 'bpm', ton: '--h-hr' },
    walking_hr_avg:  { label: 'Ø-HF Gehen', unit: 'bpm', ton: '--h-walkhr' },
    hrv:             { label: 'HRV', unit: 'ms', ton: '--h-hrv' },
    cardio_recovery: { label: 'Kardio-Erholung', unit: 'bpm', ton: '--h-recovery' },
    weight:          { label: 'Gewicht', unit: 'kg', ton: '--h-weight' },
    vo2_max:         { label: 'VO2max', unit: 'ml/kg/min', ton: '--h-vo2' },
    swim_distance:   { label: 'Schwimmdistanz', unit: 'm', ton: '--h-swim', cumulative: true },
    blood_oxygen:    { label: 'Blutsauerstoff', unit: '%', ton: '--h-oxygen' },
    walking_distance:{ label: 'Geh-/Laufstrecke', unit: 'km', ton: '--h-distance', cumulative: true },
    walking_speed:   { label: 'Gehgeschwindigkeit', unit: 'km/h', ton: '--h-speed' },
};
Object.keys(METRIC_LABELS).forEach(k => { METRIC_LABELS[k].color = cssVar(METRIC_LABELS[k].ton); });

// Die Sportart traegt ein Emoji als Marke -- wie ein Kategorie-Zeichen, kein
// Bedienelement (DESIGN 8).
const WORKOUT_META = {
    'Running':          { icon: '🏃', de: 'Laufen' },
    'Cycling':          { icon: '🚴', de: 'Radfahren' },
    'Swimming':         { icon: '🏊', de: 'Schwimmen', swim: true },
    'Walking':          { icon: '🚶', de: 'Gehen' },
    'StrengthTraining': { icon: '🏋️', de: 'Krafttraining' },
    'HIKE':             { icon: '🥾', de: 'Wandern' },
    'Outdoor Spaziergang':{icon: '🚶', de: 'Outdoor Spaziergang' },
    'Schwimmbad Schwimmen':{icon:'🏊', de: 'Schwimmen (Pool)', swim: true },
    'Outdoor Laufen':   { icon: '🏃', de: 'Outdoor Laufen' },
};
function wMeta(t) { return WORKOUT_META[t] || { icon: '🏋️', de: t || 'Workout' }; }
// Schwimmen wird anders gerechnet als Laufen/Radfahren: Distanz in Metern,
// Pace in min/100 m. Neben den bekannten Typen greift ein Namens-Fallback,
// damit auch kuenftige Apple-Bezeichnungen ("Freiwasserschwimmen") passen.
function isSwimWorkout(t) {
    if (wMeta(t).swim) return true;
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
    toastTimer = setTimeout(() => t.classList.remove('show'), 2800);
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
    return h > 0 ? `${h} h ${m} min` : `${m} min`;
}
function escHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function pctDelta(cur, prev) {
    if (!prev || !cur) return null;
    return ((cur - prev) / prev) * 100;
}
function ikon(name, groesse) { return window.VexIkon ? VexIkon.svg(name, groesse || 18) : ''; }
// Das Datum in der Ortszeit; toISOString() rechnet in UTC.
function isoTag(d) { const z = n => String(n).padStart(2, '0'); return d.getFullYear() + '-' + z(d.getMonth() + 1) + '-' + z(d.getDate()); }
function tagName(iso) {
    try { return new Date(iso + 'T12:00:00').toLocaleDateString('de-DE', { weekday: 'short', day: 'numeric', month: 'short' }); }
    catch (e) { return iso; }
}
/* Eine Tokenfarbe mit Deckkraft -- fuer Balken und Flaechen im Diagramm.
   Chart.js reicht Farben an die Leinwand weiter, und die kennt kein
   color-mix(); die Tokens sind Hexwerte, also von Hand. */
function tonAlpha(farbe, a) {
    const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(farbe || '').trim());
    if (!m) return farbe;
    let h = m[1];
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
}

// v1.39.1: Durchschnitt ohne Messluecken.
// Tage, an denen kaum gemessen wurde (angebrochener heutiger Tag, Uhr nicht
// getragen, Sync abgebrochen), liefern bei kumulativen Metriken wie Schritten
// nur einen Bruchteil des ueblichen Werts und ziehen den Ø stark nach unten,
// obwohl an dem Tag gar nicht "wenig passiert" ist. Als Messluecke gilt daher
// alles unter 20 % des Medians der Reihe — der Median ist gegenueber genau
// solchen Ausreissern robust, ein Mittelwert waere es nicht.
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

// Gleitender Durchschnitt als Trendlinie — zentriert. Messluecken (< threshold)
// fliessen nicht ein.
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
// Fensterbreite passend zur Reihenlaenge.
function trendWindow(n) {
    const win = n <= 10 ? 3 : n <= 40 ? 7 : n <= 120 ? 14 : 30;
    return Math.max(2, Math.min(win, n));
}

// ---------- Chart-Theme ----------
function chartTheme() {
    return {
        text:    cssVar('--text-1'),
        muted:   cssVar('--chart-axis'),
        grid:    cssVar('--chart-grid'),
        border:  cssVar('--line-strong'),
        surface: cssVar('--surface-3'),
    };
}
function chartDefaults(overrides) {
    const th = chartTheme();
    return Object.assign({
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
            legend: { labels: { color: th.muted, boxWidth: 8, boxHeight: 8, font: { size: 11 },
                                usePointStyle: true, pointStyle: 'circle' } },
            tooltip: themedTooltip(),
        },
        scales: {
            // Kein senkrechtes Gitter, keine Achsenrahmen -- die Linie zaehlt.
            x: { ticks: { color: th.muted, font: { size: 11 }, maxRotation: 0, autoSkipPadding: 12 },
                 grid: { display: false }, border: { display: false } },
            y: { ticks: { color: th.muted, font: { size: 11 } }, grid: { color: th.grid },
                 border: { display: false }, beginAtZero: false },
        },
    }, overrides || {});
}
// chartDefaults ersetzt bei einem `plugins`-Override den kompletten Block --
// dieser Helfer liefert das Tooltip-Styling zum Wiedereinsetzen.
function themedTooltip(extra) {
    const th = chartTheme();
    const e = extra || {};
    const out = Object.assign({
        backgroundColor: th.surface, borderColor: th.border, borderWidth: 1,
        titleColor: th.text, bodyColor: cssVar('--text-2'), padding: 10, cornerRadius: 12,
        displayColors: true, boxPadding: 3,
    }, e);
    // callbacks muss zusammengefuehrt werden, nicht ersetzt: sonst nimmt ein
    // eigener label-Callback den Datums-Titel mit ins Grab.
    out.callbacks = Object.assign({ title: vexFullTitle }, e.callbacks || {});
    return out;
}

// Die Achse zeigt "05.09.", der Tooltip zeigt "Fr, 05.09.2026". Die
// ausgeschriebene Fassung haengt als $vexFull am Diagramm.
function vexFullTitle(items) {
    if (!items || !items.length) return '';
    const full = items[0].chart && items[0].chart.$vexFull;
    const i = items[0].dataIndex;
    if (full && full[i] != null && full[i] !== '') return full[i];
    return items[0].label || '';
}
function setChartDates(chart, isoList) {
    if (!chart || !window.VexCharts) return;
    chart.$vexFull = (isoList || []).map(v => VexCharts.fullDay(v));
}

// ---------- Dialoge ----------
function dialog(titel, html, opts) {
    const d = VexModal.open(escHtml(titel), html, opts || {});
    if (window.VexIkon) VexIkon.einsetzen(d.root);
    return d;
}
function beiKlick(d, sel, fn) {
    const el = d.root.querySelector(sel);
    if (el) el.addEventListener('click', fn);
}

// ---------- Reiter ----------
const H_TABS = ['ueberblick', 'vitalwerte', 'schlaf', 'workouts'];
// Lesezeichen aus der Zeit vor v2.20.0 landen an der neuen Stelle.
const ALTE_ANKER = { dashboard: 'ueberblick', einstellungen: 'ueberblick', heute: 'ueberblick' };

function activateTab(t) {
    const zuDaten = t === 'einstellungen';
    t = ALTE_ANKER[t] || t;
    if (H_TABS.indexOf(t) < 0) t = H_TABS[0];
    document.querySelectorAll('.tabs .tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === t));
    H_TABS.forEach(id => {
        const el = document.getElementById('tab-' + id);
        if (el) el.hidden = id !== t;
    });
    // Der Reiter steht in der Adresse. Der erste bleibt ohne Anhaengsel.
    history.replaceState(null, '', t === H_TABS[0] ? location.pathname : '#' + t);
    if (t === 'vitalwerte' && !state.vitalInit) initVitalwerte();
    if (t === 'schlaf' && !state.sleepInit) initSchlaf();
    if (t === 'workouts' && !state.workoutsInit) initWorkouts();
    if (zuDaten) {
        const liste = document.getElementById('hDatenListe');
        if (liste) setTimeout(() => liste.scrollIntoView({ block: 'center' }), 60);
    }
}

// ---------- Zentraler State ----------
const state = {
    summary: null,
    dashSeries: null,
    vitalRange: null, vitalInit: false,
    metricCards: null, metricChartMap: {},   // v1.46.0: Karten bleiben stehen,
                                             // nur die Daten werden getauscht
    metricOrder: null, sortableMetrics: null,
    chartBp: null, chartGlucose: null,
    sleepRange: null, sleepInit: false, chartSleepTimes: null,
    sleepUsable: [], sleepWindows: [],   // Naechte hinter den Balken (Tooltip)
    workoutsInit: false, workoutsAll: null, workoutFilter: '', workoutRange: null,
    workoutHrChart: null, woRhythmus: null, workoutRangeMounted: false,
};

// ---------- Schlaf einer Nacht ----------
/* Geschlafen ist Tief + Kern + REM -- sonst nichts (v2.26.0). Bis dahin
   galt das Groessere aus Phasensumme und `asleep_minutes`; Letzteres
   enthaelt aber den Anteil ohne Phasen-Zuordnung, und so stand mehr Schlaf
   da, als die drei Phasen hergaben. Nur eine Nacht ganz OHNE Phasen (aeltere
   Uhr, anderer Tracker) faellt auf `asleep_minutes` zurueck -- sonst waere
   sie leer. Eine Stelle fuer alle: Ring, Karte, Schlaf-Reiter. */
function schlafMinuten(sl) {
    const num = (v) => { const n = Number(v); return Number.isFinite(n) ? n : 0; };
    const phasen = num(sl.core_minutes) + num(sl.deep_minutes) + num(sl.rem_minutes);
    return phasen > 0 ? phasen : num(sl.asleep_minutes);
}

function nachtZahlen(sl) {
    const num = (v) => { const n = Number(v); return Number.isFinite(n) ? n : 0; };
    const phases = num(sl.core_minutes) + num(sl.deep_minutes) + num(sl.rem_minutes);
    return { phases, asleepMin: schlafMinuten(sl), awake: num(sl.awake_minutes) };
}

// ---------- Überblick ----------
/* Nur abgeschlossene Tage. Der Upload kommt einmal am Tag und bringt die
   Tage bis gestern; steht doch eine Zeile fuer heute da, ist sie ein
   angebrochener Tag -- als Tageswert, in der Wochensumme und als letzter
   Balken wuerde sie eine zu kleine Zahl behaupten. */
function abgeschlossen(rows) {
    const heute = isoTag(new Date());
    return (rows || []).filter(r => String(r.sample_date || r.recorded_at || '').slice(0, 10) < heute);
}

async function loadDashboard() {
    try {
        const [summary, stepsRows, energyRows, hrRows, restRows, sleepRows] = await Promise.all([
            HEALTH_API.summary(),
            HEALTH_API.metricSeries('steps', 31).catch(() => []),
            HEALTH_API.metricSeries('active_energy', 31).catch(() => []),
            HEALTH_API.metricSeries('heart_rate', 14).catch(() => []),
            HEALTH_API.metricSeries('resting_hr', 14).catch(() => []),
            HEALTH_API.sleep(31).catch(() => []),
        ]);
        state.summary = summary;
        const steps = abgeschlossen(stepsRows), energy = abgeschlossen(energyRows);
        const hr = abgeschlossen(hrRows), rest = abgeschlossen(restRows);
        state.dashSeries = { steps: steps, active_energy: energy, heart_rate: hr,
                             resting_hr: rest, sleep: sleepRows };
        zeichneBuehne(summary, steps, energy, rest, sleepRows);
        renderSleepBlock('hDashSleep', summary.sleep_last);
        renderHeartOverview(summary, hr, rest);
        renderInsights(summary, steps, rest);
        renderActivityChart();
    } catch (e) {
        buehneFehler(e);
    }
    loadDashWorkouts();
    datenStand();
}

function buehneFehler(e) {
    document.getElementById('hTagMarke').textContent = 'Gesundheit';
    document.getElementById('hSchritte').textContent = '–';
    document.getElementById('hSchritteSub').textContent = 'Konnte nicht geladen werden';
    const box = document.getElementById('hDashSleep');
    box.innerHTML = `<div class="empty is-error"><p class="empty-text">${escHtml(e && e.message || 'Laden fehlgeschlagen')}</p>
        <button type="button" class="v-btn v-btn--sm" onclick="loadDashboard()">Erneut versuchen</button></div>`;
    document.getElementById('hDashHeart').innerHTML = '';
}

/* Der Tag auf der Buehne ist der juengste abgeschlossene mit Daten --
   normalerweise gestern. Die Marke nennt ihn mit Datum; liegt er weiter
   zurueck (ein Upload fiel aus), steht „Zuletzt“ davor. Der Schnitt kommt
   aus den dreissig Tagen DAVOR, ohne Messluecken (cleanAverage). */
function tagUndSchnitt(rows) {
    const mitDatum = (rows || []).filter(r => Number.isFinite(Number(r.qty)));
    if (!mitDatum.length) return null;
    const letzte = mitDatum[mitDatum.length - 1];
    const tag = String(letzte.sample_date || letzte.recorded_at || '').slice(0, 10);
    const davor = mitDatum.filter(r => String(r.sample_date || r.recorded_at || '').slice(0, 10) < tag)
                          .slice(-30).map(r => Number(r.qty));
    return { tag, wert: Number(letzte.qty), schnitt: cleanAverage(davor).avg };
}

function zeichneBuehne(summary, stepsRows, energyRows, restRows, sleepRows) {
    const gestern = isoTag(new Date(Date.now() - 86400000));
    const s = tagUndSchnitt(stepsRows);
    const marke = document.getElementById('hTagMarke');
    if (s) {
        marke.textContent = (s.tag === gestern ? 'Gestern' : 'Zuletzt') + ' · ' + tagName(s.tag);
    } else {
        marke.textContent = 'Letzter voller Tag';
    }

    // Schritte: die Heldenzahl im Halbring
    const elS = document.getElementById('hSchritte');
    const subS = document.getElementById('hSchritteSub');
    const ringS = document.getElementById('hRingSchritte');
    if (s) {
        const vorher = Number(elS.dataset.wert || 0);
        VexRing.zaehle(vorher, s.wert, 700, v => { elS.textContent = fmt0(v); });
        elS.dataset.wert = s.wert;
        VexRing.set(ringS, { wert: s.wert, ziel: s.schnitt || s.wert || 1 });
        subS.textContent = s.schnitt
            ? `Schritte · ${fmt0(100 * s.wert / s.schnitt)} % von Ø ${fmt0(s.schnitt)}`
            : 'Schritte';
    } else {
        elS.textContent = '–';
        subS.textContent = 'Noch keine Schritte synchronisiert';
        VexRing.set(ringS, { wert: 0, ziel: 1 });
    }

    // Aktive Energie des Tages gegen den Schnitt
    const e = tagUndSchnitt(energyRows);
    const ringE = document.getElementById('hRingEnergie');
    document.getElementById('hEnergie').textContent = e ? fmt0(e.wert) : '–';
    document.getElementById('hEnergieSub').textContent = e && e.schnitt ? `Ø ${fmt0(e.schnitt)} kcal` : '';
    VexRing.set(ringE, { wert: e ? e.wert : 0, ziel: e && e.schnitt ? e.schnitt : 1 });

    // Schlaf: die letzte Nacht gegen den Schnitt der Naechte davor
    const nacht = summary && summary.sleep_last ? nachtZahlen(summary.sleep_last) : null;
    const ringN = document.getElementById('hRingSchlaf');
    const letzteNacht = summary && summary.sleep_last ? String(summary.sleep_last.sleep_date || '') : '';
    const vorige = (sleepRows || []).filter(r => String(r.sleep_date || '') < letzteNacht)
        .map(r => nachtZahlen(r).asleepMin).filter(v => v >= 60);
    const schnittN = vorige.length ? vorige.reduce((a, v) => a + v, 0) / vorige.length : null;
    document.getElementById('hSchlaf').textContent = nacht && nacht.asleepMin ? fmt1(nacht.asleepMin / 60) : '–';
    document.getElementById('hSchlafSub').textContent = schnittN ? `Ø ${fmt1(schnittN / 60)} Std.` : '';
    VexRing.set(ringN, { wert: nacht ? nacht.asleepMin : 0, ziel: schnittN || (nacht && nacht.asleepMin) || 1 });

    // Fakten: Ruhepuls der Woche (mit Richtung), HRV, Workouts
    const rest7 = restRows.slice(-7).map(r => Number(r.qty)).filter(Number.isFinite);
    const restPrev = restRows.slice(-14, -7).map(r => Number(r.qty)).filter(Number.isFinite);
    const avg = (a) => a.length ? a.reduce((x, v) => x + v, 0) / a.length : null;
    const r7 = avg(rest7), rp = avg(restPrev);
    const elR = document.getElementById('hFRuhe');
    elR.innerHTML = r7 != null ? `${fmt0(r7)}<small>bpm</small>` : '–';
    // Ein niedrigerer Ruhepuls ist die gute Richtung.
    elR.classList.toggle('gh-gut', r7 != null && rp != null && rp - r7 >= 1);
    elR.classList.toggle('gh-acht', r7 != null && rp != null && r7 - rp >= 3);
    const hrv = summary && summary.hrv && summary.hrv.last ? summary.hrv.last.qty : null;
    document.getElementById('hFHrv').innerHTML = hrv != null ? `${fmt0(hrv)}<small>ms</small>` : '–';
    document.getElementById('hFWork').innerHTML = summary
        ? `${fmt0(summary.workouts_this_week)}<small>in 7 Tagen</small>` : '–';
}

function renderInsights(s, stepsRows, restRows) {
    const box = document.getElementById('hDashInsights');
    const sum = (arr) => arr.reduce((a, r) => a + (Number(r.qty) || 0), 0);
    const avg = (arr) => arr.length ? arr.reduce((a, r) => a + (Number(r.qty) || 0), 0) / arr.length : null;
    const stepsSum = sum(stepsRows.slice(-7));
    const restAvg = avg(restRows.slice(-7)), restPrev = avg(restRows.slice(-14, -7));
    const items = [];
    if (stepsSum >= 70000) items.push({ ton: 'var(--ok)', txt: `Starke Woche: <strong>${fmt0(stepsSum)}</strong> Schritte in sieben Tagen.` });
    else if (stepsSum > 0 && stepsSum < 20000) items.push({ ton: 'var(--info)', txt: `Ruhige Woche: <strong>${fmt0(stepsSum)}</strong> Schritte in sieben Tagen.` });
    if (restAvg != null && restPrev != null && (restAvg - restPrev) <= -2)
        items.push({ ton: 'var(--ok)', txt: `Ruhepuls <strong>${fmt0(restAvg)}</strong> bpm, ${fmt0(restPrev - restAvg)} bpm unter der Vorwoche.` });
    if (restAvg != null && restAvg >= 80)
        items.push({ ton: 'var(--warn)', txt: `Erhöhter Ruhepuls (<strong>${fmt0(restAvg)}</strong> bpm). Vielleicht Erholung einplanen.` });
    // v1.39.1: Kein Schlaf-Hinweis -- er benutzte die rohen `asleep_minutes`
    // und widersprach damit der Karte „Letzte Nacht“ direkt daneben.
    if (s.workouts_this_week >= 4) items.push({ ton: 'var(--ok)', txt: `<strong>${s.workouts_this_week}</strong> Workouts in sieben Tagen.` });
    box.innerHTML = items.map(i => `<div class="gh-hinweis" style="--ton:${i.ton}"><span>${i.txt}</span></div>`).join('');
}

function renderSleepBlock(elId, sl) {
    const el = document.getElementById(elId);
    const sub = document.getElementById('hNachtSub');
    if (!sl) {
        if (sub) sub.textContent = '';
        el.innerHTML = '<div class="empty"><p class="empty-text">Noch keine Nacht synchronisiert. Auto Health Export schickt Schlaf, sobald eine Uhr ihn aufzeichnet.</p></div>';
        return;
    }
    const z = nachtZahlen(sl);
    const total = z.phases + z.awake;
    const pct = (v) => total ? (100 * (v || 0) / total).toFixed(1) : 0;
    const pctInt = (v) => total ? Math.round(100 * (v || 0) / total) : 0;
    const timeRange = (sl.sleep_start && sl.sleep_end) ? `${fmtHM(sl.sleep_start)} → ${fmtHM(sl.sleep_end)}` : '';
    // Das Datum einer Nacht ist der Tag, an dem sie endet.
    if (sub) sub.textContent = sl.sleep_date ? 'Nacht zum ' + tagName(String(sl.sleep_date).slice(0, 10)) : '';
    const phase = (lbl, key, ton) => `<span><span class="h-phase-dot" style="--ton:var(${ton})"></span>${lbl} <strong>${fmt1((sl[key] || 0) / 60)} h</strong> <em>${pctInt(sl[key])} %</em></span>`;
    el.innerHTML = `
        <div class="h-sleep-block">
            <div class="h-sleep-head">
                <span class="h-big">${fmt1(z.asleepMin / 60)} h</span>
                <span class="h-sub">geschlafen${timeRange ? ' · ' + timeRange : ''}</span>
            </div>
            ${total ? `<div class="h-phase-bars">
                <span class="h-phase-deep" style="width:${pct(sl.deep_minutes)}%"></span>
                <span class="h-phase-core" style="width:${pct(sl.core_minutes)}%"></span>
                <span class="h-phase-rem" style="width:${pct(sl.rem_minutes)}%"></span>
                <span class="h-phase-awake" style="width:${pct(sl.awake_minutes)}%"></span>
            </div>
            <div class="h-phase-legend">
                ${phase('Tief', 'deep_minutes', '--h-sleep-deep')}
                ${phase('Kern', 'core_minutes', '--h-sleep-core')}
                ${phase('REM', 'rem_minutes', '--h-sleep-rem')}
                ${phase('Wach', 'awake_minutes', '--h-sleep-awake')}
            </div>` : ''}
        </div>`;
}

function renderHeartOverview(s, hrRows, restRows) {
    const el = document.getElementById('hDashHeart');
    const avg = (arr) => arr.length ? arr.reduce((a, r) => a + (Number(r.qty) || 0), 0) / arr.length : null;
    const rest7 = avg(restRows.slice(-7)), restPrev = avg(restRows.slice(-14, -7));
    const hr7 = avg(hrRows.slice(-7));
    const hrvLast = s.hrv && s.hrv.last ? s.hrv.last.qty : null;
    const vo2Last = s.vo2_max && s.vo2_max.last ? s.vo2_max.last.qty : null;
    let restSub = '', restCls = '';
    if (rest7 != null && restPrev != null && Math.abs(rest7 - restPrev) >= 1) {
        const besser = rest7 < restPrev;
        restSub = `${besser ? '−' : '+'}${fmt0(Math.abs(rest7 - restPrev))} zur Vorwoche`;
        restCls = besser ? 'gut' : (rest7 - restPrev >= 3 ? 'acht' : '');
    }
    const items = [
        { lbl: 'Ø Ruhepuls', val: rest7 != null ? fmt0(rest7) : '–', unit: 'bpm', sub: restSub, cls: restCls },
        { lbl: 'Ø Herzfrequenz', val: hr7 != null ? fmt0(hr7) : '–', unit: 'bpm' },
        { lbl: 'HRV, zuletzt', val: hrvLast != null ? fmt0(hrvLast) : '–', unit: 'ms' },
        { lbl: 'VO2max', val: vo2Last != null ? fmt1(vo2Last) : '–', unit: 'ml/kg/min' },
    ];
    el.innerHTML = `<div class="h-heart-grid">${items.map(i => `
        <div class="h-heart-item">
            <div class="h-heart-lbl">${i.lbl}</div>
            <div class="h-heart-val">${i.val}<small>${i.unit}</small></div>
            ${i.sub ? `<div class="h-heart-sub ${i.cls || ''}">${i.sub}</div>` : ''}
        </div>`).join('')}</div>`;
}

/* Beide Kurven, nebeneinander (v1.93.0: zeigen statt umschalten). */
function renderActivityChart() {
    const tage = (state.dashSeries && state.dashSeries.steps) || [];
    const lbl = document.getElementById('hDashActivityLbl');
    if (lbl) lbl.textContent = tage.length ? Math.min(14, tage.length) + ' Tage' : '';
    _aktivitaetKurve('hDashActivity', 'steps', 'hDashStepsTitle', 'activityChart');
    _aktivitaetKurve('hDashEnergy', 'active_energy', 'hDashEnergyTitle', 'energyChart');
}

function _aktivitaetKurve(canvasId, metrik, titelId, merker) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const rows = (state.dashSeries && state.dashSeries[metrik]) || [];
    const data = rows.slice(-14);
    const meta = METRIC_LABELS[metrik];
    // Die Zahl steht ueber ihrer eigenen Kurve, in deren Farbe.
    const titel = document.getElementById(titelId);
    if (titel) {
        const summe = data.slice(-7).reduce((s, r) => s + (Number(r.qty) || 0), 0);
        titel.innerHTML = `<span style="--ton:var(${meta.ton})">${fmt0(summe)} ${meta.unit || ''}</span> <small>${meta.label} · 7 Tage</small>`;
    }
    const th = chartTheme();
    if (state[merker]) state[merker].destroy();
    state[merker] = new Chart(canvas.getContext('2d'), {
        type: 'bar',
        data: {
            labels: data.map(r => fmtDate(r.sample_date || r.recorded_at)),
            datasets: [Object.assign({
                label: `${meta.label} (${meta.unit || '–'})`,
                data: data.map(r => Number(r.qty) || 0),
                backgroundColor: tonAlpha(meta.color, 0.85),
                barPercentage: 0.72,
            }, VexCharts.balken(6))],
        },
        options: chartDefaults({
            plugins: {
                legend: { display: false },
                tooltip: themedTooltip({ displayColors: false,
                    callbacks: { label: (ctx) => ` ${fmt0(ctx.raw)} ${meta.unit || ''}`.trim() } }),
            },
            scales: {
                x: { ticks: { color: th.muted, font: { size: 10 }, maxRotation: 0, autoSkipPadding: 10 },
                     grid: { display: false }, border: { display: false } },
                y: { ticks: { color: th.muted, font: { size: 10 }, maxTicksLimit: 4 },
                     grid: { color: th.grid }, border: { display: false }, beginAtZero: true },
            },
        }),
    });
    setChartDates(state[merker], data.map(r => r.sample_date || r.recorded_at));
}

// Die letzten Workouts auf „Heute“: dieselbe Liste wie im Reiter, nur kurz.
async function loadDashWorkouts() {
    const box = document.getElementById('hDashWorkouts');
    try {
        if (!state.workoutsAll) state.workoutsAll = await HEALTH_API.workouts();
        const rows = state.workoutsAll.slice().sort((a, b) => new Date(b.start_at) - new Date(a.start_at)).slice(0, 3);
        box.innerHTML = rows.length
            ? `<div class="rec-list gh-wo">${rows.map(workoutZeile).join('')}</div>`
            : '<div class="empty"><p class="empty-text">Noch keine Workouts synchronisiert.</p></div>';
    } catch (e) {
        box.innerHTML = `<div class="empty is-error"><p class="empty-text">Die Workouts konnten nicht geladen werden.</p>
            <button type="button" class="v-btn v-btn--sm" onclick="loadDashWorkouts()">Erneut versuchen</button></div>`;
    }
}

/* Wie frisch die Daten sind, steht an zwei Stellen: in der Zeile „iPhone-
   Verbindung“ und oben rechts auf der Buehne. Beides kommt aus dem
   Import-Protokoll -- das Datum einer Tageszeile ist der Tag, nicht die
   Uhrzeit des letzten Syncs. */
async function datenStand() {
    try {
        const [keys, imports] = await Promise.all([
            HEALTH_API.apiKeys().catch(() => null),
            HEALTH_API.imports(1).catch(() => null),
        ]);
        const aktiv = keys ? keys.filter(k => !k.revoked_at).length : null;
        const letzter = imports && imports.length ? imports[0].created_at : null;
        const teile = [];
        if (aktiv != null) teile.push(aktiv === 1 ? '1 Schlüssel aktiv' : `${aktiv} Schlüssel aktiv`);
        if (letzter) teile.push('letzter Sync ' + fmtDateTime(letzter));
        if (teile.length) document.getElementById('hDatenVerbindung').textContent = teile.join(' · ');
        if (letzter) {
            const heute = isoTag(new Date());
            document.getElementById('hStand').textContent = 'Sync ' + (isoTag(new Date(letzter)) === heute
                ? 'heute ' + fmtHM(letzter) : fmtDateTime(letzter));
        }
        if (imports && imports.length) document.getElementById('hDatenProtokoll').textContent =
            'Zuletzt ' + fmtDateTime(imports[0].created_at) + ' · ' + importStatsSummary(imports[0].stats);
    } catch (e) { /* die Zeilen behalten ihren Standardtext */ }
}

// ---------- Vitalwerte ----------
function initVitalwerte() {
    state.vitalInit = true;
    // Nach dem Loeschen von Daten wird neu aufgebaut -- auf derselben
    // Leinwand darf dann nicht noch das alte Diagramm haengen.
    if (state.chartBp) state.chartBp.destroy();
    if (state.chartGlucose) state.chartGlucose.destroy();
    state.chartBp = new Chart(document.getElementById('hChartBp').getContext('2d'), {
        type: 'line',
        data: { labels: [], datasets: [
            { label: 'Systolisch', data: [], borderColor: cssVar('--danger'), backgroundColor: cssVar('--danger-soft'), tension: 0.3, pointRadius: 2, fill: false },
            { label: 'Diastolisch', data: [], borderColor: cssVar('--info'), backgroundColor: cssVar('--info-soft'), tension: 0.3, pointRadius: 2, fill: false },
        ] },
        options: chartDefaults(),
    });
    state.chartGlucose = new Chart(document.getElementById('hChartGlucose').getContext('2d'), {
        type: 'line',
        data: { labels: [], datasets: [{
            label: 'Blutzucker', data: [], borderColor: cssVar('--warn'),
            backgroundColor: cssVar('--warn-soft'), tension: 0.3, pointRadius: 2, fill: true,
        }] },
        options: chartDefaults({
            plugins: { legend: { display: false }, tooltip: themedTooltip() },
        }),
    });
    // Der Zeitraum-Knopf meldet beim Einhaengen einmal -- das ist die erste
    // Ladung. Er steht deshalb hier unten, wenn die Diagramme schon stehen.
    VexRange.mount(document.getElementById('hVitalRange'), {
        onChange: (r) => { state.vitalRange = r; loadMetricCharts(); loadBpGlucoseCharts(); },
    });
}

// v1.45.0: Jede Metrik bekommt ihr eigenes Diagramm (zeigen statt umschalten).
// v1.46.0: Beim Wechsel des Zeitraums werden Karten und Chart-Instanzen NICHT
// neu gebaut -- sie bekommen die neuen Daten und animieren hinein.
// Gespeicherte Reihenfolge auf die bekannten Metriken anwenden: erst die
// sortierten, dann alles, was der Nutzer noch nie in der Hand hatte.
function orderedMetricKeys() {
    const all = Object.keys(METRIC_LABELS);
    const saved = (state.metricOrder || []).filter(k => all.includes(k));
    return saved.concat(all.filter(k => !saved.includes(k)));
}

async function loadMetricCharts() {
    const box = document.getElementById('hMetricCharts');
    if (!box) return;

    if (!state.metricCards) {
        try {
            const r = await HEALTH_API.metricOrder();
            state.metricOrder = (r && r.order) || [];
        } catch (e) { state.metricOrder = []; }
        state.metricCards = {};
        // Die Platzhalter bleiben stehen, bis die ersten Zahlen da sind; die
        // Karten warten verborgen (is-empty). Sonst stuenden dreizehn leere
        // Karten da, und die Haelfte verschwaende einen Augenblick spaeter
        // wieder -- die ganze Seite sprang.
        orderedMetricKeys().forEach(k => {
            const card = buildMetricShell(k);
            card.classList.add('is-empty');
            box.appendChild(card);
            state.metricCards[k] = card;
        });
        initMetricSortable(box);
    }
    const keys = orderedMetricKeys();

    const range = state.vitalRange || VexRange.resolve('30');
    box.classList.add('is-loading');
    const rowsList = await Promise.all(
        keys.map(k => HEALTH_API.metricSeries(k, range.fetchDays).catch(() => [])));
    // Zwischenzeitlicher Zeitraum-Wechsel: das spaetere Ergebnis gewinnt.
    if (state.vitalRange !== range) return;
    box.classList.remove('is-loading');
    keys.forEach((k, i) => updateMetricCard(
        k, VexRange.clip(rowsList[i], ['sample_date', 'recorded_at'], range), range.days));
    box.querySelectorAll('.gh-skel-karte').forEach(el => el.remove());
    document.getElementById('hBpBox').hidden = false;

    // Was im Zeitraum nichts hat, steht in einer Zeile -- nicht als leere Karte.
    const ohne = keys.filter(k => state.metricCards[k].classList.contains('is-empty'))
                     .map(k => METRIC_LABELS[k].label);
    const ohneEl = document.getElementById('hMetricOhne');
    ohneEl.hidden = !ohne.length;
    ohneEl.textContent = ohne.length ? 'Ohne Werte in diesem Zeitraum: ' + ohne.join(', ') + '.' : '';
    const mit = keys.length - ohne.length;
    document.getElementById('hVitalInfo').textContent =
        `${mit} ${mit === 1 ? 'Messgröße' : 'Messgrößen'} mit Werten · ${range.label || 'Zeitraum'}`;
}

// Gleiche Wert-Ermittlung wie fuer die Chart-Linie (qty, sonst avg_value).
function metricValueOf(r) {
    const v = Number(r.qty);
    return Number.isFinite(v) ? v : Number(r.avg_value);
}

function buildMetricShell(key) {
    const meta = METRIC_LABELS[key];
    const card = document.createElement('div');
    card.className = 'h-metric-card';
    card.dataset.metric = key;
    card.innerHTML = `
        <span class="drag-handle" title="Ziehen zum Sortieren" aria-hidden="true">${ikon('griff', 16)}</span>
        <div class="h-metric-head">
            <div class="h-metric-name"><span class="gh-punkt" style="--ton:var(${meta.ton})"></span>${escHtml(meta.label)}</div>
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
        // Ø, Min und Max beziehen sich auf die echten Messtage.
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
        setChartDates(ch, rows.map(r => r.sample_date || r.recorded_at));
        state.metricChartMap[key] = ch;
        return;
    }
    setChartDates(ch, rows.map(r => r.sample_date || r.recorded_at));
    ch.data.labels = labels;
    ch.data.datasets[0].data = data;
    ch.data.datasets[1].data = trend;
    ch.data.datasets[1].label = `Ø gleitend (${win})`;
    ch.update();
}

// Drag & Drop: Anfassen nur am Griff, auf dem Touchscreen mit kurzer
// Verzoegerung, damit Scrollen weiter funktioniert.
function initMetricSortable(box) {
    if (state.sortableMetrics) return;
    if (typeof Sortable === 'undefined') {
        // Sortable.min.js laedt mit `defer` -- dann einmal nach dem
        // load-Event nachziehen, statt das Sortieren still wegzulassen.
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
                    data, borderColor: meta.color, backgroundColor: tonAlpha(meta.color, 0.12),
                    tension: 0.3, fill: true, pointRadius: 0, borderWidth: 2,
                    order: VexCharts.ORDER.VALUE,
                },
                // Gleitende Ø-/Trendlinie (ohne Messluecken). Sie liegt UEBER
                // der Wertlinie (kleinere `order` = weiter oben, js/charts.js).
                {
                    label: `Ø gleitend (${win})`, data: trend,
                    borderColor: th.text, borderWidth: 1.5, borderDash: [5, 4],
                    tension: 0.35, fill: false, pointRadius: 0, spanGaps: true,
                    order: VexCharts.ORDER.TREND,
                },
            ],
        },
        options: chartDefaults({
            plugins: { legend: { display: false }, tooltip: themedTooltip() },
            scales: {
                x: { ticks: { color: th.muted, maxRotation: 0, autoSkipPadding: 20,
                              font: { size: 10 } }, grid: { display: false }, border: { display: false } },
                y: { ticks: { color: th.muted, font: { size: 10 }, maxTicksLimit: 4 },
                     grid: { color: th.grid }, border: { display: false }, beginAtZero: false },
            },
        }),
    });
}

async function loadBpGlucoseCharts() {
    try {
        const range = state.vitalRange || VexRange.resolve('30');
        const bp = VexRange.clip(await HEALTH_API.bloodPressure(range.fetchDays),
                                 'recorded_at', range);
        state.chartBp.data.labels = bp.map(r => fmtDate(r.recorded_at));
        setChartDates(state.chartBp, bp.map(r => r.recorded_at));
        state.chartBp.data.datasets[0].data = bp.map(r => r.systolic);
        state.chartBp.data.datasets[1].data = bp.map(r => r.diastolic);
        state.chartBp.update();
        kurveOk('hChartBp');
    } catch (e) {
        // Bei Messwerten ist ein stiller Fehler der schlimmste: die alte
        // Kurve bleibt stehen, man liest sie als aktuell. Also sagen, dass
        // sie nicht frisch ist.
        kurveFehler('hChartBp');
    }
    try {
        const range = state.vitalRange || VexRange.resolve('30');
        const gl = VexRange.clip(await HEALTH_API.bloodGlucose(range.fetchDays),
                                 'recorded_at', range);
        state.chartGlucose.data.labels = gl.map(r => fmtDate(r.recorded_at));
        setChartDates(state.chartGlucose, gl.map(r => r.recorded_at));
        state.chartGlucose.data.datasets[0].data = gl.map(r => r.value);
        state.chartGlucose.update();
        kurveOk('hChartGlucose');
    } catch (e) {
        kurveFehler('hChartGlucose');
    }
}

/* Ein Streifen ueber der Kurve statt einer leeren Flaeche: die Kurve selbst
   bleibt sichtbar, traegt aber den Vermerk, dass der letzte Abruf nicht
   durchkam. */
function kurveFehler(canvasId) {
    const c = document.getElementById(canvasId);
    if (!c || !c.parentElement) return;
    let hinweis = c.parentElement.querySelector('.h-kurve-alt');
    if (!hinweis) {
        hinweis = document.createElement('p');
        hinweis.className = 'h-kurve-alt';
        c.parentElement.appendChild(hinweis);
    }
    hinweis.textContent = 'Nicht aktualisiert — der Abruf ist fehlgeschlagen. '
        + 'Was du siehst, ist der Stand von vorhin.';
}

function kurveOk(canvasId) {
    const c = document.getElementById(canvasId);
    const hinweis = c && c.parentElement && c.parentElement.querySelector('.h-kurve-alt');
    if (hinweis) hinweis.remove();
}

// ---------- Schlaf ----------
// Stunden-Offset ab 18:00 -> "HH:MM". Werte ueber 24 wrappen sauber.
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
// und die Phasen kacheln diesen Balken mit ihrer ECHTEN Dauer. Technisch sind
// das mehrere Floating-Bar-Datasets im selben x-Slot (`x.stacked` gruppiert
// sie uebereinander, `y.stacked` bleibt aus).
//
// Was die Daten NICHT hergeben: die zeitliche Lage der Phasen. Apple liefert je
// Nacht nur Summen -- die Reihenfolge im Balken ist fest, kein Hypnogramm.
const SLEEP_SEGMENTS = [
    { key: 'deep',   label: 'Tief',              color: cssVar('--h-sleep-deep') },
    { key: 'core',   label: 'Kern',              color: cssVar('--h-sleep-core') },
    { key: 'rem',    label: 'REM',               color: cssVar('--h-sleep-rem') },
    { key: 'rest',   label: 'ohne Phasendetail', color: cssVar('--h-sleep-rest') },
    { key: 'awake',  label: 'Wach',              color: cssVar('--h-sleep-awake') },
];

/* Die geschlafenen Stunden jeder Nacht (v2.28.0) -- dieselbe Zahl wie in
   „Ø Schlafdauer“, also nur Tief, Kern und REM. Sie steht in gedämpfter
   Schrift ÜBER der Spalte, am Zubettgeh-Ende: in der Spalte lag sie auf
   wechselnden Phasenfarben und sah unruhig aus (v2.28.1). Erscheinen darf
   sie erst, wenn die Balken stehen -- vorher hing sie in der Luft, während
   die Spalten noch einfuhren. Ist die Spalte schmaler als die Zahl (30
   Nächte am Handy), steht keine da; der Tooltip nennt sie weiter. */
function schlafStundenPlugin() {
    return {
        id: 'schlafStunden',
        beforeUpdate(chart) { chart.$stundenZeigen = false; },
        afterDatasetsDraw(chart) {
            if (!chart.$stundenZeigen) return;
            const naechte = state.sleepUsable || [], fenster = state.sleepWindows || [];
            const n = chart.data.labels.length;
            if (!naechte.length || !n) return;
            const x = chart.scales.x, y = chart.scales.y, ctx = chart.ctx;
            const platz = x.width / n;
            ctx.save();
            ctx.font = '600 10px system-ui, -apple-system, "Segoe UI", sans-serif';
            ctx.fillStyle = cssVar('--text-2');
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';
            naechte.forEach((r, i) => {
                const w = fenster[i];
                const min = schlafMinuten(r);
                if (!w || !min) return;
                const text = fmt1(min / 60);
                if (ctx.measureText(text).width + 4 > platz) return;
                const oben = Math.max(chart.chartArea.top + 10, y.getPixelForValue(w[0]) - 4);
                ctx.fillText(text, x.getPixelForValue(i), oben);
            });
            ctx.restore();
        },
    };
}
/* Nach dem Einfahren einmal nachzeichnen, jetzt mit den Zahlen. Der
   Zeitgeber fängt den Fall ab, dass gar keine Animation läuft (reduzierte
   Bewegung) und onComplete deshalb nicht kommt. */
function schlafStundenZeigen(chart) {
    if (!chart || chart.$stundenZeigen) return;
    chart.$stundenZeigen = true;
    chart.draw();
}

function initSchlaf() {
    state.sleepInit = true;
    if (state.chartSleepTimes) state.chartSleepTimes.destroy();
    const th = chartTheme();
    state.chartSleepTimes = new Chart(document.getElementById('hChartSleepTimes').getContext('2d'), {
        type: 'bar',
        data: { labels: [], datasets: [
            // v2.26.0: kein Rahmen „Im Bett“ mehr -- die Spalte besteht nur
            // noch aus den Phasen selbst.
            ...SLEEP_SEGMENTS.map(seg => ({
                label: seg.label, data: [], backgroundColor: seg.color,
                borderSkipped: false, barPercentage: 0.8, categoryPercentage: 0.9,
            })),
            // v1.46.5: Was hinter der 18:00-Kante liegt, wird in DERSELBEN
            // Spalte ab der Oberkante weitergezeichnet -- die Achse ist ein
            // 24-h-Kreis. Die naechste Spalte ist die naechste aufgezeichnete
            // Nacht und oft nicht der naechste Tag.
            ...SLEEP_SEGMENTS.map(seg => ({
                label: seg.label + ' (nach 18:00)', data: [], backgroundColor: seg.color,
                wrap: true, borderSkipped: false, barPercentage: 0.8, categoryPercentage: 0.9,
            })),
            // Die duennen gruenen Kanten an der Bruchstelle.
            { label: 'über 18:00 hinaus', data: [], backgroundColor: cssVar('--ok'),
              marker: true, borderSkipped: false,
              barPercentage: 0.8, categoryPercentage: 0.9 },
            { label: 'über 18:00 hinaus (oben)', data: [], backgroundColor: cssVar('--ok'),
              marker: true, wrap: true, borderSkipped: false,
              barPercentage: 0.8, categoryPercentage: 0.9 },
        ] },
        options: chartDefaults({
            plugins: {
                legend: { position: 'bottom', labels: { color: th.muted, boxWidth: 8, boxHeight: 8,
                    usePointStyle: true, pointStyle: 'circle', font: { size: 11 },
                    // Die Fortsetzung hat dieselben Farben wie der Hauptteil
                    // und bekommt keinen zweiten Eintrag. Der gruene Eintrag
                    // taucht nur auf, wenn eine Nacht ueber die Kante laeuft.
                    filter: (item, data) => {
                        const ds = data.datasets[item.datasetIndex];
                        if (ds.wrap) return false;
                        // Nur, was in diesem Zeitraum vorkommt -- „ohne
                        // Phasendetail“ etwa gibt es nur bei aelteren Naechten.
                        return (ds.data || []).some(v => Array.isArray(v));
                    } } },
                tooltip: themedTooltip({
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
            animation: { onComplete: (e) => schlafStundenZeigen(e.chart) },
            scales: {
                x: { stacked: true, ticks: { color: th.muted, maxRotation: 0, autoSkipPadding: 12, font: { size: 10 } },
                     grid: { display: false }, border: { display: false } },
                y: { stacked: false, reverse: true, min: 0, max: 24,
                     ticks: { color: th.muted, stepSize: 3, font: { size: 10 }, callback: (v) => sleepOffsetToClock(v) },
                     grid: { color: th.grid }, border: { display: false } },
            },
        }),
        plugins: [schlafStundenPlugin()],
    });
    VexRange.mount(document.getElementById('hSleepRange'), {
        onChange: (r) => { state.sleepRange = r; loadSleepChart(); },
    });
}

async function loadSleepChart() {
    try {
        const range = state.sleepRange || VexRange.resolve('30');
        const rows = VexRange.clip(await HEALTH_API.sleep(range.fetchDays),
                                   'sleep_date', range);
        const kpiBox = document.getElementById('hSleepKpis');
        const info = document.getElementById('hSleepInfo');
        if (!rows.length) {
            kpiBox.innerHTML = '';
            info.textContent = 'Keine Nacht in diesem Zeitraum';
            const emptyNote = document.getElementById('hSleepNote');
            if (emptyNote) emptyNote.textContent = 'Auto Health Export schickt Schlaf nur, wenn eine Uhr '
                + 'ihn aufzeichnet (oder ein anderer Tracker die Phasen liefert).';
            state.sleepUsable = []; state.sleepWindows = [];
            renderSleepRhythm([]);
            state.chartSleepTimes.data.labels = [];
            state.chartSleepTimes.data.datasets.forEach(d => d.data = []);
            state.chartSleepTimes.update();
            return;
        }
        // Ø nur ueber Naechte mit tatsaechlichem Wert; faellt das Feld leer
        // aus, zaehlen die Phasen -- damit KPIs und Diagramm uebereinstimmen.
        const num = (v) => { const n = Number(v); return Number.isFinite(n) ? n : null; };
        const asleepMin = (r) => schlafMinuten(r) || null;
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
        // Tage ohne getragene Uhr. Das Gate ist die GESAMTE Schlafdauer der
        // Nacht, damit sich alle Kacheln auf dieselben Naechte beziehen.
        const MIN_SLEEP_MIN = 60;
        const usable = rows.filter(r => (asleepMin(r) || 0) >= MIN_SLEEP_MIN);
        const skippedNights = rows.length - usable.length;

        // v1.46.2: Ohne Zubettgeh- UND Aufstehzeit laesst sich eine Nacht auf
        // der Uhrzeit-Achse nicht platzieren. Sie fliegt aus dem Diagramm,
        // bleibt aber in den Ø-Kacheln; die Notiz darunter benennt das.
        const plotted = usable.filter(r => r.sleep_start && r.sleep_end
            && toOffset(r.sleep_start) != null && toOffset(r.sleep_end) != null);
        const undatedNights = usable.length - plotted.length;
        state.sleepUsable = plotted;
        const windows = plotted.map(r => {
            const a = toOffset(r.sleep_start), b = toOffset(r.sleep_end);
            if (a == null || b == null) return null;
            return [a, b <= a ? b + 24 : b];
        });
        // `sleepWindows` behaelt die UNGEKAPPTEN Zeiten fuer Tooltip und Fusszeile.
        state.sleepWindows = windows;
        const AXIS_END = 24;   // 18:00 des Folgetags
        // Der Rest laeuft oben in DERSELBEN Spalte weiter und hoert spaetestens
        // am eigenen Zubettgeh-Zeitpunkt auf.
        const wrapped = windows.map(w => (w && w[1] > AXIS_END + 1e-6)
            ? [0, Math.min(w[1] - AXIS_END, w[0])] : null);
        const cutLow  = wrapped.map(x => x ? [AXIS_END - 0.2, AXIS_END] : null);
        const cutHigh = wrapped.map(x => x ? [0, 0.2] : null);

        // Phasen kacheln das Fenster ab der Zubettgeh-Kante mit ihrer echten
        // Dauer; was ueberschiesst, wird am Fensterende abgeschnitten.
        const segH = (r) => {
            const h = (v) => (num(v) || 0) / 60;
            const phases = h(r.deep_minutes) + h(r.core_minutes) + h(r.rem_minutes);
            return {
                deep: h(r.deep_minutes), core: h(r.core_minutes), rem: h(r.rem_minutes),
                rest: Math.max(0, ((asleepMin(r) || 0) / 60) - phases),
                awake: h(r.awake_minutes),
            };
        };
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
        setChartDates(state.chartSleepTimes, plotted.map(r => r.sleep_date));
        segData.forEach((d, si) => { ds[si].data = d; });
        segWrap.forEach((d, si) => { ds[N + si].data = d; });
        ds[2 * N].data = cutLow;
        ds[2 * N + 1].data = cutHigh;
        state.chartSleepTimes.update();
        setTimeout(() => schlafStundenZeigen(state.chartSleepTimes), 1200);
        renderSleepRhythm(windows);

        const meanOf = (extract) => {
            const arr = usable.map(extract).filter(v => v != null && v > 0);
            return arr.length ? arr.reduce((s,v)=>s+v,0) / arr.length : null;
        };
        const meanAsleepMin = meanOf(asleepMin);
        const meanDeepMin   = meanOf(r => num(r.deep_minutes));
        const meanCoreMin   = meanOf(r => num(r.core_minutes));
        const meanRemMin    = meanOf(r => num(r.rem_minutes));

        const fmtH = (min) => min == null ? '<span class="gh-leer">–</span>' : fmt1(min / 60) + '<small>h</small>';
        const kpis = [
            // v2.26.0: ohne „Im Bett“ und die Effizienz, die daraus folgte.
            { label: 'Ø Schlafdauer', value: fmtH(meanAsleepMin) },
            { label: 'Ø Tief',        value: fmtH(meanDeepMin) },
            { label: 'Ø Kern',        value: fmtH(meanCoreMin) },
            { label: 'Ø REM',         value: fmtH(meanRemMin) },
        ];
        kpiBox.innerHTML = kpis.map(k => `
            <div class="gh-kpi"><div class="gh-kpi-lbl">${k.label}</div><div class="gh-kpi-val">${k.value}</div></div>`).join('');
        info.textContent = `${usable.length} ${usable.length === 1 ? 'Nacht' : 'Nächte'} · ${range.label || 'Zeitraum'}`;

        // Transparenz statt stiller Filterung: die Zeile nennt, was fehlt.
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
    } catch (e) { showToast('Schlaf laden fehlgeschlagen: ' + e.message, true); }
}

// v1.46.2 / v1.71.0: Typische Zubettgeh-/Aufstehzeit als Median mit dem
// Bereich der mittleren Haelfte. Gerechnet auf den 18:00-Offsets und um den
// Median neu verankert -- sonst waere der Mittelwert aus 23:30 und 00:30 die
// Mittagszeit, und eine Nacht vor 18:00 verzoege alles.
function quantile(sorted, p) {
    if (!sorted.length) return null;
    if (sorted.length === 1) return sorted[0];
    const pos = (sorted.length - 1) * p;
    const lo = Math.floor(pos), hi = Math.ceil(pos);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

// ``circular`` fuer Uhrzeiten, ohne fuer Dauern.
function spreadStats(values, circular) {
    const arr = values.filter(v => Number.isFinite(v));
    if (!arr.length) return null;
    let work = arr;
    if (circular && arr.length > 1) {
        const first = quantile(arr.slice().sort((a, b) => a - b), 0.5);
        work = arr.map(v => {
            const d = v - first;
            return d > 12 ? v - 24 : (d < -12 ? v + 24 : v);
        });
    }
    const sorted = work.slice().sort((a, b) => a - b);
    return {
        median: quantile(sorted, 0.5),
        q1: quantile(sorted, 0.25),
        q3: quantile(sorted, 0.75),
        n: arr.length,
    };
}

function renderSleepRhythm(windows) {
    const box = document.getElementById('hSleepRhythm');
    if (!box) return;
    const valid = (windows || []).filter(Boolean);
    if (!valid.length) { box.innerHTML = ''; return; }

    const bed = spreadStats(valid.map(w => w[0]), true);
    const wake = spreadStats(valid.map(w => w[1]), true);
    const items = [
        { lbl: 'Zubettgehen', st: bed,  clock: true },
        { lbl: 'Aufstehen',   st: wake, clock: true },
    ];
    // Liegt die Haelfte der Naechte ueber mehr als zwei Stunden verteilt, ist
    // auch der Median wenig wert -- das steht dann dabei.
    const WOBBLY_H = 2;
    box.innerHTML = items.map(i => {
        const st = i.st;
        const fmtV = (v) => i.clock ? sleepOffsetToClock(v) : fmt1(v) + ' h';
        const iqr = (st && st.q1 != null && st.q3 != null) ? st.q3 - st.q1 : null;
        const range = (iqr != null && st.n > 2)
            ? `meist ${fmtV(st.q1)}–${fmtV(st.q3)}` : null;
        const nights = valid.length === 1 ? '1 Nacht' : valid.length + ' Nächte';
        const sub = [range, nights, (iqr != null && iqr > WOBBLY_H) ? 'stark schwankend' : null]
            .filter(Boolean).join(' · ');
        return `
        <div class="h-rhythm-item">
            <div class="h-rhythm-lbl">${i.lbl}</div>
            <div class="h-rhythm-val">${fmtV(st.median)}</div>
            <div class="h-rhythm-sub">${sub}</div>
        </div>`;
    }).join('');
}

// ---------- Workouts ----------
/* v2.27.0: Der Reiter erzählt von oben nach unten: wie viel trainiert wurde
   und in welchem Rhythmus (Bühne), womit (Sportarten -- ein Tipp filtert,
   sie ersetzen die Chipreihe) und wann (die Workouts nach Wochen). Alles
   bezieht sich auf denselben Zeitraum und dieselbe Sportart. */
async function initWorkouts() {
    state.workoutsInit = true;
    try {
        if (!state.workoutsAll) state.workoutsAll = await HEALTH_API.workouts();
    } catch (e) {
        state.workoutsInit = false;
        document.getElementById('hWorkoutList').innerHTML = `<div class="empty is-error"><p class="empty-text">Die Workouts konnten nicht geladen werden.</p>
            <button type="button" class="v-btn v-btn--sm" onclick="initWorkouts()">Erneut versuchen</button></div>`;
        return;
    }
    state.workoutFilter = '';
    const alle = document.getElementById('hWoAlle');
    if (alle && !alle.dataset.an) {
        alle.dataset.an = '1';
        alle.addEventListener('click', () => { state.workoutFilter = ''; renderWorkouts(); });
    }
    // Der Zeitraum meldet beim Einhaengen einmal und zeichnet damit zum
    // ersten Mal. Nach dem Loeschen wird nicht neu eingehaengt.
    if (!state.workoutRangeMounted) {
        state.workoutRangeMounted = true;
        VexRange.mount(document.getElementById('hWorkoutRange'), {
            preset: 'all',
            onChange: (r) => { state.workoutRange = r; renderWorkouts(); },
        });
    } else {
        renderWorkouts();
    }
}

function woFilter(typ) {
    state.workoutFilter = state.workoutFilter === typ ? '' : typ;
    renderWorkouts();
}

// Montag der Woche, Kalenderwoche nach ISO.
function woMontag(d) {
    const m = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    m.setDate(m.getDate() - ((m.getDay() + 6) % 7));
    return m;
}
function woKw(d) {
    const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    const tag = t.getUTCDay() || 7;
    t.setUTCDate(t.getUTCDate() + 4 - tag);
    const neujahr = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
    return Math.ceil(((t - neujahr) / 86400000 + 1) / 7);
}
const woKurz = (d) => d.toLocaleDateString('de-DE', { day: 'numeric', month: 'numeric' });
const woMin = (w) => Number(w.duration_min) || 0;
function woPulsOk(v) { const n = Number(v); return Number.isFinite(n) && n >= 30 && n <= 240; }

/* Die Trainingszeit als Heldenzahl: Stunden groß, Minuten daneben. */
function woZeitHeld(min) {
    const h = Math.floor(min / 60), m = Math.round(min % 60);
    return h > 0
        ? `${h}<span class="v-held-rest">h</span><span class="gw-held-min">${m}</span><span class="v-held-rest">min</span>`
        : `${m}<span class="v-held-rest">min</span>`;
}

function renderWorkouts() {
    const range = state.workoutRange || VexRange.resolve('all');
    // Workouts liegen vollstaendig im Browser -- das Fenster wird hier
    // geschnitten und nicht nachgeladen.
    const imZeitraum = VexRange.clip(state.workoutsAll, 'start_at', range);
    const typen = new Set(imZeitraum.map(w => w.workout_type));
    if (state.workoutFilter && !typen.has(state.workoutFilter)) state.workoutFilter = '';
    const rows = imZeitraum
        .filter(w => !state.workoutFilter || w.workout_type === state.workoutFilter)
        .slice().sort((a, b) => new Date(b.start_at) - new Date(a.start_at));
    const zeitraum = range.preset === 'all' ? 'gesamt' : range.label;

    document.getElementById('hWoInfo').textContent =
        `${fmt0(rows.length)} ${rows.length === 1 ? 'Workout' : 'Workouts'} · ${range.preset === 'all' ? 'Gesamter Zeitraum' : range.label}`;
    document.getElementById('hWorkoutRangeLbl').textContent =
        state.workoutFilter ? wMeta(state.workoutFilter).de : '';
    zeichneWoBuehne(rows, range, zeitraum);
    zeichneWoArten(imZeitraum);
    zeichneWoListe(rows);
}

function zeichneWoBuehne(rows, range, zeitraum) {
    const summe = rows.reduce((s, w) => s + woMin(w), 0);
    const kcal = rows.reduce((s, w) => s + (Number(w.active_energy_kcal) || 0), 0);
    const meter = rows.reduce((s, w) => s + (Number(w.distance_m) || 0), 0);
    const puls = rows.map(w => Number(w.avg_heart_rate)).filter(woPulsOk);
    const pulsSchnitt = puls.length ? puls.reduce((s, v) => s + v, 0) / puls.length : null;

    document.getElementById('hWoMarke').textContent = 'Training · ' + zeitraum;
    document.getElementById('hWoFilterLbl').textContent =
        state.workoutFilter ? 'nur ' + wMeta(state.workoutFilter).de : '';
    document.getElementById('hWoZeit').innerHTML = woZeitHeld(summe);
    document.getElementById('hWoUnter').textContent = rows.length
        ? `in ${fmt0(rows.length)} ${rows.length === 1 ? 'Workout' : 'Workouts'} · Ø ${fmtDuration(summe / rows.length)}`
        : 'Kein Workout in diesem Zeitraum';
    const fakt = (dt, dd) => `<div><dt>${dt}</dt><dd>${dd}</dd></div>`;
    document.getElementById('hWoFakten').innerHTML =
        fakt('Workouts', fmt0(rows.length))
        + fakt('Energie', kcal > 0 ? fmt0(kcal) + '<small>kcal</small>' : '–')
        + fakt('Distanz', meter > 0 ? fmt1(meter / 1000) + '<small>km</small>' : '–')
        + fakt('Ø Puls', pulsSchnitt != null ? fmt0(pulsSchnitt) + '<small>bpm</small>' : '–');
    zeichneWoRhythmus(rows, range);
}

/* Der Rhythmus: Trainingszeit je Tag, Woche oder Monat -- je nachdem, wie
   lang der Zeitraum ist. Ein Monat in Tagen, ein Jahr in Wochen, alles
   darüber in Monaten; so stehen nie mehr als gut fünfzig Balken da. */
async function zeichneWoRhythmus(rows, range) {
    const heute = new Date(); heute.setHours(0, 0, 0, 0);
    const bis = range.to ? new Date(range.to + 'T00:00:00') : heute;
    let von = range.from ? new Date(range.from + 'T00:00:00') : null;
    if (!von) {
        const erstes = rows.reduce((m, w) => Math.min(m, new Date(w.start_at).getTime()), bis.getTime());
        von = new Date(erstes); von.setHours(0, 0, 0, 0);
    }
    const tage = Math.round((bis - von) / 86400000) + 1;
    const art = tage <= 31 ? 'tag' : tage <= 371 ? 'woche' : 'monat';
    const schluessel = (d) => art === 'tag' ? isoTag(d)
        : art === 'woche' ? isoTag(woMontag(d))
        : d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
    const eimer = [];
    const lauf = art === 'woche' ? woMontag(von) : art === 'monat' ? new Date(von.getFullYear(), von.getMonth(), 1) : new Date(von);
    while (lauf <= bis) {
        const d = new Date(lauf);
        eimer.push({ key: schluessel(d), d: d, min: 0 });
        if (art === 'tag') lauf.setDate(lauf.getDate() + 1);
        else if (art === 'woche') lauf.setDate(lauf.getDate() + 7);
        else lauf.setMonth(lauf.getMonth() + 1);
    }
    const nachSchluessel = new Map(eimer.map(e => [e.key, e]));
    rows.forEach(w => { const e = nachSchluessel.get(schluessel(new Date(w.start_at))); if (e) e.min += woMin(w); });

    const wort = { tag: 'je Tag', woche: 'je Woche', monat: 'je Monat' }[art];
    document.getElementById('hWoRhythmusLbl').textContent = 'Trainingszeit ' + wort;
    const aktiv = eimer.filter(e => e.min > 0).length;
    const einheit = { tag: ['Tag', 'Tagen'], woche: ['Woche', 'Wochen'], monat: ['Monat', 'Monaten'] }[art];
    document.getElementById('hWoRhythmusSub').textContent = eimer.length
        ? `in ${aktiv} von ${eimer.length} ${eimer.length === 1 ? einheit[0] : einheit[1]}` : '';

    const titel = (e) => art === 'tag' ? tagName(e.key)
        : art === 'woche' ? `KW ${woKw(e.d)} · ${woKurz(e.d)}–${woKurz(new Date(e.d.getTime() + 6 * 86400000))}`
        : e.d.toLocaleDateString('de-DE', { month: 'long', year: 'numeric' });
    const achse = (e) => art === 'tag' ? woKurz(e.d)
        : art === 'woche' ? 'KW ' + woKw(e.d)
        : e.d.toLocaleDateString('de-DE', { month: 'short' });

    try { await VexCharts.bereit(); } catch (e) { return; }
    const hoechst = Math.max(1, ...eimer.map(e => e.min));
    const canvas = document.getElementById('hWoRhythmus');
    if (!canvas) return;
    const th = chartTheme();
    const ton = getComputedStyle(document.getElementById('hWoBuehne')).getPropertyValue('--gh-ton').trim() || cssVar('--m-health');
    if (state.woRhythmus) state.woRhythmus.destroy();
    state.woRhythmus = new Chart(canvas.getContext('2d'), {
        type: 'bar',
        data: { labels: eimer.map(achse), datasets: [Object.assign({
            label: 'Trainingszeit', data: eimer.map(e => Math.round(e.min)),
            backgroundColor: ton, maxBarThickness: 28, order: VexCharts.ORDER.VALUE,
        }, VexCharts.balken(4))] },
        options: chartDefaults({
            plugins: {
                legend: { display: false },
                tooltip: themedTooltip({ displayColors: false, callbacks: {
                    title: (items) => items.length ? titel(eimer[items[0].dataIndex]) : '',
                    label: (ctx) => ctx.raw ? fmtDuration(ctx.raw) : 'kein Training',
                } }),
            },
            scales: {
                x: { ticks: { color: th.muted, font: { size: 10 }, maxRotation: 0, autoSkipPadding: 10 },
                     grid: { display: false }, border: { display: false } },
                // Runde Stufen (30 min, 1 h, 2 h …) statt „3,3 h“.
                y: { beginAtZero: true, ticks: { color: th.muted, font: { size: 10 },
                         stepSize: [15, 30, 60, 120, 180, 300, 600, 1200].find(st => hoechst / st <= 4) || 1200,
                         callback: (v) => v >= 60 ? (v / 60).toLocaleString('de-DE', { maximumFractionDigits: 1 }) + ' h' : v + ' min' },
                     grid: { color: th.grid }, border: { display: false } },
            },
        }),
    });
}

/* Je Sportart eine Zeile: wie oft, wie lange, wie weit. Die Zeile ist der
   Filter -- ein zweiter Tipp hebt ihn wieder auf. Gezählt wird über den
   ganzen Zeitraum, auch wenn gerade gefiltert ist: sonst stünde nach dem
   ersten Tipp nur noch eine Zeile da, und der Weg zurück wäre weg. */
function zeichneWoArten(imZeitraum) {
    const box = document.getElementById('hWoArten');
    const abschnitt = document.getElementById('hWoArtenAbschnitt');
    const gruppen = new Map();
    imZeitraum.forEach(w => {
        const g = gruppen.get(w.workout_type) || { typ: w.workout_type, n: 0, min: 0, m: 0 };
        g.n += 1; g.min += woMin(w); g.m += Number(w.distance_m) || 0;
        gruppen.set(w.workout_type, g);
    });
    const liste = [...gruppen.values()].sort((a, b) => b.min - a.min);
    abschnitt.hidden = liste.length < 2 && !state.workoutFilter;
    document.getElementById('hWoAlle').hidden = !state.workoutFilter;
    document.getElementById('hWoArtenSub').textContent = state.workoutFilter ? '' : 'Tippen filtert';
    const gesamt = liste.reduce((s, g) => s + g.min, 0) || 1;
    box.innerHTML = `<div class="rec-list gh-wo gw-arten">${liste.map(g => {
        const m = wMeta(g.typ);
        const dist = g.m > 0 ? (isSwimWorkout(g.typ) || g.m < 1000 ? fmt0(g.m) + ' m' : fmt1(g.m / 1000) + ' km') : null;
        const meta = [`${fmt0(g.n)}×`, dist].filter(Boolean);
        const anteil = Math.round(g.min / gesamt * 100);
        const aktiv = state.workoutFilter === g.typ;
        return `<button type="button" class="rec-row gw-art${aktiv ? ' is-active' : ''}" aria-pressed="${aktiv}"
                    onclick="woFilter(${escHtml(JSON.stringify(g.typ))})" style="--gw-anteil:${(g.min / gesamt).toFixed(3)}">
            <span class="rec-mark" style="--tone:var(--gh-ton)"><span class="gh-sport" aria-hidden="true">${m.icon}</span></span>
            <span class="rec-main"><span class="rec-title">${escHtml(m.de)}</span>
                <span class="rec-meta">${meta.map(escHtml).join('<span class="sep">·</span>')}</span></span>
            <span class="rec-side"><span class="rec-val">${escHtml(fmtDuration(g.min))}</span>
                <span class="rec-sub">${anteil} %</span></span>
        </button>`;
    }).join('')}</div>`;
}

/* Die Workouts nach Wochen. Der Kopf jeder Woche trägt ihre Summe -- so
   liest man den Rhythmus auch hier, ohne zu zählen. */
function zeichneWoListe(rows) {
    const list = document.getElementById('hWorkoutList');
    if (!rows.length) {
        list.innerHTML = `<div class="empty"><p class="empty-text">${state.workoutsAll.length
            ? 'Keine Workouts in diesem Zeitraum. Ein längerer Zeitraum zeigt mehr.'
            : 'Noch keine Workouts synchronisiert. Auto Health Export schickt sie mit dem täglichen Upload.'}</p></div>`;
        return;
    }
    const diese = woMontag(new Date()).getTime();
    const wochen = new Map();
    rows.forEach(w => {
        const mo = woMontag(new Date(w.start_at));
        const k = mo.getTime();
        if (!wochen.has(k)) wochen.set(k, { mo: mo, rows: [] });
        wochen.get(k).rows.push(w);
    });
    list.innerHTML = [...wochen.values()].map(wo => {
        const abstand = Math.round((diese - wo.mo.getTime()) / (7 * 86400000));
        const so = new Date(wo.mo.getTime() + 6 * 86400000);
        const name = abstand === 0 ? 'Diese Woche' : abstand === 1 ? 'Letzte Woche'
            : `KW ${woKw(wo.mo)} · ${woKurz(wo.mo)}–${woKurz(so)}`;
        const min = wo.rows.reduce((s, w) => s + woMin(w), 0);
        return `<div class="gw-woche">
            <div class="gw-woche-kopf"><span>${escHtml(name)}</span>
                <span>${escHtml(fmtDuration(min))} · ${wo.rows.length}×</span></div>
            <div class="rec-list gh-wo">${wo.rows.map(workoutZeile).join('')}</div>
        </div>`;
    }).join('');
}

function workoutDistanz(w) {
    const dist = Number(w.distance_m);
    if (!(Number.isFinite(dist) && dist > 0)) return null;
    return (dist >= 1000 && !isSwimWorkout(w.workout_type)) ? fmt1(dist / 1000) + ' km' : fmt0(dist) + ' m';
}

// Eine Zeile je Workout: die Marke sagt die Sportart, der Wert am Rand die
// Energie. Die Zeile oeffnet den Dialog mit allem Weiteren.
function workoutZeile(w) {
    const m = wMeta(w.workout_type);
    const meta = [fmtDateTime(w.start_at), fmtDuration(w.duration_min), workoutDistanz(w)].filter(Boolean);
    const kcal = Number(w.active_energy_kcal);
    return `<button type="button" class="rec-row" id="hwo_${w.id}" onclick="dlgWorkout(${w.id})">
        <span class="rec-mark" style="--tone:var(--gh-ton)"><span class="gh-sport" aria-hidden="true">${m.icon}</span></span>
        <span class="rec-main"><span class="rec-title">${escHtml(m.de)}</span>
            <span class="rec-meta">${meta.map(escHtml).join('<span class="sep">·</span>')}</span></span>
        <span class="rec-side">${Number.isFinite(kcal) ? `<span class="rec-val">${fmt0(kcal)}<small>kcal</small></span>` : ''}
            ${w.avg_heart_rate ? `<span class="rec-sub">Ø ${fmt0(w.avg_heart_rate)} bpm</span>` : ''}</span>
        <span class="rec-go">${ikon('pfeil', 16)}</span>
    </button>`;
}

/* Pace nur für Distanz-Sportarten. Beim Schwimmen ist die übliche Einheit
   min/100 m -- in min/km wäre sie als „38:00“ nicht lesbar. */
function workoutPace(w) {
    const swim = isSwimWorkout(w.workout_type);
    const dist = Number(w.distance_m);
    if (!(Number.isFinite(dist) && dist > 0 && w.duration_min > 0)) return null;
    const pace = w.duration_min / (dist / (swim ? 100 : 1000));
    if (!(Number.isFinite(pace) && pace > 0 && pace < (swim ? 20 : 60))) return null;
    let mm = Math.floor(pace), ss = Math.round((pace - mm) * 60);
    if (ss === 60) { mm += 1; ss = 0; }
    return { wert: `${mm}:${String(ss).padStart(2, '0')}`, einheit: swim ? 'min/100 m' : 'min/km' };
}

/* Zusatzwerte aus dem Export. Die Einheit steht hier und nicht im Namen --
   bis v2.26.0 stand sie in beidem („Schrittfrequenz (spm) … 168,0 spm“) --,
   und Zählwerte tragen keine Nachkommastelle („Schritte 6980,0“). */
const EXTRA_LABELS = {
    resting_energy_kcal:   { name: 'Ruhe-Energie', einheit: 'kcal', ganz: true },
    intensity_kcal_h_kg:   { name: 'Intensität', einheit: 'kcal/h·kg' },
    max_speed_kmh:         { name: 'Max. Geschwindigkeit', einheit: 'km/h' },
    avg_speed_kmh:         { name: 'Ø Geschwindigkeit', einheit: 'km/h' },
    flights_climbed:       { name: 'Etagen gestiegen', ganz: true },
    elevation_descended_m: { name: 'Abstieg', einheit: 'm', ganz: true },
    step_count:            { name: 'Schritte', ganz: true },
    cadence_spm:           { name: 'Schrittfrequenz', einheit: 'spm', ganz: true },
    swim_stroke_count:     { name: 'Schwimmzüge', ganz: true },
    swim_cadence_spm:      { name: 'Schwimmkadenz', einheit: 'spm', ganz: true },
    lap_length_m:          { name: 'Bahnlänge', einheit: 'm', ganz: true },
    swolf:                 { name: 'SWOLF', ganz: true },
    temperature_c:         { name: 'Temperatur', einheit: '°C' },
    humidity_pct:          { name: 'Luftfeuchtigkeit', einheit: '%', ganz: true },
    cycling_speed_kmh:     { name: 'Rad-Geschwindigkeit', einheit: 'km/h' },
    cycling_power_w:       { name: 'Rad-Leistung', einheit: 'W', ganz: true },
};

/* Alles zu einem Workout in einem Dialog (v2.27.0): oben die drei Zahlen,
   um die es geht, darunter der Puls mit seinem Verlauf, dann der Rest als
   ruhige Liste -- statt neun gleich lauter Kacheln. Löschen einen Griff
   tiefer im Fuß (DESIGN 6d). */
async function dlgWorkout(id) {
    const w = (state.workoutsAll || []).find(x => x.id === id);
    if (!w) return;
    const m = wMeta(w.workout_type);
    const dist = workoutDistanz(w);
    const pace = workoutPace(w);
    const teil = (s) => { const i = s.lastIndexOf(' '); return i < 0 ? [s, ''] : [s.slice(0, i), s.slice(i + 1)]; };
    const dm = Math.round(Number(w.duration_min) || 0);
    const haupt = [dm >= 60
        ? { lbl: 'Dauer', wert: `${Math.floor(dm / 60)}:${String(dm % 60).padStart(2, '0')}`, einheit: 'h' }
        : { lbl: 'Dauer', wert: fmt0(dm), einheit: 'min' }];
    if (dist) { const [z, e] = teil(dist); haupt.push({ lbl: 'Distanz', wert: z, einheit: e }); }
    if (w.active_energy_kcal != null) haupt.push({ lbl: 'Aktive Energie', wert: fmt0(w.active_energy_kcal), einheit: 'kcal' });
    if (haupt.length < 3 && pace) haupt.push({ lbl: 'Pace', wert: pace.wert, einheit: pace.einheit });

    const zeile = (name, wert) => `<div class="gw-d-zeile"><span>${escHtml(name)}</span><strong>${wert}</strong></div>`;
    const grund = [];
    if (pace && !haupt.some(h => h.lbl === 'Pace')) grund.push(zeile('Pace', `${pace.wert} <small>${pace.einheit}</small>`));
    if (w.total_energy_kcal != null && w.total_energy_kcal !== w.active_energy_kcal)
        grund.push(zeile('Gesamt-Energie', `${fmt0(w.total_energy_kcal)} <small>kcal</small>`));
    if (w.elevation_m != null && w.elevation_m > 0) grund.push(zeile('Aufstieg', `${fmt0(w.elevation_m)} <small>m</small>`));

    const puls = [['Ø', w.avg_heart_rate], ['max', w.max_heart_rate], ['min', w.min_heart_rate]]
        .filter(([, v]) => woPulsOk(v)).map(([k, v]) => `${k} <strong>${fmt0(v)}</strong>`);

    const d = dialog(m.de, `
        <p class="gw-d-wann">${escHtml(new Date(w.start_at).toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }))}
            · ${escHtml(fmtHM(w.start_at))}${w.end_at ? '–' + escHtml(fmtHM(w.end_at)) : ''}</p>
        <div class="gw-d-haupt">${haupt.map(h => `<div><span class="gw-d-lbl">${h.lbl}</span>
            <span class="gw-d-wert">${escHtml(h.wert)}<small>${escHtml(h.einheit)}</small></span></div>`).join('')}</div>
        ${puls.length ? `<div class="gw-d-puls">
            <div class="gw-d-puls-kopf"><span>Puls</span><span>${puls.join(' · ')} <small>bpm</small></span></div>
            <div id="hwxPuls"><span class="skel skel-block"></span></div></div>` : '<div id="hwxPuls" hidden></div>'}
        <div class="gw-d-liste" id="hwxListe">${grund.join('')}</div>
        <div class="modal-fuss">
            <button type="button" class="v-btn v-btn--danger" data-weg>${ikon('muell', 16)} Löschen</button>
            <button type="button" class="v-btn" data-zu>Schließen</button>
        </div>`, { breit: true, beimSchliessen: () => {
            if (state.workoutHrChart) { state.workoutHrChart.destroy(); state.workoutHrChart = null; }
        } });
    beiKlick(d, '[data-zu]', () => d.close());
    beiKlick(d, '[data-weg]', async () => { if (await deleteWorkout(id)) d.close(); });
    const pulsBox = document.getElementById('hwxPuls');
    const listeBox = document.getElementById('hwxListe');
    try {
        const det = await HEALTH_API.workoutDetail(id);
        if (!listeBox.isConnected) return;
        const extras = (det.extra_metrics || []).filter(x => x.value != null && Math.abs(x.value) > 0.0001);
        listeBox.insertAdjacentHTML('beforeend', extras.map(x => {
            const l = EXTRA_LABELS[x.metric_key] || { name: x.metric_key, einheit: x.unit };
            const wert = l.ganz ? fmt0(x.value) : fmt1(x.value);
            const einheit = l.einheit || x.unit || '';
            return zeile(l.name, `${wert}${einheit ? ` <small>${escHtml(einheit)}</small>` : ''}`);
        }).join(''));
        const series = det.hr_series || [], recovery = det.hr_recovery || [];
        if ((series.length + recovery.length) >= 2) {
            pulsBox.hidden = false;
            pulsBox.innerHTML = `<div class="gw-d-flaeche"><canvas id="hwhr-${id}" aria-label="Pulsverlauf"></canvas></div>`;
            await VexCharts.bereit().catch(() => {});
            if (pulsBox.isConnected) mountWorkoutHrChart(id, w, series, recovery);
        } else {
            pulsBox.innerHTML = '';
        }
    } catch (e) {
        if (pulsBox.isConnected) pulsBox.innerHTML = '';
        if (listeBox.isConnected) listeBox.insertAdjacentHTML('beforeend',
            '<p class="h-kurve-alt">Pulsverlauf und Zusatzdaten konnten nicht geladen werden.</p>');
    }
}

/* Puls auf einer ECHTEN Zeitachse (v2.27.0): Minuten seit dem Start, als
   Uhrzeit beschriftet. Auf der alten Kategorienachse lag jeder Messpunkt
   gleich weit vom nächsten -- die Erholung nach dem Training (andere
   Abstände) sah so lang aus wie das Training selbst, und die Achse sprang
   von 18:58 auf 19:13. */
function mountWorkoutHrChart(id, w, series, recovery) {
    const canvas = document.getElementById('hwhr-' + id);
    if (!canvas || typeof Chart === 'undefined') return;
    const punkte = (reihe) => reihe.filter(r => r.avg_bpm != null && r.recorded_at)
        .map(r => ({ t: new Date(r.recorded_at).getTime(), y: Number(r.avg_bpm) }))
        .sort((a, b) => a.t - b.t);
    const im = punkte(series), nach = punkte(recovery);
    const alle = im.concat(nach);
    if (alle.length < 2) return;
    const start = w.start_at ? new Date(w.start_at).getTime() : alle[0].t;
    const xy = (p) => ({ x: (p.t - start) / 60000, y: p.y });
    const imXY = im.map(xy);
    // Anschluss ohne Lücke: die Erholung beginnt am letzten Messpunkt.
    const nachXY = (im.length && nach.length ? [im[im.length - 1]] : []).concat(nach).map(xy);
    const uhr = (min) => fmtHM(new Date(start + min * 60000).toISOString());

    const th = chartTheme();
    if (state.workoutHrChart) state.workoutHrChart.destroy();
    state.workoutHrChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: { datasets: [
            { label: 'Training', data: imXY, borderColor: cssVar('--danger'),
              backgroundColor: cssVar('--danger-soft'), fill: true, tension: 0.3,
              pointRadius: 0, borderWidth: 2 },
            { label: 'Erholung', data: nachXY, borderColor: cssVar('--warn'),
              borderDash: [4, 3], fill: false, tension: 0.3, pointRadius: 0, borderWidth: 2 },
        ] },
        options: chartDefaults({
            interaction: { mode: 'nearest', axis: 'x', intersect: false },
            plugins: {
                legend: { display: nachXY.length > 0, labels: { color: th.muted, boxWidth: 8, boxHeight: 8,
                    usePointStyle: true, pointStyle: 'circle', font: { size: 10 } } },
                tooltip: themedTooltip({ callbacks: {
                    title: (items) => items.length ? uhr(items[0].parsed.x) : '',
                    label: (ctx) => `${ctx.dataset.label}: ${fmt0(ctx.parsed.y)} bpm`,
                } }),
            },
            scales: {
                x: { type: 'linear', min: 0, max: Math.max(...alle.map(p => (p.t - start) / 60000)),
                     ticks: { color: th.muted, maxRotation: 0, font: { size: 10 }, maxTicksLimit: 6,
                              callback: (v) => uhr(v) },
                     grid: { display: false }, border: { display: false } },
                y: { ticks: { color: th.muted, font: { size: 10 }, maxTicksLimit: 4 },
                     grid: { color: th.grid }, border: { display: false }, beginAtZero: false },
            },
        }),
    });
}

// v1.28.0: einzelnes Workout loeschen
async function deleteWorkout(id) {
    const w = (state.workoutsAll || []).find(x => x.id === id);
    const label = w ? wMeta(w.workout_type).de + ' vom ' + fmtDateTime(w.start_at) : 'Workout';
    if (!await askConfirm({ title: `${label} löschen?`,
        text: 'Zusatzdaten wie Kadenz und SWOLF werden mit entfernt.',
        ok: 'Löschen', danger: true }))
        return false;
    try {
        await HEALTH_API.deleteWorkout(id);
        state.workoutsAll = state.workoutsAll.filter(x => x.id !== id);
        if (state.workoutsInit) renderWorkouts();
        loadDashWorkouts();
        showToast('Workout gelöscht');
        return true;
    } catch (e) {
        showToast('Löschen fehlgeschlagen: ' + e.message, true);
        return false;
    }
}

// ---------- Daten & Verbindung (bis v2.19.0 der Reiter „Einstellungen“) ----------
function dlgVerbindung() {
    const url = `${API_BASE}/api/health/import`;
    const d = dialog('iPhone-Verbindung', `
        <p class="h-hint">In Auto Health Export unter <strong>Automations → REST API</strong> diese
            Adresse eintragen und als Header <code>Authorization: Bearer &lt;Schlüssel&gt;</code>
            setzen.</p>
        <div class="gh-kopier">
            <input id="hImportUrl" readonly value="${escHtml(url)}" aria-label="Adresse für den Import">
            <button type="button" class="v-btn" data-kopier>Kopieren</button>
        </div>
        <h4 class="gh-dlg-h">Schlüssel</h4>
        <div id="hApiKeyList"><span class="skel skel-block"></span></div>
        <h4 class="gh-dlg-h">Neuer Schlüssel</h4>
        <div class="gh-reihe">
            <input id="hNewKeyLabel" placeholder="Bezeichnung, z. B. iPhone" aria-label="Bezeichnung des Schlüssels">
            <button type="button" class="v-btn v-btn--primary" data-neu>${ikon('plus', 16)} Erzeugen</button>
        </div>`, { breit: true });
    beiKlick(d, '[data-kopier]', () => kopieren(document.getElementById('hImportUrl'), 'Adresse kopiert'));
    beiKlick(d, '[data-neu]', createApiKey);
    document.getElementById('hNewKeyLabel').addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); createApiKey(); }
    });
    loadApiKeys();
}

function kopieren(input, text) {
    input.select();
    if (navigator.clipboard) navigator.clipboard.writeText(input.value)
        .then(() => showToast(text)).catch(() => showToast('Markiert — mit Strg+C kopieren'));
}

async function loadApiKeys() {
    const list = document.getElementById('hApiKeyList');
    if (!list) return;
    try {
        const keys = await HEALTH_API.apiKeys();
        if (!keys.length) { list.innerHTML = '<p class="h-hint">Noch kein Schlüssel. Ohne ihn kann die App nichts senden.</p>'; return; }
        list.innerHTML = `<div class="gh-zeilen">${keys.map(k => `
            <div class="gh-zeile${k.revoked_at ? ' ist-aus' : ''}">
                <div class="gh-zeile-main">
                    <div class="gh-zeile-titel">${escHtml(k.label || 'Schlüssel')}${k.revoked_at ? '<span class="gh-marke ist-warn">widerrufen</span>' : ''}</div>
                    <div class="gh-zeile-meta">Erstellt ${fmtDateTime(k.created_at)} · zuletzt genutzt ${k.last_used_at ? fmtDateTime(k.last_used_at) : 'nie'}</div>
                </div>
                ${k.revoked_at ? '' : `<div class="gh-zeile-aktion"><button type="button" class="v-btn v-btn--sm v-btn--danger" onclick="revokeApiKey(${k.id})">Widerrufen</button></div>`}
            </div>`).join('')}</div>`;
    } catch (e) {
        list.innerHTML = `<div class="empty is-error"><p class="empty-text">Die Schlüssel konnten nicht geladen werden.</p>
            <button type="button" class="v-btn v-btn--sm" onclick="loadApiKeys()">Erneut versuchen</button></div>`;
    }
}

async function createApiKey() {
    const feld = document.getElementById('hNewKeyLabel');
    const label = (feld && feld.value.trim()) || 'Auto Health Export';
    try {
        const res = await HEALTH_API.createKey(label);
        if (feld) feld.value = '';
        loadApiKeys();
        datenStand();
        // Der Schluessel steht nur jetzt da -- danach kennt ihn niemand mehr,
        // auch der Server nicht (er speichert nur den Hash).
        const d = dialog('Neuer Schlüssel', `
            <p class="h-hint">Dieser Schlüssel wird nur <strong>jetzt</strong> angezeigt. Kopiere ihn gleich in Auto Health Export.</p>
            <div class="gh-kopier">
                <input id="hKeyModalValue" readonly value="${escHtml(res.api_key)}" aria-label="Neuer Schlüssel">
                <button type="button" class="v-btn v-btn--primary" data-kopier>Kopieren</button>
            </div>`);
        beiKlick(d, '[data-kopier]', () => kopieren(document.getElementById('hKeyModalValue'), 'Schlüssel kopiert'));
    } catch (e) { showToast('Erzeugen fehlgeschlagen: ' + e.message, true); }
}

async function revokeApiKey(id) {
    if (!await askConfirm({ title: 'Schlüssel widerrufen?',
        text: 'Geräte, die diesen Schlüssel benutzen, können danach nichts mehr senden.',
        ok: 'Widerrufen', danger: true })) return;
    try {
        await HEALTH_API.revokeKey(id);
        showToast('Schlüssel widerrufen');
        loadApiKeys();
        datenStand();
    } catch (e) { showToast('Widerrufen fehlgeschlagen: ' + e.message, true); }
}

// ---------- Import-Protokoll (v1.40.0) ----------
// Die letzten Sync-Aufrufe der iPhone-App mit Ergebnis und Roh-Payload --
// Grundlage fuer den Abgleich „was hat die App geliefert“ gegen „was steht
// in der Datenbank“.
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

function dlgImportProtokoll() {
    const d = dialog('Import-Protokoll', `
        <p class="h-hint">Jeder Sync der iPhone-App steht hier mit dem, was sie geschickt hat. So
            lässt sich prüfen, ob ein auffälliger Wert schon so geliefert wurde. Gespeichert werden
            die letzten 200 Aufrufe.</p>
        <div id="hImportLog"><span class="skel skel-block"></span></div>
        <div class="modal-fuss">
            <button type="button" class="v-btn v-btn--danger" data-leeren>${ikon('muell', 16)} Protokoll leeren</button>
            <button type="button" class="v-btn" data-neu>${ikon('zurueck', 16)} Neu laden</button>
        </div>`, { breit: true, voll: true });
    beiKlick(d, '[data-neu]', loadImportLog);
    beiKlick(d, '[data-leeren]', clearImportLog);
    loadImportLog();
}

async function loadImportLog() {
    const box = document.getElementById('hImportLog');
    if (!box) return;
    try {
        const rows = await HEALTH_API.imports(50);
        if (!rows.length) {
            box.innerHTML = '<p class="h-hint">Noch kein Sync über die Schnittstelle eingegangen.</p>';
            return;
        }
        box.innerHTML = `<div class="gh-zeilen">${rows.map(r => `
            <div class="gh-zeile">
                <div class="gh-zeile-main">
                    <div class="gh-zeile-titel">${fmtDateTime(r.created_at)}
                        <span class="gh-marke">${escHtml(IMPORT_KIND_LABELS[r.kind] || r.kind || '?')}</span>
                        ${r.truncated ? '<span class="gh-marke ist-warn">gekürzt</span>' : ''}</div>
                    <div class="gh-zeile-meta">${escHtml(r.filename || 'ohne Dateiname')} · ${fmtBytes(r.size_bytes)} · ${escHtml(importStatsSummary(r.stats))}</div>
                    ${r.preview ? `<div class="gh-zeile-vorschau">${escHtml(r.preview)}</div>` : ''}
                </div>
                <div class="gh-zeile-aktion">
                    <button type="button" class="v-btn v-btn--sm v-btn--icon" onclick="downloadImportPayload(${r.id})" ${r.size_bytes ? '' : 'disabled'} aria-label="Payload herunterladen" title="Payload herunterladen">${ikon('herunter', 16)}</button>
                    <button type="button" class="v-btn v-btn--sm v-btn--icon v-btn--danger" onclick="deleteImportEntry(${r.id})" aria-label="Eintrag löschen" title="Eintrag löschen">${ikon('muell', 16)}</button>
                </div>
            </div>`).join('')}</div>`;
    } catch (e) {
        box.innerHTML = `<div class="empty is-error"><p class="empty-text">Das Protokoll konnte nicht geladen werden.</p>
            <button type="button" class="v-btn v-btn--sm" onclick="loadImportLog()">Erneut versuchen</button></div>`;
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
        a.href = url; a.download = m ? m[1] : `health-sync_${id}.txt`;
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
        showToast('Payload heruntergeladen');
    } catch (e) {
        showToast('Download fehlgeschlagen: ' + e.message, true);
    }
}

async function deleteImportEntry(id) {
    try {
        await HEALTH_API.deleteImport(id);
        loadImportLog();
        datenStand();
    } catch (e) { showToast('Löschen fehlgeschlagen: ' + e.message, true); }
}

async function clearImportLog() {
    if (!await askConfirm({ title: 'Import-Protokoll leeren?',
        text: 'Nur das Protokoll verschwindet — die importierten Gesundheitsdaten bleiben erhalten.',
        ok: 'Leeren', danger: true })) return;
    try {
        const res = await HEALTH_API.clearImports();
        showToast(`${res.deleted} Einträge gelöscht`);
        loadImportLog();
        datenStand();
    } catch (e) { showToast('Leeren fehlgeschlagen: ' + e.message, true); }
}

// ---------- Dateien importieren (Backfill) ----------
function dlgDateiImport() {
    const d = dialog('Dateien importieren', `
        <div class="gh-art">
            <button type="button" class="v-chip is-active" data-art="csv">CSV (empfohlen)</button>
            <button type="button" class="v-chip" data-art="json">JSON</button>
        </div>
        <div id="hImportCsvBox">
            <p class="h-hint">In Auto Health Export unter <strong>Export → Quick Export</strong> das Format
                <strong>CSV</strong> wählen und <strong>alle</strong> Dateien des Exports gleichzeitig hier
                ablegen. Tages-, Schlaf- und Workout-Datei werden am Kopf erkannt, alles andere übersprungen.</p>
            <div class="dropzone" id="hDropzoneCsv" tabindex="0" role="button" aria-label="CSV-Dateien auswählen">
                <input type="file" id="hImportCsvFiles" accept=".csv,text/csv" multiple hidden>
                <div class="dropzone-title">CSV-Dateien hier ablegen oder tippen</div>
                <div class="dropzone-sub" id="hDropzoneCsvSub">Mehrere auf einmal</div>
            </div>
        </div>
        <div id="hImportJsonBox" hidden>
            <p class="h-hint">Das JSON-Format enthält mehr Detail (minutengenau), ist dafür deutlich größer.</p>
            <div class="dropzone" id="hDropzoneJson" tabindex="0" role="button" aria-label="JSON-Datei auswählen">
                <input type="file" id="hImportFile" accept="application/json,.json" hidden>
                <div class="dropzone-title">JSON-Datei hier ablegen oder tippen</div>
                <div class="dropzone-sub" id="hDropzoneJsonSub">Eine Datei</div>
            </div>
        </div>
        <div class="gh-ergebnis" id="hImportErgebnis"></div>
        <div class="modal-fuss"><button type="button" class="v-btn v-btn--primary" data-los>${ikon('herunter', 16)} Importieren</button></div>`,
        { breit: true });
    setupDropzone('hDropzoneCsv', 'hImportCsvFiles', 'hDropzoneCsvSub', true);
    setupDropzone('hDropzoneJson', 'hImportFile', 'hDropzoneJsonSub', false);
    let art = 'csv';
    d.root.querySelectorAll('[data-art]').forEach(b => b.addEventListener('click', () => {
        art = b.dataset.art;
        d.root.querySelectorAll('[data-art]').forEach(x => x.classList.toggle('is-active', x === b));
        document.getElementById('hImportCsvBox').hidden = art !== 'csv';
        document.getElementById('hImportJsonBox').hidden = art !== 'json';
    }));
    beiKlick(d, '[data-los]', () => art === 'csv' ? uploadHealthCsv() : uploadHealthFile());
}

function setupDropzone(dropId, inputId, subId, multiple) {
    const zone = document.getElementById(dropId);
    const input = document.getElementById(inputId);
    const sub = document.getElementById(subId);
    zone.addEventListener('click', () => input.click());
    zone.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
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
        } catch (_e) { /* Safari: dann eben per Tipp auswaehlen */ }
        updateDropzoneLabel();
    });
    input.addEventListener('change', updateDropzoneLabel);
    function updateDropzoneLabel() {
        const files = input.files;
        if (!files || !files.length) {
            zone.classList.remove('has-files');
            sub.textContent = multiple ? 'Mehrere auf einmal' : 'Eine Datei';
            return;
        }
        zone.classList.add('has-files');
        sub.textContent = files.length === 1 ? files[0].name : `${files.length} Dateien ausgewählt`;
    }
}

function importMeldung(stats, praefix) {
    const skipped = stats.skipped || [];
    return `<div class="gh-meldung">${praefix}${fmt0(stats.metrics_imported)} Vitalwerte,
        ${fmt0(stats.bp_imported)} Blutdruck, ${fmt0(stats.glucose_imported)} Blutzucker,
        ${fmt0(stats.sleep_imported)} Nächte und ${fmt0(stats.workouts_imported)} Workouts importiert.
        ${skipped.length ? `${skipped.length} Punkte übersprungen.` : ''}</div>`;
}

async function uploadHealthCsv() {
    const input = document.getElementById('hImportCsvFiles');
    const resultEl = document.getElementById('hImportErgebnis');
    const files = input.files;
    if (!files || !files.length) { showToast('Erst CSV-Dateien auswählen', true); return; }
    resultEl.innerHTML = `<div class="gh-meldung">Importiere ${files.length} ${files.length === 1 ? 'Datei' : 'Dateien'} …</div>`;
    try {
        const stats = await HEALTH_API.importCsv(files);
        resultEl.innerHTML = importMeldung(stats, `${fmt0(stats.files_processed)} Dateien verarbeitet: `);
        showToast('Import abgeschlossen');
        input.value = ''; input.dispatchEvent(new Event('change'));
        loadDashboard();
    } catch (e) {
        resultEl.innerHTML = `<div class="gh-meldung ist-fehler">Import fehlgeschlagen: ${escHtml(e.message)}</div>`;
        showToast('Import fehlgeschlagen', true);
    }
}

async function uploadHealthFile() {
    const input = document.getElementById('hImportFile');
    const resultEl = document.getElementById('hImportErgebnis');
    const file = input.files && input.files[0];
    if (!file) { showToast('Erst eine Datei auswählen', true); return; }
    resultEl.innerHTML = '<div class="gh-meldung">Importiere …</div>';
    try {
        const stats = await HEALTH_API.importFile(file);
        resultEl.innerHTML = importMeldung(stats, '');
        showToast('Import abgeschlossen');
        input.value = ''; input.dispatchEvent(new Event('change'));
        loadDashboard();
    } catch (e) {
        resultEl.innerHTML = `<div class="gh-meldung ist-fehler">Import fehlgeschlagen: ${escHtml(e.message)}</div>`;
        showToast('Import fehlgeschlagen', true);
    }
}

// ---------- Daten loeschen (v1.28.0) ----------
const DELETE_SCOPE_LABELS = {
    all: 'alle Gesundheitsdaten',
    metrics: 'Vitalwerte',
    blood_pressure: 'Blutdruck',
    blood_glucose: 'Blutzucker',
    sleep: 'Schlaf-Nächte',
    workouts: 'Workouts',
};
function dlgDatenLoeschen() {
    const d = dialog('Daten löschen', `
        <p class="h-hint">Löscht importierte Gesundheitsdaten <strong>endgültig</strong>. Ohne Zeitraum
            für alle Zeit; wer vorher sichern will, nimmt den Gesamt-Export.</p>
        <label for="hDelScope">Bereich</label>
        <select id="hDelScope">
            <option value="all">Alles</option>
            <option value="metrics">Vitalwerte (Schritte, Puls, Gewicht, …)</option>
            <option value="blood_pressure">Blutdruck</option>
            <option value="blood_glucose">Blutzucker</option>
            <option value="sleep">Schlaf-Nächte</option>
            <option value="workouts">Workouts samt Zusatzdaten</option>
        </select>
        <div class="gh-felder">
            <div><label for="hDelFrom">Von</label><input type="date" id="hDelFrom"></div>
            <div><label for="hDelTo">Bis</label><input type="date" id="hDelTo"></div>
        </div>
        <div class="gh-ergebnis" id="hDelResult"></div>
        <div class="modal-fuss"><button type="button" class="v-btn v-btn--danger" data-los>${ikon('muell', 16)} Endgültig löschen</button></div>`);
    beiKlick(d, '[data-los]', bulkDeleteHealth);
}
async function bulkDeleteHealth() {
    const scope = document.getElementById('hDelScope').value;
    const from  = document.getElementById('hDelFrom').value || null;
    const to    = document.getElementById('hDelTo').value || null;
    const resultEl = document.getElementById('hDelResult');
    const range = (from || to) ? ` (${from || 'Anfang'} – ${to || 'heute'})` : ' für alle Zeit';
    const label = DELETE_SCOPE_LABELS[scope] || scope;
    if (!await askConfirm({ title: `${label}${range} löschen?`,
        text: 'Das lässt sich nicht rückgängig machen.',
        ok: 'Endgültig löschen', danger: true }))
        return;
    resultEl.innerHTML = '<div class="gh-meldung">Lösche …</div>';
    try {
        const res = await HEALTH_API.bulkDelete({ scope, from_date: from, to_date: to });
        const dd = res.deleted || {};
        const parts = Object.keys(dd).filter(k => dd[k] > 0).map(k =>
            `${DELETE_SCOPE_LABELS[k] || k}: ${fmt0(dd[k])}`);
        resultEl.innerHTML = `<div class="gh-meldung"><strong>${fmt0(res.total)}</strong> Einträge gelöscht${parts.length ? ' — ' + parts.join(', ') : ''}.</div>`;
        showToast(res.total > 0 ? `${fmt0(res.total)} Einträge gelöscht` : 'Keine passenden Einträge');
        // Alles neu laden: jede Ansicht kann betroffen sein.
        state.workoutsAll = null; state.workoutsInit = false;
        state.sleepInit = false; state.vitalInit = false;
        loadDashboard();
    } catch (e) {
        resultEl.innerHTML = `<div class="gh-meldung ist-fehler">Löschen fehlgeschlagen: ${escHtml(e.message)}</div>`;
        showToast('Löschen fehlgeschlagen', true);
    }
}

// ---------- Start ----------
(async function () {
    if (!isLoggedIn()) { window.location.href = '/private/login.html'; return; }
    document.body.classList.add('ready');
    document.getElementById('logoutBtn').addEventListener('click',
        () => { clearToken(); location.href = '/private/login.html'; });
    document.querySelectorAll('.tabs .tab-btn').forEach(b =>
        b.addEventListener('click', () => activateTab(b.dataset.tab)));
    // Ein Serverfehler ist keine Abmeldung (CLAUDE.md): ohne Namen in der
    // Leiste geht es weiter, und jede Karte meldet ihren eigenen Fehler.
    try {
        const me = await fetchMe(true);
        document.getElementById('userLabel').textContent = me.username;
    } catch (e) { /* Name bleibt leer */ }
    // Steht ein Reiter in der Adresse, wird er geoeffnet -- samt Nachladung.
    activateTab((location.hash || '').replace('#', '') || H_TABS[0]);
    loadDashboard();
})();
