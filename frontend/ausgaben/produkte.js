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

// Gewaehlter Zeitraum (VexRange). Wird in bindFilters() gesetzt.
let prodRange = null;

function currentFilters() {
    const filters = {};
    // Neu seit v1.60.2: auch ein Ende. Vorher ging der Zeitraum immer bis
    // heute, ein zurueckliegendes Fenster war gar nicht ausdrueckbar.
    const r = prodRange || VexRange.resolve('90');
    if (r.from) filters.date_from = r.from;
    if (r.to) filters.date_to = r.to;
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

/* Ein Vorschlag ist ein Angebot, kein Befehl: der Name ist frei änderbar und
 * jede Schreibweise lässt sich abwählen, wenn sie doch ein anderes Produkt ist.
 * Zusammengeführt wird nur, was angehakt bleibt (mindestens zwei Einträge) —
 * der Rest bleibt als eigene Produktzeile stehen. */
function renderMergeSuggestions() {
    const box = document.getElementById('mergeBox');
    if (!box) return;
    if (!mergeSuggestions.length) { box.innerHTML = ''; box.style.display = 'none'; return; }
    box.style.display = '';
    box.innerHTML = mergeSuggestions.map((s, i) => {
        const variants = s.variants.map(v => {
            const stores = (v.stores || []).join(', ');
            return `<li>
                <label class="merge-variant">
                    <input type="checkbox" class="merge-pick" data-key="${escHtml(v.key)}" data-title="${escHtml(v.title)}" checked>
                    <span class="merge-variant-name">${escHtml(v.title)}</span>
                    <span class="merge-meta">${v.count}× ${stores ? '· ' + escHtml(stores) : ''}</span>
                </label>
            </li>`;
        }).join('');
        return `<div class="merge-card" data-idx="${i}">
            <div class="merge-head">
                <span class="merge-icon">🔗</span>
                <div>
                    <div class="merge-title">${s.variants.length} Schreibweisen von „${escHtml(s.suggested_title)}"?</div>
                    <div class="merge-sub">Wird eine Produktzeile — auch für künftige Käufe. Name änderbar, einzelne Schreibweisen kannst du abwählen.</div>
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
        const nameInput = card.querySelector('.merge-name');
        const doBtn = card.querySelector('.merge-do');
        const picks = () => [...card.querySelectorAll('.merge-pick:checked')];
        let nameTouched = false;
        nameInput.addEventListener('input', () => { nameTouched = true; });

        // Solange der Name nicht von Hand geändert wurde, folgt er der Auswahl:
        // der kürzeste angehakte Name ist in aller Regel der generische.
        const sync = () => {
            const sel = picks();
            doBtn.disabled = sel.length < 2;
            doBtn.textContent = sel.length < 2
                ? 'Mindestens zwei wählen'
                : (sel.length === s.variants.length ? 'Zusammenführen' : `${sel.length} zusammenführen`);
            if (!nameTouched && sel.length) {
                nameInput.value = sel
                    .map(cb => cb.dataset.title)
                    .sort((a, b) => a.length - b.length || a.localeCompare(b))[0];
            }
        };
        card.querySelectorAll('.merge-pick').forEach(cb => cb.addEventListener('change', sync));
        sync();

        doBtn.onclick = async () => {
            const sel = picks();
            if (sel.length < 2) return;
            const keys = sel.map(cb => cb.dataset.key);
            const dropped = [...card.querySelectorAll('.merge-pick:not(:checked)')].map(cb => cb.dataset.key);
            const title = nameInput.value.trim() || s.suggested_title;
            try {
                const r = await AUSGABEN_API.mergeProducts(keys, title);
                // Abgewaehltes ist eine Entscheidung, kein Uebersehen: sonst
                // schlaegt der naechste Seitenaufruf dieselbe Gruppe wieder vor.
                if (dropped.length && r.product_group) {
                    try { await AUSGABEN_API.dismissMerge([r.product_group, ...dropped]); } catch (_) {}
                }
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
                <div class="prod-name">${escHtml(p.title || p.key)}${p.is_merged ? ' <button type="button" class="prod-merged" title="Zusammengeführt — klicken zum Bearbeiten">🔗</button>' : ''}</div>
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
            if (ev.target.closest('.prod-merged')) {
                ev.stopPropagation();
                openMergeEditor(product);
                return;
            }
            openProductDetail(key, product);
        };
    });
}

/* Bestehende Zusammenführung bearbeiten: Gruppenname ändern und einzelne
 * Schreibweisen wieder herauslösen. Die Mitglieder stehen in keiner eigenen
 * Tabelle — sie ergeben sich aus den Positionen der Gruppe, deshalb kommt die
 * Liste aus der Kaufhistorie und wird hier nach Basisnamen verdichtet. */
async function openMergeEditor(product) {
    const title = product.title || product.key;
    const modal = openModal(`🔗 „${escHtml(title)}" bearbeiten`, `
        <p class="me-hint">Angehakt bleibt in der Gruppe. Was du abwählst, steht danach wieder als eigenes Produkt in der Liste.</p>
        <div id="mePicks" class="me-list"><div class="pv-empty">Lade …</div></div>
        <label class="me-name-lbl">Name der Gruppe
            <input id="meName" class="merge-name" value="${escHtml(title)}">
        </label>
        <div class="me-actions">
            <button class="me-split">Ganz auftrennen</button>
            <button class="me-cancel">Abbrechen</button>
            <button class="me-save merge-do">Speichern</button>
        </div>
    `, { wide: true });

    const picksWrap = modal.root.querySelector('#mePicks');
    let variants = [];
    try {
        const data = await AUSGABEN_API.productHistory(product.key);
        const byName = new Map();
        (data.items || []).forEach(h => {
            const name = String(h.base_name || h.description || '').trim();
            const k = name.toLowerCase();
            if (!k) return;
            const entry = byName.get(k) || { name, count: 0 };
            entry.count += 1;
            byName.set(k, entry);
        });
        variants = [...byName.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
    } catch (e) {
        picksWrap.innerHTML = `<div class="pv-empty">Fehler: ${escHtml(e.message)}</div>`;
        return;
    }

    picksWrap.innerHTML = variants.length
        ? `<ul class="merge-variants">${variants.map(v => `
            <li><label class="merge-variant">
                <input type="checkbox" class="me-pick" data-name="${escHtml(v.name)}" checked>
                <span class="merge-variant-name">${escHtml(v.name)}</span>
                <span class="merge-meta">${v.count}×</span>
            </label></li>`).join('')}</ul>`
        : '<div class="pv-empty">Diese Gruppe hat nur eine Schreibweise — du kannst sie umbenennen oder auftrennen.</div>';

    modal.root.querySelector('.me-cancel').onclick = () => modal.close();
    modal.root.querySelector('.me-split').onclick = async () => {
        modal.close();
        await splitProduct(product);
    };
    modal.root.querySelector('.me-save').onclick = async () => {
        const dropped = [...modal.root.querySelectorAll('.me-pick:not(:checked)')].map(cb => cb.dataset.name);
        const newTitle = modal.root.querySelector('#meName').value.trim() || title;
        if (dropped.length === variants.length && variants.length) {
            modal.close();
            await splitProduct(product);
            return;
        }
        try {
            const r = await AUSGABEN_API.regroupProduct(product.key, newTitle, dropped);
            // Herausgelöstes ist eine Entscheidung: sonst schlägt die Seite
            // beim nächsten Laden dieselbe Zusammenführung wieder vor.
            if (dropped.length && r.product_group) {
                try {
                    await AUSGABEN_API.dismissMerge([r.product_group, ...dropped.map(n => n.toLowerCase())]);
                } catch (_) {}
            }
            modal.close();
            showToast(dropped.length
                ? `Gespeichert — ${r.dropped} Position${r.dropped === 1 ? '' : 'en'} herausgelöst`
                : 'Gespeichert', 'success');
            await Promise.all([loadProducts(), loadMergeSuggestions()]);
        } catch (e) { showToast('Fehler: ' + e.message, 'error'); }
    };
}

async function splitProduct(product) {
    const ok = await askConfirm({ title: `„${product.title}" auftrennen?`,
        text: 'Die Artikel fallen auf ihre einzelnen Namen zurück und stehen danach wieder als getrennte Produkte in der Liste.',
        ok: 'Auftrennen' });
    if (!ok) return;
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
    // fire:false -- init() laedt gleich selbst; sonst gaebe es zwei Ladungen
    // direkt hintereinander.
    const rf = VexRange.mount(document.getElementById('prodRange'), {
        fire: false,
        onChange: (r) => { prodRange = r; loadProducts(); },
    });
    prodRange = rf.get();
    ['prodCategory', 'prodStore'].forEach(id => {
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
            <button class="cancel" style="width:auto;margin:0;background:var(--surface-2);color:var(--text-1);border:1px solid var(--line-strong)">Abbrechen</button>
            <button class="start primary" style="width:auto;margin:0;background:var(--grad-accent);color:#fff">Los geht's</button>
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
                bar.style.background = msg.errors ? 'var(--warn)' : 'var(--grad-accent)';
            }
        }
    }
}

