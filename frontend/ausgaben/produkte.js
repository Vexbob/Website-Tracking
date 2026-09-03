/* Produkte — v1.42.0
 * Zeigt alle gekauften Produkte mit Kaufhäufigkeit, Gesamtausgaben und den
 * Läden, in denen sie gekauft wurden.
 *
 * Ein Produkt ist EINE Zeile, unabhängig vom Laden — der Laden war nie Teil des
 * Gruppenschlüssels, aber jeder Laden druckt denselben Artikel anders auf den
 * Bon ("Gouda", "Gouda jung", "Goudakäse"), wodurch die KI drei Basisnamen
 * ableitete und es so wirkte, als würde nach Laden getrennt. Dagegen gibt es
 * jetzt die Zusammenführen-Vorschläge oben auf der Seite.
 *
 * Der frühere Preisvergleich (Ø-Preis je Einheit, günstigster Laden, €/kg) ist
 * entfallen: er hat €/Stück-Werte mit €/kg-Werten in denselben Durchschnitt
 * geworfen, sobald die Mengeneinheit fehlte. Gezeigt wird jetzt ausschließlich,
 * was tatsächlich bezahlt wurde.
 *
 * WICHTIG: Die Felder hier MÜSSEN zum Response von /api/expenses/products
 * passen (title, count, total_spent, avg_price, last_price, last_date, stores…).
 */

let allProducts = [];
let allCategories = [];
let allStores = [];
let mergeSuggestions = [];

// escHtml lokal definieren statt sich auf ein zufällig vorher geladenes Script
// zu verlassen (produkte.html lädt keine weiteren Seiten-Scripts).
if (typeof escHtml === 'undefined') {
    window.escHtml = function escHtml(s) {
        if (!s) return '';
        return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    };
}

async function init() {
    // statistik.css setzt body{visibility:hidden} und erwartet, dass JS nach dem
    // Laden 'ready' setzt. finally sorgt dafür, dass die Seite auch bei einem
    // Fehler sichtbar wird, statt für immer leer zu bleiben.
    try {
        const me = await ensureLoggedIn();
        if (!me) return;
        renderSubnav();
        await Promise.all([loadCategories(), loadStores()]);
        bindFilters();
        await Promise.all([loadProducts(), loadMergeSuggestions()]);
    } finally {
        document.body.classList.add('ready');
    }
}

async function loadCategories() {
    try {
        allCategories = await AUSGABEN_API.categories() || [];
        const sel = document.getElementById('prodCategory');
        sel.innerHTML = '<option value="">Alle Kategorien</option>' +
            allCategories.map(c => `<option value="${c.id}">${escHtml(c.icon || '')} ${escHtml(c.name)}</option>`).join('');
    } catch (e) { console.error(e); }
}

async function loadStores() {
    try {
        allStores = await AUSGABEN_API.stores() || [];
        const sel = document.getElementById('prodStore');
        sel.innerHTML = '<option value="">Alle Läden</option>' +
            allStores.map(s => `<option value="${s.id}">${escHtml(s.icon || '')} ${escHtml(s.name)}</option>`).join('');
    } catch (e) { console.error(e); }
}

function currentFilters() {
    const days = parseInt(document.getElementById('prodPeriod').value, 10);
    const filters = {};
    if (days > 0) {
        const from = new Date();
        from.setDate(from.getDate() - days);
        filters.date_from = from.toISOString().slice(0, 10);
    }
    const catId = document.getElementById('prodCategory').value;
    if (catId) filters.category_id = catId;
    const storeId = document.getElementById('prodStore').value;
    if (storeId) filters.store_id = storeId;
    return filters;
}

async function loadProducts() {
    const body = document.getElementById('prodBody');
    body.innerHTML = '<tr><td colspan="7" class="stat-empty">Lade …</td></tr>';
    try {
        // min_count=1: auch einmal gekaufte Produkte anzeigen — die Seite
        // beantwortet "was habe ich wie oft gekauft", da gehören Einmalkäufe dazu.
        allProducts = await AUSGABEN_API.products(1, currentFilters()) || [];
        renderProducts();
    } catch (e) {
        body.innerHTML = `<tr><td colspan="7" class="stat-empty">Fehler: ${escHtml(e.message)}</td></tr>`;
    }
}

// ---------- Zusammenführen-Vorschläge ----------

async function loadMergeSuggestions() {
    const box = document.getElementById('mergeBox');
    if (!box) return;
    try {
        mergeSuggestions = await AUSGABEN_API.mergeSuggestions() || [];
    } catch (e) {
        mergeSuggestions = [];
    }
    renderMergeSuggestions();
}

