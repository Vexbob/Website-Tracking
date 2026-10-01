/* Gemeinsame Helper für das Ausgaben-Modul. */

const AUSGABEN_API = {
    stores:      () => apiCall('/api/stores'),
    createStore: (b) => apiCall('/api/stores', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    updateStore: (id, b) => apiCall(`/api/stores/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    deleteStore: (id) => apiCall(`/api/stores/${id}`, { method: 'DELETE' }),
    storeMergeSuggestions: () => apiCall('/api/stores/merge-suggestions'),
    mergeStores: (b) => apiCall('/api/stores/merge', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    dismissStoreMerge: (b) => apiCall('/api/stores/merge-dismiss', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),

    expenseTypes:    () => apiCall('/api/expense-types'),

    categories:      () => apiCall('/api/expense-categories'),
    createCategory:  (b) => apiCall('/api/expense-categories', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    updateCategory:  (id, b) => apiCall(`/api/expense-categories/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    deleteCategory:  (id) => apiCall(`/api/expense-categories/${id}`, { method: 'DELETE' }),

    brands:      (sort) => apiCall('/api/brands' + (sort ? ('?sort=' + sort) : '')),
    createBrand: (b) => apiCall('/api/brands', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    updateBrand: (id, b) => apiCall(`/api/brands/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    deleteBrand: (id) => apiCall(`/api/brands/${id}`, { method: 'DELETE' }),

    rules:      () => apiCall('/api/category-rules'),
    createRule: (b) => apiCall('/api/category-rules', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    deleteRule: (id) => apiCall(`/api/category-rules/${id}`, { method: 'DELETE' }),
    suggestRule: (b) => apiCall('/api/category-rules/suggest', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),

    expenses: (params={}) => {
        const qs = new URLSearchParams();
        Object.entries(params).forEach(([k,v]) => { if (v !== null && v !== undefined && v !== '') qs.append(k, v); });
        const q = qs.toString();
        return apiCall('/api/expenses' + (q ? '?' + q : ''));
    },
    // Anzahl und Summe ueber ALLE Bons des Filters -- ohne die Obergrenze,
    // mit der `expenses` die Liste kurz haelt.
    expensesGefiltert: (params={}) => {
        const qs = new URLSearchParams();
        Object.entries(params).forEach(([k,v]) => {
            if (k === 'limit') return;
            if (v !== null && v !== undefined && v !== '') qs.append(k, v);
        });
        const q = qs.toString();
        return apiCall('/api/expenses/stats/filtered' + (q ? '?' + q : ''));
    },
    getExpense:    (id) => apiCall(`/api/expenses/${id}`),
    createExpense: (b) => apiCall('/api/expenses', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    updateExpense: (id, b) => apiCall(`/api/expenses/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    deleteExpense: (id) => apiCall(`/api/expenses/${id}`, { method: 'DELETE' }),
    addItem:       (eid, b) => apiCall(`/api/expenses/${eid}/items`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    updateItem:    (id, b) => apiCall(`/api/expense-items/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    deleteItem:    (id) => apiCall(`/api/expense-items/${id}`, { method: 'DELETE' }),

    uploadReceipt: (file, runOcr=true) => {
        const fd = new FormData();
        fd.append('file', file);
        fd.append('run_ocr', runOcr ? 'true' : 'false');
        return apiCall('/api/receipts/upload', { method: 'POST', body: fd });
    },
    listReceipts:  () => apiCall('/api/receipts'),
    deleteReceipt: (id) => apiCall(`/api/receipts/${id}`, { method: 'DELETE' }),
    receiptImageUrl: (id) => `${API_BASE}/api/receipts/${id}/image`,
    receiptThumbUrl: (id) => `${API_BASE}/api/receipts/${id}/thumb`,
    ocrStatus: () => apiCall('/api/expenses/ocr/status'),

    statsSummary:    () => apiCall('/api/expenses/stats/summary'),
    statsCategory:   (p={}) => { const q = new URLSearchParams(p).toString(); return apiCall('/api/expenses/stats/by-category' + (q ? '?' + q : '')); },
    statsStore:      (p={}) => { const q = new URLSearchParams(p).toString(); return apiCall('/api/expenses/stats/by-store' + (q ? '?' + q : '')); },
    statsMonthly:    (p={}) => { const q = new URLSearchParams(typeof p==='object'?p:{months:p}).toString(); return apiCall('/api/expenses/stats/monthly' + (q ? '?' + q : '')); },
    statsWeekly:     (p={}) => { const q = new URLSearchParams(typeof p==='object'?p:{weeks:p}).toString(); return apiCall('/api/expenses/stats/weekly' + (q ? '?' + q : '')); },
    statsDaily:      (p={}) => { const q = new URLSearchParams(typeof p==='object'?p:{days:p}).toString(); return apiCall('/api/expenses/stats/daily' + (q ? '?' + q : '')); },
    statsInsights:   (p={}) => { const q = new URLSearchParams(p).toString(); return apiCall('/api/expenses/stats/insights' + (q ? '?' + q : '')); },
    products:        (minCount, filters) => {
        const params = new URLSearchParams();
        if (minCount) params.set('min_count', minCount);
        if (filters) {
            if (filters.date_from) params.set('date_from', filters.date_from);
            if (filters.date_to) params.set('date_to', filters.date_to);
            if (filters.category_id) params.set('category_id', filters.category_id);
            if (filters.store_id) params.set('store_id', filters.store_id);
        }
        const qs = params.toString();
        return apiCall('/api/expenses/products' + (qs ? ('?' + qs) : ''));
    },

    productHistory:  (key) => apiCall('/api/expenses/products/history?key=' + encodeURIComponent(key)),
    mergeSuggestions:(  ) => apiCall('/api/expenses/products/merge-suggestions'),
    mergeProducts:   (keys, title) => apiCall('/api/expenses/products/merge', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ keys, title }) }),
    dismissMerge:    (keys) => apiCall('/api/expenses/products/merge-dismiss', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ keys }) }),
    regroupProduct:  (key, title, drop) => apiCall('/api/expenses/products/regroup', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ key, title, drop }) }),
    splitProduct:    (key) => apiCall('/api/expenses/products/split', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ keys: [key] }) }),
    mergeCategory:   (srcId, targetId) => apiCall(`/api/expense-categories/${srcId}/merge-into/${targetId}`, { method: 'POST' }),
    setItemGroup:    (iid, group) => apiCall(`/api/expense-items/${iid}/product-group`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ product_group: group }) }),
    setItemComparable: (iid, comparable) => apiCall(`/api/expense-items/${iid}/price-comparable`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ price_comparable: comparable }) }),
    reparseAllUrl:   () => `${API_BASE}/api/receipts/reparse-all`,
    recurring:       () => apiCall('/api/expenses/recurring/suggestions'),
    checkDuplicate:  (date, total, store_id) => {
        const q = new URLSearchParams({ date, total }); if (store_id) q.append('store_id', store_id);
        return apiCall('/api/expenses/duplicates/check?' + q.toString());
    },
    duplicateGroups: () => apiCall('/api/expenses/duplicates'),
    mergeDuplicates: (keep_id, remove_ids) => apiCall('/api/expenses/duplicates/merge', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ keep_id, remove_ids }),
    }),
    dismissDuplicate: (expense_ids) => apiCall('/api/expenses/duplicates/dismiss', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ expense_ids }),
    }),
};


/* ---------- Stückzahl einer Position ---------- */
/* Gibt die anzuzeigende Stückzahl zurück oder 0, wenn keine hingehört.
 * Bis v1.51 stand in ``quantity`` auch Gewicht oder Volumen ("500" mit der
 * Einheit "g"). Solche Altbestands-Zeilen sind keine Stückzahl und dürfen
 * nicht als "500×" auftauchen — erkennbar an der alten Einheit, die es für
 * neue Positionen nicht mehr gibt. */
function itemPieceCount(it) {
    if (!it) return 0;
    const unit = String(it.quantity_unit || '').toLowerCase();
    if (unit && unit !== 'stk' && unit !== 'stück' && unit !== 'x') return 0;
    const q = Math.round(Number(it.quantity));
    return (Number.isFinite(q) && q > 1 && q <= 99) ? q : 0;
}

/* ---------- Beleg-Typen ---------- */
/* Der Typ eines Bons (Kassenbon, Abo, ...) ist seit v1.52.0 nicht mehr fest
 * verdrahtet: der KI-Parser entscheidet ihn beim Scannen und darf einen eigenen
 * Namen vergeben ("Arztrechnung"). Die fuenf eingebauten Typen stehen hier
 * trotzdem, damit Beschriftungen auch ohne Server-Antwort stimmen. */
const EXPENSE_TYPE_BUILTINS = [
    { key: 'receipt',      label: 'Kassenbon',         icon: '🧾', builtin: true },
    { key: 'online_order', label: 'Online-Bestellung', icon: '📦', builtin: true },
    { key: 'restaurant',   label: 'Restaurant',        icon: '🍽️', builtin: true },
    { key: 'subscription', label: 'Abo',               icon: '🔁', builtin: true },
    { key: 'other',        label: 'Sonstiges',         icon: '📌', builtin: true },
];
let _expenseTypes = null;

async function loadExpenseTypes(force = false) {
    if (_expenseTypes && !force) return _expenseTypes;
    try {
        const rows = await AUSGABEN_API.expenseTypes();
        _expenseTypes = (rows && rows.length) ? rows : EXPENSE_TYPE_BUILTINS.slice();
    } catch (e) {
        _expenseTypes = EXPENSE_TYPE_BUILTINS.slice();
    }
    return _expenseTypes;
}

function expenseTypeMeta(key) {
    const list = _expenseTypes || EXPENSE_TYPE_BUILTINS;
    const hit = list.find(t => t.key === key);
    if (hit) return hit;
    // Eigener Typ, der (noch) nicht in der Liste steht: Klartext als Beschriftung.
    return key ? { key, label: key, icon: '🏷️' } : list[0];
}
function expenseTypeLabel(key) { return expenseTypeMeta(key).label; }
function expenseTypeIcon(key)  { return expenseTypeMeta(key).icon; }

/* <option>-Liste fuer ein Typ-Dropdown. Ein Typ, den es noch nicht gibt (frisch
 * vom Parser vorgeschlagen), wird hinten angehaengt, damit er auswaehlbar ist. */
function expenseTypeOptions(selected) {
    const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
        c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const list = (_expenseTypes || EXPENSE_TYPE_BUILTINS).slice();
    if (selected && !list.some(t => t.key === selected)) {
        list.push({ key: selected, label: selected, icon: '🏷️' });
    }
    return list.map(t =>
        `<option value="${esc(t.key)}"${t.key === selected ? ' selected' : ''}>${t.icon || '🏷️'} ${esc(t.label)}</option>`
    ).join('');
}

/* ---------- Auth Bootstrap ----------
 *
 * Die Freigabe des Body steht hier und NICHT bei den Aufrufern. Alle acht
 * Ausgaben-Seiten schrieben `const me = await ensureLoggedIn(); if (!me)
 * return;` und deckten sich erst DANACH auf. Antwortete `/api/me` mit einem
 * Fehler (nicht 401 -- den faengt api.js ab), kehrte jede dieser Seiten
 * vorher zurueck und liess `body{visibility:hidden}` stehen: eine
 * vollstaendig unsichtbare Seite, DOM komplett, Konsole sauber. Selbst der
 * Fehler-Toast haing am selben verborgenen Body und war damit ebenfalls weg.
 *
 * Aufgedeckt wird deshalb direkt hinter dem SYNCHRONEN Login-Check -- der
 * ist der eigentliche Schutz, und er haengt an keiner Antwort. Was danach
 * schiefgeht, sieht man dann wenigstens.
 */
async function ensureLoggedIn() {
    if (!isLoggedIn()) { window.location.href = '/private/login.html'; return null; }
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';
    try {
        const me = await fetchMe(true);
        const label = document.getElementById('userLabel');
        if (label) label.textContent = '👤 ' + me.username;
        const logout = document.getElementById('logoutBtn'); if (logout) logout.onclick = () => { clearToken(); location.reload(); };
        return me;
    } catch (e) {
        // Nicht still zurueckgeben: der Aufrufer bricht ab, und ohne Meldung
        // steht man vor einer leeren Seite und haelt die Anwendung fuer
        // kaputt statt den Server fuer langsam.
        showToast('Das Konto konnte nicht geladen werden: '
            + (e && e.message ? e.message : 'unbekannter Fehler'), 'error', 8000);
        return null;
    }
}

/* ---------- Toast ---------- */
function showToast(msg, type='info', ms=2500) {
    // Seit v1.58.0 gibt es einen Toast fuer die ganze App (ui.js). Nur wenn
    // der noch nicht geladen ist, baut diese Funktion ihren eigenen.
    if (window.Toast) {
        const fn = type === 'success' ? Toast.success : (type === 'error' ? Toast.error : Toast.info);
        fn(msg, { timeout: ms });
        if (type === 'error') haptic('error'); else if (type === 'success') haptic('success');
        return;
    }
    const t = document.createElement('div');
    t.className = 'ausg-toast ausg-toast-' + type;
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.classList.add('show'), 10);
    setTimeout(() => { t.classList.remove('show'); setTimeout(() => t.remove(), 300); }, ms);
    if (type === 'error') haptic('error'); else if (type === 'success') haptic('success');
}

/* ---------- Undo-Toast (mit Rückgängig-Button, 3 Sekunden) ---------- */
function showUndoToast(msg, onUndo, ms=3000) {
    const t = document.createElement('div');
    t.className = 'ausg-toast ausg-toast-undo';
    t.innerHTML = `<span>${msg}</span> <button class="undo-btn" type="button">Rückgängig</button>`;
    document.body.appendChild(t);
    let done = false;
    const cleanup = () => { t.classList.remove('show'); setTimeout(() => t.remove(), 300); };
    t.querySelector('.undo-btn').onclick = async () => {
        if (done) return; done = true;
        cleanup();
        try { await onUndo(); showToast('Rückgängig gemacht', 'success', 1500); }
        catch (e) { showToast('Rückgängig fehlgeschlagen: ' + e.message, 'error'); }
    };
    setTimeout(() => t.classList.add('show'), 10);
    setTimeout(() => { if (!done) cleanup(); }, ms);
    haptic('tap');
}

/* ---------- Fullscreen-Image-Viewer ----------
   Seit v1.99.0 in js/bild.js, damit das Ernaehrungs-Modul denselben Viewer
   benutzt statt eines zweiten. Die Weiterleitung bleibt, damit die rund
   zwanzig Aufrufstellen unveraendert sind. */
function openImageFullscreen(src) { return VexBild.vollbild(src, 'Bon'); }

/* ---------- Modal (generisch) ---------- */
/* Der Dialog liegt seit v2.1.0 in /js/modal.js -- eine Fassung fuer alle
   Module, mit gesperrtem Hintergrund, Fokus im Kasten und role="dialog".
   Der Name hier bleibt, damit die Aufrufstellen unveraendert bleiben. */
function openModal(title, contentHtml, opts) {
    return VexModal.open(title, contentHtml, opts || {});
}


/* ---------- Bild-Kompression ---------- */
async function compressImage(file, maxDim = 1600, quality = 0.85) {
    return VexBild.komprimieren(file, maxDim, quality);
}

/* ---------- Formatter ---------- */
function fmtDate(iso) {
    if (!iso) return '';
    try { const d = new Date(iso); return d.toLocaleDateString('de-DE'); } catch(e) { return iso; }
}
function todayISO() {
    const d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
}

/* ---------- Bild mit Auth laden -> Blob-URL ---------- */
async function fetchImageAsBlobUrl(url) { return VexBild.alsBlobUrl(url); }

/* ---------- Kopf: drei Bereiche statt sechs Pillen (v2.21.0) ----------
 * Bis v2.20.0 stand hier eine Leiste mit sechs Emoji-Pillen, am Handy in zwei
 * Zeilen: Übersicht, Statistik, Läden, Kategorien, Duplikate, Import. Vier
 * davon sind Pflege -- man braucht sie selten, und sie standen gleichrangig
 * neben dem, was man täglich öffnet. Jetzt sind es drei Bereiche; die Pflege
 * liegt unter „Verwalten“ (DESIGN 6d), und jede ihrer Seiten trägt einen Weg
 * zurück. Die Adressen der Seiten sind dieselben geblieben.
 *
 * Nutzung: <div id="subnav" data-active="..."></div>, direkt dahinter
 * <script>renderSubnav()</script> -- dann steht der Kopf vor dem ersten Bild,
 * und nichts darunter rutscht, wenn er erscheint. */
const AUSGABEN_BEREICHE = [
    { key: 'uebersicht', href: '/ausgaben/',                label: 'Übersicht' },
    { key: 'statistik',  href: '/ausgaben/statistik.html',  label: 'Statistik' },
    { key: 'verwalten',  href: '/ausgaben/verwalten.html',  label: 'Verwalten' },
];
const AUSGABEN_SEITEN = {
    dashboard: 'uebersicht', neu: 'uebersicht', bon: 'uebersicht',
    statistik: 'statistik', produkte: 'statistik',
    verwalten: 'verwalten', laeden: 'verwalten', kategorien: 'verwalten',
    marken: 'verwalten', duplikate: 'verwalten', import: 'verwalten',
};
const AUSGABEN_ZURUECK = {
    laeden: ['/ausgaben/verwalten.html', 'Verwalten'],
    kategorien: ['/ausgaben/verwalten.html', 'Verwalten'],
    marken: ['/ausgaben/verwalten.html', 'Verwalten'],
    duplikate: ['/ausgaben/verwalten.html', 'Verwalten'],
    import: ['/ausgaben/verwalten.html', 'Verwalten'],
    bon: ['/ausgaben/', 'Übersicht'],
    neu: ['/ausgaben/', 'Übersicht'],
};

function renderSubnav() {
    const el = document.getElementById('subnav');
    if (!el) return;
    const seite = el.dataset.active || '';
    const bereich = AUSGABEN_SEITEN[seite] || 'uebersicht';
    const zurueck = AUSGABEN_ZURUECK[seite];
    const zeichen = (n) => window.VexIkon ? VexIkon.svg(n, 18) : '';
    el.className = 'az-kopf';
    el.innerHTML = '<nav class="tabs" aria-label="Bereiche der Ausgaben">'
        + AUSGABEN_BEREICHE.map(b => `<a class="tab-btn${b.key === bereich ? ' active' : ''}" href="${b.href}"`
            + `${b.key === bereich ? ' aria-current="page"' : ''}>${b.label}</a>`).join('')
        + '</nav>'
        + (zurueck ? `<a class="az-zurueck" href="${zurueck[0]}">${zeichen('links')}${zurueck[1]}</a>` : '');
    const leiste = el.querySelector('.tabs');
    if (window.VexReiter && leiste) VexReiter.verzieren(leiste);
}

/* ---------- Die Bühne der Übersicht ----------
 * Sie steht hier und nicht in dashboard.js, weil diese Datei im <head> geladen
 * wird: index.html ruft sie direkt hinter #kpiGrid auf, bevor der Browser das
 * erste Mal zeichnet (v2.17.0: sonst rutschten die Kacheln darunter).
 *
 * Eine Gestalt, geladen oder als Platzhalter: der Platzhalter hat dieselbe
 * Struktur mit Skeletons an Stelle der Zahlen, damit nichts springt.
 *
 * Kein Ring: ein Ring sagt „wie viel von einem Ziel“ (DESIGN 7a), und für
 * Ausgaben gibt es kein Ziel. Die Bühne vergleicht deshalb mit dem Vormonat --
 * und zwar bis zum SELBEN Tag. Bis v2.20.0 stand hier der ganze Vormonat gegen
 * den angebrochenen: am 5. hiess das jeden Monat „−80 %“. */
function zeichneKpis(s) {
    const box = document.getElementById('kpiGrid');
    if (!box) return;
    const held = (v) => {
        const t = fmtEur(v), i = t.lastIndexOf(',');
        return i < 0 ? t : t.slice(0, i) + '<span class="v-held-rest">' + t.slice(i) + '</span>';
    };
    const wert = (v) => s ? fmtEur(v) : '<span class="skel az-skel-text" style="width:5rem"></span>';
    const monat = new Date().toLocaleDateString('de-DE', { month: 'long' });
    let vergleich = '<span class="skel az-skel-text"></span>';
    if (s) {
        // Verglichen wird NUR mit dem Vormonat bis zum selben Tag (v2.25.0:
        // der Server rechnet ihn, vorher stand hier bis zum Laden der Kurve
        // „Vormonat gesamt“ -- und blieb stehen, wenn der Vormonat bis
        // heute leer war).
        const tag = new Date().getDate();
        const prev = Number(s.prev_month_to_date) || 0;
        if (prev > 0) {
            const pct = Math.round(((Number(s.this_month) || 0) / prev - 1) * 100);
            const cls = Math.abs(pct) < 5 ? '' : (pct > 0 ? ' ist-mehr' : ' ist-weniger');
            vergleich = `<span class="az-delta${cls}">${pct > 0 ? '+' : pct < 0 ? '\u2212' : '\u00b1'}${Math.abs(pct)} %</span>`
                + `<span>zum Vormonat bis zum ${tag}. (${fmtEur(prev)})</span>`;
        } else {
            vergleich = `<span>Im Vormonat bis zum ${tag}. nichts ausgegeben</span>`;
        }
    }
    box.className = 'v-buehne az-buehne';
    box.innerHTML = `
        <div class="az-b-haupt">
            <span class="v-buehne-marke">Dieser Monat · ${monat}</span>
            <strong class="v-held" id="azMonat">${s ? held(s.this_month) : '<span class="skel az-held-skel"></span>'}</strong>
            <div class="az-b-vergleich" id="azVergleich">${vergleich}</div>
            <dl class="az-b-fakten">
                <div><dt>Heute</dt><dd>${wert(s && s.today)}</dd></div>
                <div><dt>Diese Woche</dt><dd>${wert(s && s.this_week)}</dd></div>
                <div><dt>Dieses Jahr</dt><dd>${wert(s && s.this_year)}</dd></div>
            </dl>
        </div>
        <div class="az-b-kurve">
            <div class="az-b-kurve-kopf"><span>Monatsverlauf</span>
                <span class="az-legende" id="azLegende"></span></div>
            <div class="az-b-flaeche"><canvas id="azKurve" aria-label="Ausgaben dieses Monats gegen den Vormonat"></canvas></div>
        </div>`;
}

/* ---------- Kassenzettel ----------
 * Ein Bon, gezeichnet wie ein Bon: Laden oben, Positionen untereinander,
 * Summe unten. Dieselbe Gestalt im Blatt der Übersicht und auf bon.html --
 * zwei Fassungen desselben Zettels würden sich beim nächsten Nachtrag
 * unterscheiden. ``bildUrl`` ist eine Blob-URL (VexBild.alsBlobUrl) oder leer. */
function kassenzettelHTML(e, bildUrl) {
    const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
        c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const items = e.items || [];
    const typ = expenseTypeLabel(e.expense_type);
    const tag = e.purchase_date
        ? new Date(e.purchase_date + 'T12:00:00').toLocaleDateString('de-DE', { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric' })
        : '';
    const ton = e.store_color ? `--tone:${esc(e.store_color)}` : '';
    const mark = e.store_icon || (e.store_name || typ || '€').slice(0, 1).toUpperCase();
    const positionen = items.length ? items.map(it => {
        const q = itemPieceCount(it);
        const unter = [];
        if (it.category_name) unter.push(`${esc(it.category_icon || '')} ${esc(it.category_name)}`.trim());
        if (it.is_reduced) unter.push(`<span class="az-reduziert">reduziert${it.original_price ? ' · vorher ' + fmtEur(it.original_price) : ''}</span>`);
        if (it.price_comparable === false) unter.push('nicht im Preisvergleich');
        return `<div class="az-pos${it.price_comparable === false ? ' ist-aus' : ''}">
            <span class="az-pos-name">${q ? `<b>${q}×</b>` : ''}${esc(it.description || '')}</span>
            <span class="az-pos-preis">${fmtEur(it.total_price)}</span>
            ${unter.length ? `<span class="az-pos-unter">${unter.join('<span>·</span>')}</span>` : ''}
        </div>`;
    }).join('') : '<p class="az-zettel-leer">Keine Einzelpositionen gespeichert.</p>';
    return `<article class="az-zettel" style="${ton}">
        <header class="az-zettel-kopf">
            <span class="az-zettel-mark" aria-hidden="true">${esc(mark)}</span>
            <span class="az-zettel-laden">${esc(e.store_name || typ)}</span>
            <span class="az-zettel-meta">${esc(typ)}${tag ? ' · ' + esc(tag) : ''}</span>
        </header>
        <hr class="az-zettel-trenner">
        <div class="az-zettel-pos">${positionen}</div>
        <hr class="az-zettel-trenner">
        <div class="az-zettel-summe"><span>Summe</span><strong>${fmtEur(e.total_amount)}</strong></div>
        <div class="az-zettel-fuss"><span>${items.length} ${items.length === 1 ? 'Position' : 'Positionen'}</span>${e.is_recurring ? '<span>wiederkehrend</span>' : ''}</div>
        ${e.note ? `<div class="az-zettel-notiz">${esc(e.note)}</div>` : ''}
        ${bildUrl ? `<img class="az-zettel-foto" src="${bildUrl}" alt="Foto des Bons" data-vollbild>` : ''}
    </article>`;
}