// ---------- Detail-Modal: Kaufhistorie ----------
let currentChartInstance = null;

async function openProductDetail(key, product) {
    const modal = openModal(`🛒 ${escHtml(product.title || key)}`, `
        <div class="pv-toolbar">
            <button type="button" class="pv-action" id="pvMerge">
                ${product.is_merged ? '🔗 Zusammenführung bearbeiten' : '🔗 Mit anderem Produkt zusammenführen'}
            </button>
        </div>
        <div id="pvStores" class="pv-stores"></div>
        <div class="pv-chart-wrap"><canvas id="pvChart"></canvas></div>
        <div id="pvHistList" class="pv-hist-list"></div>
    `, { wide: true, onClose: () => {
        if (currentChartInstance) { try { currentChartInstance.destroy(); } catch(_) {} currentChartInstance = null; }
    }});

    const mergeBtn = modal.root.querySelector('#pvMerge');
    if (mergeBtn) mergeBtn.onclick = () => {
        modal.close();
        if (product.is_merged) openMergeEditor(product);
        else openMergePicker(product);
    };

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

/* Zwei Produkte von Hand zusammenführen — unabhängig davon, ob der Server sie
 * als Schreibvarianten erkannt hat. Die Vorschläge oben auf der Seite finden
 * nur ähnliche Namen; „Klopapier" und „Toilettenpapier" muss man selbst
 * zusammenlegen können. */
function openMergePicker(product) {
    const others = allProducts.filter(p => p.key !== product.key);
    const modal = openModal(`🔗 „${escHtml(product.title || product.key)}" zusammenführen`, `
        <p class="me-hint">Wähle die Produkte, die dasselbe meinen. Sie werden zu einer Zeile —
        auch für künftige Käufe.</p>
        <input type="search" class="me-search" id="mpSearch" placeholder="🔍 Produkt suchen …">
        <div class="me-list me-scroll" id="mpList"></div>
        <label class="me-name-lbl">Name der Gruppe
            <input id="mpName" class="merge-name" value="${escHtml(product.title || product.key)}">
        </label>
        <div class="me-actions">
            <button class="me-cancel">Abbrechen</button>
            <button class="me-save merge-do" disabled>Mindestens eines wählen</button>
        </div>
    `, { wide: true });

    const listEl = modal.root.querySelector('#mpList');
    const searchEl = modal.root.querySelector('#mpSearch');
    const saveBtn = modal.root.querySelector('.me-save');
    const picked = new Set();

    const render = () => {
        const q = searchEl.value.trim().toLowerCase();
        const rows = others
            .filter(p => !q || (p.title || p.key).toLowerCase().includes(q))
            .slice(0, 200);
        listEl.innerHTML = rows.length
            ? `<ul class="merge-variants">${rows.map(p => `
                <li><label class="merge-variant">
                    <input type="checkbox" class="mp-pick" data-key="${escHtml(p.key)}"${picked.has(p.key) ? ' checked' : ''}>
                    <span class="merge-variant-name">${escHtml(p.title || p.key)}</span>
                    <span class="merge-meta">${p.count}× · ${fmtEur(p.total_spent || 0)}</span>
                </label></li>`).join('')}</ul>`
            : '<div class="pv-empty">Kein Produkt gefunden.</div>';
        listEl.querySelectorAll('.mp-pick').forEach(cb => {
            cb.onchange = () => {
                if (cb.checked) picked.add(cb.dataset.key); else picked.delete(cb.dataset.key);
                sync();
            };
        });
    };
    const sync = () => {
        saveBtn.disabled = picked.size < 1;
        saveBtn.textContent = picked.size < 1
            ? 'Mindestens eines wählen'
            : `${picked.size + 1} zusammenführen`;
    };

    searchEl.oninput = render;
    render();
    sync();

    modal.root.querySelector('.me-cancel').onclick = () => modal.close();
    saveBtn.onclick = async () => {
        if (!picked.size) return;
        const title = modal.root.querySelector('#mpName').value.trim() || product.title;
        try {
            const r = await AUSGABEN_API.mergeProducts([product.key, ...picked], title);
            modal.close();
            showToast(`Zusammengeführt (${r.items} Positionen)`, 'success');
            await Promise.all([loadProducts(), loadMergeSuggestions()]);
        } catch (e) { showToast('Fehler: ' + e.message, 'error'); }
    };
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
    // Achse kurz, Tooltip mit Jahr -- die Preishistorie geht ueber Jahre.
    const fullLabels = sorted.map(h => VexCharts.fullDay(h.date));
    // Bezahlter Preis, nicht hochgerechnet: eine 500-g-Packung und eine
    // 1-kg-Packung sind zwei ehrliche Punkte, keine vergleichbaren €/kg-Werte.
    const prices = sorted.map(h => h.total_price);

    const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
    const tick = cssVar('--chart-axis');
    // Flaeche unter der Linie: Verlauf von 18 % auf 0 derselben Farbe.
    const line = cssVar('--chart-1');
    const g = ctx.getContext('2d').createLinearGradient(0, 0, 0, 220);
    g.addColorStop(0, line + '2e');   // 18 % derselben Farbe, wie in DESIGN.md
    g.addColorStop(1, line + '00');

    currentChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: 'Bezahlt',
                data: prices,
                borderColor: line,
                backgroundColor: g,
                borderWidth: 2,
                fill: true,
                tension: 0.35,
                pointRadius: 0,
                pointHoverRadius: 4,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: cssVar('--surface-3'), borderColor: cssVar('--line-strong'),
                    borderWidth: 1, titleColor: cssVar('--text-1'), bodyColor: cssVar('--text-2'),
                    cornerRadius: 12, padding: 10, displayColors: false,
                    callbacks: {
                    title: VexCharts.titleFrom(fullLabels),
                    afterLabel: (c) => {
                        const h = sorted[c.dataIndex];
                        return [h.store_name, mengeLabel(h)].filter(Boolean).join(' · ');
                    }
                } }
            },
            scales: {
                x: { ticks: { color: tick, font: { size: 11 } }, grid: { display: false }, border: { display: false } },
                y: { beginAtZero: false, ticks: { color: tick, font: { size: 11 }, callback: v => fmtEur(v) },
                     grid: { color: cssVar('--chart-grid') }, border: { display: false } }
            }
        }
    });
}

// Menge heißt seit v1.52.0 Stückzahl: sie steht nur da, wenn derselbe Artikel
// mehrfach gekauft wurde. Gewicht und Packungsgröße stehen im Bon-Text darüber.
function mengeLabel(h) {
    const q = itemPieceCount(h);
    return q ? `${q}× gekauft` : '';
}

function renderHistList(items) {
    const wrap = document.getElementById('pvHistList');
    if (!items.length) {
        wrap.innerHTML = '<div class="pv-empty">Keine Käufe in dieser Gruppe.</div>';
        return;
    }
    wrap.innerHTML = items.slice().reverse().map(h => {
        const menge = mengeLabel(h);
        return `
        <div class="pv-hist-item">
            <span class="pv-hist-date">${fmtDate(h.date)}</span>
            <div class="pv-hist-body">
                <div class="pv-hist-desc">${escHtml(h.original_text || h.description || h.base_name || '')}</div>
                <div class="pv-hist-store" style="color:${h.store_color}">${h.store_icon} ${escHtml(h.store_name)}${menge ? ' · ' + menge : ''}</div>
            </div>
            <span class="pv-hist-price">${fmtEur(h.total_price)}</span>
        </div>`;
    }).join('');
}

init();
