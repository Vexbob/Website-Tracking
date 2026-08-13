async function init() {
    const me = await ensureLoggedIn(); if (!me) return;
    await Promise.all([loadMonthly(), loadCategory(), loadStore(), loadHeatmap()]);
    document.getElementById('searchBtn').onclick = doSearch;
    document.getElementById('searchInput').addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';
}

function escHtml(s) { if (!s) return ''; return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

const isDark = () => document.documentElement.getAttribute('data-theme') === 'dark';
const gridColor = () => isDark() ? '#2a2e37' : '#e8e8e8';
const textColor = () => isDark() ? '#a0a5b0' : '#666';

async function loadMonthly() {
    try {
        const data = await AUSGABEN_API.statsMonthly(12);
        new Chart(document.getElementById('chartMonthly'), {
            type: 'bar',
            data: {
                labels: data.map(d => d.month),
                datasets: [{ label: 'Ausgaben (€)', data: data.map(d => d.total), backgroundColor: '#14b8a6', borderRadius: 4 }],
            },
            options: {
                maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => fmtEur(c.parsed.y) } } },
                scales: {
                    x: { ticks: { color: textColor() }, grid: { display: false } },
                    y: { ticks: { color: textColor(), callback: v => fmtEur(v) }, grid: { color: gridColor() } },
                },
            },
        });
    } catch(e) { console.error(e); }
}

async function loadCategory() {
    try {
        const data = await AUSGABEN_API.statsCategory();
        if (!data.length) return;
        new Chart(document.getElementById('chartCategory'), {
            type: 'doughnut',
            data: {
                labels: data.map(d => d.name),
                datasets: [{ data: data.map(d => d.total), backgroundColor: data.map(d => d.color) }],
            },
            options: {
                maintainAspectRatio: false,
                plugins: { legend: { position: 'right', labels: { color: textColor(), font: { size: 11 } } }, tooltip: { callbacks: { label: (c) => c.label + ': ' + fmtEur(c.parsed) } } },
            },
        });
    } catch(e) { console.error(e); }
}

async function loadStore() {
    try {
        const data = await AUSGABEN_API.statsStore();
        if (!data.length) return;
        new Chart(document.getElementById('chartStore'), {
            type: 'bar',
            data: {
                labels: data.map(d => d.name),
                datasets: [{ label: 'Ausgaben (€)', data: data.map(d => d.total), backgroundColor: data.map(d => d.color), borderRadius: 4 }],
            },
            options: {
                indexAxis: 'y',
                maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => fmtEur(c.parsed.x) } } },
                scales: {
                    x: { ticks: { color: textColor(), callback: v => fmtEur(v) }, grid: { color: gridColor() } },
                    y: { ticks: { color: textColor() }, grid: { display: false } },
                },
            },
        });
    } catch(e) { console.error(e); }
}

async function loadHeatmap() {
    try {
        const data = await AUSGABEN_API.heatmap();
        const grid = document.getElementById('heatmap');
        // Auf ISO-Wochenanfang justieren (Mo = 0)
        if (!data.length) return;
        const first = new Date(data[0].date);
        const firstWeekday = (first.getDay() + 6) % 7; // 0 = Mo
        const leading = Array(firstWeekday).fill(null);
        const cells = leading.concat(data);
        grid.innerHTML = cells.map(c => {
            if (!c) return '<div class="hm-cell" style="visibility:hidden"></div>';
            return `<div class="hm-cell l${c.level}" title="${c.date}: ${fmtEur(c.amount)} · ${c.count} Bons"></div>`;
        }).join('');
    } catch(e) { console.error(e); }
}

