/* Gemeinsame Helper für das Ausgaben-Modul. */

const AUSGABEN_API = {
    stores:      () => apiCall('/api/stores'),
    createStore: (b) => apiCall('/api/stores', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    updateStore: (id, b) => apiCall(`/api/stores/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    deleteStore: (id) => apiCall(`/api/stores/${id}`, { method: 'DELETE' }),

    categories:      () => apiCall('/api/expense-categories'),
    createCategory:  (b) => apiCall('/api/expense-categories', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    updateCategory:  (id, b) => apiCall(`/api/expense-categories/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    deleteCategory:  (id) => apiCall(`/api/expense-categories/${id}`, { method: 'DELETE' }),

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
    statsMonthly:    (months=12) => apiCall(`/api/expenses/stats/monthly?months=${months}`),
    statsWeekly:     (weeks=12) => apiCall(`/api/expenses/stats/weekly?weeks=${weeks}`),
    statsDaily:     (days=30) => apiCall(`/api/expenses/stats/daily?days=${days}`),
    products:        () => apiCall('/api/expenses/products'),
    productHistory:  (key) => apiCall('/api/expenses/products/history?key=' + encodeURIComponent(key)),
    priceHistory:    (q) => apiCall('/api/expenses/price-history?q=' + encodeURIComponent(q)),
    mergeCategory:   (srcId, targetId) => apiCall(`/api/expense-categories/${srcId}/merge-into/${targetId}`, { method: 'POST' }),
    recurring:       () => apiCall('/api/expenses/recurring/suggestions'),
    checkDuplicate:  (date, total, store_id) => {
        const q = new URLSearchParams({ date, total }); if (store_id) q.append('store_id', store_id);
        return apiCall('/api/expenses/duplicates/check?' + q.toString());
    },
    exportCsv:  () => `${API_BASE}/api/expenses/export`,
};


/* ---------- Auth Bootstrap ---------- */
async function ensureLoggedIn() {
    if (!isLoggedIn()) { window.location.href = '/private/login.html'; return null; }
    try {
        const me = await fetchMe(true);
        const label = document.getElementById('userLabel');
        if (label) label.textContent = '👤 ' + me.username;
        const logout = document.getElementById('logoutBtn'); if (logout) logout.onclick = () => { clearToken(); location.reload(); };
        const theme = document.getElementById('themeBtn'); if (theme) theme.onclick = toggleTheme;
        return me;
    } catch (e) { return null; }
}

/* ---------- Toast ---------- */
function showToast(msg, type='info', ms=2500) {
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
    t.innerHTML = `<span>${msg}</span> <button class="undo-btn" type="button">↺ Rückgängig</button>`;
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

/* ---------- Fullscreen-Image-Viewer ---------- */
function openImageFullscreen(src) {
    const overlay = document.createElement('div');
    overlay.className = 'img-fullscreen';
    overlay.innerHTML = `<button class="img-close" aria-label="Schließen">✕</button><img src="${src}" alt="Bon">`;
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('show'));
    const close = () => { overlay.classList.remove('show'); setTimeout(() => overlay.remove(), 200); };
    overlay.onclick = (e) => { if (e.target === overlay || e.target.classList.contains('img-close')) close(); };
    const onKey = (e) => { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', onKey); } };
    document.addEventListener('keydown', onKey);
}

/* ---------- Modal (generisch) ---------- */
function openModal(title, contentHtml, opts={}) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `<div class="modal-box${opts.wide ? ' wide' : ''}">
        <div class="modal-head"><h3>${title}</h3><button class="modal-close" aria-label="Schließen">✕</button></div>
        <div class="modal-body">${contentHtml}</div>
    </div>`;
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('show'));
    const close = () => { overlay.classList.remove('show'); setTimeout(() => overlay.remove(), 200); if (opts.onClose) opts.onClose(); };
    overlay.querySelector('.modal-close').onclick = close;
    overlay.onclick = (e) => { if (e.target === overlay) close(); };
    const onKey = (e) => { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', onKey); } };
    document.addEventListener('keydown', onKey);
    return { close, root: overlay.querySelector('.modal-body') };
}

/* ---------- Bild-Kompression ---------- */
async function compressImage(file, maxDim = 1600, quality = 0.85) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        const url = URL.createObjectURL(file);
        img.onload = () => {
            const w = img.naturalWidth, h = img.naturalHeight;
            const scale = Math.min(1, maxDim / Math.max(w, h));
            const cw = Math.round(w * scale), ch = Math.round(h * scale);
            const canvas = document.createElement('canvas');
            canvas.width = cw; canvas.height = ch;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, cw, ch);
            URL.revokeObjectURL(url);
            canvas.toBlob(
                (blob) => blob ? resolve(new File([blob], (file.name || 'bon.jpg').replace(/\.[^.]+$/, '') + '.jpg', { type: 'image/jpeg' })) : reject(new Error('Kompression fehlgeschlagen')),
                'image/jpeg', quality
            );
        };
        img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Bild kann nicht geladen werden')); };
        img.src = url;
    });
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
async function fetchImageAsBlobUrl(url) {
    const token = getToken();
    const res = await fetch(url, { headers: { 'Authorization': 'Bearer ' + token } });
    if (!res.ok) throw new Error('Bild laden fehlgeschlagen');
    const blob = await res.blob();
    return URL.createObjectURL(blob);
}

