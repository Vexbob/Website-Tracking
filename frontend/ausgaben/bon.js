let stores = [], categories = [];
let currentExpense = null;
let imgBlobUrl = null;

function getId() {
    const p = new URLSearchParams(location.search);
    return +p.get('id') || null;
}
function escapeHtml(s) { if (!s) return ''; return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function escapeAttr(s) { return escapeHtml(s).replace(/"/g, '&quot;'); }

async function init() {
    const me = await ensureLoggedIn(); if (!me) return;
    renderSubnav();
    const id = getId();
    if (!id) { location.href = '/ausgaben/'; return; }
    try {
        [stores, categories, currentExpense] = await Promise.all([
            AUSGABEN_API.stores(), AUSGABEN_API.categories(), AUSGABEN_API.getExpense(id)
        ]);
    } catch(e) { showToast('Bon nicht gefunden', 'error'); setTimeout(() => location.href='/ausgaben/', 1500); return; }
    await render();
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';
}

async function render() {
    const e = currentExpense;
    const storeOpts = '<option value="">– Kein Laden –</option>' +
        stores.map(s => `<option value="${s.id}"${e.store_id==s.id?' selected':''}>${s.icon || ''} ${escapeHtml(s.name)}</option>`).join('');
    const paymentVal = e.payment_method || '';
    const pmts = [['','–'],['cash','Bar'],['card','EC/Karte'],['credit','Kreditkarte'],['paypal','PayPal'],['other','Sonstiges']];
    const paymentOpts = pmts.map(([v,l]) => `<option value="${v}"${v===paymentVal?' selected':''}>${l}</option>`).join('');
    const typeVal = e.expense_type || 'receipt';
    const types = [['receipt','🧾 Kassenbon'],['online_order','📦 Online-Bestellung'],['restaurant','🍽️ Restaurant'],['subscription','🔁 Abo'],['other','📌 Sonstiges']];
    const typeOpts = types.map(([v,l]) => `<option value="${v}"${v===typeVal?' selected':''}>${l}</option>`).join('');

    let imgHtml = '';
    if (e.receipt_image_id) {
        try {
            if (imgBlobUrl) URL.revokeObjectURL(imgBlobUrl);
            imgBlobUrl = await fetchImageAsBlobUrl(AUSGABEN_API.receiptImageUrl(e.receipt_image_id));
            imgHtml = `<div class="card"><img src="${imgBlobUrl}" class="preview-img"></div>`;
        } catch(err) { imgHtml = '<div class="card muted">Bild konnte nicht geladen werden</div>'; }
    }

    document.getElementById('content').innerHTML = `
        ${imgHtml}
        <div class="card">
            <div class="total-hdr">
                <div><strong>${escapeHtml(e.store_name || 'Ohne Laden')}</strong><div style="font-size:0.75rem;color:var(--text-muted)">${fmtDate(e.purchase_date)}</div></div>
                <div class="total-val">${fmtEur(e.total_amount)}</div>
            </div>
            <div style="margin-bottom:0.5rem"><label>Typ</label><select id="eType">${typeOpts}</select></div>
            <div class="form-row">
                <div><label>Datum</label><input type="date" id="eDate" value="${e.purchase_date || ''}"></div>
                <div><label>Laden</label><select id="eStore">${storeOpts}</select></div>
            </div>
            <div class="form-row">
                <div><label>Gesamtbetrag (€)</label><input type="number" step="0.01" id="eTotal" value="${e.total_amount || ''}"></div>
                <div><label>Zahlungsart</label><select id="ePayment">${paymentOpts}</select></div>
            </div>
            <div style="margin-top:0.5rem"><label>Notiz</label><textarea id="eNote">${escapeHtml(e.note || '')}</textarea></div>
            <div class="actions">
                <button id="eSave" class="primary">Speichern</button>
                <button id="eDelete" class="danger">Bon löschen</button>
                <a href="/ausgaben/" class="nav-btn" style="align-self:center">Zurück</a>
            </div>
        </div>
        <div class="card">
            <h3 style="margin-bottom:0.75rem">Positionen</h3>
            <div id="itemList" class="item-list"></div>
            <button id="addItemBtn" style="margin-top:0.5rem;width:auto;padding:0.375rem 0.75rem;font-size:0.8125rem;background:var(--surface-2);color:var(--text);border:1px solid var(--border)">+ Position</button>
        </div>
    `;
    renderItems();
    document.getElementById('eSave').onclick = saveExpense;
    document.getElementById('eDelete').onclick = deleteExpense;
    document.getElementById('addItemBtn').onclick = () => addNewItem();
}

function renderItems() {
    const c = document.getElementById('itemList');
    c.innerHTML = '';
    if (!currentExpense.items || currentExpense.items.length === 0) {
        c.innerHTML = '<div class="muted" style="font-size:0.8125rem">Keine Positionen. Für schnelle Ausgaben ohne Details ist das ok.</div>';
        return;
    }
    currentExpense.items.forEach(it => renderItemRow(it));
}

function renderItemRow(item) {
    const c = document.getElementById('itemList');
    const row = document.createElement('div');
    row.className = 'item-row';
    row.dataset.id = item.id || '';
    // Falls Item vom Preisvergleich ausgeschlossen ist: visuell abheben
    const comparable = item.price_comparable !== false;
    if (!comparable) row.classList.add('not-comparable');
    const catOpts = '<option value="">– Kategorie –</option>' +
        categories.map(cat => `<option value="${cat.id}"${item.category_id==cat.id?' selected':''}>${cat.icon || ''} ${escapeHtml(cat.name)}</option>`).join('');
    const reducedBadge = item.is_reduced
        ? `<span class="badge" style="background:#dcfce7;color:#166534;font-size:0.625rem;padding:1px 4px" title="${item.original_price ? 'Vorher: ' + item.original_price + ' €' : 'Reduziert'}">RED</span>`
        : '';
    const cmpTitle = comparable
        ? 'Aus Preisvergleich ausschließen (z.B. Einmalkauf)'
        : 'In Preisvergleich aufnehmen';
    const cmpIcon = comparable ? '📊' : '🚫';
    row.innerHTML = `
        <input type="text" class="d-desc" value="${escapeAttr(item.description||'')}" placeholder="Beschreibung">
        <input type="number" step="0.01" class="d-price" value="${item.total_price || ''}" placeholder="Preis">
        <select class="d-cat">${catOpts}</select>
        <button class="cmp" title="${cmpTitle}">${cmpIcon}</button>
        <button class="del" title="Entfernen">✕</button>
        ${reducedBadge}
    `;
    c.appendChild(row);
    const save = async () => {
        const desc = row.querySelector('.d-desc').value.trim();
        const price = parseFloat(row.querySelector('.d-price').value);
        const cat = row.querySelector('.d-cat').value;
        if (!desc || isNaN(price)) return;
        try {
            if (item.id) {
                await AUSGABEN_API.updateItem(item.id, {
                    description: desc, total_price: price,
                    quantity: item.quantity || 1, quantity_unit: item.quantity_unit || null,
                    category_id: cat ? +cat : null,
                    price_comparable: item.price_comparable !== false,
                });
            } else {
                const created = await AUSGABEN_API.addItem(currentExpense.id, {
                    description: desc, total_price: price, quantity: 1,
                    category_id: cat ? +cat : null,
                });
                item.id = created.id;
                row.dataset.id = created.id;
            }
            showToast('Gespeichert', 'success', 1200);
        } catch(err) { showToast('Fehler: ' + err.message, 'error'); }
    };
    row.querySelectorAll('input, select').forEach(el => { el.onchange = save; });
    // Preisvergleich-Toggle
    row.querySelector('.cmp').onclick = async () => {
        if (!item.id) {
            showToast('Erst speichern, dann Preisvergleich togglen', 'error');
            return;
        }
        const newVal = !(item.price_comparable !== false);
        try {
            await AUSGABEN_API.setItemComparable(item.id, newVal);
            item.price_comparable = newVal;
            row.classList.toggle('not-comparable', !newVal);
            const btn = row.querySelector('.cmp');
            btn.textContent = newVal ? '📊' : '🚫';
            btn.title = newVal
                ? 'Aus Preisvergleich ausschließen (z.B. Einmalkauf)'
                : 'In Preisvergleich aufnehmen';
            showToast(newVal ? 'Wieder im Preisvergleich' : 'Aus Preisvergleich ausgeschlossen', 'success', 1500);
        } catch (err) { showToast('Fehler: ' + err.message, 'error'); }
    };
    row.querySelector('.del').onclick = async () => {
        if (!item.id) { row.remove(); return; }
        if (!confirm('Position löschen?')) return;
        try { await AUSGABEN_API.deleteItem(item.id); row.remove(); showToast('Gelöscht', 'success', 1200); }
        catch(err) { showToast('Fehler: ' + err.message, 'error'); }
    };
}

function addNewItem() {
    // Wenn "keine Positionen"-Hinweis da ist, wegräumen
    const c = document.getElementById('itemList');
    if (c.querySelector('.muted')) c.innerHTML = '';
    renderItemRow({ description: '', total_price: '', category_id: null });
}

async function saveExpense() {
    const btn = document.getElementById('eSave'); btn.disabled = true;
    try {
        const body = {
            store_id: +document.getElementById('eStore').value || null,
            purchase_date: document.getElementById('eDate').value,
            total_amount: +document.getElementById('eTotal').value || 0,
            payment_method: document.getElementById('ePayment').value || null,
            is_recurring: false,
            expense_type: document.getElementById('eType').value || 'receipt',
            note: document.getElementById('eNote').value || null,
        };
        currentExpense = await AUSGABEN_API.updateExpense(currentExpense.id, body);
        showToast('Gespeichert', 'success');
    } catch(e) { showToast('Fehler: ' + e.message, 'error'); }
    finally { btn.disabled = false; }
}

async function deleteExpense() {
    if (!confirm('Diesen Bon wirklich löschen?')) return;
    try {
        await AUSGABEN_API.deleteExpense(currentExpense.id);
        showToast('Gelöscht', 'success');
        setTimeout(() => location.href = '/ausgaben/', 500);
    } catch(e) { showToast('Fehler: ' + e.message, 'error'); }
}

init();