async function doSearch() {
    const q = document.getElementById('searchInput').value.trim();
    const wrap = document.getElementById('phResults');
    if (q.length < 2) { wrap.innerHTML = '<div class="muted">Mindestens 2 Zeichen</div>'; return; }
    wrap.innerHTML = '<div class="muted">Suche …</div>';
    try {
        const data = await AUSGABEN_API.priceHistory(q);
        if (!data.count) { wrap.innerHTML = '<div class="muted">Keine Treffer für "' + escHtml(q) + '"</div>'; return; }

        // Summary
        let summaryHtml = '';
        if (data.cheapest && data.most_expensive && data.cheapest.store_name !== data.most_expensive.store_name) {
            summaryHtml = `
                <div class="ph-summary">
                    <div class="ph-summary-title">💡 Vergleich (${data.count} Käufe · Ø ${fmtEur(data.avg_unit_price)} pro Einheit)</div>
                    <div class="ph-summary-grid">
                        <div class="ph-summary-card cheap">
                            <div class="ph-summary-lbl">Günstigster Laden</div>
                            <div class="ph-summary-store" style="color:${data.cheapest.store_color}">${data.cheapest.store_icon} ${escHtml(data.cheapest.store_name)}</div>
                            <div class="ph-summary-val">${fmtEur(data.cheapest.avg_unit_price)}<span class="ph-summary-sub">Ø / Einheit</span></div>
                        </div>
                        <div class="ph-summary-card expensive">
                            <div class="ph-summary-lbl">Teuerster Laden</div>
                            <div class="ph-summary-store" style="color:${data.most_expensive.store_color}">${data.most_expensive.store_icon} ${escHtml(data.most_expensive.store_name)}</div>
                            <div class="ph-summary-val">${fmtEur(data.most_expensive.avg_unit_price)}<span class="ph-summary-sub">+${data.max_diff_pct}%</span></div>
                        </div>
                    </div>
                </div>`;
        } else if (data.avg_unit_price != null) {
            summaryHtml = `<div class="ph-summary"><div class="ph-summary-title">${data.count} Käufe · Ø ${fmtEur(data.avg_unit_price)} pro Einheit</div></div>`;
        }

        // Pro Store
        let byStoreHtml = '';
        if (data.by_store.length > 1) {
            byStoreHtml = '<h4 style="margin:0.75rem 0 0.375rem;font-size:0.8125rem;color:var(--text-muted)">Nach Laden</h4>';
            byStoreHtml += data.by_store.map(s => {
                const pct = s.diff_to_avg_pct;
                const cls = pct < -1 ? 'cheap' : pct > 1 ? 'expensive' : '';
                const arrow = pct < -1 ? '▼' : pct > 1 ? '▲' : '—';
                return `<div class="ph-store-row">
                    <div class="ph-store-name" style="color:${s.store_color}">${s.store_icon} ${escHtml(s.store_name)}</div>
                    <div class="ph-store-count">${s.count}×</div>
                    <div class="ph-store-price ${cls}">${fmtEur(s.avg_unit_price)} <small>${arrow} ${pct > 0 ? '+' : ''}${pct}%</small></div>
                </div>`;
            }).join('');
        }

        // Einzelkäufe
        const itemsHtml = '<h4 style="margin:0.75rem 0 0.375rem;font-size:0.8125rem;color:var(--text-muted)">Alle Käufe</h4>' +
            data.items.map(r => {
                const pct = r.diff_pct || 0;
                const cls = pct < -5 ? 'cheap' : pct > 5 ? 'expensive' : '';
                const diffLabel = Math.abs(pct) < 1 ? '' : (pct < 0 ? `${pct}%` : `+${pct}%`);
                const reduced = r.is_reduced ? '<span class="ph-badge">REDUZIERT</span>' : '';
                const origPrice = r.original_price ? ` <s style="color:var(--text-fainter)">${fmtEur(r.original_price)}</s>` : '';
                return `<div class="ph-item ${cls}">
                    <div><div class="ph-name">${escHtml(r.description)} ${reduced}</div>
                         <div class="ph-meta"><span style="color:${r.store_color}">${r.store_icon} ${escHtml(r.store_name)}</span> · ${fmtDate(r.purchase_date)}${r.quantity > 1 ? ' · '+r.quantity+'x' : ''}</div></div>
                    <div class="ph-diff ${cls}">${diffLabel}</div>
                    <div class="ph-price">${fmtEur(r.total_price)}${origPrice}</div>
                </div>`;
            }).join('');

        wrap.innerHTML = summaryHtml + byStoreHtml + itemsHtml;
    } catch(e) { wrap.innerHTML = '<div class="muted">Fehler: ' + e.message + '</div>'; }
}

init();