/* ---------- Datei mit Auth-Header herunterladen (für CSV-Export) ---------- */
async function downloadFile(url, filename) {
    try {
        const token = getToken();
        const res = await fetch(url, { headers: { 'Authorization': 'Bearer ' + token } });
        if (!res.ok) {
            // Fehler-Payload robust in einen String verwandeln (nicht "[object Object]")
            let msg = 'HTTP ' + res.status;
            try {
                const txt = await res.text();
                if (txt) {
                    try {
                        const j = JSON.parse(txt);
                        if (typeof j === 'string') msg = j;
                        else if (j && typeof j.detail === 'string') msg = j.detail;
                        else if (j && Array.isArray(j.detail)) msg = j.detail.map(x => x.msg || JSON.stringify(x)).join('; ');
                        else msg = JSON.stringify(j);
                    } catch (_) { msg = txt; }
                }
            } catch (_) {}
            console.error('Export-Fehler:', res.status, msg);
            throw new Error(msg);
        }
        const blob = await res.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    } catch (e) {
        const msg = (e && typeof e.message === 'string') ? e.message : String(e);
        showToast('Export fehlgeschlagen: ' + msg, 'error');
    }
}

/* ---------- Gemeinsame Subnav für alle Ausgaben-Seiten ---------- */
// Nutzung: <div id="subnav" data-active="..."></div> ins HTML, wobei active z.B.
// "dashboard" | "neu" | "statistik" | "preisverlauf" | "laeden" | "kategorien"
function renderSubnav() {
    const el = document.getElementById('subnav');
    if (!el) return;
    const active = el.dataset.active || '';
    const links = [
        { key: 'neu',          href: '/ausgaben/neu.html',           label: '+ Neuer Bon' },
        { key: 'dashboard',    href: '/ausgaben/',                   label: '📋 Übersicht' },
        { key: 'statistik',    href: '/ausgaben/statistik.html',     label: '📊 Statistik' },
        { key: 'preisverlauf', href: '/ausgaben/preisverlauf.html',  label: '💶 Preisverlauf' },
        { key: 'laeden',       href: '/ausgaben/laeden.html',        label: '🏪 Läden' },
        { key: 'kategorien',   href: '/ausgaben/kategorien.html',    label: '🏷️ Kategorien' },
    ];
    el.className = 'subnav';
    el.innerHTML = links.map(l =>
        `<a href="${l.href}"${l.key === active ? ' class="primary"' : ''}>${l.label}</a>`
    ).join('') + '<a href="#" id="exportCsvLink">⬇ CSV</a>';
    const csv = document.getElementById('exportCsvLink');
    if (csv) csv.onclick = (e) => { e.preventDefault(); downloadFile(AUSGABEN_API.exportCsv(), 'ausgaben.csv'); };
}
