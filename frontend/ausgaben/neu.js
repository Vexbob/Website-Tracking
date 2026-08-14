let stores = [], categories = [];
let uploadedReceipt = null;
let uploadedImgUrl = null;

async function init() {
    const me = await ensureLoggedIn(); if (!me) return;
    try {
        [stores, categories] = await Promise.all([AUSGABEN_API.stores(), AUSGABEN_API.categories()]);
    } catch(e) { showToast('Laden fehlgeschlagen: ' + e.message, 'error'); return; }
    fillStoreSelects();
    document.getElementById('mDate').value = todayISO();
    setupTabs();
    setupOcrUpload();
    setupClipboardPaste();
    setupManualForm();
    addManualItemRow();
    try {
        const st = await AUSGABEN_API.ocrStatus();
        const el = document.getElementById('ocrStatus');
        if (st.available) el.innerHTML = '<span class="badge ok">OCR aktiv</span> Provider: ' + st.provider;
        else el.innerHTML = '<span class="badge warn">OCR nicht konfiguriert</span> Bild wird gespeichert, Werte manuell eintragen.';
    } catch(e) {}
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';
}

function fillStoreSelects() {
    const html = stores.map(s => `<option value="${s.id}">${s.icon || ''} ${escapeHtml(s.name)}</option>`).join('');
    ['mStore'].forEach(id => {
        const sel = document.getElementById(id);
        if (!sel) return;
        const prev = sel.value;
        sel.innerHTML = '<option value="">– Kein Laden –</option>' + html;
        if (prev) sel.value = prev;
    });
}

function setupTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const tab = btn.dataset.tab;
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
            document.getElementById(tab + 'Panel').classList.add('active');
            haptic('tap');
        };
    });
}

function setupOcrUpload() {
    const drop = document.getElementById('uploadDrop');
    const input = document.getElementById('fileInput');
    drop.onclick = () => input.click();
    drop.ondragover = e => { e.preventDefault(); drop.classList.add('dragover'); };
    drop.ondragleave = () => drop.classList.remove('dragover');
    drop.ondrop = e => {
        e.preventDefault(); drop.classList.remove('dragover');
        if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
    };
    input.onchange = () => { if (input.files.length) handleFile(input.files[0]); };
}

