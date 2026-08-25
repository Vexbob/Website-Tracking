/* Produkte-Statistik — v1.20.0
 * Zeigt alle gekauften Produkte mit Kaufhäufigkeit, Gesamtausgaben, Ø-Preis.
 * Filter: Zeitraum, Kategorie, Laden — werden an den Server geschickt.
 *
 * WICHTIG: Die Felder hier MÜSSEN zum echten Response von
 * /api/expenses/products passen (title, count, last_price, last_date,
 * last_store_name, category_name, min_price, max_price, avg_unit_price, ...).
 * Frühere Version hat mit nie existierenden Feldern (display_name,
 * total_spent, last_purchase, store_name, brand) gerechnet -> Tabelle wirkte leer.
 */

let allProducts = [];
let allCategories = [];
let allStores = [];

// v1.20.1: escHtml war nirgends global definiert, wenn diese Seite ohne
// preisverlauf.js geladen wird (produkte.html laedt es nicht) -> ReferenceError
// beim ersten renderProducts()-Aufruf -> Seite blieb bei "Lade …" haengen und
// wirkte komplett leer. Fix: escHtml lokal definieren statt sich auf ein
// zufaellig vorher geladenes Script zu verlassen.
if (typeof escHtml === 'undefined') {
    window.escHtml = function escHtml(s) {
        if (!s) return '';
        return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    };
}

async function init() {
    // v1.21.3: statistik.css (von dieser Seite mitgeladen) setzt
    // body{visibility:hidden} und erwartet, dass JS nach dem Laden die Klasse
    // 'ready' hinzufuegt (body.ready{visibility:visible}). Das fehlte hier
    // komplett -> die Seite blieb UNSICHTBAR obwohl Navbar, Tabelle und alle
    // Daten laengst korrekt im DOM standen ("nur Hintergrundfarbe" sichtbar).
    // finally stellt sicher, dass die Seite auch bei einem Fehler irgendwo
    // in init() sichtbar wird, statt fuer immer leer zu bleiben.
    try {
        const me = await ensureLoggedIn();
        if (!me) return;
        renderSubnav();
        await Promise.all([loadCategories(), loadStores()]);
        bindFilters();
        await loadProducts();
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

async function loadProducts() {
    const body = document.getElementById('prodBody');
    body.innerHTML = '<tr><td colspan="7" class="stat-empty">Lade …</td></tr>';
    try {
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

        // min_count=1: auch einmal gekaufte Produkte anzeigen (User will "was wie
        // oft gekauft" sehen — auch Einmalkäufe zählen dazu).
        allProducts = await AUSGABEN_API.products(1, filters) || [];
        renderProducts();
    } catch (e) {
        body.innerHTML = `<tr><td colspan="7" class="stat-empty">Fehler: ${escHtml(e.message)}</td></tr>`;
    }
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
        // "Gesamt ausgegeben" gibt es nicht direkt vom Server — approximiert über
        // Ø-Einheitspreis * Anzahl (gut genug für die Übersicht; exakte Summe
        // würde eine eigene Aggregation je Item benötigen).
        const totalApprox = (p.avg_unit_price || 0) * (p.count || 0);
        return `<tr class="prod-row" data-key="${escHtml(p.key)}">
            <td>
                <div class="prod-name">${escHtml(p.title || p.key)}</div>
                ${p.brand_name ? `<div class="prod-brand">${escHtml(p.brand_name)}</div>` : ''}
            </td>
            <td>${escHtml(p.category_name || '–')}</td>
            <td>
                <span style="color:${p.last_store_color || '#9ca3af'}">${p.last_store_icon || ''}</span>
                ${escHtml(p.last_store_name || '–')}
            </td>
            <td style="text-align:right;font-variant-numeric:tabular-nums">${p.count || 0}×</td>
            <td style="text-align:right;font-variant-numeric:tabular-nums">${fmtEur(totalApprox)}</td>
            <td style="text-align:right;font-variant-numeric:tabular-nums">${fmtEur(p.last_price || 0)}</td>
            <td style="text-align:right">${lastBuy}</td>
        </tr>`;
    }).join('');

    updateKpis(filtered);

    // Klick auf Zeile → Preisverlauf-Modal
    body.querySelectorAll('.prod-row').forEach(row => {
        row.style.cursor = 'pointer';
        row.onclick = () => {
            const key = row.dataset.key;
            const product = allProducts.find(p => p.key === key);
            if (product) openProductChart(key, product.title || key);
        };
    });
}

function updateKpis(products) {
    const count = products.length;
    const buys = products.reduce((a, p) => a + (p.count || 0), 0);
    const total = products.reduce((a, p) => a + (p.avg_unit_price || 0) * (p.count || 0), 0);
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
}

// Preisverlauf-Modal (aus preisverlauf.js übernommen, vereinfacht)
let currentChartInstance = null;

async function openProductChart(key, title) {
    const modal = openModal(`📈 ${escHtml(title)}`, `
        <div class="pv-chart-wrap"><canvas id="pvChart"></canvas></div>
        <div id="pvHistList" class="pv-hist-list"></div>
    `, { wide: true, onClose: () => {
        if (currentChartInstance) { try { currentChartInstance.destroy(); } catch(_) {} currentChartInstance = null; }
    }});

    try {
        const data = await AUSGABEN_API.productHistory(key);
        const items = data.items || [];
        renderChart(items);
        renderHistList(items);
    } catch (e) {
        modal.root.innerHTML = `<div class="pv-empty">Fehler: ${escHtml(e.message)}</div>`;
    }
}

function renderChart(items) {
    const ctx = document.getElementById('pvChart');
    if (!ctx) return;
    if (currentChartInstance) { try { currentChartInstance.destroy(); } catch(_) {} }

    const sorted = items.slice().sort((a, b) => new Date(a.date) - new Date(b.date));
    const labels = sorted.map(h => fmtDate(h.date));
    const prices = sorted.map(h => h.unit_price || h.total_price);

    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const tick = isDark ? '#a0a5b0' : '#666';

    currentChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: 'Preis',
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
            plugins: { legend: { display: false } },
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
    wrap.innerHTML = items.slice().reverse().map(h => `
        <div class="pv-hist-item">
            <span class="pv-hist-date">${fmtDate(h.date)}</span>
            <div class="pv-hist-body">
                <div class="pv-hist-desc">${escHtml(h.original_text || h.description || h.base_name || '')}</div>
                <div class="pv-hist-store" style="color:${h.store_color}">${h.store_icon} ${escHtml(h.store_name)}</div>
            </div>
            <span class="pv-hist-price">${fmtEur(h.total_price)}</span>
        </div>
    `).join('');
}

init();
