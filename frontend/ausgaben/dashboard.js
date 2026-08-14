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

const TYPE_ICONS = { receipt:'🧾', online_order:'📦', restaurant:'🍽️', subscription:'🔁', other:'📌' };
const TYPE_LABELS = { receipt:'Kassenbon', online_order:'Online', restaurant:'Restaurant', subscription:'Abo', other:'Sonstiges' };
const PAYMENT_LABELS = { cash:'Bar', card:'EC/Karte', credit:'Kreditkarte', paypal:'PayPal', other:'Sonstiges' };

// Cache pro Bon-ID: { detail: fullExpense, imgUrl: blobUrl|null, expanded: bool }
const expDetailCache = new Map();

async function loadExpenses() {
    const params = {
        expense_type: document.getElementById('filterType').value || undefined,
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
        list.innerHTML = rows.map(r => renderExpItem(r)).join('');
        // Klick-Handler binden
        list.querySelectorAll('.exp-row').forEach(row => {
            row.onclick = (e) => {
                e.preventDefault();
                const id = +row.dataset.id;
                toggleExpDetail(id, row);
            };
        });
    } catch(e) { list.innerHTML = '<div class="empty muted">Fehler: '+e.message+'</div>'; }
}

function renderExpItem(r) {
    const initial = (r.store_name || '€').slice(0,1).toUpperCase();
    const color = r.store_color || '#6b7280';
    const typeIcon = TYPE_ICONS[r.expense_type] || '🧾';
    const typeLabel = TYPE_LABELS[r.expense_type] || 'Kassenbon';
    return `<div class="exp-item" data-item-id="${r.id}">
        <div class="exp-row" data-id="${r.id}" role="button" tabindex="0">
            <div class="exp-store" style="background:${color}">${r.store_icon || initial}</div>
            <div class="exp-info">
                <div class="exp-name">${typeIcon} ${escapeHtml(r.store_name || typeLabel)}${r.is_recurring?' 🔁':''}</div>
                <div class="exp-meta">${fmtDate(r.purchase_date)} · ${r.item_count||0} Position${r.item_count===1?'':'en'}${r.expense_type && r.expense_type !== 'receipt' ? ' · ' + typeLabel : ''}</div>
            </div>
            <div class="exp-amount">${fmtEur(r.total_amount)}</div>
            <span class="exp-chevron">▶</span>
        </div>
    </div>`;
}

async function toggleExpDetail(id, rowEl) {
    const container = rowEl.parentElement; // .exp-item
    const existingDetail = container.querySelector('.exp-detail');
    if (existingDetail) {
        // schließen
        existingDetail.remove();
        rowEl.classList.remove('open');
        return;
    }
    // Öffnen: placeholder rendern
    const placeholder = document.createElement('div');
    placeholder.className = 'exp-detail';
    placeholder.innerHTML = '<div class="muted" style="text-align:center;padding:0.5rem">Laden …</div>';
    container.appendChild(placeholder);
    rowEl.classList.add('open');

    try {
        let cache = expDetailCache.get(id);
        if (!cache) {
            const detail = await AUSGABEN_API.getExpense(id);
            let imgUrl = null;
            if (detail.receipt_image_id) {
                try {
                    imgUrl = await fetchImageAsBlobUrl(AUSGABEN_API.receiptThumbUrl(detail.receipt_image_id));
                } catch (_) {}
            }
            cache = { detail, imgUrl };
            expDetailCache.set(id, cache);
        }
        placeholder.innerHTML = renderExpDetail(cache.detail, cache.imgUrl);
    } catch (e) {
        placeholder.innerHTML = `<div class="muted">Fehler: ${escapeHtml(e.message)}</div>`;
    }
}

function renderExpDetail(e, imgUrl) {
    const items = e.items || [];
    const itemsHtml = items.length
        ? items.map(it => `<div class="it">
            <span class="it-desc">${escapeHtml(it.description || '')}${it.category_name ? '<span class="it-cat">· ' + escapeHtml(it.category_name) + '</span>' : ''}</span>
            <span class="it-price">${fmtEur(it.total_price)}</span>
        </div>`).join('')
        : '<div class="muted" style="font-size:0.75rem">Keine Einzelpositionen gespeichert.</div>';

    const pm = e.payment_method ? PAYMENT_LABELS[e.payment_method] || e.payment_method : '–';
    const typeLabel = TYPE_LABELS[e.expense_type] || 'Kassenbon';

    return `
        ${imgUrl ? `<img src="${imgUrl}" class="thumb" alt="Bon-Foto">` : ''}
        <div class="grid">
            <div class="k">Typ</div><div class="v">${TYPE_ICONS[e.expense_type] || '🧾'} ${typeLabel}</div>
            <div class="k">Datum</div><div class="v">${fmtDate(e.purchase_date)}</div>
            <div class="k">Laden</div><div class="v">${escapeHtml(e.store_name || '–')}</div>
            <div class="k">Zahlungsart</div><div class="v">${pm}</div>
            <div class="k">Gesamt</div><div class="v"><strong>${fmtEur(e.total_amount)}</strong></div>
            ${e.note ? `<div class="k">Notiz</div><div class="v">${escapeHtml(e.note)}</div>` : ''}
        </div>
        ${items.length ? `<div class="items-hdr">Positionen (${items.length})</div><div class="items">${itemsHtml}</div>` : itemsHtml}
        <div class="actions">
            <a href="/ausgaben/bon.html?id=${e.id}" class="nav-btn primary" style="background:var(--teal);color:#fff;border:none">✏️ Bearbeiten</a>
        </div>
    `;
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
    ['filterType','filterStore','filterCategory','filterFrom','filterTo'].forEach(id => document.getElementById(id).value = '');
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
