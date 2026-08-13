let stores=[], categories=[];

async function loadInit() {
    const me = await ensureLoggedIn(); if (!me) return;
    try {
        [stores, categories] = await Promise.all([AUSGABEN_API.stores(), AUSGABEN_API.categories()]);
    } catch(e) { showToast('Laden fehlgeschlagen: ' + e.message, 'error'); return; }
    populateFilters();
    await Promise.all([loadKpis(), loadExpenses(), loadRecurring()]);
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(()=>{});
}

function populateFilters() {
    const s = document.getElementById('filterStore');
    stores.forEach(x => s.insertAdjacentHTML('beforeend', `<option value="${x.id}">${x.icon || ''} ${x.name}</option>`));
    const c = document.getElementById('filterCategory');
    categories.forEach(x => c.insertAdjacentHTML('beforeend', `<option value="${x.id}">${x.icon || ''} ${x.name}</option>`));
}

async function loadKpis() {
    try {
        const s = await AUSGABEN_API.statsSummary();
        const kpis = [
            { lbl: 'Heute',       val: fmtEur(s.today) },
            { lbl: 'Diese Woche', val: fmtEur(s.this_week) },
            { lbl: 'Dieser Monat',val: fmtEur(s.this_month), accent: true },
            { lbl: 'Vormonat',    val: fmtEur(s.prev_month) },
            { lbl: 'Dieses Jahr', val: fmtEur(s.this_year) },
            { lbl: 'Gesamt',      val: fmtEur(s.total), sub: s.count + ' Bons' },
        ];
        document.getElementById('kpiGrid').innerHTML = kpis.map(k =>
            `<div class="kpi${k.accent?' accent':''}"><div class="lbl">${k.lbl}</div><div class="val">${k.val}</div>${k.sub?`<div class="sub">${k.sub}</div>`:''}</div>`
        ).join('');
    } catch(e) { console.error(e); }
}

async function loadExpenses() {
    const params = {
        store_id:    document.getElementById('filterStore').value || undefined,
        category_id: document.getElementById('filterCategory').value || undefined,
        from:        document.getElementById('filterFrom').value || undefined,
        to:          document.getElementById('filterTo').value || undefined,
        limit: 100,
    };
    const list = document.getElementById('expList');
    list.innerHTML = '<div class="empty muted">Laden …</div>';
    try {
        const rows = await AUSGABEN_API.expenses(params);
        if (!rows.length) {
            list.innerHTML = '<div class="empty"><div class="empty-icon">🧾</div>Noch keine Ausgaben — <a href="/ausgaben/neu.html">jetzt anlegen</a></div>';
            return;
        }
        list.innerHTML = rows.map(r => {
            const initial = (r.store_name || '€').slice(0,1).toUpperCase();
            const color = r.store_color || '#6b7280';
            return `<a href="/ausgaben/bon.html?id=${r.id}" class="exp-row">
                <div class="exp-store" style="background:${color}">${r.store_icon || initial}</div>
                <div class="exp-info">
                    <div class="exp-name">${escapeHtml(r.store_name || 'Ohne Laden')}${r.is_recurring?' 🔁':''}</div>
                    <div class="exp-meta">${fmtDate(r.purchase_date)} · ${r.item_count||0} Position${r.item_count===1?'':'en'}</div>
                </div>
                <div class="exp-amount">${fmtEur(r.total_amount)}</div>
            </a>`;
        }).join('');
    } catch(e) { list.innerHTML = '<div class="empty muted">Fehler: '+e.message+'</div>'; }
}

async function loadRecurring() {
    try {
        const rows = await AUSGABEN_API.recurring();
        if (!rows.length) return;
        document.getElementById('recurringCard').style.display = '';
        document.getElementById('recurringList').innerHTML = rows.map(r =>
            `<div class="rec-item"><span class="dot"></span><strong>${escapeHtml(r.store_name)}</strong> · ~${fmtEur(r.avg_amount)} · ${r.months} Monate hintereinander · zuletzt ${fmtDate(r.last_date)}</div>`
        ).join('');
    } catch(e) { console.warn(e); }
}

function escapeHtml(s) {
    if (!s) return '';
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

document.getElementById('filterApply').onclick = loadExpenses;
document.getElementById('filterReset').onclick = () => {
    ['filterStore','filterCategory','filterFrom','filterTo'].forEach(id => document.getElementById(id).value = '');
    loadExpenses();
};

async function downloadFile(url, filename) {
    try {
        const token = getToken();
        const res = await fetch(url, { headers: { 'Authorization': 'Bearer ' + token } });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const blob = await res.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    } catch(e) { showToast('Export fehlgeschlagen: ' + e.message, 'error'); }
}
document.getElementById('exportCsvLink').onclick = (e) => { e.preventDefault(); downloadFile(AUSGABEN_API.exportCsv(), 'ausgaben.csv'); };
document.getElementById('exportJsonLink').onclick = (e) => { e.preventDefault(); downloadFile(AUSGABEN_API.exportJson(), 'ausgaben.json'); };

loadInit();
