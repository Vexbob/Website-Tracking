/* Marken-Verwaltung (v1.16.0). */

let allBrands = [];
let allStores = [];
let currentFilter = 'all';

async function init() {
    const me = await ensureLoggedIn(); if (!me) return;
    renderSubnav();
    try {
        // v1.21.0: standardmaessig nach Kaufhaeufigkeit sortiert laden
        // (liefert purchase_count pro Marke mit).
        [allBrands, allStores] = await Promise.all([
            AUSGABEN_API.brands('purchases'),
            AUSGABEN_API.stores(),
        ]);
    } catch (e) {
        showToast('Laden fehlgeschlagen: ' + e.message, 'error');
        allBrands = []; allStores = [];
    }
    const sel = document.getElementById('newStore');
    allStores.forEach(s => {
        const o = document.createElement('option');
        o.value = s.id; o.textContent = (s.icon || '') + ' ' + s.name;
        sel.appendChild(o);
    });
    document.getElementById('newBtn').onclick = createBrand;
    document.getElementById('q').addEventListener('input', render);
    document.querySelectorAll('.filter-chip').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.filter-chip').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentFilter = btn.dataset.filter;
            render();
        };
    });
    render();
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';
}

function escHtml(s) { if (!s) return ''; return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function render() {
    const q = (document.getElementById('q').value || '').trim().toLowerCase();
    let list = allBrands.slice();
    if (currentFilter === 'private') list = list.filter(b => b.is_private_label);
    else if (currentFilter === 'brand') list = list.filter(b => !b.is_private_label);
    if (q) list = list.filter(b => (b.name || '').toLowerCase().includes(q));

    document.getElementById('brandCount').textContent =
        list.length + (list.length === allBrands.length ? ' Marken' : ` von ${allBrands.length} Marken`);

    const wrap = document.getElementById('list');
    if (!list.length) {
        wrap.innerHTML = '<div style="text-align:center;padding:1.5rem;color:var(--text-faint);font-size:0.875rem">Keine Marken gefunden.</div>';
        return;
    }
    // v1.21.0: Standard-Ranking nach Kaufhaeufigkeit (meistgekaufte Marke oben),
    // bei Gleichstand alphabetisch als Tiebreaker.
    list.sort((a, b) => (b.purchase_count || 0) - (a.purchase_count || 0)
        || (a.name || '').localeCompare(b.name || '', 'de'));
    wrap.innerHTML = list.map(renderBrandRow).join('');
    wrap.querySelectorAll('.brand-row').forEach(row => {
        const id = +row.dataset.id;
        const brand = allBrands.find(b => b.id === id);
        if (!brand) return;
        const storeSelect = row.querySelector('select.store');
        if (storeSelect) {
            storeSelect.onchange = async () => {
                const newVal = storeSelect.value ? +storeSelect.value : null;
                const isPrivate = newVal !== null;
                try {
                    await AUSGABEN_API.updateBrand(id, { store_id: newVal, is_private_label: isPrivate });
                    brand.store_id = newVal;
                    brand.is_private_label = isPrivate;
                    // Store-Name/-Icon nachziehen fuer korrekte Anzeige
                    const st = allStores.find(s => s.id === newVal);
                    brand.store_name = st ? st.name : null;
                    brand.store_color = st ? st.color : null;
                    brand.store_icon = st ? st.icon : null;
                    showToast('Aktualisiert', 'success', 1000);
                    render();
                } catch (e) { showToast('Fehler: ' + e.message, 'error'); }
            };
        }
        const delBtn = row.querySelector('button.del');
        if (delBtn) {
            delBtn.onclick = async () => {
                if (!confirm(`Marke "${brand.name}" löschen? Bestehende Artikel verlieren die Verknüpfung, bleiben aber erhalten.`)) return;
                try {
                    await AUSGABEN_API.deleteBrand(id);
                    allBrands = allBrands.filter(b => b.id !== id);
                    showToast('Gelöscht', 'success', 1000);
                    render();
                } catch (e) { showToast('Fehler: ' + e.message, 'error'); }
            };
        }
    });
}

function renderBrandRow(b) {
    const isSystem = b.seed_source === 'system';
    const badge = b.is_private_label
        ? `<span class="brand-badge private" title="Eigenmarke${b.store_name ? ' von ' + escHtml(b.store_name) : ''}">Eigenmarke</span>`
        : `<span class="brand-badge parent">Marke</span>`;
    const parent = b.parent_company ? `<span title="Mutterkonzern">🏭 ${escHtml(b.parent_company)}</span>` : '';
    const storeInfo = b.store_name
        ? `<span style="color:${b.store_color || 'inherit'}">${b.store_icon || '🏪'} ${escHtml(b.store_name)}</span>`
        : '';
    // v1.21.0: Kaufhaeufigkeit anzeigen
    const count = b.purchase_count || 0;
    const purchaseBadge = count > 0
        ? `<span class="brand-purchases" title="${count}× gekauft">🛒 ${count}×</span>`
        : `<span class="brand-purchases muted" title="Noch nie gekauft">🛒 0×</span>`;
    const storeOpts = ['<option value="">— kein Laden (Hersteller-Marke) —</option>']
        .concat(allStores.map(s =>
            `<option value="${s.id}"${b.store_id === s.id ? ' selected' : ''}>${escHtml((s.icon || '') + ' ' + s.name)}</option>`
        )).join('');
    return `<div class="brand-row${isSystem ? ' system' : ''}" data-id="${b.id}">
        <div style="min-width:0">
            <div class="brand-name">${escHtml(b.name)}</div>
            <div class="brand-meta">${purchaseBadge} ${badge} ${storeInfo} ${parent} ${isSystem ? '<span title="Vom System vorbelegt">📦 System</span>' : '<span title="Von dir angelegt">👤 Eigen</span>'}</div>
        </div>
        <div></div>
        <select class="store" title="Ladenzuordnung ändern (Eigenmarke / Hersteller)">${storeOpts}</select>
        <button class="del" title="Löschen">🗑</button>
    </div>`;
}

async function createBrand() {
    const name = document.getElementById('newName').value.trim();
    if (!name) { showToast('Name erforderlich', 'error'); return; }
    const storeId = document.getElementById('newStore').value;
    try {
        const created = await AUSGABEN_API.createBrand({
            name,
            store_id: storeId ? +storeId : null,
            is_private_label: !!storeId,
        });
        // Server liefert store_name/-icon nicht direkt zurueck -> nachziehen
        if (created.store_id) {
            const st = allStores.find(s => s.id === created.store_id);
            if (st) { created.store_name = st.name; created.store_color = st.color; created.store_icon = st.icon; }
        }
        allBrands.push(created);
        document.getElementById('newName').value = '';
        document.getElementById('newStore').value = '';
        showToast('Marke angelegt', 'success', 1000);
        render();
    } catch (e) { showToast('Fehler: ' + e.message, 'error'); }
}

init();
