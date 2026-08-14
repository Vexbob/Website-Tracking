let allProducts = [];

function escHtml(s) { if (!s) return ''; return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

async function init() {
    const me = await ensureLoggedIn(); if (!me) return;
    renderSubnav();
    try {
        allProducts = await AUSGABEN_API.products();
    } catch (e) {
        document.getElementById('pvList').innerHTML = `<div class="pv-empty">Fehler: ${escHtml(e.message)}</div>`;
        allProducts = [];
    }
    document.getElementById('pvSearch').addEventListener('input', render);
    document.getElementById('pvFilter').onchange = render;
    render();
    // Klick auf Kachel öffnet Chart-Modal
    document.getElementById('pvList').addEventListener('click', (e) => {
        const card = e.target.closest('.pv-item');
        if (!card) return;
        const key = card.dataset.key;
        if (key) openProductChart(key, card.dataset.title || '');
    });
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';
}

// Trennt "Basisname 2kg (Original)" in { base, extras }
function splitDescription(desc) {
    if (!desc) return { base: '', extras: '' };
    const m = desc.match(/^(.*?)\s*\(([^)]+)\)\s*$/);
    if (m) return { base: m[1].trim(), extras: m[2].trim() };
    return { base: desc.trim(), extras: '' };
}

function render() {
    const q = (document.getElementById('pvSearch').value || '').trim().toLowerCase();
    const filter = document.getElementById('pvFilter').value;
    let list = allProducts;
    if (q) {
        list = list.filter(p => (p.description || '').toLowerCase().includes(q) ||
                                (p.key || '').includes(q));
    }
    if (filter === 'reduced') {
        list = list.filter(p => p.last_is_reduced);
    } else if (filter === 'up') {
        list = list.filter(p => p.price_change_direction === 'up');
    } else if (filter === 'down') {
        list = list.filter(p => p.price_change_direction === 'down');
    }

    const wrap = document.getElementById('pvList');
    if (!list.length) {
        wrap.innerHTML = `<div class="pv-empty"><div class="icon">💶</div>${
            allProducts.length ? 'Keine Treffer für diese Filter.' :
            'Noch keine gespeicherten Positionen. Lade Bons mit „Einzelpositionen speichern" hoch.'
        }</div>`;
        return;
    }
    wrap.innerHTML = '<div class="pv-grid">' + list.map(renderProductCard).join('') + '</div>';
}

