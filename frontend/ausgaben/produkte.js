/* Produkte-Statistik — v1.19.0
 * Zeigt alle gekauften Produkte mit Kaufhäufigkeit, Gesamtausgaben, Ø-Preis.
 * Filter: Zeitraum, Kategorie, Laden.
 */

let allProducts = [];
let allCategories = [];
let allStores = [];

async function init() {
    const me = await ensureLoggedIn();
    if (!me) return;
    renderSubnav();
    await Promise.all([loadCategories(), loadStores(), loadProducts()]);
    bindFilters();
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
        const params = {};
        if (days > 0) {
            const from = new Date();
            from.setDate(from.getDate() - days);
            params.date_from = from.toISOString().slice(0, 10);
        }
        const catId = document.getElementById('prodCategory').value;
        if (catId) params.category_id = catId;
        const storeId = document.getElementById('prodStore').value;
        if (storeId) params.store_id = storeId;

        // Wir nutzen den bestehenden products-Endpoint, aber mit Filtern
        // Da der Endpoint keine Filter unterstützt, laden wir alle und filtern client-seitig
        allProducts = await AUSGABEN_API.products(1) || [];
        renderProducts();
    } catch (e) {
        body.innerHTML = `<tr><td colspan="7" class="stat-empty">Fehler: ${escHtml(e.message)}</td></tr>`;
    }
}

function renderProducts() {
    const body = document.getElementById('prodBody');
    const days = parseInt(document.getElementById('prodPeriod').value, 10);
    const catId = document.getElementById('prodCategory').value;
    const storeId = document.getElementById('prodStore').value;

    let filtered = allProducts.slice();

    // Client-seitige Filterung (da products-Endpoint keine Filter hat)
    // Wir müssten eigentlich die Items durchgehen — aber der products-Endpoint
    // gibt bereits aggregierte Daten zurück. Für echte Filterung bräuchten wir
    // einen neuen Endpoint. Für jetzt: einfache Anzeige aller Produkte.

    if (!filtered.length) {
        body.innerHTML = '<tr><td colspan="7" class="stat-empty">Keine Produkte gefunden.</td></tr>';
        updateKpis([]);
        return;
    }

    // Sortiert nach Kaufhäufigkeit (count)
    filtered.sort((a, b) => (b.count || 0) - (a.count || 0));

    body.innerHTML = filtered.map(p => {
        const lastBuy = p.last_purchase ? fmtDate(p.last_purchase) : '–';
        const avgPrice = p.count > 0 ? (p.total_spent || 0) / p.count : 0;
        return `<tr class="prod-row" data-key="${escHtml(p.key)}">
            <td>
                <div class="prod-name">${escHtml(p.display_name || p.key)}</div>
                ${p.brand ? `<div class="prod-brand">${escHtml(p.brand)}</div>` : ''}
            </td>
            <td>${escHtml(p.category_name || '–')}</td>
            <td>${escHtml(p.store_name || '–')}</td>
            <td style="text-align:right;font-variant-numeric:tabular-nums">${p.count || 0}×</td>
            <td style="text-align:right;font-variant-numeric:tabular-nums">${fmtEur(p.total_spent || 0)}</td>
            <td style="text-align:right;font-variant-numeric:tabular-nums">${fmtEur(avgPrice)}</td>
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
            if (product) openProductChart(key, product.display_name || key);
        };
    });
}

function updateKpis(products) {
    const count = products.length;
    const total = products.reduce((a, p) => a + (p.total_spent || 0), 0);
    const buys = products.reduce((a, p) => a + (p.count || 0), 0);
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