function renderMergeSuggestions() {
    const box = document.getElementById('mergeBox');
    if (!box) return;
    if (!mergeSuggestions.length) { box.innerHTML = ''; box.style.display = 'none'; return; }
    box.style.display = '';
    box.innerHTML = mergeSuggestions.map((s, i) => {
        const variants = s.variants.map(v => {
            const stores = (v.stores || []).join(', ');
            return `<li><strong>${escHtml(v.title)}</strong>
                <span class="merge-meta">${v.count}× ${stores ? '· ' + escHtml(stores) : ''}</span></li>`;
        }).join('');
        return `<div class="merge-card" data-idx="${i}">
            <div class="merge-head">
                <span class="merge-icon">🔗</span>
                <div>
                    <div class="merge-title">${s.variants.length} Schreibweisen von „${escHtml(s.suggested_title)}"?</div>
                    <div class="merge-sub">Zusammengeführt werden sie zu einer Produktzeile — auch für künftige Käufe.</div>
                </div>
            </div>
            <ul class="merge-variants">${variants}</ul>
            <div class="merge-actions">
                <input class="merge-name" value="${escHtml(s.suggested_title)}" aria-label="Name der zusammengeführten Gruppe">
                <button class="merge-do">Zusammenführen</button>
                <button class="merge-skip">Sind verschieden</button>
            </div>
        </div>`;
    }).join('');

    box.querySelectorAll('.merge-card').forEach(card => {
        const s = mergeSuggestions[+card.dataset.idx];
        card.querySelector('.merge-do').onclick = async () => {
            const title = card.querySelector('.merge-name').value.trim() || s.suggested_title;
            try {
                const r = await AUSGABEN_API.mergeProducts(s.keys, title);
                showToast(`Zusammengeführt (${r.items} Positionen)`, 'success');
                await Promise.all([loadProducts(), loadMergeSuggestions()]);
            } catch (e) { showToast('Fehler: ' + e.message, 'error'); }
        };
        card.querySelector('.merge-skip').onclick = async () => {
            try {
                await AUSGABEN_API.dismissMerge(s.keys);
                await loadMergeSuggestions();
            } catch (e) { showToast('Fehler: ' + e.message, 'error'); }
        };
    });
}

// ---------- Tabelle ----------

function storesCell(p) {
    const stores = p.stores || [];
    if (!stores.length) return '–';
    // Alle Läden, häufigster zuerst — ein Produkt bleibt EINE Zeile.
    return stores.map(s =>
        `<span class="prod-store" title="${escHtml(s.store_name)}: ${s.count}× · ${fmtEur(s.total)}">
            <span style="color:${s.store_color}">${s.store_icon || '🏪'}</span> ${escHtml(s.store_name)}
            ${stores.length > 1 ? `<span class="prod-store-n">${s.count}×</span>` : ''}
        </span>`).join('');
}

function renderProducts() {
    const body = document.getElementById('prodBody');
    const filtered = allProducts.slice();

    if (!filtered.length) {
        body.innerHTML = '<tr><td colspan="7" class="stat-empty">Keine Produkte gefunden.</td></tr>';
        updateKpis([]);
        return;
    }

    // Sortiert nach Kaufhäufigkeit (count)
    filtered.sort((a, b) => (b.count || 0) - (a.count || 0));

    body.innerHTML = filtered.map(p => {
        const lastBuy = p.last_date ? fmtDate(p.last_date) : '–';
        return `<tr class="prod-row" data-key="${escHtml(p.key)}">
            <td>
                <div class="prod-name">${escHtml(p.title || p.key)}${p.is_merged ? ' <span class="prod-merged" title="Manuell zusammengeführt — klicken zum Auftrennen">🔗</span>' : ''}</div>
                ${p.brand_name ? `<div class="prod-brand">${escHtml(p.brand_name)}</div>` : ''}
            </td>
            <td>${escHtml(p.category_name || '–')}</td>
            <td class="prod-stores">${storesCell(p)}</td>
            <td style="text-align:right;font-variant-numeric:tabular-nums">${p.count || 0}×</td>
            <td style="text-align:right;font-variant-numeric:tabular-nums">${fmtEur(p.total_spent || 0)}</td>
            <td style="text-align:right;font-variant-numeric:tabular-nums">${fmtEur(p.avg_price || 0)}</td>
            <td style="text-align:right">${lastBuy}</td>
        </tr>`;
    }).join('');

    updateKpis(filtered);

    body.querySelectorAll('.prod-row').forEach(row => {
        row.style.cursor = 'pointer';
        row.onclick = (ev) => {
            const key = row.dataset.key;
            const product = allProducts.find(p => p.key === key);
            if (!product) return;
            if (ev.target.classList.contains('prod-merged')) {
                ev.stopPropagation();
                splitProduct(product);
                return;
            }
            openProductDetail(key, product);
        };
    });
}