function renderProductCard(p) {
    const { base, extras } = splitDescription(p.description);

    // Klassen für farbliche Markierung
    let cardCls = '';
    if (p.last_is_reduced) cardCls = 'reduced';
    else if (p.price_change_direction === 'up') cardCls = 'increased';
    else if (p.price_change_direction === 'down') cardCls = 'decreased';

    // Aktueller Preis + ggf. Originalpreis
    const priceHtml = `<div class="pv-prices">
        <span class="pv-current">${fmtEur(p.last_price)}</span>
        ${p.last_original_price ? `<span class="pv-orig">${fmtEur(p.last_original_price)}</span>` : ''}
        ${p.last_is_reduced ? '<span class="pv-badge">REDUZIERT</span>' : ''}
    </div>`;

    // Preisänderung ggü. vorherigem Kauf
    let changeHtml = '';
    if (p.price_change_direction && p.price_change_pct != null) {
        const cls = p.price_change_direction; // 'up' | 'down'
        const arrow = cls === 'up' ? '▲' : '▼';
        const sign = p.price_change_pct > 0 ? '+' : '';
        const abs = p.price_change_abs != null
            ? ` (${p.price_change_abs > 0 ? '+' : ''}${fmtEur(p.price_change_abs).replace('€', '€')})`
            : '';
        changeHtml = `<span class="pv-change ${cls}">${arrow} ${sign}${p.price_change_pct}%${abs}</span>`;
    }

    // Einheitspreise
    const unitBits = [];
    if (p.price_per_kg != null) unitBits.push(`<span><strong>${fmtEur(p.price_per_kg)}</strong>/kg</span>`);
    if (p.price_per_l != null) unitBits.push(`<span><strong>${fmtEur(p.price_per_l)}</strong>/L</span>`);
    if (p.last_quantity && p.last_quantity > 1 && !p.price_per_kg && !p.price_per_l) {
        const unit = p.last_quantity_unit || 'Stk';
        unitBits.push(`<span>${p.last_quantity} ${escHtml(unit)}</span>`);
    }
    const unitHtml = unitBits.length ? `<div class="pv-unit">${unitBits.join(' · ')}</div>` : '';

    // Meta-Chips: Laden, Kategorie, Datum, Anzahl Käufe
    const chips = [];
    chips.push(`<span class="chip" style="color:${p.last_store_color}">${p.last_store_icon} ${escHtml(p.last_store_name)}</span>`);
    if (p.category_name) chips.push(`<span class="chip">${escHtml(p.category_name)}</span>`);
    chips.push(`<span class="chip">${fmtDate(p.last_date)}</span>`);
    if (p.count > 1) chips.push(`<span class="chip">${p.count}× gekauft</span>`);

    const titleAttr = (base || p.description || '').replace(/"/g, '&quot;');
    return `<div class="pv-item ${cardCls}" data-key="${escHtml(p.key)}" data-title="${titleAttr}" role="button" tabindex="0">
        <div class="pv-title">${escHtml(base || p.description)}${extras ? `<small>${escHtml(extras)}</small>` : ''}</div>
        ${priceHtml}
        <div style="display:flex;justify-content:space-between;align-items:center;gap:0.5rem;flex-wrap:wrap">
            ${unitHtml}
            ${changeHtml}
        </div>
        <div class="pv-meta">${chips.join('')}</div>
    </div>`;
}

async function openProductChart(key, title) {
    const modal = openModal(`📈 Preisverlauf: ${escHtml(title)}`,
        `<div class="pv-chart-wrap"><canvas id="pvChart"></canvas></div><div id="pvHistList"></div>`,
        { wide: true }
    );
    try {
        const history = await AUSGABEN_API.productHistory(key);
        if (!history.length) {
            modal.root.innerHTML = '<div class="pv-empty">Keine Käufe gefunden.</div>';
            return;
        }
        // Chart: Einzelpreis über Zeit, farblich nach Laden
        const byStore = {};
        for (const h of history) {
            const sn = h.store_name;
            if (!byStore[sn]) byStore[sn] = { color: h.store_color, points: [] };
            byStore[sn].points.push({ x: h.date, y: h.unit_price });
        }
        const datasets = Object.entries(byStore).map(([name, obj]) => ({
            label: name,
            data: obj.points,
            borderColor: obj.color,
            backgroundColor: obj.color,
            tension: 0.2,
            spanGaps: true,
        }));
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const textCol = isDark ? '#a0a5b0' : '#666';
        const gridCol = isDark ? '#2a2e37' : '#e8e8e8';
        new Chart(document.getElementById('pvChart'), {
            type: 'line',
            data: { datasets },
            options: {
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: textCol, font: { size: 11 } } },
                    tooltip: { callbacks: {
                        label: (c) => c.dataset.label + ': ' + fmtEur(c.parsed.y) + ' / Einheit',
                    } },
                },
                scales: {
                    x: {
                        type: 'category',
                        ticks: { color: textCol, maxRotation: 0, autoSkip: true, autoSkipPadding: 20,
                                 callback: function(v) { const d = new Date(this.getLabelForValue(v)+'T00:00:00'); return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' }); } },
                        grid: { display: false },
                    },
                    y: { ticks: { color: textCol, callback: v => fmtEur(v) }, grid: { color: gridCol }, beginAtZero: true },
                },
            },
        });
        // History-Liste unter dem Chart (neueste oben)
        const listHtml = history.slice().reverse().map(h => `
            <div class="pv-hist-item">
                <span class="pv-hist-date">${fmtDate(h.date)}</span>
                <span class="pv-hist-store" style="color:${h.store_color}">${h.store_icon} ${escHtml(h.store_name)}${h.quantity > 1 ? ` · ${h.quantity}${h.quantity_unit || ''}` : ''}</span>
                <span class="pv-hist-price${h.is_reduced ? ' reduced' : ''}">${fmtEur(h.total_price)}${h.is_reduced ? ' 🏷️' : ''}</span>
            </div>
        `).join('');
        document.getElementById('pvHistList').innerHTML = listHtml;
    } catch (e) {
        modal.root.innerHTML = `<div class="pv-empty">Fehler: ${escHtml(e.message)}</div>`;
    }
}

init();
