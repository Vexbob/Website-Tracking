/* Läden — v1.53.0
 *
 * Gleiche Kur wie bei den Kategorien: statt einer Liste aus dauerhaft offenen
 * Formularzeilen jetzt Karten mit Nutzungszahlen (Einkäufe + Summe aus
 * stats/by-store), Suche und Sortierung. Bearbeitet wird im Modal.
 */
const SKEL_CARDS = Array.from({ length: 6 }, () =>
    '<article class="entity-card"><span class="skel skel-line" style="width:2rem;height:2rem;border-radius:10px"></span>' +
    '<div class="entity-main"><span class="skel skel-line long"></span>' +
    '<span class="skel skel-line short"></span></div></article>').join('');

function emptyBox(mark, text, error) {
    return '<div class="empty' + (error ? ' is-error' : '') + '">' +
        '<span class="empty-mark" aria-hidden="true">' + mark + '</span>' +
        '<p class="empty-text">' + text + '</p></div>';
}

let stores = [];
let usage = {};          // store_id -> { count, total }
let maxSpent = 0;

async function init() {
    const me = await ensureLoggedIn(); if (!me) return;
    renderSubnav();
    document.getElementById('addBtn').onclick = openAddModal;
    document.getElementById('q').oninput = render;
    document.getElementById('sort').onchange = render;
    await loadStores();
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';
}

