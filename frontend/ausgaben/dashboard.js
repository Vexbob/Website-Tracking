let stores=[], categories=[];
/* v2.11.5: Der Zeitraum kommt aus VexRange -- wie auf jeder anderen
   Modulseite. Vorher standen hier ZWEI Antworten auf dieselbe Frage
   uebereinander: eine eigene Chipreihe (Woche/Monat/Quartal/Jahr) und
   zusaetzlich Von/Bis im Filter-Popover. Welche gerade galt, sah man keiner
   von beiden an, und markiert war ohnehin nie eine. */
let zeitraum = null;
/* Ein Zeitraum filtert nur, wenn er nicht „Gesamt“ ist. „Gesamt“ schickt
   ein Enddatum (heute) mit -- bis v2.20.0 zählte das als Filter, und über
   der ungefilterten Liste stand „247 Bons gefiltert“. */
function zeitraumAktiv() { return !!(zeitraum && zeitraum.preset && zeitraum.preset !== 'all'); }

async function loadInit() {
    // Leiste und Platzhalter stehen schon -- gezeichnet von zwei Zeilen im
    // HTML direkt an ihrer Stelle (siehe index.html).
    const me = await ensureLoggedIn(); if (!me) return;
    try {
        [stores, categories] = await Promise.all([AUSGABEN_API.stores(), AUSGABEN_API.categories()]);
    } catch(e) { showToast('Laden fehlgeschlagen: ' + e.message, 'error'); return; }
    await loadExpenseTypes();
    populateFilters();
    zeitraumAufbauen();
    setupFilterPopover();
    setupQuickNew();
    await Promise.all([loadKpis(), loadExpenses(), loadRecurring()]);
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';
}

function populateFilters() {
    // Typ-Filter: eingebaute + eigene Typen, wie sie der Server kennt.
    const t = document.getElementById('filterType');
    if (t) t.innerHTML = '<option value="">Alle Typen</option>' + expenseTypeOptions('');
    const s = document.getElementById('filterStore');
    stores.forEach(x => s.insertAdjacentHTML('beforeend', `<option value="${x.id}">${x.icon || ''} ${x.name}</option>`));
    const c = document.getElementById('filterCategory');
    categories.forEach(x => c.insertAdjacentHTML('beforeend', `<option value="${x.id}">${x.icon || ''} ${x.name}</option>`));
}

/* Eine Hauptzahl, der Rest ordnet sich unter. Der laufende Monat ist die
 * Zahl, wegen der man diese Seite aufmacht; alles andere ist Einordnung. */
async function loadKpis() {
    const box = document.getElementById('kpiGrid');
    try {
        zeichneKpis(await AUSGABEN_API.statsSummary());
    } catch(e) {
        box.innerHTML = `<div class="empty is-error"><p class="empty-text">Die Kennzahlen konnten nicht geladen werden.</p>
            <button type="button" class="v-btn v-btn--sm" onclick="loadKpis()">Erneut versuchen</button></div>`;
        console.error(e);
        return;
    }
    monatsverlauf();
}

/* Der Monat gegen den Vormonat, Tag für Tag aufsummiert. Die Zahl neben der
   Heldenzahl vergleicht bis zum SELBEN Tag -- am 5. gegen die ersten fünf
   Tage des Vormonats, nicht gegen seine ganze Summe. */
