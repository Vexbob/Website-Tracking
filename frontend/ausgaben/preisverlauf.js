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
    document.getElementById('pvReparse').onclick = openReparseModal;
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
    let list = allProducts;
    if (q) {
        list = list.filter(p => (p.description || '').toLowerCase().includes(q) ||
                                (p.key || '').includes(q));
    }
    const wrap = document.getElementById('pvList');
    if (!list.length) {
        wrap.innerHTML = `<div class="pv-empty"><div class="icon">💶</div>${
            allProducts.length ? 'Keine Treffer.' :
            'Noch keine gespeicherten Positionen. Lade Bons mit „Einzelpositionen speichern" hoch.'
        }</div>`;
        return;
    }
    // Sortierung: Preisänderungen zuerst (up), dann normal, dann alphabetisch
    list = list.slice().sort((a, b) => {
        const rank = (p) => p.price_change_direction === 'up' ? 0 :
                           p.price_change_direction === 'down' ? 1 : 2;
        const r = rank(a) - rank(b);
        if (r !== 0) return r;
        return (a.key || '').localeCompare(b.key || '');
    });
    wrap.innerHTML = list.map(renderProductRow).join('');
}

// Kompakte Listen-Zeile — eine Zeile pro Produkt.
// Grid: Name+Meta | Preis-Spalte | Änderungsbadge
function renderProductRow(p) {
    const { base } = splitDescription(p.description);
    const name = base || p.description || '(unbekannt)';

    // Preisänderungs-Klasse für den linken Border
    let rowCls = '';
    if (p.price_change_direction === 'up') rowCls = 'up';
    else if (p.price_change_direction === 'down') rowCls = 'down';

    // Kompakter Preis (letzter Kauf) + kleine Zusatzinfo (Menge/Einheit falls sinnvoll)
    let priceSub = '';
    if (p.last_quantity && p.last_quantity_unit) {
        // z.B. "2 kg" oder "1 L"
        const qty = p.last_quantity === Math.floor(p.last_quantity)
            ? String(Math.floor(p.last_quantity))
            : String(p.last_quantity).replace('.', ',');
        priceSub = `${qty} ${escHtml(p.last_quantity_unit)}`;
    }

    // Änderungs-Badge (kompakt)
    let changeHtml = '';
    if (p.price_change_direction && p.price_change_pct != null) {
        const cls = p.price_change_direction;
        const arrow = cls === 'up' ? '▲' : '▼';
        const sign = p.price_change_pct > 0 ? '+' : '';
        changeHtml = `<span class="pv-change ${cls}">${arrow} ${sign}${p.price_change_pct}%</span>`;
    } else if (p.count > 1) {
        changeHtml = `<span class="pv-change flat">— stabil</span>`;
    } else {
        changeHtml = `<span class="pv-change flat">neu</span>`;
    }

    // Untere Meta-Zeile: letzter Laden · Kategorie · Datum · Kaufhäufigkeit
    const subBits = [];
    subBits.push(`<span style="color:${p.last_store_color}">${p.last_store_icon} ${escHtml(p.last_store_name)}</span>`);
    if (p.category_name) subBits.push(`<span>${escHtml(p.category_name)}</span>`);
    subBits.push(`<span>${fmtDate(p.last_date)}</span>`);
    if (p.count > 1) subBits.push(`<span>${p.count}× gekauft</span>`);
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

function _pvRenderChart(history) {
    if (currentChartInstance) { try { currentChartInstance.destroy(); } catch(_) {} }
    if (!history.length) return;
    const byStore = {};
    for (const h of history) {
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

function _pvRenderHistList(history, reloadFn) {
    const wrap = document.getElementById('pvHistList');
    if (!history.length) {
        wrap.innerHTML = '<div class="pv-empty">Keine Käufe mehr in dieser Gruppe.</div>';
        return;
    }
    // neueste oben
    wrap.innerHTML = history.slice().reverse().map(h => {
        const original = extractOriginal(h.description);
        const qtyBits = h.quantity && h.quantity > 1
            ? ` · ${h.quantity}${h.quantity_unit || ''}` : '';
        return `<div class="pv-hist-item" data-item-id="${h.item_id}">
            <span class="pv-hist-date">${fmtDate(h.date)}</span>
            <div class="pv-hist-body">
                <div class="pv-hist-desc">${escHtml(original)}${qtyBits}</div>
                <div class="pv-hist-store" style="color:${h.store_color}">${h.store_icon} ${escHtml(h.store_name)}</div>
            </div>
            <span class="pv-hist-price${h.is_reduced ? ' reduced' : ''}">${fmtEur(h.total_price)}${h.is_reduced ? ' 🏷️' : ''}</span>
            <span class="pv-hist-actions">
                <a href="/ausgaben/bon.html?id=${h.expense_id}" title="Bon öffnen" target="_blank" rel="noopener">↗</a>
                <button class="detach" title="Aus dieser Produkt-Gruppe herauslösen">✂</button>
            </span>
        </div>`;
    }).join('');
    wrap.querySelectorAll('.pv-hist-item').forEach(el => {
        const iid = +el.dataset.itemId;
        const detachBtn = el.querySelector('.detach');
        if (!detachBtn) return;
        detachBtn.onclick = async () => {
            if (!confirm('Diesen Artikel aus dieser Produkt-Gruppe herauslösen?\n\nEr bekommt eine eigene Gruppe und erscheint dann separat im Preisverlauf.')) return;
            detachBtn.disabled = true;
            try {
                const soloKey = `_solo_${iid}_${Date.now()}`;
                await AUSGABEN_API.setItemGroup(iid, soloKey);
                showToast('Artikel aufgelöst', 'success', 2000);
                try { allProducts = await AUSGABEN_API.products(); render(); } catch(_) {}
                await reloadFn();
            } catch (e) {
                detachBtn.disabled = false;
                showToast('Fehler: ' + e.message, 'error');
            }
        };
    });
}

async function openProductChart(key, title) {
    const modal = openModal(`📈 Preisverlauf: ${escHtml(title)}`,
        `<div class="pv-chart-wrap"><canvas id="pvChart"></canvas></div>
         <div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:0.5rem">
             ↗ öffnet den zugehörigen Bon · ✂ trennt einen fehlerhaft zugeordneten Artikel aus dieser Produkt-Gruppe heraus
         </div>
         <div id="pvHistList" class="pv-hist-list"></div>`,
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

    async function reload() {
        try {
            const history = await AUSGABEN_API.productHistory(key);
            _pvRenderChart(history);
            _pvRenderHistList(history, reload);
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
