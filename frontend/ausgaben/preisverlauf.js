let allProducts = [];
let historyCache = new Map();  // key -> product-history (fuer Sparkline)
let currentView = 'grid';       // 'grid' | 'list'  (v1.16.0)

function escHtml(s) { if (!s) return ''; return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

async function init() {
    const me = await ensureLoggedIn(); if (!me) return;
    renderSubnav();
    try {
        // v1.16.0: Backend filtert bereits nur Produkte mit >=2 Käufen oder Marken-Bezug
        allProducts = await AUSGABEN_API.products(2);
    } catch (e) {
        document.getElementById('pvList').innerHTML = `<div class="pv-empty">Fehler: ${escHtml(e.message)}</div>`;
        allProducts = [];
    }
    document.getElementById('pvSearch').addEventListener('input', render);
    document.getElementById('pvReparse').onclick = openReparseModal;
    document.querySelectorAll('.pv-toolbar-toggle button').forEach(btn => {
        btn.onclick = () => {
            document.querySelectorAll('.pv-toolbar-toggle button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentView = btn.dataset.view;
            render();
        };
    });
    render();
    // Klick auf Kachel / Zeile öffnet Chart-Modal
    document.getElementById('pvList').addEventListener('click', (e) => {
        const card = e.target.closest('.pv-tile, .pv-item');
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
    let list = allProducts;
    if (q) {
        list = list.filter(p => (p.description || '').toLowerCase().includes(q) ||
                                (p.title || '').toLowerCase().includes(q) ||
                                (p.brand_name || '').toLowerCase().includes(q) ||
                                (p.key || '').includes(q));
    }
    const wrap = document.getElementById('pvList');
    if (!list.length) {
        wrap.innerHTML = `<div class="pv-empty"><div class="icon">💶</div>${
            allProducts.length ? 'Keine Treffer.' :
            'Noch keine geeigneten Produkte. Lade Bons mit „Einzelpositionen speichern" hoch und kaufe Produkte mind. 2× — dann tauchen sie hier auf.'
        }</div>`;
        return;
    }
    list = list.slice().sort((a, b) => {
        const rank = (p) => p.price_change_direction === 'up' ? 0 :
                           p.price_change_direction === 'down' ? 1 : 2;
        const r = rank(a) - rank(b);
        if (r !== 0) return r;
        return (a.title || a.key || '').localeCompare(b.title || b.key || '');
    });
    if (currentView === 'grid') {
        wrap.className = 'pv-grid';
        wrap.innerHTML = list.map(renderProductTile).join('');
        list.forEach(p => loadSparkline(p.key));
    } else {
        wrap.className = 'pv-list';
        wrap.innerHTML = list.map(renderProductRow).join('');
    }
}

// Kompakte Listen-Zeile — eine Zeile pro Produkt.
// Grid: Name+Meta | Preis-Spalte | Änderungsbadge
function renderProductRow(p) {
    // Backend liefert 'title' als Basisname; Fallback für Alt-Daten
    const name = p.title || (p.base_name) || splitDescription(p.description).base || p.description || '(unbekannt)';

    // Preisänderungs-Klasse für den linken Border
    let rowCls = '';
    if (p.price_change_direction === 'up') rowCls = 'up';
    else if (p.price_change_direction === 'down') rowCls = 'down';

    // Preis-Sub: bevorzugt €/kg oder €/L (ehrlicher Vergleich); sonst Menge/Einheit
    let priceSub = '';
    if (p.price_per_kg != null) {
        priceSub = `${fmtEur(p.price_per_kg)}/kg`;
    } else if (p.price_per_l != null) {
        priceSub = `${fmtEur(p.price_per_l)}/L`;
    } else if (p.last_quantity && p.last_quantity_unit) {
        const qty = p.last_quantity === Math.floor(p.last_quantity)
            ? String(Math.floor(p.last_quantity))
            : String(p.last_quantity).replace('.', ',');
        priceSub = `${qty} ${escHtml(p.last_quantity_unit)}`;
    }

    // Änderungs-Badge — mit Hinweis "beim selben Laden" wenn zutreffend
    let changeHtml = '';
    if (p.price_change_direction && p.price_change_pct != null) {
        const cls = p.price_change_direction;
        const arrow = cls === 'up' ? '▲' : '▼';
        const sign = p.price_change_pct > 0 ? '+' : '';
        const tooltip = p.price_change_same_store
            ? `vs. letzter Kauf beim gleichen Laden (${escHtml(p.last_store_name)})`
            : 'vs. letzter Kauf';
        changeHtml = `<span class="pv-change ${cls}" title="${tooltip}">${arrow} ${sign}${p.price_change_pct}%</span>`;
    } else if (p.count > 1) {
        changeHtml = `<span class="pv-change flat" title="Erstkauf bei diesem Laden">neu bei ${escHtml(p.last_store_icon)}</span>`;
    } else {
        changeHtml = `<span class="pv-change flat">neu</span>`;
    }

    // Untere Meta-Zeile: Laden · Kategorie · Datum · Kaufhäufigkeit
    const subBits = [];
    subBits.push(`<span style="color:${p.last_store_color}">${p.last_store_icon} ${escHtml(p.last_store_name)}</span>`);
    if (p.category_name) subBits.push(`<span>${escHtml(p.category_name)}</span>`);
    subBits.push(`<span>${fmtDate(p.last_date)}</span>`);
    if (p.count > 1) subBits.push(`<span>${p.count}× gekauft</span>`);
    // Hinweis wenn Preisdifferenz zwischen Läden groß ist
    if (p.max_diff_pct != null && p.max_diff_pct >= 10 && p.cheapest_store && p.cheapest_store.store_id !== p.last_store_id) {
        subBits.push(`<span style="color:var(--green-dark)" title="Ø-Preis bei ${escHtml(p.cheapest_store.store_name)}">💡 -${p.max_diff_pct}% bei ${p.cheapest_store.store_icon} ${escHtml(p.cheapest_store.store_name)}</span>`);
    }
    const sub = subBits.join('<span class="dot">·</span>');

    return `<div class="pv-item ${rowCls}" data-key="${escHtml(p.key)}" data-title="${escHtml(name)}" role="button" tabindex="0">
        <div>
            <div class="pv-name">${escHtml(name)}${p.last_is_reduced ? ' 🏷️' : ''}</div>
            <div class="pv-sub">${sub}</div>
        </div>
        <div class="pv-price-col">
            <span class="pv-price">${fmtEur(p.last_price)}</span>
            ${priceSub ? `<span class="pv-price-sub">${priceSub}</span>` : ''}
        </div>
        ${changeHtml}
    </div>`;
}

/** Kachel-Ansicht (v1.16.0): 300px-Grid, mit Titel, Marke, Preis, Meta und
 *  einer SVG-Sparkline (die per lazy-load Product-History gefüllt wird). */
function renderProductTile(p) {
    const name = p.title || p.base_name || (p.description || '(unbekannt)');
    let rowCls = '';
    if (p.price_change_direction === 'up') rowCls = 'up';
    else if (p.price_change_direction === 'down') rowCls = 'down';

    const brand = p.brand_name
        ? `<span class="pv-tile-brand ${p.brand_is_private_label ? 'private' : ''}" title="${p.brand_is_private_label ? 'Eigenmarke' : 'Marke'}">${escHtml(p.brand_name)}</span>`
        : '';

    let priceSub = '';
    if (p.price_per_kg != null) priceSub = `${fmtEur(p.price_per_kg)}/kg`;
    else if (p.price_per_l != null) priceSub = `${fmtEur(p.price_per_l)}/L`;
    else if (p.last_quantity && p.last_quantity_unit) {
        const qty = p.last_quantity === Math.floor(p.last_quantity)
            ? String(Math.floor(p.last_quantity))
            : String(p.last_quantity).replace('.', ',');
        priceSub = `${qty} ${escHtml(p.last_quantity_unit)}`;
    }

    let changeHtml = '';
    if (p.price_change_direction && p.price_change_pct != null) {
        const cls = p.price_change_direction;
        const arrow = cls === 'up' ? '▲' : '▼';
        const sign = p.price_change_pct > 0 ? '+' : '';
        changeHtml = `<span class="pv-tile-change ${cls}">${arrow} ${sign}${p.price_change_pct}%</span>`;
    }

    const metaBits = [];
    metaBits.push(`<span style="color:${p.last_store_color}">${p.last_store_icon} ${escHtml(p.last_store_name)}</span>`);
    metaBits.push(`<span>${fmtDate(p.last_date)}</span>`);
    metaBits.push(`<span>${p.count}× gekauft</span>`);
    const meta = metaBits.join('<span class="dot">·</span>');

    let cheapHint = '';
    if (p.max_diff_pct != null && p.max_diff_pct >= 10 && p.cheapest_store && p.cheapest_store.store_id !== p.last_store_id) {
        cheapHint = `<div class="pv-tile-cheap-hint" title="Ø-Preis bei ${escHtml(p.cheapest_store.store_name)}">💡 -${p.max_diff_pct}% bei ${p.cheapest_store.store_icon} ${escHtml(p.cheapest_store.store_name)}</div>`;
    }

    return `<div class="pv-tile ${rowCls}" data-key="${escHtml(p.key)}" data-title="${escHtml(name)}" role="button" tabindex="0">
        ${changeHtml}
        <div class="pv-tile-head">
            <div style="min-width:0;flex:1">
                <div class="pv-tile-title">${escHtml(name)}${p.last_is_reduced ? ' 🏷️' : ''}</div>
                ${brand}
            </div>
        </div>
        <div>
            <div class="pv-tile-price">${fmtEur(p.last_price)}</div>
            ${priceSub ? `<div class="pv-tile-price-sub">${priceSub}</div>` : ''}
        </div>
        ${cheapHint}
        <div class="pv-tile-chart" data-spark-key="${escHtml(p.key)}"></div>
        <div class="pv-tile-meta">${meta}</div>
    </div>`;
}

async function loadSparkline(key) {
    const target = document.querySelector(`.pv-tile-chart[data-spark-key="${CSS.escape(key)}"]`);
    if (!target) return;
    let data;
    if (historyCache.has(key)) {
        data = historyCache.get(key);
    } else {
        try {
            data = await AUSGABEN_API.productHistory(key);
            historyCache.set(key, data);
        } catch (e) { target.innerHTML = ''; return; }
    }
    const items = (data.items || []).filter(i => i.total_price > 0);
    if (items.length < 2) { target.innerHTML = ''; return; }
    const pts = items.map(i => ({
        d: i.date,
        v: (i.total_price / (i.quantity || 1)) * (['g','ml'].includes((i.quantity_unit||'').toLowerCase()) ? 1000 : 1),
    }));
    target.innerHTML = _makeSparklineSVG(pts);
}

function _makeSparklineSVG(pts) {
    if (!pts.length) return '';
    const w = 100, h = 100;
    const min = Math.min(...pts.map(p => p.v));
    const max = Math.max(...pts.map(p => p.v));
    const range = (max - min) || 1;
    const xStep = pts.length > 1 ? w / (pts.length - 1) : 0;
    const path = pts.map((p, i) => {
        const x = i * xStep;
        const y = h - ((p.v - min) / range) * (h - 8) - 4;
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(' ');
    const trendUp = pts[pts.length - 1].v > pts[0].v;
    const color = trendUp ? '#ef4444' : '#22c55e';
    const fillColor = trendUp ? 'rgba(239,68,68,0.12)' : 'rgba(34,197,94,0.12)';
    const fillPath = path + ` L${(pts.length - 1) * xStep},${h} L0,${h} Z`;
    const lastX = (pts.length - 1) * xStep;
    const lastY = h - ((pts[pts.length - 1].v - min) / range) * (h - 8) - 4;
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
        <path d="${fillPath}" fill="${fillColor}" stroke="none"/>
        <path d="${path}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>
        <circle cx="${lastX.toFixed(2)}" cy="${lastY.toFixed(2)}" r="3" fill="${color}" stroke="var(--surface)" stroke-width="1.5"/>
    </svg>`;
}

// Zerlegt "Basisname 2kg (Original)" → nur den Original-Teil für die Anzeige pro Item.
function extractOriginal(desc) {
    if (!desc) return '';
    const m = String(desc).match(/\(([^)]+)\)\s*$/);
    return m ? m[1].trim() : String(desc).trim();
}

let currentChartInstance = null;

function _pvChartOptions() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const textCol = isDark ? '#a0a5b0' : '#666';
    const gridCol = isDark ? '#2a2e37' : '#e8e8e8';
    return {
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
    };
}

function _pvRenderChart(items) {
    if (currentChartInstance) { try { currentChartInstance.destroy(); } catch(_) {} }
    if (!items.length) return;
    const byStore = {};
    for (const h of items) {
        const sn = h.store_name;
        if (!byStore[sn]) byStore[sn] = { color: h.store_color, points: [] };
        byStore[sn].points.push({ x: h.date, y: h.unit_price });
    }
    const datasets = Object.entries(byStore).map(([name, obj]) => ({
        label: name, data: obj.points,
        borderColor: obj.color, backgroundColor: obj.color,
        tension: 0.2, spanGaps: true,
    }));
    currentChartInstance = new Chart(document.getElementById('pvChart'),
        { type: 'line', data: { datasets }, options: _pvChartOptions() });
}

/** v1.16.0: Vergleichs-Tabelle zwischen Läden — welcher ist im Schnitt am günstigsten. */
function _pvRenderCompareTable(data) {
    const wrap = document.getElementById('pvCompareTable');
    if (!wrap) return;
    const stores = (data.store_summary || []).slice().sort((a, b) => a.avg_unit_price - b.avg_unit_price);
    if (stores.length < 2) {
        wrap.innerHTML = '<div class="pv-empty" style="padding:1rem">Nur ein Laden vorhanden — Vergleich nicht möglich.<br><small>Kauf dasselbe Produkt in einem anderen Laden für einen Preisvergleich.</small></div>';
        return;
    }
    const cheapest = stores[0].avg_unit_price;
    wrap.innerHTML = `
        <table style="width:100%;border-collapse:collapse;font-size:0.8125rem">
            <thead>
                <tr style="border-bottom:1px solid var(--border);color:var(--text-muted);font-size:0.6875rem;text-transform:uppercase;letter-spacing:0.5px">
                    <th style="text-align:left;padding:0.5rem 0.375rem">Laden</th>
                    <th style="text-align:right;padding:0.5rem 0.375rem">Ø/Einheit</th>
                    <th style="text-align:right;padding:0.5rem 0.375rem">Min – Max</th>
                    <th style="text-align:right;padding:0.5rem 0.375rem">Käufe</th>
                    <th style="text-align:right;padding:0.5rem 0.375rem">Diff</th>
                </tr>
            </thead>
            <tbody>
                ${stores.map((s, i) => {
                    const diffPct = cheapest > 0 ? Math.round((s.avg_unit_price - cheapest) / cheapest * 1000) / 10 : 0;
                    const isCheapest = i === 0;
                    const rowStyle = isCheapest ? 'background:rgba(34,197,94,0.06)' : '';
                    return `<tr style="border-bottom:1px solid var(--border);${rowStyle}">
                        <td style="padding:0.5rem 0.375rem">
                            <span style="color:${s.store_color}">${s.store_icon} ${escHtml(s.store_name)}</span>
                            ${isCheapest ? ' <span style="color:var(--green-dark);font-weight:700;font-size:0.6875rem">💚 GÜNSTIGSTER</span>' : ''}
                        </td>
                        <td style="text-align:right;padding:0.5rem 0.375rem;font-variant-numeric:tabular-nums;font-weight:600">${fmtEur(s.avg_unit_price)}</td>
                        <td style="text-align:right;padding:0.5rem 0.375rem;font-variant-numeric:tabular-nums;color:var(--text-muted);font-size:0.75rem">${fmtEur(s.min_unit_price || s.avg_unit_price)} – ${fmtEur(s.max_unit_price || s.avg_unit_price)}</td>
                        <td style="text-align:right;padding:0.5rem 0.375rem;color:var(--text-muted)">${s.count}×</td>
                        <td style="text-align:right;padding:0.5rem 0.375rem;font-variant-numeric:tabular-nums;font-weight:600;color:${diffPct > 0 ? '#991b1b' : 'var(--text-muted)'}">${isCheapest ? '—' : '+' + diffPct + '%'}</td>
                    </tr>`;
                }).join('')}
            </tbody>
        </table>
        <div style="font-size:0.75rem;color:var(--text-faint);margin-top:0.75rem">Alle Preise auf gleiche Einheit normiert (€/kg bzw. €/L wo möglich).</div>
    `;
}

function _pvRenderStoreSummary(data) {
    const wrap = document.getElementById('pvStoreSummary');
    if (!wrap) return;
    if (!data.cheapest_store || data.store_summary.length < 2) {
        wrap.innerHTML = '';
        return;
    }
    const c = data.cheapest_store, e = data.most_expensive_store;
    const savingsPct = data.max_diff_pct;
    wrap.innerHTML = `
        <div class="pv-summary-grid">
            <div class="pv-summary-card cheap">
                <div class="pv-summary-lbl">💚 Günstigster Laden</div>
                <div class="pv-summary-store" style="color:${c.store_color}">${c.store_icon} ${escHtml(c.store_name)}</div>
                <div class="pv-summary-val">${fmtEur(c.avg_unit_price)}<span class="pv-summary-sub">Ø/Einheit · ${c.count}×</span></div>
            </div>
            <div class="pv-summary-card expensive">
                <div class="pv-summary-lbl">🔴 Teuerster Laden</div>
                <div class="pv-summary-store" style="color:${e.store_color}">${e.store_icon} ${escHtml(e.store_name)}</div>
                <div class="pv-summary-val">${fmtEur(e.avg_unit_price)}<span class="pv-summary-sub">+${savingsPct}% · ${e.count}×</span></div>
            </div>
        </div>
    `;
}

function _pvRenderHistList(items, reloadFn) {
    const wrap = document.getElementById('pvHistList');
    if (!items.length) {
        wrap.innerHTML = '<div class="pv-empty">Keine Käufe mehr in dieser Gruppe.</div>';
        return;
    }
    // neueste oben — bevorzuge original_text (strukturiert), sonst extrahiert
    wrap.innerHTML = items.slice().reverse().map(h => {
        const original = h.original_text || extractOriginal(h.description) || h.base_name || '';
        const qtyBits = h.quantity && h.quantity > 1
            ? ` · ${h.quantity}${h.quantity_unit || ''}` : '';
        const soloCls = (h.product_group || '').startsWith('_solo_') ? ' solo' : '';
        return `<div class="pv-hist-item${soloCls}" data-item-id="${h.item_id}" data-comparable="${h.price_comparable ? '1' : '0'}">
            <span class="pv-hist-date">${fmtDate(h.date)}</span>
            <div class="pv-hist-body">
                <div class="pv-hist-desc">${escHtml(original)}${qtyBits}</div>
                <div class="pv-hist-store" style="color:${h.store_color}">${h.store_icon} ${escHtml(h.store_name)}</div>
            </div>
            <span class="pv-hist-price${h.is_reduced ? ' reduced' : ''}">${fmtEur(h.total_price)}${h.is_reduced ? ' 🏷️' : ''}</span>
            <span class="pv-hist-actions">
                <a href="/ausgaben/bon.html?id=${h.expense_id}" title="Bon öffnen" target="_blank" rel="noopener">↗</a>
                <button class="detach" title="Aus dieser Produkt-Gruppe herauslösen (Fehl­gruppierung)">✂</button>
                <button class="exclude" title="Aus Preisvergleich ausschließen (z.B. Einmalkauf)">🚫</button>
            </span>
        </div>`;
    }).join('');
    wrap.querySelectorAll('.pv-hist-item').forEach(el => {
        const iid = +el.dataset.itemId;
        const detachBtn = el.querySelector('.detach');
        const excludeBtn = el.querySelector('.exclude');
        if (detachBtn) detachBtn.onclick = async () => {
            if (!confirm('Diesen Artikel aus dieser Produkt-Gruppe herauslösen?\n\nEr bekommt eine eigene Gruppe und erscheint dann separat im Preisverlauf.')) return;
            detachBtn.disabled = true;
            try {
                await AUSGABEN_API.setItemGroup(iid, `_solo_${iid}_${Date.now()}`);
                showToast('Artikel aufgelöst', 'success', 2000);
                try { allProducts = await AUSGABEN_API.products(); render(); } catch(_) {}
                await reloadFn();
            } catch (e) {
                detachBtn.disabled = false;
                showToast('Fehler: ' + e.message, 'error');
            }
        };
        if (excludeBtn) excludeBtn.onclick = async () => {
            if (!confirm('Diesen Artikel dauerhaft vom Preisvergleich ausschließen?\n\nGeeignet für Einmalkäufe (Topf, Vorratsdose, Werkzeug etc.).')) return;
            excludeBtn.disabled = true;
            try {
                await AUSGABEN_API.setItemComparable(iid, false);
                showToast('Vom Preisvergleich ausgeschlossen', 'success', 2000);
                try { allProducts = await AUSGABEN_API.products(); render(); } catch(_) {}
                await reloadFn();
            } catch (e) {
                excludeBtn.disabled = false;
                showToast('Fehler: ' + e.message, 'error');
            }
        };
    });
}

async function openProductChart(key, title) {
    // v1.16.0: Zwei-Tab-Layout im Modal:
    //   Tab 1 "Preisverlauf pro Laden"   — same-store history (Verlauf mit Rabatt/Preissteigerung)
    //   Tab 2 "Preisvergleich Läden"     — cross-store (welcher Laden ist billiger)
    const modal = openModal(`📈 Preisverlauf: ${escHtml(title)}`,
        `<div class="pv-tabs">
             <button class="pv-tab-btn active" data-pvtab="history">📊 Preisverlauf pro Laden</button>
             <button class="pv-tab-btn" data-pvtab="compare">🏪 Läden-Vergleich</button>
         </div>
         <div id="pvTabHistory" class="pv-tab-panel active">
             <div class="pv-chart-wrap"><canvas id="pvChart"></canvas></div>
             <div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:0.5rem">
                 ↗ Bon öffnen · ✂ Artikel aus Produkt-Gruppe herauslösen · 🚫 Aus Preisvergleich ausschließen
             </div>
             <div id="pvHistList" class="pv-hist-list"></div>
         </div>
         <div id="pvTabCompare" class="pv-tab-panel">
             <div id="pvStoreSummary"></div>
             <div id="pvCompareTable"></div>
         </div>`,
        {
            wide: true,
            onClose: () => {
                if (currentChartInstance) {
                    try { currentChartInstance.destroy(); } catch(_) {}
                    currentChartInstance = null;
                }
            },
        }
    );

    // Tab-Umschaltung
    modal.root.querySelectorAll('.pv-tab-btn').forEach(btn => {
        btn.onclick = () => {
            modal.root.querySelectorAll('.pv-tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const t = btn.dataset.pvtab;
            modal.root.querySelectorAll('.pv-tab-panel').forEach(p => p.classList.remove('active'));
            modal.root.querySelector('#pvTab' + (t === 'history' ? 'History' : 'Compare')).classList.add('active');
        };
    });

    async function reload() {
        try {
            const data = await AUSGABEN_API.productHistory(key);
            const items = data.items || [];
            _pvRenderStoreSummary(data);
            _pvRenderCompareTable(data);
            _pvRenderChart(items);
            _pvRenderHistList(items, reload);
        } catch (e) {
            modal.root.innerHTML = `<div class="pv-empty">Fehler: ${escHtml(e.message)}</div>`;
        }
    }
    await reload();
}

// Bulk-Reparse aller Bons mit gespeicherten Foto (OCR-Rohtext).
// Der Backend-Endpoint streamt NDJSON — wir lesen inkrementell.
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
        // Nach Abschluss: Preisverlauf neu laden
        try { allProducts = await AUSGABEN_API.products(); render(); } catch (_) {}
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
    let ok = 0, err = 0;
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
                    ok++;
                    log.innerHTML += `<span class="ok">✓ Bon #${msg.expense_id}: ${msg.items} Positionen</span>\n`;
                } else {
                    err++;
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

init();