let monatsKurve = null;
async function monatsverlauf() {
    const heute = new Date();
    const tagHeute = heute.getDate();
    const start = new Date(heute.getFullYear(), heute.getMonth() - 1, 1);
    let rows;
    try {
        rows = await AUSGABEN_API.statsDaily({ from: isoDate(start), to: isoDate(heute) });
    } catch (e) { console.warn(e); return; }
    const monatStart = new Date(heute.getFullYear(), heute.getMonth(), 1);
    const vormonatTage = new Date(heute.getFullYear(), heute.getMonth(), 0).getDate();
    const dies = new Array(tagHeute).fill(0), vor = new Array(vormonatTage).fill(0);
    (rows || []).forEach(r => {
        const d = new Date(String(r.date).slice(0, 10) + 'T12:00:00');
        const betrag = Number(r.total) || 0;
        if (d >= monatStart) { if (d.getDate() <= tagHeute) dies[d.getDate() - 1] += betrag; }
        else if (d >= start) vor[d.getDate() - 1] += betrag;
    });
    const kum = (a) => { let s = 0; return a.map(v => (s += v)); };
    const diesK = kum(dies), vorK = kum(vor);
    const bisHeute = vorK[Math.min(tagHeute, vormonatTage) - 1] || 0;
    const jetzt = diesK[tagHeute - 1] || 0;
    const box = document.getElementById('azVergleich');
    if (box && bisHeute > 0) {
        const pct = Math.round((jetzt / bisHeute - 1) * 100);
        const cls = Math.abs(pct) < 5 ? '' : (pct > 0 ? ' ist-mehr' : ' ist-weniger');
        box.innerHTML = `<span class="az-delta${cls}">${pct > 0 ? '+' : pct < 0 ? '−' : '±'}${Math.abs(pct)} %</span>`
            + `<span>zum Vormonat bis zum ${tagHeute}. (${fmtEur(bisHeute)})</span>`;
    }
    const monatName = (d) => d.toLocaleDateString('de-DE', { month: 'short' });
    const leg = document.getElementById('azLegende');
    if (leg) leg.innerHTML = `<span><i style="--ton:var(--az-ton)"></i>${monatName(heute)}</span>`
        + `<span><i class="ist-gestrichelt" style="--ton:var(--text-3)"></i>${monatName(start)}</span>`;
    const tage = Math.max(vormonatTage, new Date(heute.getFullYear(), heute.getMonth() + 1, 0).getDate());
    const labels = Array.from({ length: tage }, (_, i) => String(i + 1));
    const reihe = (k, n) => labels.map((_, i) => i < n ? k[i] : null);
    const zeichnen = () => {
        const cv = document.getElementById('azKurve');
        if (!cv || typeof Chart === 'undefined') return;
        const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
        const ton = css('--figure') || css('--m-ausgaben');
        const schmal = window.matchMedia('(max-width: 899px)').matches;
        if (monatsKurve) monatsKurve.destroy();
        monatsKurve = new Chart(cv.getContext('2d'), {
            type: 'line',
            data: { labels, datasets: [
                { label: monatName(heute), data: reihe(diesK, tagHeute), borderColor: ton,
                  backgroundColor: tonMitAlpha(ton, 0.16), fill: true, tension: 0.25,
                  pointRadius: 0, pointHoverRadius: 4, borderWidth: 2 },
                { label: monatName(start), data: reihe(vorK, vormonatTage), borderColor: css('--text-3'),
                  borderDash: [5, 4], fill: false, tension: 0.25, pointRadius: 0, pointHoverRadius: 3, borderWidth: 1.5 },
            ] },
            options: { responsive: true, maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: { legend: { display: false }, tooltip: { callbacks: {
                    title: (it) => it.length ? it[0].label + '. des Monats' : '',
                    label: (c) => ` ${c.dataset.label}: ${fmtEur(c.parsed.y)}` } } },
                scales: {
                    x: { ticks: { color: css('--chart-axis'), font: { size: 10 }, maxRotation: 0, autoSkip: true, maxTicksLimit: schmal ? 6 : 10 },
                         grid: { display: false }, border: { display: false } },
                    y: { display: !schmal, beginAtZero: true, ticks: { color: css('--chart-axis'), font: { size: 10 }, maxTicksLimit: 4,
                         callback: (v) => fmtEur(v).replace(/,00\s/, ' ') }, grid: { color: css('--chart-grid') }, border: { display: false } },
                },
            },
        });
    };
    // Chart.js kommt mit defer vom CDN und kann später da sein als die
    // Antwort (derselbe Fehler, der den Sparverlauf leer liess).
    if (typeof Chart !== 'undefined') zeichnen();
    else if (document.readyState !== 'complete') window.addEventListener('load', zeichnen, { once: true });
}