function escHtml(s) { if (!s) return ''; return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function escAttr(s) { return escHtml(s).replace(/"/g, '&quot;'); }

async function loadStores() {
    const list = document.getElementById('list');
    list.innerHTML = SKEL_CARDS;
    try {
        const [rows, stats] = await Promise.all([
            AUSGABEN_API.stores(),
            AUSGABEN_API.statsStore().catch(() => []),
        ]);
        stores = rows || [];
        usage = {};
        maxSpent = 0;
        (stats || []).forEach(r => {
            if (!r.store_id) return;      // 0 = "Ohne Laden"
            const total = Number(r.total) || 0;
            usage[r.store_id] = { count: Number(r.visit_count) || 0, total };
            if (total > maxSpent) maxSpent = total;
        });
        render();
    } catch (e) {
        list.innerHTML = emptyBox('\u26A0\uFE0F',
            'Die L\u00e4den konnten nicht geladen werden: ' + escHtml(e.message), true);
    }
}

function sortedStores() {
    const q = (document.getElementById('q').value || '').trim().toLowerCase();
    const mode = document.getElementById('sort').value;
    const rows = stores.filter(s => !q || (s.name || '').toLowerCase().includes(q));
    const u = s => usage[s.id] || { count: 0, total: 0 };
    if (mode === 'name') rows.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
    else if (mode === 'count') rows.sort((a, b) => u(b).count - u(a).count || (a.name || '').localeCompare(b.name || ''));
    else rows.sort((a, b) => u(b).total - u(a).total || (a.name || '').localeCompare(b.name || ''));
    return rows;
}

function render() {
    const list = document.getElementById('list');
    const rows = sortedStores();
    const unused = stores.filter(s => !(usage[s.id] && usage[s.id].count));

    document.getElementById('count').textContent = rows.length === stores.length
        ? `${stores.length} Läden${unused.length ? ` · ${unused.length} ohne Einkauf` : ''}`
        : `${rows.length} von ${stores.length} Läden`;

    renderCleanup(unused);

    if (!stores.length) {
        list.innerHTML = emptyBox('\uD83C\uDFEA',
            'Noch keine L\u00e4den. Beim Scannen eines Bons legt Vexbob den erkannten Laden selbst an.');
        return;
    }
    if (!rows.length) {
        list.innerHTML = emptyBox('\uD83D\uDD0D',
            'Kein Laden passt zu dieser Suche. Ein k\u00fcrzerer Begriff findet mehr.');
        return;
    }

    list.innerHTML = rows.map(s => {
        const u = usage[s.id] || { count: 0, total: 0 };
        const color = s.color || '#6b7280';
        const initial = (s.name || '?').slice(0, 1).toUpperCase();
        const share = maxSpent > 0 ? Math.round((u.total / maxSpent) * 100) : 0;
        const meta = u.count
            ? `${u.count} ${u.count === 1 ? 'Einkauf' : 'Einkäufe'} · ${fmtEur(u.total)}`
            : 'noch kein Einkauf';
        return `<article class="entity-card cat-card${u.count ? '' : ' is-unused'}" style="--cat-color:${escAttr(color)}">
            <span class="entity-avatar" aria-hidden="true">${escHtml(s.icon || initial)}</span>
            <div class="entity-main">
                <div class="entity-title">${escHtml(s.name)}</div>
                <div class="entity-sub">${meta}</div>
                ${u.count ? `<div class="cat-bar"><span style="width:${share}%"></span></div>` : ''}
            </div>
            <button class="entity-action" data-id="${s.id}" title="Bearbeiten" aria-label="${escAttr(s.name)} bearbeiten">✏️</button>
        </article>`;
    }).join('');

    list.querySelectorAll('.entity-action').forEach(btn => {
        btn.onclick = () => {
            const st = stores.find(s => s.id === +btn.dataset.id);
            if (st) openEditModal(st);
        };
    });
}

function renderCleanup(unused) {
    const box = document.getElementById('cleanup');
    if (unused.length < 3) { box.innerHTML = ''; return; }
    box.innerHTML = `<div class="cleanup-bar">
        <span><strong>${unused.length} Läden</strong> hängen an keinem einzigen Einkauf.</span>
        <button class="cleanup-do">Alle löschen</button>
    </div>`;
    box.querySelector('.cleanup-do').onclick = async () => {
        const ok = await askConfirm({
            title: `${unused.length} ungenutzte Läden löschen?`,
            text: 'Betroffen sind nur Läden ohne jeden Einkauf.',
            ok: 'Löschen', danger: true,
        });
        if (!ok) return;
        let done = 0;
        for (const s of unused) {
            try { await AUSGABEN_API.deleteStore(s.id); done++; } catch (e) { /* weiter */ }
        }
        showToast(`${done} Läden gelöscht`, 'success');
        await loadStores();
    };
}

function storeFormHtml(s) {
    return `<div class="form-grid">
        <div>
            <label for="sfName">Name</label>
            <input type="text" id="sfName" value="${escAttr(s.name || '')}" placeholder="z.B. Billa" style="margin:0">
        </div>
        <div class="row2">
            <div>
                <label for="sfIcon">Icon</label>
                <input type="text" id="sfIcon" value="${escAttr(s.icon || '')}" placeholder="🛒" maxlength="3" style="margin:0">
            </div>
            <div>
                <label for="sfColor">Farbe</label>
                <input type="color" id="sfColor" value="${escAttr(s.color || '#6b7280')}" style="margin:0;height:42px;padding:2px">
            </div>
        </div>
    </div>`;
}

function openAddModal() {
    const modal = openModal('Neuer Laden', `
        ${storeFormHtml({ color: '#6b7280' })}
        <div class="modal-actions">
            <button class="cancel">Abbrechen</button>
            <button class="save primary">Anlegen</button>
        </div>
    `);
    modal.root.querySelector('.cancel').onclick = () => modal.close();
    modal.root.querySelector('#sfName').focus();
    modal.root.querySelector('.save').onclick = async () => {
        const name = modal.root.querySelector('#sfName').value.trim();
        if (!name) { showToast('Name erforderlich', 'error'); return; }
        try {
            await AUSGABEN_API.createStore({
                name,
                icon: modal.root.querySelector('#sfIcon').value || null,
                color: modal.root.querySelector('#sfColor').value,
            });
            modal.close();
            showToast('Angelegt', 'success', 1200);
            await loadStores();
        } catch (e) { showToast('Fehler: ' + e.message, 'error'); }
    };
}

function openEditModal(s) {
    const u = usage[s.id] || { count: 0, total: 0 };
    const modal = openModal(`${s.icon || '🏪'} ${escHtml(s.name)}`, `
        <p class="page-sub" style="margin:0 0 1rem">${u.count
            ? `${u.count} Einkäufe · ${fmtEur(u.total)} insgesamt`
            : 'An diesem Laden hängt noch kein Einkauf.'}</p>
        ${storeFormHtml(s)}
        <div class="modal-actions">
            <button class="del danger">Löschen</button>
            <button class="cancel">Abbrechen</button>
            <button class="save primary">Speichern</button>
        </div>
    `);
    modal.root.querySelector('.cancel').onclick = () => modal.close();
    modal.root.querySelector('.save').onclick = async () => {
        try {
            await AUSGABEN_API.updateStore(s.id, {
                name: modal.root.querySelector('#sfName').value.trim(),
                icon: modal.root.querySelector('#sfIcon').value,
                color: modal.root.querySelector('#sfColor').value,
            });
            modal.close();
            showToast('Gespeichert', 'success', 1200);
            await loadStores();
        } catch (e) { showToast('Fehler: ' + e.message, 'error'); }
    };
    modal.root.querySelector('.del').onclick = async () => {
        const ok = await askConfirm({
            title: `„${s.name}" löschen?`,
            text: u.count
                ? `${u.count} Einkäufe behalten ihre Beträge, verlieren aber die Zuordnung zum Laden.`
                : 'Der Laden wird nirgends verwendet.',
            ok: 'Löschen', danger: true,
        });
        if (!ok) return;
        try {
            await AUSGABEN_API.deleteStore(s.id);
            modal.close();
            showToast('Gelöscht', 'success', 1200);
            await loadStores();
        } catch (e) { showToast('Fehler: ' + e.message, 'error'); }
    };
}

init();
