let stores=[], categories=[];

async function loadInit() {
    const me = await ensureLoggedIn(); if (!me) return;
    renderSubnav();
    try {
        [stores, categories] = await Promise.all([AUSGABEN_API.stores(), AUSGABEN_API.categories()]);
    } catch(e) { showToast('Laden fehlgeschlagen: ' + e.message, 'error'); return; }
    populateFilters();
    setupFilterPopover();
    setupNewExpenseModal();
    await Promise.all([loadKpis(), loadExpenses(), loadRecurring(), loadDuplicates()]);
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';
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
        e.preventDefault();
        const id = +row.dataset.id;
        toggleExpDetail(id, row);
    };
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
    // Foto-Icon wenn der Bon ein Bild im Anhang hat (aus OCR-Upload)
    const photoBadge = r.has_image
        ? `<span class="exp-photo-badge" title="Foto vorhanden">📷</span>`
        : '';
    return `<div class="exp-item" data-item-id="${r.id}">
        <div class="exp-row" data-id="${r.id}" role="button" tabindex="0">
            <div class="exp-store" style="background:${color}">${r.store_icon || initial}</div>
            <div class="exp-info">
                <div class="exp-name">${typeIcon} ${escapeHtml(r.store_name || typeLabel)}${r.is_recurring?' 🔁':''}${photoBadge}</div>
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

// v1.21.0: Duplikat-Erkennung — findet Bons mit gleichem Laden, gleichem
// Kaufdatum und (fast) gleichem Betrag und bietet eine automatische
// Zusammenfuehrung an (Positionen werden auf den behaltenen Bon umgehaengt,
// Duplikate geloescht). Nichts passiert automatisch ohne Bestaetigung.
async function loadDuplicates() {
    try {
        const data = await AUSGABEN_API.duplicateGroups();
        const groups = data.groups || [];
        const card = document.getElementById('duplicatesCard');
        if (!groups.length) { card.style.display = 'none'; return; }
        card.style.display = '';
        document.getElementById('duplicatesList').innerHTML = groups.map((g, gi) => {
            const rows = g.items.map(it => `
                <div class="dup-row${it.id === g.keep_id ? ' dup-keep' : ''}">
                    <span class="dot"></span>
                    <span>${it.store_icon} <strong>${escapeHtml(it.store_name)}</strong></span>
                    <span>${fmtDate(it.purchase_date)}</span>
                    <span>${fmtEur(it.total_amount)}</span>
                    <span class="muted">${it.item_count} Positionen${it.has_image ? ' · 📷 Beleg' : ''}</span>
                    ${it.id === g.keep_id ? '<span class="muted">← wird behalten</span>' : ''}
                </div>`).join('');
            const removeIds = g.items.filter(it => it.id !== g.keep_id).map(it => it.id);
            return `<div class="dup-group" data-idx="${gi}">
                ${rows}
                <button class="btn-merge" data-keep="${g.keep_id}" data-remove="${removeIds.join(',')}">Zusammenführen</button>
            </div>`;
        }).join('');
        document.querySelectorAll('.btn-merge').forEach(btn => {
            btn.onclick = async () => {
                const keepId = parseInt(btn.dataset.keep, 10);
                const removeIds = btn.dataset.remove.split(',').filter(Boolean).map(Number);
                btn.disabled = true; btn.textContent = 'Führe zusammen …';
                try {
                    await AUSGABEN_API.mergeDuplicates(keepId, removeIds);
                    showToast('Duplikate zusammengeführt', 'success');
                    await Promise.all([loadExpenses(), loadDuplicates(), loadKpis()]);
                } catch (e) {
                    showToast('Fehler: ' + e.message, 'error');
                    btn.disabled = false; btn.textContent = 'Zusammenführen';
                }
            };
        });
    } catch (e) { console.warn(e); }
}

// Live-Reload bei Filter-Änderung
['filterType','filterStore','filterCategory','filterFrom','filterTo'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.onchange = () => {
        clearPresetActive();
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
    ['filterType','filterStore','filterCategory','filterFrom','filterTo','filterQ'].forEach(id => {
        const el = document.getElementById(id); if (el) el.value = '';
    });
    clearPresetActive();
    if (typeof updateFilterBadge === 'function') updateFilterBadge();
    if (typeof renderActiveFilterChips === 'function') renderActiveFilterChips();
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
    if (typeof updateFilterBadge === 'function') updateFilterBadge();
    if (typeof renderActiveFilterChips === 'function') renderActiveFilterChips();
    loadExpenses();
}
document.querySelectorAll('#datePresets button').forEach(b => {
    b.onclick = () => applyPreset(b.dataset.preset);
});

// downloadFile + Export-Link kommen aus ausgaben.js (renderSubnav)

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
    const ids = ['filterType','filterStore','filterCategory','filterFrom','filterTo'];
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
            '<button type="button" data-clear="' + id + '" aria-label="' + escapeHtml(label) + ' entfernen">✕</button></span>');
    };
    const typeEl = document.getElementById('filterType');
    if (typeEl && typeEl.value) push('filterType', 'Typ', typeEl.options[typeEl.selectedIndex].text);
    const storeEl = document.getElementById('filterStore');
    if (storeEl && storeEl.value) push('filterStore', 'Laden', storeEl.options[storeEl.selectedIndex].text);
    const catEl = document.getElementById('filterCategory');
    if (catEl && catEl.value) push('filterCategory', 'Kategorie', catEl.options[catEl.selectedIndex].text);
    const from = document.getElementById('filterFrom')?.value;
    const to = document.getElementById('filterTo')?.value;
    if (from && to) push('filterFromTo', 'Zeitraum', fmtDate(from) + ' – ' + fmtDate(to));
    else if (from) push('filterFrom', 'Ab', fmtDate(from));
    else if (to) push('filterTo', 'Bis', fmtDate(to));
    box.innerHTML = chips.join('');
    box.querySelectorAll('button[data-clear]').forEach(b => {
        b.onclick = () => {
            const id = b.dataset.clear;
            if (id === 'filterFromTo') {
                document.getElementById('filterFrom').value = '';
                document.getElementById('filterTo').value = '';
            } else {
                const el = document.getElementById(id); if (el) el.value = '';
            }
            clearPresetActive();
            updateFilterBadge();
            renderActiveFilterChips();
            loadExpenses();
        };
    });

/* v1.38.0 — "Neuer Bon"-Modal (iframe zu /ausgaben/neu.html?embed=1) */
function setupNewExpenseModal() {
    [document.getElementById('btnNewExpense'), document.getElementById('fabNewExpense')]
        .filter(Boolean)
        .forEach(b => b.addEventListener('click', openNewExpenseModal));
    window.addEventListener('message', (ev) => {
        if (ev.origin !== location.origin) return;
        const t = ev.data && ev.data.type;
        if (t === 'vexbob:expense-saved') {
            closeNewExpenseModal();
            showToast('Bon gespeichert', 'success', 1500);
            Promise.all([loadExpenses(), loadKpis(), loadRecurring(), loadDuplicates()]);
        } else if (t === 'vexbob:expense-cancel') {
            closeNewExpenseModal();
        }
    });
}

let _newExpOverlay = null;
function openNewExpenseModal() {
    if (_newExpOverlay) return;
    const overlay = document.createElement('div');
    overlay.className = 'new-exp-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Neuer Bon');
    overlay.innerHTML =
        '<div class="new-exp-box">' +
            '<div class="new-exp-head">' +
                '<h3>Neuer Bon</h3>' +
                '<button type="button" class="new-exp-close" aria-label="Schliessen">✕</button>' +
            '</div>' +
            '<iframe class="new-exp-frame" src="/ausgaben/neu.html?embed=1" title="Neuer Bon"></iframe>' +
        '</div>';
    document.body.appendChild(overlay);
    _newExpOverlay = overlay;
    overlay.dataset.prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    overlay.querySelector('.new-exp-close').onclick = closeNewExpenseModal;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeNewExpenseModal(); });
    document.addEventListener('keydown', _newExpKey);
    requestAnimationFrame(() => overlay.classList.add('show'));
}
function _newExpKey(e) { if (e.key === 'Escape') closeNewExpenseModal(); }
function closeNewExpenseModal() {
    if (!_newExpOverlay) return;
    const ov = _newExpOverlay; _newExpOverlay = null;
    ov.classList.remove('show');
    document.removeEventListener('keydown', _newExpKey);
    setTimeout(() => { ov.remove(); document.body.style.overflow = ov.dataset.prevOverflow || ''; }, 200);
}

}