// Eine Tokenfarbe mit Deckkraft -- Chart.js kennt kein color-mix().
function tonMitAlpha(farbe, a) {
    const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(farbe || '').trim());
    if (!m) return farbe;
    let h = m[1];
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
}

// Cache pro Bon-ID: { detail: fullExpense, imgUrl: blobUrl|null }
const expDetailCache = new Map();

let searchDebounceTimer = null;

async function loadExpenses() {
    const params = {
        expense_type: document.getElementById('filterType').value || undefined,
        store_id:    document.getElementById('filterStore').value || undefined,
        category_id: document.getElementById('filterCategory').value || undefined,
        from:        (zeitraum && zeitraum.from) || undefined,
        to:          (zeitraum && zeitraum.to) || undefined,
        q:           (document.getElementById('filterQ')?.value || '').trim() || undefined,
        limit: 200,
    };
    const list = document.getElementById('expList');
    // Beim Nachladen bleibt die alte Liste stehen und wird nur gedimmt --
    // ein Platzhalter an ihrer Stelle liess alles darunter springen.
    list.classList.add('is-loading');
    const sub = document.getElementById('azListeSub');
    const hasFilterParam = !!(params.q || params.expense_type || params.store_id || params.category_id || zeitraumAktiv());
    try {
        const rows = await AUSGABEN_API.expenses(params);
        list.classList.remove('is-loading');
        if (sub) sub.textContent = hasFilterParam ? 'gefiltert' : 'die letzten 14 Tage';
        if (!rows.length) {
            list.innerHTML = hasFilterParam
                ? '<div class="empty"><p class="empty-text">Kein Bon passt zu diesem Filter.</p><button type="button" class="v-btn v-btn--sm" onclick="document.getElementById(\'filterReset\').click()">Filter zurücksetzen</button></div>'
                : `<div class="empty"><span class="empty-mark">${ikon('kamera', 26)}</span><p class="empty-text">Noch kein Bon. Mit der Kamera oben ist der erste in einer halben Minute drin.</p></div>`;
            renderFilterTotal(rows, params);
            return;
        }
        // Total-Row (nur wenn Filter aktiv)
        renderFilterTotal(rows, params);

        // Gruppierung nach Datum (rows sind bereits DESC sortiert vom Backend)
        const groups = [];
        let cur = null;
        for (const r of rows) {
            const d = r.purchase_date;
            if (!cur || cur.date !== d) {
                cur = { date: d, items: [], total: 0 };
                groups.push(cur);
            }
            cur.items.push(r);
            cur.total += Number(r.total_amount) || 0;
        }

        const hasFilter = !!(params.q || params.expense_type || params.store_id || params.category_id || zeitraumAktiv());
        const cutoff = new Date(); cutoff.setHours(0, 0, 0, 0); cutoff.setDate(cutoff.getDate() - 13);
        const cutoffIso = isoDate(cutoff);
        const recent = hasFilter ? groups : groups.filter(g => g.date >= cutoffIso);
        const older = hasFilter ? [] : groups.filter(g => g.date < cutoffIso);

        const renderGroups = (gs) => gs.map(g => renderDateHeader(g)
            + '<div class="rec-list">' + g.items.map(r => renderExpItem(r)).join('') + '</div>').join('');
        list.innerHTML = recent.length ? renderGroups(recent)
            : (older.length ? '<div class="empty"><p class="empty-text">In den letzten 14 Tagen kam kein Bon dazu.</p></div>' : '');
        if (older.length) {
            const oldCount = older.reduce((n, g) => n + g.items.length, 0);
            list.insertAdjacentHTML('beforeend', `<button type="button" id="expShowAllBtn" class="v-btn v-btn--ghost az-mehr">Ältere zeigen (${oldCount})</button>`);
            document.getElementById('expShowAllBtn').onclick = () => {
                list.innerHTML = renderGroups(groups);
                if (sub) sub.textContent = 'alle geladenen';
            };
        }
    } catch(e) {
        list.classList.remove('is-loading');
        list.innerHTML = `<div class="empty is-error"><p class="empty-text">Die Bons konnten nicht geladen werden: ${escapeHtml(e.message)}</p>
            <button type="button" class="v-btn v-btn--sm" onclick="loadExpenses()">Erneut versuchen</button></div>`;
    }
}

