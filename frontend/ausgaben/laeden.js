async function init() {
    const me = await ensureLoggedIn(); if (!me) return;
    await loadStores();
    document.getElementById('newBtn').onclick = createStore;
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';
}

function escHtml(s) { if (!s) return ''; return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function escAttr(s) { return escHtml(s).replace(/"/g, '&quot;'); }

async function loadStores() {
    const list = document.getElementById('list');
    list.innerHTML = '<div class="muted">Laden …</div>';
    try {
        const rows = await AUSGABEN_API.stores();
        if (!rows.length) { list.innerHTML = '<div class="muted">Noch keine Läden angelegt.</div>'; return; }
        list.innerHTML = '';
        rows.forEach(s => renderRow(s));
    } catch(e) { list.innerHTML = '<div class="muted">Fehler: ' + e.message + '</div>'; }
}

function renderRow(s) {
    const row = document.createElement('div');
    row.className = 'entity-row';
    const initial = (s.name || '?').slice(0,1).toUpperCase();
    row.innerHTML = `
        <div class="entity-badge" style="background:${s.color || '#6b7280'}">${s.icon || initial}</div>
        <input class="name" value="${escAttr(s.name)}">
        <input class="icon" value="${escAttr(s.icon || '')}" placeholder="🛒" maxlength="3">
        <input class="color" type="color" value="${s.color || '#6b7280'}">
        <button class="save">Speichern</button>
        <button class="del" title="Löschen">🗑</button>
    `;
    row.querySelector('.save').onclick = async () => {
        try {
            await AUSGABEN_API.updateStore(s.id, {
                name: row.querySelector('.name').value.trim(),
                icon: row.querySelector('.icon').value,
                color: row.querySelector('.color').value,
            });
            showToast('Gespeichert', 'success', 1200);
            loadStores();
        } catch(e) { showToast('Fehler: ' + e.message, 'error'); }
    };
    row.querySelector('.del').onclick = async () => {
        if (!confirm('Laden "' + s.name + '" löschen? (Bestehende Ausgaben behalten ihre Werte, verlieren nur die Verknüpfung)')) return;
        try { await AUSGABEN_API.deleteStore(s.id); loadStores(); showToast('Gelöscht', 'success', 1200); }
        catch(e) { showToast('Fehler: ' + e.message, 'error'); }
    };
    document.getElementById('list').appendChild(row);
}

async function createStore() {
    const name = document.getElementById('newName').value.trim();
    if (!name) { showToast('Name erforderlich', 'error'); return; }
    try {
        await AUSGABEN_API.createStore({
            name,
            icon: document.getElementById('newIcon').value || null,
            color: document.getElementById('newColor').value,
        });
        document.getElementById('newName').value = '';
        document.getElementById('newIcon').value = '';
        showToast('Angelegt', 'success', 1200);
        loadStores();
    } catch(e) { showToast('Fehler: ' + e.message, 'error'); }
}

init();