async function splitProduct(product) {
    if (!confirm(`„${product.title}" wieder auftrennen? Die Artikel fallen auf ihre einzelnen Namen zurück.`)) return;
    try {
        await AUSGABEN_API.splitProduct(product.key);
        showToast('Aufgetrennt', 'success');
        await Promise.all([loadProducts(), loadMergeSuggestions()]);
    } catch (e) { showToast('Fehler: ' + e.message, 'error'); }
}

function updateKpis(products) {
    const count = products.length;
    const buys = products.reduce((a, p) => a + (p.count || 0), 0);
    // Echte Summe der bezahlten Preise (früher: Ø-Einheitspreis × Anzahl —
    // eine Hochrechnung, die mit €/kg-Werten grob danebenlag).
    const total = products.reduce((a, p) => a + (p.total_spent || 0), 0);
    const avg = buys > 0 ? total / buys : 0;

    document.getElementById('kpiCount').textContent = count;
    document.getElementById('kpiTotal').textContent = fmtEur(total);
    document.getElementById('kpiAvg').textContent = fmtEur(avg);
    document.getElementById('kpiBuys').textContent = buys;
}

function bindFilters() {
    ['prodPeriod', 'prodCategory', 'prodStore'].forEach(id => {
        document.getElementById(id).addEventListener('change', loadProducts);
    });
    const rp = document.getElementById('prodReparse');
    if (rp) rp.onclick = openReparseModal;
}

// ---------- Bulk-Reparse aller Bons mit Foto ----------
// Zog von der entfernten Preisverlauf-Seite hierher um: bessere Artikelnamen und
// Mengeneinheiten sind genau das, was diese Seite braucht. Der Endpoint streamt
// NDJSON, wir lesen inkrementell mit.

function openReparseModal() {
    const modal = openModal('🔄 Alle Bons neu parsen', `
        <p style="margin-top:0;font-size:0.875rem;color:var(--text-muted)">
            Ruft für jeden Bon mit hinterlegtem Foto den KI-Parser erneut auf und
            <strong>ersetzt die Einzelpositionen</strong>. Kopfdaten (Betrag, Datum, Laden)
            bleiben unverändert. Der Vorgang kann pro Bon ein paar Sekunden dauern.
        </p>
        <div class="reparse-progress" style="display:none" id="reparseWrap">
            <div style="display:flex;justify-content:space-between;font-size:0.8125rem"><span id="reparseStatus">Starte …</span><span id="reparseCount">0/0</span></div>
            <div class="reparse-bar-wrap"><div class="reparse-bar" id="reparseBar"></div></div>
            <div class="reparse-log" id="reparseLog"></div>
        </div>
        <div style="display:flex;gap:0.5rem;justify-content:flex-end;margin-top:1rem">
            <button class="cancel" style="width:auto;margin:0;background:var(--surface-2);color:var(--text);border:1px solid var(--border)">Abbrechen</button>
            <button class="start primary" style="width:auto;margin:0;background:var(--teal);color:#fff">Los geht's</button>
        </div>
    `, { wide: true });
    modal.root.querySelector('.cancel').onclick = () => modal.close();
    modal.root.querySelector('.start').onclick = async () => {
        modal.root.querySelector('.start').disabled = true;
        modal.root.querySelector('.cancel').disabled = true;
        document.getElementById('reparseWrap').style.display = 'flex';
        await runReparse();
        await Promise.all([loadProducts(), loadMergeSuggestions()]);
    };
}

async function runReparse() {
    const bar = document.getElementById('reparseBar');
    const cnt = document.getElementById('reparseCount');
    const st = document.getElementById('reparseStatus');
    const log = document.getElementById('reparseLog');
    let res;
    try {
        res = await fetch(AUSGABEN_API.reparseAllUrl(), {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + getToken() },
        });
    } catch (e) {
        st.textContent = 'Verbindungsfehler';
        log.innerHTML += `<span class="err">Netzwerkfehler: ${escHtml(e.message)}</span>\n`;
        return;
    }
    if (!res.ok) {
        st.textContent = 'Server-Fehler ' + res.status;
        try { const t = await res.text(); log.innerHTML += `<span class="err">${escHtml(t.substring(0, 300))}</span>\n`; } catch (_) {}
        return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let total = 0;
    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop(); // Rest zurücklegen
        for (const line of lines) {
            if (!line.trim()) continue;
            let msg;
            try { msg = JSON.parse(line); } catch (_) { continue; }
            if (msg.type === 'start') {
                total = msg.total;
                st.textContent = total ? `Verarbeite ${total} Bons …` : 'Nichts zu tun (keine Bons mit Foto vorhanden)';
                cnt.textContent = `0/${total}`;
            } else if (msg.type === 'progress') {
                const pct = total ? Math.round((msg.processed / total) * 100) : 0;
                bar.style.width = pct + '%';
                cnt.textContent = `${msg.processed}/${total}`;
                if (msg.ok) {
                    log.innerHTML += `<span class="ok">✓ Bon #${msg.expense_id}: ${msg.items} Positionen</span>\n`;
                } else {
                    log.innerHTML += `<span class="err">✕ Bon #${msg.expense_id}: ${escHtml(msg.error || '')}</span>\n`;
                }
                log.scrollTop = log.scrollHeight;
            } else if (msg.type === 'done') {
                st.textContent = `Fertig — ${msg.updated_items} Positionen aktualisiert, ${msg.errors} Fehler`;
                bar.style.width = '100%';
                bar.style.background = msg.errors ? 'var(--orange)' : 'var(--teal)';
            }
        }
    }
}