/* v2.11.8: Die Zeile rechnete ueber `rows` -- und `rows` endet bei 200.
   Wer nach „Rewe, dieses Jahr“ filtert und mehr als 200 Bons hat, bekam eine
   zu kleine Summe und eine zu kleine Anzahl praesentiert, ohne Hinweis. Die
   Zahl kommt jetzt aus derselben Filterfunktion wie die Liste, nur ohne
   Obergrenze. Bleibt sie aus, steht dort lieber nichts als etwas Falsches. */
let summenLauf = 0;
async function renderFilterTotal(rows, params) {
    const el = document.getElementById('filterTotal');
    if (!el) return;
    const hasFilter = params.q || params.expense_type || params.store_id || params.category_id || zeitraumAktiv();
    if (!hasFilter || !rows.length) { el.innerHTML = ''; return; }
    const lauf = ++summenLauf;
    let zahl;
    try {
        zahl = await AUSGABEN_API.expensesGefiltert(params);
    } catch (e) {
        if (lauf === summenLauf) el.innerHTML = '';
        return;
    }
    // Waehrend wir gefragt haben, hat der Nutzer weitergefiltert.
    if (lauf !== summenLauf) return;
    const n = Number(zahl && zahl.count) || 0;
    if (!n) { el.innerHTML = ''; return; }
    // Die Liste zeigt hoechstens 200 Zeilen. Wenn der Filter mehr trifft,
    // gehoert das dazugesagt -- sonst widersprechen sich Zahl und Liste.
    const hinweis = n > rows.length
        ? `<small class="filter-total-hint">Liste zeigt die neuesten ${rows.length}</small>` : '';
    el.innerHTML = `<div class="filter-total">
        <span>${n} Bon${n === 1 ? '' : 's'} gefiltert${hinweis}</span>
        <strong>${fmtEur(Number(zahl.total) || 0)}</strong>
    </div>`;
}

function ikon(name, groesse) { return window.VexIkon ? VexIkon.svg(name, groesse || 18) : ''; }

// Tageskopf: „Heute“ / „Gestern“ / „Montag, 22.9.“ und die Summe des Tages
function renderDateHeader(g) {
    const iso = g.date;
    const d = new Date(iso + 'T00:00:00');
    const today = new Date(); today.setHours(0,0,0,0);
    const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
    const isSameDay = (a, b) => a.getFullYear()===b.getFullYear() && a.getMonth()===b.getMonth() && a.getDate()===b.getDate();
    let label;
    if (isSameDay(d, today)) label = 'Heute';
    else if (isSameDay(d, yesterday)) label = 'Gestern';
    else label = d.toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long' });
    return `<div class="az-tag-kopf"><strong>${label}</strong>
        <span>${g.items.length} Bon${g.items.length===1?'':'s'} · ${fmtEur(g.total)}</span></div>`;
}

/* Eine Zeile je Bon. Die Ladenfarbe ist Nutzerdatum und erscheint nur als
   Tönung der Marke (DESIGN 3) -- bis v2.20.0 war sie die Vollfläche hinter
   weißer Schrift. Die Zeile öffnet den Kassenzettel als Blatt. */
