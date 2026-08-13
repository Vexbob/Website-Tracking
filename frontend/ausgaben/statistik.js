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
        const rows = await AUSGABEN_API.priceHistory(q);
        if (!rows.length) { wrap.innerHTML = '<div class="muted">Keine Treffer</div>'; return; }
        wrap.innerHTML = rows.map(r => `
            <div class="ph-item">
                <div><div class="ph-name">${escHtml(r.description)}</div><div class="ph-meta">${escHtml(r.store_name || 'Ohne Laden')} · ${fmtDate(r.purchase_date)}</div></div>
                <div class="ph-meta">${r.quantity && r.quantity > 1 ? r.quantity + 'x' : ''}</div>
                <div class="ph-price">${fmtEur(r.total_price)}</div>
            </div>
        `).join('');
    } catch(e) { wrap.innerHTML = '<div class="muted">Fehler: ' + e.message + '</div>'; }
}

init();