// ---------- Detail-Modal: Kaufhistorie ----------
let currentChartInstance = null;

async function openProductDetail(key, product) {
    const modal = openModal(`🛒 ${escHtml(product.title || key)}`, `
        <div id="pvStores" class="pv-stores"></div>
        <div class="pv-chart-wrap"><canvas id="pvChart"></canvas></div>
        <div id="pvHistList" class="pv-hist-list"></div>
    `, { wide: true, onClose: () => {
        if (currentChartInstance) { try { currentChartInstance.destroy(); } catch(_) {} currentChartInstance = null; }
    }});

    try {
        const data = await AUSGABEN_API.productHistory(key);
        const items = data.items || [];
        renderStoreChips(data.stores || []);
        renderChart(items);
        renderHistList(items);
    } catch (e) {
        modal.root.innerHTML = `<div class="pv-empty">Fehler: ${escHtml(e.message)}</div>`;
    }
}

function renderStoreChips(stores) {
    const wrap = document.getElementById('pvStores');
    if (!wrap) return;
    if (!stores.length) { wrap.innerHTML = ''; return; }
    wrap.innerHTML = stores.map(s => `
        <span class="pv-store-chip">
            <span style="color:${s.store_color}">${s.store_icon || '🏪'}</span>
            ${escHtml(s.store_name)} · ${s.count}× · ${fmtEur(s.total)}
        </span>`).join('');
}

function renderChart(items) {
    const ctx = document.getElementById('pvChart');
    if (!ctx) return;
    if (currentChartInstance) { try { currentChartInstance.destroy(); } catch(_) {} }

    const sorted = items.slice().sort((a, b) => new Date(a.date) - new Date(b.date));
    const labels = sorted.map(h => fmtDate(h.date));
    // Bezahlter Preis, nicht hochgerechnet: eine 500-g-Packung und eine
    // 1-kg-Packung sind zwei ehrliche Punkte, keine vergleichbaren €/kg-Werte.
    const prices = sorted.map(h => h.total_price);

    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const tick = isDark ? '#a0a5b0' : '#666';

    currentChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: 'Bezahlt',
                data: prices,
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59,130,246,0.1)',
                fill: true,
                tension: 0.3,
                pointRadius: 3,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: {
                    afterLabel: (c) => {
                        const h = sorted[c.dataIndex];
                        const menge = h.quantity && h.quantity_unit
                            ? `${String(h.quantity).replace('.', ',')} ${h.quantity_unit}` : null;
                        return [h.store_name, menge].filter(Boolean).join(' · ');
                    }
                } }
            },
            scales: {
                x: { ticks: { color: tick, font: { size: 10 } }, grid: { display: false } },
                y: { beginAtZero: false, ticks: { color: tick, font: { size: 10 }, callback: v => fmtEur(v) }, grid: { color: isDark ? '#2a2e37' : '#f0f0f0' } }
            }
        }
    });
}

function renderHistList(items) {
    const wrap = document.getElementById('pvHistList');
    if (!items.length) {
        wrap.innerHTML = '<div class="pv-empty">Keine Käufe in dieser Gruppe.</div>';
        return;
    }
    wrap.innerHTML = items.slice().reverse().map(h => {
        const menge = h.quantity && h.quantity_unit
            ? `${String(h.quantity).replace('.', ',')} ${escHtml(h.quantity_unit)}`
            : '<span class="pv-hist-nounit" title="Auf dem Bon war keine Menge erkennbar">ohne Menge</span>';
        return `
        <div class="pv-hist-item">
            <span class="pv-hist-date">${fmtDate(h.date)}</span>
            <div class="pv-hist-body">
                <div class="pv-hist-desc">${escHtml(h.original_text || h.description || h.base_name || '')}</div>
                <div class="pv-hist-store" style="color:${h.store_color}">${h.store_icon} ${escHtml(h.store_name)} · ${menge}</div>
            </div>
            <span class="pv-hist-price">${fmtEur(h.total_price)}</span>
        </div>`;
    }).join('');
}

init();