function renderExpItem(r) {
    const initial = (r.store_name || '€').slice(0,1).toUpperCase();
    const typeLabel = expenseTypeLabel(r.expense_type);
    const ton = r.store_color ? ` style="--tone:${escapeHtml(r.store_color)}"` : '';
    const meta = [];
    if (r.expense_type && r.expense_type !== 'receipt') meta.push(escapeHtml(typeLabel));
    meta.push(`${r.item_count||0} Position${r.item_count===1?'':'en'}`);
    if (r.is_recurring) meta.push('wiederkehrend');
    return `<button type="button" class="rec-row" data-id="${r.id}" onclick="dlgBon(${r.id})">
        <span class="rec-mark"${ton}>${escapeHtml(r.store_icon || initial)}</span>
        <span class="rec-main">
            <span class="rec-title"><span>${escapeHtml(r.store_name || typeLabel)}</span>${r.has_image ? ikon('kamera', 14) : ''}</span>
            <span class="rec-meta">${meta.join('<span class="sep">·</span>')}</span>
        </span>
        <span class="rec-side"><span class="rec-val">${fmtEur(r.total_amount)}</span></span>
        <span class="rec-go">${ikon('pfeil', 16)}</span>
    </button>`;
}

/* Der Kassenzettel als Blatt: dieselbe Gestalt wie auf bon.html
   (kassenzettelHTML in ausgaben.js). Bis v2.20.0 klappte die Zeile auf, mit
   einem türkisen „✏️ Bearbeiten“ in weißer Schrift darunter. */
async function dlgBon(id) {
    const d = openModal('Bon', '<div id="azBonBlatt"><span class="skel skel-block"></span></div>'
        + `<div class="modal-fuss"><a class="v-btn" href="/ausgaben/bon.html?id=${id}">${ikon('stift', 16)} Bearbeiten</a></div>`);
    const box = document.getElementById('azBonBlatt');
    try {
        let cache = expDetailCache.get(id);
        if (!cache) {
            const detail = await AUSGABEN_API.getExpense(id);
            let imgUrl = null;
            if (detail.receipt_image_id) {
                try { imgUrl = await fetchImageAsBlobUrl(AUSGABEN_API.receiptThumbUrl(detail.receipt_image_id)); } catch (_) {}
            }
            cache = { detail, imgUrl };
            expDetailCache.set(id, cache);
        }
        if (!box.isConnected) return;
        const kopf = d.el.querySelector('.modal-head h3');
        if (kopf) kopf.textContent = cache.detail.store_name || expenseTypeLabel(cache.detail.expense_type);
        box.innerHTML = kassenzettelHTML(cache.detail, cache.imgUrl);
        // Die Vollansicht braucht das ganze Bild; die Adresse verlangt eine
        // Anmeldung, also als Blob holen -- im Zweifel reicht das Vorschaubild.
        const foto = box.querySelector('[data-vollbild]');
        if (foto) foto.onclick = async () => {
            let url = cache.imgUrl;
            try { url = await fetchImageAsBlobUrl(AUSGABEN_API.receiptImageUrl(cache.detail.receipt_image_id)); } catch (_) {}
            openImageFullscreen(url);
        };
    } catch (e) {
        if (box.isConnected) box.innerHTML = `<div class="empty is-error"><p class="empty-text">Der Bon konnte nicht geladen werden: ${escapeHtml(e.message)}</p></div>`;
    }
}

async function loadRecurring() {
    try {
        const rows = await AUSGABEN_API.recurring();
        if (!rows.length) return;
        document.getElementById('recurringCard').hidden = false;
        document.getElementById('recurringList').innerHTML = '<div class="rec-list az-wiederkehr">' + rows.map(r =>
            `<div class="rec-row">
                <span class="rec-mark">${ikon('wiederkehr', 16)}</span>
                <span class="rec-main"><span class="rec-title">${escapeHtml(r.store_name)}</span>
                    <span class="rec-meta">${r.months} Monate in Folge<span class="sep">·</span>zuletzt ${fmtDate(r.last_date)}</span></span>
                <span class="rec-side"><span class="rec-val">~${fmtEur(r.avg_amount)}</span></span>
            </div>`).join('') + '</div>';
    } catch(e) { console.warn(e); }
}

