let categories = [];

async function init() {
    const me = await ensureLoggedIn(); if (!me) return;
    renderSubnav();
    await Promise.all([loadCategories(), loadRules()]);
    document.getElementById('newBtn').onclick = createCategory;
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';
}

function escHtml(s) { if (!s) return ''; return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function escAttr(s) { return escHtml(s).replace(/"/g, '&quot;'); }

async function loadCategories() {
    const list = document.getElementById('list');
    list.innerHTML = '<div class="muted">Laden …</div>';
    try {
        categories = await AUSGABEN_API.categories();
        if (!categories.length) { list.innerHTML = '<div class="muted">Noch keine Kategorien.</div>'; return; }
        list.innerHTML = '';
        categories.forEach(c => renderRow(c));
    } catch(e) { list.innerHTML = '<div class="muted">Fehler: ' + e.message + '</div>'; }
}

function renderRow(c) {
    const row = document.createElement('div');
    row.className = 'entity-row';
    const initial = (c.name || '?').slice(0,1).toUpperCase();
    row.innerHTML = `
        <div class="entity-badge" style="background:${c.color || '#3b82f6'}">${c.icon || initial}</div>
        <input class="name" value="${escAttr(c.name)}">
        <input class="icon" value="${escAttr(c.icon || '')}" placeholder="📚" maxlength="3">
        <input class="color" type="color" value="${c.color || '#3b82f6'}">
        <button class="save">Speichern</button>
        <button class="merge" title="In andere Kategorie zusammenführen">🔀</button>
        <button class="del" title="Löschen">🗑</button>
    `;
    row.querySelector('.save').onclick = async () => {
        try {
            await AUSGABEN_API.updateCategory(c.id, {
                name: row.querySelector('.name').value.trim(),
                icon: row.querySelector('.icon').value,
                color: row.querySelector('.color').value,
            });
            showToast('Gespeichert', 'success', 1200);
            loadCategories();
        } catch(e) { showToast('Fehler: ' + e.message, 'error'); }
    };
    row.querySelector('.merge').onclick = () => openMergeModal(c);
    row.querySelector('.del').onclick = async () => {
        if (!confirm('Kategorie "' + c.name + '" löschen? Positionen behalten ihre Werte, verlieren nur die Zuordnung.')) return;
        try { await AUSGABEN_API.deleteCategory(c.id); loadCategories(); loadRules(); showToast('Gelöscht', 'success', 1200); }
        catch(e) { showToast('Fehler: ' + e.message, 'error'); }
    };
    document.getElementById('list').appendChild(row);
}

function openMergeModal(src) {
    const targets = categories.filter(x => x.id !== src.id);
    if (!targets.length) { showToast('Keine andere Kategorie zum Verschmelzen vorhanden', 'error'); return; }
    const options = targets.map(t => `<option value="${t.id}">${t.icon || ''} ${escHtml(t.name)}</option>`).join('');
    const modal = openModal(`🔀 „${escHtml(src.name)}" zusammenführen`,
        `<p style="margin-top:0;font-size:0.875rem;color:var(--text-muted)">
            Alle Positionen und Regeln von <strong>${escHtml(src.name)}</strong>
            werden in die gewählte Ziel-Kategorie verschoben. Die Quelle wird danach gelöscht.
        </p>
        <label>Ziel-Kategorie</label>
        <select id="mergeTarget" style="width:100%;margin-bottom:1rem">${options}</select>
        <div style="display:flex;gap:0.5rem;justify-content:flex-end">
            <button class="cancel" style="width:auto;margin:0;background:var(--surface-2);color:var(--text);border:1px solid var(--border)">Abbrechen</button>
            <button class="confirm primary" style="width:auto;margin:0;background:var(--teal);color:#fff">Zusammenführen</button>
        </div>`
    );
    modal.root.querySelector('.cancel').onclick = () => modal.close();
    modal.root.querySelector('.confirm').onclick = async () => {
        const targetId = +modal.root.querySelector('#mergeTarget').value;
        try {
            const res = await AUSGABEN_API.mergeCategory(src.id, targetId);
            modal.close();
            showToast(`${res.moved_items} Positionen verschoben`, 'success', 2500);
            await Promise.all([loadCategories(), loadRules()]);
        } catch (e) { showToast('Fehler: ' + e.message, 'error'); }
    };
}

async function createCategory() {
    const name = document.getElementById('newName').value.trim();
    if (!name) { showToast('Name erforderlich', 'error'); return; }
    try {
        await AUSGABEN_API.createCategory({
            name,
            icon: document.getElementById('newIcon').value || null,
            color: document.getElementById('newColor').value,
        });
        document.getElementById('newName').value = '';
        document.getElementById('newIcon').value = '';
        showToast('Angelegt', 'success', 1200);
        loadCategories();
    } catch(e) { showToast('Fehler: ' + e.message, 'error'); }
}

async function loadRules() {
    const wrap = document.getElementById('rules');
    wrap.innerHTML = '<div class="muted" style="font-size:0.8125rem">Laden …</div>';
    try {
        const rules = await AUSGABEN_API.rules();
        if (!rules.length) { wrap.innerHTML = '<div class="muted" style="font-size:0.8125rem">Noch keine Regeln gelernt.</div>'; return; }
        // Nachschlage-Map für Kategorien
        const catMap = Object.fromEntries((await AUSGABEN_API.categories()).map(c => [c.id, c]));
        wrap.innerHTML = rules.map(r => {
            const cat = catMap[r.category_id];
            return `<div class="rule-row">
                <span class="rule-kw">${escHtml(r.keyword)}</span>
                <span class="rule-arrow">→</span>
                <span class="rule-cat" style="color:${cat?cat.color:'inherit'}">${cat?(cat.icon||'')+' '+escHtml(cat.name):'?'}</span>
                <span class="rule-hits">${r.hit_count}× gelernt</span>
                <button data-id="${r.id}" title="Regel löschen">✕</button>
            </div>`;
        }).join('');
        wrap.querySelectorAll('button[data-id]').forEach(btn => {
            btn.onclick = async () => {
                try { await AUSGABEN_API.deleteRule(+btn.dataset.id); loadRules(); showToast('Regel gelöscht', 'success', 1200); }
                catch(e) { showToast('Fehler: ' + e.message, 'error'); }
            };
        });
    } catch(e) { wrap.innerHTML = '<div class="muted">Fehler: ' + e.message + '</div>'; }
}

init();
