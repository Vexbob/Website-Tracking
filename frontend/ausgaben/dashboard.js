let stores=[], categories=[];

async function loadInit() {
    const me = await ensureLoggedIn(); if (!me) return;
    renderSubnav();
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

let searchDebounceTimer = null;

async function loadExpenses() {
    const params = {
        expense_type: document.getElementById('filterType').value || undefined,
        store_id:    document.getElementById('filterStore').value || undefined,
        category_id: document.getElementById('filterCategory').value || undefined,
        from:        document.getElementById('filterFrom').value || undefined,
        to:          document.getElementById('filterTo').value || undefined,
        q:           (document.getElementById('filterQ')?.value || '').trim() || undefined,
        limit: 200,
    };
    const list = document.getElementById('expList');
    list.innerHTML = '<div class="empty muted">Laden …</div>';
    try {
        const rows = await AUSGABEN_API.expenses(params);
        if (!rows.length) {
            list.innerHTML = '<div class="empty"><div class="empty-icon">🧾</div>Noch keine Ausgaben — <a href="/ausgaben/neu.html">jetzt anlegen</a></div>';
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
        list.innerHTML = groups.map(g =>
            renderDateHeader(g) + g.items.map(r => renderExpItem(r)).join('')
        ).join('');
        // Klick-Handler + Swipe binden
        list.querySelectorAll('.exp-item').forEach(bindItemHandlers);
    } catch(e) { list.innerHTML = '<div class="empty muted">Fehler: '+e.message+'</div>'; }
}

function renderFilterTotal(rows, params) {
    const el = document.getElementById('filterTotal');
    if (!el) return;
    const hasFilter = params.q || params.expense_type || params.store_id || params.category_id || params.from || params.to;
    if (!hasFilter || !rows.length) { el.innerHTML = ''; return; }
    const total = rows.reduce((s, r) => s + (Number(r.total_amount) || 0), 0);
    el.innerHTML = `<div class="filter-total">
        <span>${rows.length} Bon${rows.length === 1 ? '' : 's'} gefiltert</span>
        <strong>${fmtEur(total)}</strong>
    </div>`;
}

function bindItemHandlers(itemEl) {
    const row = itemEl.querySelector('.exp-row');
    if (!row) return;
    row.onclick = (e) => {
        // Wenn Swipe offen: erst zurückschieben
        if (itemEl.classList.contains('swipe-open')) {
            itemEl.classList.remove('swipe-open');
            return;
        }
        e.preventDefault();
        const id = +row.dataset.id;
        toggleExpDetail(id, row);
    };

    // Swipe-Handling nur auf Touch-Geräten (Mobile)
    let startX = null, startY = null, deltaX = 0, active = false;
    row.addEventListener('touchstart', (e) => {
        const t = e.touches[0];
        startX = t.clientX; startY = t.clientY; deltaX = 0; active = true;
    }, { passive: true });
    row.addEventListener('touchmove', (e) => {
        if (!active || startX === null) return;
        const t = e.touches[0];
        const dx = t.clientX - startX;
        const dy = t.clientY - startY;
        if (Math.abs(dy) > Math.abs(dx)) { active = false; return; }
        deltaX = Math.max(-80, Math.min(0, dx));
    }, { passive: true });
    row.addEventListener('touchend', () => {
        if (!active) return;
        active = false;
        if (deltaX < -40) itemEl.classList.add('swipe-open');
        else itemEl.classList.remove('swipe-open');
    }, { passive: true });

    // Delete-Button in Swipe-Actions
    const delBtn = itemEl.querySelector('.exp-swipe-actions .del-btn');
    if (delBtn) delBtn.onclick = async (e) => {
        e.stopPropagation();
        const id = +row.dataset.id;
        await deleteExpenseWithUndo(id, itemEl);
    };
}

async function deleteExpenseWithUndo(id, itemEl) {
    // Wir laden den Bon vor dem Löschen komplett — für Rückgängig
    let full = null;
    try { full = await AUSGABEN_API.getExpense(id); } catch (_) {}
    try {
        await AUSGABEN_API.deleteExpense(id);
    } catch (e) { showToast('Löschen fehlgeschlagen: ' + e.message, 'error'); return; }
    itemEl.style.transition = 'opacity .2s, max-height .2s';
    itemEl.style.overflow = 'hidden';
    itemEl.style.maxHeight = itemEl.offsetHeight + 'px';
    requestAnimationFrame(() => { itemEl.style.maxHeight = '0'; itemEl.style.opacity = '0'; });
    setTimeout(() => itemEl.remove(), 220);
    // KPIs neu laden (Betrag hat sich geändert)
    loadKpis();
    if (full) {
        showUndoToast('Bon gelöscht', async () => {
            // Re-Create mit gleichem Content
            const items = (full.items || []).map(it => ({
                description: it.description, quantity: it.quantity, quantity_unit: it.quantity_unit,
                unit_price: it.unit_price, total_price: it.total_price,
                category_id: it.category_id, is_reduced: it.is_reduced, original_price: it.original_price,
            }));
            await AUSGABEN_API.createExpense({
                store_id: full.store_id, purchase_date: full.purchase_date,
                total_amount: full.total_amount, payment_method: full.payment_method,
                is_recurring: false, expense_type: full.expense_type, note: full.note,
                receipt_image_id: full.receipt_image_id, items,
            });
            await loadExpenses(); loadKpis();
        }, 3000);
    } else {
        showToast('Bon gelöscht', 'success', 1500);
    }
}

// Datums-Trennlinie mit „Heute" / „Gestern" / „<Wochentag>, DD.MM.YYYY" + Tagesumsatz
function renderDateHeader(g) {
    const iso = g.date;
    const d = new Date(iso + 'T00:00:00');
    const today = new Date(); today.setHours(0,0,0,0);
    const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
    const isSameDay = (a, b) => a.getFullYear()===b.getFullYear() && a.getMonth()===b.getMonth() && a.getDate()===b.getDate();
    let label;
    if (isSameDay(d, today)) label = 'Heute';
    else if (isSameDay(d, yesterday)) label = 'Gestern';
    else {
        const wd = d.toLocaleDateString('de-DE', { weekday: 'long' });
        label = `${wd}, ${d.toLocaleDateString('de-DE')}`;
    }
    return `<div class="date-header">
        <span class="date-label">${label}</span>
        <span class="date-line"></span>
        <span class="date-total">${g.items.length} Bon${g.items.length===1?'':'s'} · ${fmtEur(g.total)}</span>
    </div>`;
}

function renderExpItem(r) {
    const initial = (r.store_name || '€').slice(0,1).toUpperCase();
    const color = r.store_color || '#6b7280';
    const typeIcon = TYPE_ICONS[r.expense_type] || '🧾';
    const typeLabel = TYPE_LABELS[r.expense_type] || 'Kassenbon';
    const amt = Number(r.total_amount) || 0;
    // Farb-Codierung: >= 100 € = groß (rot), < 5 € = klein (grün)
    let sizeCls = '';
    if (amt >= 100) sizeCls = 'big';
    else if (amt > 0 && amt < 5) sizeCls = 'tiny';
    // Foto-Icon wenn der Bon ein Bild im Anhang hat (aus OCR-Upload)
    const photoBadge = r.has_image
        ? `<span class="exp-photo-badge" title="Foto vorhanden">📷</span>`
        : '';
    return `<div class="exp-item" data-item-id="${r.id}">
        <div class="exp-row ${sizeCls}" data-id="${r.id}" role="button" tabindex="0">
            <div class="exp-store" style="background:${color}">${r.store_icon || initial}</div>
            <div class="exp-info">
                <div class="exp-name">${typeIcon} ${escapeHtml(r.store_name || typeLabel)}${r.is_recurring?' 🔁':''}${photoBadge}</div>
                <div class="exp-meta">${fmtDate(r.purchase_date)} · ${r.item_count||0} Position${r.item_count===1?'':'en'}${r.expense_type && r.expense_type !== 'receipt' ? ' · ' + typeLabel : ''}</div>
            </div>
            <div class="exp-amount">${fmtEur(r.total_amount)}</div>
            <span class="exp-chevron">▶</span>
        </div>
        <div class="exp-swipe-actions">
            <button class="del-btn" title="Löschen">🗑️</button>
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
        container.classList.remove('expanded');
        return;
    }
    // Öffnen: placeholder rendern
    const placeholder = document.createElement('div');
    placeholder.className = 'exp-detail';
    placeholder.innerHTML = '<div class="muted" style="text-align:center;padding:0.5rem">Laden …</div>';
    container.appendChild(placeholder);
    rowEl.classList.add('open');
    container.classList.add('expanded');

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
        // Bild-Fullscreen aktivieren
        const thumbImg = placeholder.querySelector('img[data-fullscreen]');
        if (thumbImg) thumbImg.onclick = () => openImageFullscreen(thumbImg.src);
    } catch (e) {
        placeholder.innerHTML = `<div class="muted">Fehler: ${escapeHtml(e.message)}</div>`;
    }
}

function renderExpDetail(e, imgUrl) {
    const items = e.items || [];
    const itemsHtml = items.length
        ? items.map(it => {
            const catIcon = it.category_icon || (it.category_id ? '🏷️' : '');
            const catName = it.category_name ? `${catIcon ? catIcon + ' ' : ''}${escapeHtml(it.category_name)}` : '';
            return `<div class="it">
                <span class="it-desc">${escapeHtml(it.description || '')}${catName ? '<span class="it-cat">· ' + catName + '</span>' : ''}</span>
                <span class="it-price">${fmtEur(it.total_price)}</span>
            </div>`;
        }).join('')
        : '<div class="muted" style="font-size:0.75rem">Keine Einzelpositionen gespeichert.</div>';

    const pm = e.payment_method ? PAYMENT_LABELS[e.payment_method] || e.payment_method : '–';
    const typeLabel = TYPE_LABELS[e.expense_type] || 'Kassenbon';

    return `
        ${imgUrl ? `<img src="${imgUrl}" class="thumb" alt="Bon-Foto" data-fullscreen="1" style="cursor:zoom-in">` : ''}
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

// Live-Reload bei Filter-Änderung
['filterType','filterStore','filterCategory','filterFrom','filterTo'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.onchange = () => { clearPresetActive(); loadExpenses(); };
});
// Suche mit Debounce (500ms)
const searchEl = document.getElementById('filterQ');
if (searchEl) searchEl.oninput = () => {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(loadExpenses, 500);
};
document.getElementById('filterReset').onclick = () => {
    ['filterType','filterStore','filterCategory','filterFrom','filterTo','filterQ'].forEach(id => {
        const el = document.getElementById(id); if (el) el.value = '';
    });
    clearPresetActive();
    loadExpenses();
};

// Datums-Presets
function clearPresetActive() {
    document.querySelectorAll('#datePresets button').forEach(b => b.classList.remove('active'));
}
function pad(n) { return String(n).padStart(2, '0'); }
function isoDate(d) { return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`; }
function applyPreset(name) {
    const today = new Date(); today.setHours(0,0,0,0);
    let from = null, to = today;
    if (name === 'week') {
        // Montag dieser Woche (ISO)
        const d = new Date(today);
        const dow = (d.getDay() + 6) % 7; // 0=Mo
        d.setDate(d.getDate() - dow);
        from = d;
    } else if (name === 'month') {
        from = new Date(today.getFullYear(), today.getMonth(), 1);
    } else if (name === 'quarter') {
        from = new Date(today.getFullYear(), today.getMonth() - 2, 1);
    } else if (name === 'year') {
        from = new Date(today.getFullYear(), 0, 1);
    }
    document.getElementById('filterFrom').value = from ? isoDate(from) : '';
    document.getElementById('filterTo').value = isoDate(to);
    clearPresetActive();
    document.querySelector(`#datePresets button[data-preset="${name}"]`)?.classList.add('active');
    loadExpenses();
}
document.querySelectorAll('#datePresets button').forEach(b => {
    b.onclick = () => applyPreset(b.dataset.preset);
});

// downloadFile + Export-Link kommen aus ausgaben.js (renderSubnav)

loadInit();
