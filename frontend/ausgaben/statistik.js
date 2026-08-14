async function init() {
    const me = await ensureLoggedIn(); if (!me) return;
    renderSubnav();
    await Promise.all([loadMonthly(), loadWeekly(), loadDaily(), loadCategory(), loadStore()]);
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';
}

function escHtml(s) { if (!s) return ''; return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

const isDark = () => document.documentElement.getAttribute('data-theme') === 'dark';
const gridColor = () => isDark() ? '#2a2e37' : '#e8e8e8';
const textColor = () => isDark() ? '#a0a5b0' : '#666';

function barOptions(fmtY = v => fmtEur(v), fmtTooltip = c => fmtEur(c.parsed.y)) {
    return {
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: fmtTooltip } } },
        scales: {
            x: { ticks: { color: textColor(), maxRotation: 0, autoSkip: true, autoSkipPadding: 12 }, grid: { display: false } },
            y: { ticks: { color: textColor(), callback: fmtY }, grid: { color: gridColor() }, beginAtZero: true },
        },
    };
}

async function loadMonthly() {
    try {
        const data = await AUSGABEN_API.statsMonthly(12);
        new Chart(document.getElementById('chartMonthly'), {
            type: 'bar',
            data: {
                labels: data.map(d => d.month),
                datasets: [{ label: 'Ausgaben (€)', data: data.map(d => d.total), backgroundColor: '#14b8a6', borderRadius: 4 }],
            },
            options: barOptions(),
        });
    } catch(e) { console.error(e); }
}

async function loadWeekly() {
    try {
        const data = await AUSGABEN_API.statsWeekly(12);
        new Chart(document.getElementById('chartWeekly'), {
            type: 'bar',
            data: {
                // Kompakt-Label: "KW 33"
                labels: data.map(d => d.week.split('-').pop()),
                datasets: [{ label: 'Ausgaben (€)', data: data.map(d => d.total), backgroundColor: '#3b82f6', borderRadius: 4 }],
            },
            options: barOptions(),
        });
    } catch(e) { console.error(e); }
}

async function loadDaily() {
    try {
        const data = await AUSGABEN_API.statsDaily(30);
        new Chart(document.getElementById('chartDaily'), {
            type: 'bar',
            data: {
                labels: data.map(d => {
                    const dt = new Date(d.date + 'T00:00:00');
                    return dt.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' });
                }),
                datasets: [{ label: 'Ausgaben (€)', data: data.map(d => d.total), backgroundColor: '#f59e0b', borderRadius: 3 }],
            },
            options: barOptions(),
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

init();