// Bild aus Zwischenablage per Strg+V einfügen (z.B. Screenshot oder kopiertes Bild).
function setupClipboardPaste() {
    window.addEventListener('paste', (e) => {
        // Nur wenn OCR-Tab aktiv und kein Text-Input fokussiert ist
        const ocrTabActive = document.getElementById('ocrPanel')?.classList.contains('active');
        if (!ocrTabActive) return;
        const tag = (document.activeElement?.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea') return;
        const items = e.clipboardData?.items;
        if (!items) return;
        for (const it of items) {
            if (it.kind === 'file' && it.type.startsWith('image/')) {
                const blob = it.getAsFile();
                if (blob) {
                    e.preventDefault();
                    // Blob als File verpacken, damit handleFile file.name/type nutzen kann
                    const ext = (blob.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
                    const file = new File([blob], `clipboard-${Date.now()}.${ext}`, { type: blob.type });
                    handleFile(file);
                    return;
                }
            }
        }
    });
}

async function handleFile(file) {
    if (!file.type.startsWith('image/')) { showToast('Nur Bilddateien erlaubt', 'error'); return; }
    const drop = document.getElementById('uploadDrop');
    drop.classList.add('working');
    drop.innerHTML = '<div class="icon">⏳</div><div style="font-weight:600">Wird verarbeitet …</div><div style="font-size:0.8125rem;color:var(--text-muted)" id="uploadStep">Bild wird komprimiert</div>';
    try {
        const compressed = await compressImage(file, 1600, 0.85);
        document.getElementById('uploadStep').textContent = 'Wird hochgeladen & OCR läuft …';
        const resp = await AUSGABEN_API.uploadReceipt(compressed, true);
        uploadedReceipt = resp.receipt;
        renderOcrEditForm(resp.ocr);
        // Diagnose-Text
        const ocr = resp.ocr || {};
        const p = ocr.parsed || {};
        let msg = '✓ Bild gespeichert';
        if (!ocr.provider_available) msg = '⚠️ Bild gespeichert – OCR nicht konfiguriert';
        else if (!ocr.available) msg = '⚠️ Bild gespeichert – OCR lieferte leeren Text';
        else {
            const found = [];
            if (p.store_hint) found.push('Laden');
            if (p.purchase_date) found.push('Datum');
            if (p.total_amount) found.push('Summe');
            if (p.payment_method) found.push('Zahlung');
            msg = '✓ OCR: ' + (found.length ? found.join(' + ') + ' erkannt' : 'kein Feld erkannt');
        }
        showToast(msg, ocr.available && p.total_amount ? 'success' : 'error', 4000);
    } catch(e) {
        showToast('Fehler: ' + e.message, 'error');
        resetUploadDrop();
    }
}

function resetUploadDrop() {
    const drop = document.getElementById('uploadDrop');
    drop.classList.remove('working');
    drop.innerHTML = '<div class="icon">📸</div><div style="font-weight:600;margin-bottom:0.25rem">Bild wählen</div><div style="font-size:0.8125rem;color:var(--text-muted)">Kamera nutzen oder Datei ziehen · JPG/PNG · max 8 MB</div><input type="file" id="fileInput" accept="image/*" capture="environment" style="display:none">';
    setupOcrUpload();
}

function escapeHtml(s) { if (!s) return ''; return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function escapeAttr(s) { return escapeHtml(s).replace(/"/g, '&quot;'); }

// Legt fehlende Kategorien an, die die AI per category_name vorgeschlagen hat,
// und trägt bei den Items category_id nach. Idempotent: existierende (case-insensitive)
// Kategorien werden wiederverwendet, ohne dass ein API-Call nötig ist.
async function ensureCategoriesFromParsed(parsed) {
    const items = parsed?.items || [];
    if (!items.length) return;

    // Lookup: name-lowercased -> id
    const byName = new Map(categories.map(c => [(c.name || '').toLowerCase(), c.id]));

    // Vor 1. Durchlauf: existierende Kategorien direkt auflösen und queued-Set bilden
    const toCreate = new Set(); // Namen (Original-Casing)
    for (const it of items) {
        if (it.category_id) continue;
        const name = (it.category_name || '').trim();
        if (!name) continue;
        const hit = byName.get(name.toLowerCase());
        if (hit) {
            it.category_id = hit;
        } else {
            toCreate.add(name);
        }
    }
    if (!toCreate.size) return;

    // Fehlende Kategorien anlegen (sequenziell, damit UniqueViolation deterministisch abgefangen wird)
    let createdCount = 0;
    for (const name of toCreate) {
        try {
            const created = await AUSGABEN_API.createCategory({ name });
            categories.push(created);
            byName.set(name.toLowerCase(), created.id);
            createdCount++;
        } catch (e) {
            // Vielleicht Race: nochmals frisch laden und Lookup versuchen
            try {
                const fresh = await AUSGABEN_API.categories();
                categories.length = 0;
                categories.push(...fresh);
                for (const c of fresh) byName.set((c.name || '').toLowerCase(), c.id);
            } catch (_) {}
            console.warn('Auto-Kategorie-Anlage:', name, e.message);
        }
    }
    // sort by name for stable Dropdown
    categories.sort((a, b) => (a.name || '').localeCompare(b.name || ''));

    // 2. Durchlauf: Items final zuweisen
    for (const it of items) {
        if (it.category_id) continue;
        const name = (it.category_name || '').trim().toLowerCase();
        if (!name) continue;
        const hit = byName.get(name);
        if (hit) it.category_id = hit;
    }

    if (createdCount > 0) {
        showToast(`${createdCount} neue Kategorie${createdCount === 1 ? '' : 'n'} angelegt`, 'success', 2500);
    }
}

async function renderOcrEditForm(ocr) {
    const card = document.getElementById('ocrEditCard');
    const parsed = ocr.parsed || {};
    let matchedStore = '';
    if (parsed.store_hint) {
        const found = stores.find(s => s.name.toLowerCase() === parsed.store_hint.toLowerCase());
        if (found) {
            matchedStore = found.id;
        } else {
            // Laden nicht in User-Liste -> automatisch anlegen (vom AI-Parser erkannt)
            try {
                const created = await AUSGABEN_API.createStore({ name: parsed.store_hint });
                stores.push(created);
                stores.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
                fillStoreSelects();
                matchedStore = created.id;
                showToast('Neuer Laden angelegt: ' + parsed.store_hint, 'success', 2500);
            } catch (e) {
                // Nicht kritisch — User kann Laden manuell setzen. Doppelter Name -> ignorieren.
                console.warn('Auto-Store-Anlage fehlgeschlagen:', e.message);
            }
        }
    }

    // Fehlende Kategorien aus AI-Vorschlägen (category_name) automatisch anlegen
    // und den Items die neue category_id nachtragen. So sind die Dropdowns direkt vorbelegt.
    await ensureCategoriesFromParsed(parsed);

    if (uploadedImgUrl) URL.revokeObjectURL(uploadedImgUrl);
    try { uploadedImgUrl = await fetchImageAsBlobUrl(AUSGABEN_API.receiptThumbUrl(uploadedReceipt.id)); } catch(e) {}
    const storeOpts = '<option value="">– Kein Laden –</option>' +
        stores.map(s => `<option value="${s.id}"${matchedStore==s.id?' selected':''}>${s.icon || ''} ${escapeHtml(s.name)}</option>`).join('');

    // Payment-Vorauswahl aus OCR
    const pmethodVal = parsed.payment_method || '';
    const pmts = [['','–'],['cash','Bar'],['card','EC/Karte'],['credit','Kreditkarte'],['paypal','PayPal'],['other','Sonstiges']];
    const paymentOpts = pmts.map(([v,l]) => `<option value="${v}"${v===pmethodVal?' selected':''}>${l}</option>`).join('');

    // Diagnose-Zeile für OCR
    let diagBadges = '';
    if (!ocr.provider_available) diagBadges = '<span class="badge warn">⚠️ OCR-Provider nicht konfiguriert</span> ';
    else if (!ocr.available) diagBadges = `<span class="badge warn">⚠️ OCR (${ocr.provider}) lieferte leeren Text</span> `;
    else diagBadges = `<span class="badge ok">OCR: ${ocr.provider} · ${ocr.text_length || 0} Zeichen</span> `;
    if (ocr.error) diagBadges += `<span class="badge warn" title="${escapeAttr(ocr.error)}">Fehler</span> `;

    const rawSection = ocr.raw_text ? `
        <details style="margin-bottom:0.75rem">
            <summary style="cursor:pointer;font-size:0.75rem;color:var(--text-muted)">🔍 OCR-Rohtext anzeigen (${ocr.text_length} Zeichen)</summary>
            <pre style="background:var(--surface-2);border:1px solid var(--border);border-radius:8px;padding:0.5rem;margin-top:0.375rem;font-size:0.6875rem;white-space:pre-wrap;max-height:220px;overflow:auto">${escapeHtml(ocr.raw_text)}</pre>
        </details>` : '';

    card.innerHTML = `
        ${uploadedImgUrl ? `<img src="${uploadedImgUrl}" class="preview-img">` : ''}
        <div style="font-size:0.8125rem;color:var(--text-muted);margin-bottom:0.75rem">
            ${diagBadges}
            ${parsed.store_hint ? '· Erkannt: <strong>' + escapeHtml(parsed.store_hint) + '</strong>' : ''}
        </div>
        ${rawSection}
        <div style="margin-bottom:0.5rem"><label>Typ</label>
        <select id="oType">
            <option value="receipt" selected>🧾 Kassenbon</option>
            <option value="online_order">📦 Online-Bestellung</option>
            <option value="restaurant">🍽️ Restaurant</option>
            <option value="subscription">🔁 Abo</option>
            <option value="other">📌 Sonstiges</option>
        </select></div>
        <div class="form-row">
            <div><label>Datum</label><input type="date" id="oDate" value="${parsed.purchase_date || todayISO()}"></div>
            <div><label>Laden</label><select id="oStore">${storeOpts}</select></div>
        </div>
        <div class="form-row">
            <div><label>Gesamtbetrag (€)</label><input type="number" step="0.01" id="oTotal" value="${parsed.total_amount || ''}"></div>
            <div><label>Zahlungsart</label><select id="oPayment">${paymentOpts}</select></div>
        </div>
        <label style="margin-top:0.25rem"><input type="checkbox" id="oRecurring"> Wiederkehrend</label>
        <div style="margin-top:1rem;padding:0.625rem;background:var(--surface-2);border:1px solid var(--border);border-radius:8px">
            <label style="display:flex;align-items:center;gap:0.5rem;margin:0;cursor:pointer;font-size:0.875rem">
                <input type="checkbox" id="oIncludeItems" checked style="width:auto;margin:0">
                <span>Einzelpositionen speichern (${(parsed.items||[]).length} erkannt) — für Preisverlauf & Detail-Statistik</span>
            </label>
        </div>
        <div id="oItemsWrap" style="margin-top:0.75rem">
            <div id="oItems" class="item-list"></div>
            <button id="oAddItem" style="margin-top:0.5rem;width:auto;padding:0.375rem 0.75rem;font-size:0.8125rem;background:var(--surface-2);color:var(--text);border:1px solid var(--border)">+ Position</button>
        </div>
        <div style="margin-top:0.75rem"><label>Notiz</label><textarea id="oNote"></textarea></div>
        <div id="oDupeWarn"></div>
        <div class="actions">
            <button id="oSave" class="primary">Bon speichern</button>
            <button id="oDiscard" class="secondary">Bild verwerfen</button>
        </div>
    `;
    card.style.display = '';
    const items = parsed.items || [];
    if (items.length === 0) addOcrItemRow();
    else items.forEach(it => addOcrItemRow(it));
    // Toggle für Positionen: aus = Positionen werden beim Speichern NICHT geschickt
    const includeCb = document.getElementById('oIncludeItems');
    const itemsWrap = document.getElementById('oItemsWrap');
    includeCb.onchange = () => { itemsWrap.style.display = includeCb.checked ? '' : 'none'; };
    document.getElementById('oAddItem').onclick = () => { addOcrItemRow(); includeCb.checked = true; itemsWrap.style.display = ''; };
    document.getElementById('oSave').onclick = saveOcrExpense;
    document.getElementById('oDiscard').onclick = discardReceipt;
    document.getElementById('oTotal').oninput =
    document.getElementById('oStore').onchange =
    document.getElementById('oDate').onchange = () => checkDupe('o');
    setTimeout(() => checkDupe('o'), 100);
}

function addOcrItemRow(item) { addItemRow('oItems', item); }
function addManualItemRow(item) { addItemRow('mItems', item); }

function addItemRow(containerId, item) {
    const c = document.getElementById(containerId);
    const row = document.createElement('div');
    row.className = 'item-row';
    if (item && item.is_reduced) row.dataset.isReduced = '1';
    if (item && item.original_price != null) row.dataset.originalPrice = item.original_price;
    const catOpts = '<option value="">– Kategorie –</option>' +
        categories.map(cat => `<option value="${cat.id}"${item && item.category_id==cat.id?' selected':''}>${cat.icon || ''} ${escapeHtml(cat.name)}</option>`).join('');
    const reducedBadge = item && item.is_reduced
        ? `<span class="badge" style="background:#dcfce7;color:#166534;font-size:0.625rem;padding:1px 4px" title="${item.original_price ? 'Vorher: ' + item.original_price + ' €' : 'Reduziert'}">RED</span>`
        : '';
    row.innerHTML = `
        <input type="text" class="d-desc" placeholder="Beschreibung" value="${item?escapeAttr(item.description||''):''}">
        <input type="number" step="0.01" class="d-price" placeholder="Preis" value="${item?item.total_price||'':''}">
        <select class="d-cat">${catOpts}</select>
        <button class="del" title="Entfernen">✕</button>
        ${reducedBadge}
    `;
    c.appendChild(row);
    row.querySelector('.del').onclick = () => row.remove();
    const descInput = row.querySelector('.d-desc');
    const catSelect = row.querySelector('.d-cat');
    descInput.onblur = async () => {
        if (catSelect.value || !descInput.value) return;
        try {
            const storeId = document.getElementById(containerId === 'oItems' ? 'oStore' : 'mStore')?.value;
            const res = await AUSGABEN_API.suggestRule({ description: descInput.value, store_id: storeId ? +storeId : null });
            if (res.category_id) catSelect.value = res.category_id;
        } catch(e) {}
    };
    if (item && !item.category_id && item.description) {
        setTimeout(() => descInput.dispatchEvent(new Event('blur')), 50);
    }
}

function collectItems(containerId) {
    const rows = document.querySelectorAll('#' + containerId + ' .item-row');
    const items = [];
    rows.forEach(r => {
        const desc = r.querySelector('.d-desc').value.trim();
        const price = parseFloat(r.querySelector('.d-price').value);
        if (!desc || isNaN(price)) return;
        const cat = r.querySelector('.d-cat').value;
        const it = { description: desc, total_price: price, category_id: cat ? +cat : null };
        // Reduziert-Info aus data-Attributen übernehmen (nur bei OCR-Vorbelegung)
        if (r.dataset.isReduced === '1') it.is_reduced = true;
        if (r.dataset.originalPrice) it.original_price = parseFloat(r.dataset.originalPrice);
        items.push(it);
    });
    return items;
}


async function saveOcrExpense() {
    const btn = document.getElementById('oSave'); btn.disabled = true;
    try {
        const includeItems = document.getElementById('oIncludeItems')?.checked;
        const items = includeItems ? collectItems('oItems') : [];
        const body = {
            store_id:  +document.getElementById('oStore').value || null,
            receipt_image_id: uploadedReceipt.id,
            purchase_date: document.getElementById('oDate').value,
            total_amount: +document.getElementById('oTotal').value || 0,
            payment_method: document.getElementById('oPayment').value || null,
            is_recurring:   document.getElementById('oRecurring').checked,
            expense_type:   document.getElementById('oType').value || 'receipt',
            note: document.getElementById('oNote').value || null,
            items,
        };
        const res = await AUSGABEN_API.createExpense(body);
        showToast('Bon gespeichert', 'success');
        setTimeout(() => location.href = '/ausgaben/bon.html?id=' + res.id, 600);
    } catch(e) { showToast('Fehler: ' + e.message, 'error'); btn.disabled = false; }
}

async function discardReceipt() {
    if (!uploadedReceipt) return;
    if (!confirm('Bild und OCR-Daten verwerfen?')) return;
    try { await AUSGABEN_API.deleteReceipt(uploadedReceipt.id); } catch(e) {}
    uploadedReceipt = null;
    document.getElementById('ocrEditCard').style.display = 'none';
    resetUploadDrop();
}

function setupManualForm() {
    document.getElementById('mAddItem').onclick = () => addManualItemRow();
    document.getElementById('mSave').onclick = async () => {
        const btn = document.getElementById('mSave'); btn.disabled = true;
        try {
            const items = collectItems('mItems');
            const body = {
                store_id:  +document.getElementById('mStore').value || null,
                purchase_date: document.getElementById('mDate').value,
                total_amount: +document.getElementById('mTotal').value || 0,
                payment_method: document.getElementById('mPayment').value || null,
                is_recurring:   document.getElementById('mRecurring').checked,
                expense_type:   document.getElementById('mType').value || 'receipt',
                note: document.getElementById('mNote').value || null,
                items,
            };
            if (!body.purchase_date || body.total_amount <= 0) {
                showToast('Datum und Betrag erforderlich', 'error'); btn.disabled = false; return;
            }
            const res = await AUSGABEN_API.createExpense(body);
            showToast('Bon gespeichert', 'success');
            setTimeout(() => location.href = '/ausgaben/bon.html?id=' + res.id, 500);
        } catch(e) { showToast('Fehler: ' + e.message, 'error'); btn.disabled = false; }
    };
}

async function checkDupe(prefix) {
    const dateEl = document.getElementById(prefix + 'Date');
    const totalEl = document.getElementById(prefix + 'Total');
    const storeEl = document.getElementById(prefix + 'Store');
    const warnEl = document.getElementById(prefix + 'DupeWarn');
    if (!warnEl) return;
    const d = dateEl?.value; const t = parseFloat(totalEl?.value);
    if (!d || isNaN(t) || t <= 0) { warnEl.innerHTML = ''; return; }
    try {
        const rows = await AUSGABEN_API.checkDuplicate(d, t, storeEl?.value ? +storeEl.value : null);
        if (rows.length) {
            warnEl.innerHTML = `<div class="dupe-warn">⚠️ Achtung: es existiert bereits ein ähnlicher Bon vom ${fmtDate(rows[0].purchase_date)} mit ${fmtEur(rows[0].total_amount)}. Duplikat?</div>`;
        } else warnEl.innerHTML = '';
    } catch(e) {}
}

init();