function escapeHtml(s) {
    if (!s) return '';
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// Live-Reload bei Filter-Änderung
['filterType','filterStore','filterCategory'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.onchange = () => {
        if (typeof updateFilterBadge === 'function') updateFilterBadge();
        if (typeof renderActiveFilterChips === 'function') renderActiveFilterChips();
        loadExpenses();
    };
});
// Suche mit Debounce (500ms)
const searchEl = document.getElementById('filterQ');
if (searchEl) searchEl.oninput = () => {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(loadExpenses, 500);
};
document.getElementById('filterReset').onclick = () => {
    ['filterType','filterStore','filterCategory','filterQ'].forEach(id => {
        const el = document.getElementById(id); if (el) el.value = '';
    });
    // Der Zeitraum gehoert dazu: "Zuruecksetzen" heisst alles, nicht alles
    // ausser dem einen Filter, der oben steht.
    if (zeitraumFilter) zeitraumFilter.set('all'); else loadExpenses();
    if (typeof updateFilterBadge === 'function') updateFilterBadge();
    if (typeof renderActiveFilterChips === 'function') renderActiveFilterChips();
};

function pad(n) { return String(n).padStart(2, '0'); }
function isoDate(d) { return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`; }

/* Der Zeitraum: ein Knopf, der benennt, was gerade gilt. Er wird erst nach
   dem Laden gesetzt -- `mount` loest `onChange` sofort aus, und die erste
   Liste soll nicht zweimal geholt werden. */
let zeitraumFilter = null;
function zeitraumAufbauen() {
    const host = document.getElementById('expRange');
    if (!host || !window.VexRange) return;
    let erster = true;
    zeitraumFilter = VexRange.mount(host, {
        preset: 'all',
        onChange: (r) => {
            zeitraum = r;
            if (typeof updateFilterBadge === 'function') updateFilterBadge();
            if (typeof renderActiveFilterChips === 'function') renderActiveFilterChips();
            if (erster) { erster = false; return; }
            loadExpenses();
        },
    });
}


loadInit();

/* v1.38.0 — Filter-Popover: Toggle, Klick-Outside, ESC, Badge, aktive Chips */
function setupFilterPopover() {
    const btn = document.getElementById('filterToggle');
    const pop = document.getElementById('filterPopover');
    const apply = document.getElementById('filterApply');
    if (!btn || !pop) return;
    const outside = (e) => { if (!pop.contains(e.target) && !btn.contains(e.target)) close(); };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    const open = () => {
        pop.hidden = false;
        btn.setAttribute('aria-expanded', 'true');
        setTimeout(() => document.addEventListener('click', outside), 0);
        document.addEventListener('keydown', onKey);
    };
    const close = () => {
        pop.hidden = true;
        btn.setAttribute('aria-expanded', 'false');
        document.removeEventListener('click', outside);
        document.removeEventListener('keydown', onKey);
    };
    btn.addEventListener('click', () => { pop.hidden ? open() : close(); });
    if (apply) apply.addEventListener('click', close);
    updateFilterBadge();
    renderActiveFilterChips();
}

function activeFilterCount() {
    // Der Zeitraum zaehlt hier NICHT mit: er steht als eigener Knopf daneben
    // und benennt sich selbst. Ihn zusaetzlich als Zahl am Filter zu fuehren
    // waere die zweite Auskunft ueber dieselbe Einstellung.
    const ids = ['filterType','filterStore','filterCategory'];
    return ids.reduce((n, id) => n + ((document.getElementById(id)?.value || '') ? 1 : 0), 0);
}

function updateFilterBadge() {
    const badge = document.getElementById('filterBadge');
    const btn = document.getElementById('filterToggle');
    if (!badge || !btn) return;
    const n = activeFilterCount();
    if (n > 0) { badge.textContent = String(n); badge.hidden = false; btn.classList.add('has-active'); }
    else { badge.hidden = true; btn.classList.remove('has-active'); }
}

function renderActiveFilterChips() {
    const box = document.getElementById('activeFilterChips');
    if (!box) return;
    const chips = [];
    const push = (id, label, valueLabel) => {
        chips.push('<span class="aff-chip">' + escapeHtml(label) + ': <strong>' + escapeHtml(valueLabel) + '</strong>' +
            '<button type="button" data-clear="' + id + '" aria-label="' + escapeHtml(label) + ' entfernen">' + ikon('plus', 14).replace('<svg ', '<svg style="transform:rotate(45deg)" ') + '</button></span>');
    };
    const typeEl = document.getElementById('filterType');
    if (typeEl && typeEl.value) push('filterType', 'Typ', typeEl.options[typeEl.selectedIndex].text);
    const storeEl = document.getElementById('filterStore');
    if (storeEl && storeEl.value) push('filterStore', 'Laden', storeEl.options[storeEl.selectedIndex].text);
    const catEl = document.getElementById('filterCategory');
    if (catEl && catEl.value) push('filterCategory', 'Kategorie', catEl.options[catEl.selectedIndex].text);
    box.innerHTML = chips.join('');
    box.querySelectorAll('button[data-clear]').forEach(b => {
        b.onclick = () => {
            const el = document.getElementById(b.dataset.clear);
            if (el) el.value = '';
            updateFilterBadge();
            renderActiveFilterChips();
            loadExpenses();
        };
    });
}

/* v1.38.2 — Neuer Bon direkt im Dashboard: Kamera / Galerie / Einfuegen / Drop / Strg+V.
 * Der Datei-Empfang lauft rein clientseitig; die Bild-Datei wird als DataURL
 * ueber sessionStorage an /ausgaben/neu.html?src=dash weitergereicht. Vorteile:
 * keine iframe-/postMessage-Bruecke, gleiche Origin, kein doppelter Upload,
 * und der komplette OCR-/Edit-Flow auf neu.html bleibt unveraendert. */
const DASH_HANDOFF_KEY = 'vexbob:new-bon-file';

function setupQuickNew() {
    const btnCam = document.getElementById('nqCamera');
    const btnGal = document.getElementById('nqGallery');
    const btnPaste = document.getElementById('nqPaste');
    const fileCam = document.getElementById('nqFileCam');
    const fileGal = document.getElementById('nqFileGal');
    if (!btnCam || !btnGal || !btnPaste || !fileCam || !fileGal) return;

    btnCam.onclick = () => fileCam.click();
    btnGal.onclick = () => fileGal.click();
    btnPaste.onclick = () => quickPasteFromClipboard();

    fileCam.onchange = () => { if (fileCam.files.length) handoffToNeu(fileCam.files[0]); fileCam.value = ''; };
    fileGal.onchange = () => { if (fileGal.files.length) handoffToNeu(fileGal.files[0]); fileGal.value = ''; };

    // Ganzseitiger Drag & Drop mit temporaerem Overlay (nur wenn wirklich
    // gezogen wird — keine dauerhafte "durchsuchen"-Kiste im UI).
    setupPageDragDrop();

    // Globaler Strg+V-Listener fuer die Dashboard-Seite (nicht in Inputs)
    window.addEventListener('paste', (e) => {
        const tag = (document.activeElement?.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea') return;
        const items = e.clipboardData?.items;
        if (!items) return;
        for (const it of items) {
            if (it.kind === 'file' && it.type.startsWith('image/')) {
                const blob = it.getAsFile();
                if (blob) {
                    e.preventDefault();
                    const ext = (blob.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
                    handoffToNeu(new File([blob], `clipboard-${Date.now()}.${ext}`, { type: blob.type }));
                    return;
                }
            }
        }
    });
}

async function quickPasteFromClipboard() {
    if (!navigator.clipboard || !navigator.clipboard.read) {
        showToast('Clipboard-API nicht verfügbar — nutze Strg+V', 'error', 2500);
        return;
    }
    try {
        const items = await navigator.clipboard.read();
        for (const item of items) {
            for (const type of item.types) {
                if (type.startsWith('image/')) {
                    const blob = await item.getType(type);
                    const ext = (type.split('/')[1] || 'png').replace('jpeg', 'jpg');
                    handoffToNeu(new File([blob], `clipboard-${Date.now()}.${ext}`, { type: blob.type }));
                    return;
                }
            }
        }
        showToast('Kein Bild in der Zwischenablage', 'error', 2500);
    } catch (e) {
        if (e.name === 'NotAllowedError') showToast('Erlaubnis für Zwischenablage abgelehnt', 'error', 2500);
        else showToast('Einfügen fehlgeschlagen: ' + (e.message || e), 'error', 2500);
    }
}

async function handoffToNeu(file) {
    if (!file || !file.type || !file.type.startsWith('image/')) {
        showToast('Nur Bilddateien erlaubt', 'error');
        return;
    }
    if (file.size > 8 * 1024 * 1024) {
        showToast('Bild zu groß (max 8 MB)', 'error');
        return;
    }
    try {
        const dataUrl = await new Promise((resolve, reject) => {
            const fr = new FileReader();
            fr.onload = () => resolve(fr.result);
            fr.onerror = () => reject(new Error('Datei konnte nicht gelesen werden'));
            fr.readAsDataURL(file);
        });
        try {
            sessionStorage.setItem(DASH_HANDOFF_KEY, JSON.stringify({
                name: file.name || ('bon-' + Date.now() + '.jpg'),
                type: file.type,
                dataUrl,
            }));
        } catch (e) {
            showToast('Bild zu groß für die Übergabe — nutze die Vollansicht', 'error');
            location.href = '/ausgaben/neu.html';
            return;
        }
        location.href = '/ausgaben/neu.html?src=dash';
    } catch (e) {
        showToast('Fehler: ' + (e.message || e), 'error');
    }
}

/* v1.38.3 — Ganzseiten-Drag&Drop mit temporaerem Overlay */
function setupPageDragDrop() {
    if (window.__vexbobPageDnD) return;
    window.__vexbobPageDnD = true;
    let overlay = null;
    let depth = 0;
    const ensureOverlay = () => {
        if (overlay) return overlay;
        overlay = document.createElement('div');
        overlay.className = 'nq-drag-overlay';
        overlay.textContent = 'Bild hier fallen lassen';
        document.body.appendChild(overlay);
        return overlay;
    };
    const hasFiles = (e) => {
        const t = e.dataTransfer && e.dataTransfer.types;
        if (!t) return false;
        for (let i = 0; i < t.length; i++) if (t[i] === 'Files') return true;
        return false;
    };
    window.addEventListener('dragenter', (e) => {
        if (!hasFiles(e)) return;
        e.preventDefault(); depth++;
        ensureOverlay().classList.add('show');
    });
    window.addEventListener('dragover', (e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
    });
    window.addEventListener('dragleave', (e) => {
        if (!hasFiles(e)) return;
        depth = Math.max(0, depth - 1);
        if (depth === 0 && overlay) overlay.classList.remove('show');
    });
    window.addEventListener('drop', (e) => {
        if (!hasFiles(e)) return;
        e.preventDefault(); depth = 0;
        if (overlay) overlay.classList.remove('show');
        const f = e.dataTransfer.files && e.dataTransfer.files[0];
        if (f) handoffToNeu(f);
    });
}

