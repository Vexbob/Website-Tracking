/* Kategorien — v1.53.0
 *
 * Die Seite war eine Liste aus Formularzeilen: jede Kategorie zeigte dauerhaft
 * Namensfeld, Icon-Feld, Farbwähler und drei Buttons. Bei den ~80 Kategorien,
 * die der KI-Parser im Laufe der Zeit anlegt, war das eine Wand aus
 * Eingabefeldern, in der man nichts wiederfand — und sie verriet nichts
 * darüber, welche Kategorie überhaupt benutzt wird.
 *
 * Jetzt: Karten mit Nutzungszahlen (Positionen + Summe, aus stats/by-category),
 * Suche, Sortierung, ein Aufräum-Hinweis für nie benutzte Kategorien. Bearbeitet
 * wird im Modal — dort liegen auch Zusammenführen und Löschen.
 */
let categories = [];
let usage = {};          // category_id -> { count, total }
let maxSpent = 0;

async function init() {
    const me = await ensureLoggedIn(); if (!me) return;
    renderSubnav();
    document.getElementById('addBtn').onclick = openAddModal;
    document.getElementById('q').oninput = render;
    document.getElementById('sort').onchange = render;
    await Promise.all([loadCategories(), loadRules()]);
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';
}

function escHtml(s) { if (!s) return ''; return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function escAttr(s) { return escHtml(s).replace(/"/g, '&quot;'); }

/* Nutzung kommt aus der Kategorie-Statistik ohne Zeitraumfilter — das ist die
 * Gesamtzahl aller je erfassten Positionen, genau das, was für "wird das hier
 * überhaupt benutzt?" zählt. Schlägt der Aufruf fehl, bleibt die Liste ohne
 * Zahlen statt ganz leer. */
async function loadCategories() {
    const list = document.getElementById('list');
    list.innerHTML = '<div class="empty-note">Lade …</div>';
    try {
        const [cats, stats] = await Promise.all([
            AUSGABEN_API.categories(),
            AUSGABEN_API.statsCategory().catch(() => []),
        ]);
        categories = cats || [];
        usage = {};
        maxSpent = 0;
        (stats || []).forEach(r => {
            if (!r.category_id) return;   // 0 = "Unkategorisiert"
            const total = Number(r.total) || 0;
            usage[r.category_id] = { count: Number(r.item_count) || 0, total };
            if (total > maxSpent) maxSpent = total;
        });
        render();
    } catch (e) {
        list.innerHTML = `<div class="empty-note">Fehler: ${escHtml(e.message)}</div>`;
    }
}

function sortedCategories() {
    const q = (document.getElementById('q').value || '').trim().toLowerCase();
    const mode = document.getElementById('sort').value;
    const rows = categories.filter(c => !q || (c.name || '').toLowerCase().includes(q));
    const u = c => usage[c.id] || { count: 0, total: 0 };
    if (mode === 'name') rows.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
    else if (mode === 'count') rows.sort((a, b) => u(b).count - u(a).count || (a.name || '').localeCompare(b.name || ''));
    else rows.sort((a, b) => u(b).total - u(a).total || (a.name || '').localeCompare(b.name || ''));
    return rows;
}

function render() {
    const list = document.getElementById('list');
    const rows = sortedCategories();
    const unused = categories.filter(c => !(usage[c.id] && usage[c.id].count));

    document.getElementById('count').textContent = rows.length === categories.length
        ? `${categories.length} Kategorien${unused.length ? ` · ${unused.length} nie benutzt` : ''}`
        : `${rows.length} von ${categories.length} Kategorien`;

    renderCleanup(unused);

    if (!categories.length) {
        list.innerHTML = '<div class="empty-note">Noch keine Kategorien. Beim ersten gescannten Bon legt der Parser sie selbst an.</div>';
        return;
    }
    if (!rows.length) {
        list.innerHTML = '<div class="empty-note">Keine Kategorie gefunden.</div>';
        return;
    }

    list.innerHTML = rows.map(c => {
        const u = usage[c.id] || { count: 0, total: 0 };
        const color = c.color || '#3b82f6';
        const initial = (c.name || '?').slice(0, 1).toUpperCase();
        const share = maxSpent > 0 ? Math.round((u.total / maxSpent) * 100) : 0;
        const meta = u.count
            ? `${u.count} Position${u.count === 1 ? '' : 'en'} · ${fmtEur(u.total)}`
            : 'noch nicht benutzt';
        return `<article class="entity-card cat-card${u.count ? '' : ' is-unused'}" style="--cat-color:${escAttr(color)}">
            <span class="entity-avatar" aria-hidden="true">${escHtml(c.icon || initial)}</span>
            <div class="entity-main">
                <div class="entity-title">${escHtml(c.name)}</div>
                <div class="entity-sub">${meta}</div>
                ${u.count ? `<div class="cat-bar"><span style="width:${share}%"></span></div>` : ''}
            </div>
            <button class="entity-action" data-id="${c.id}" title="Bearbeiten" aria-label="${escAttr(c.name)} bearbeiten">✏️</button>
        </article>`;
    }).join('');

    list.querySelectorAll('.entity-action').forEach(btn => {
        btn.onclick = () => {
            const cat = categories.find(c => c.id === +btn.dataset.id);
            if (cat) openEditModal(cat);
        };
    });
}

/* Nie benutzte Kategorien sammeln sich an, weil der Parser bei jedem Bon neue
 * anlegen darf. Ein Sammel-Löschen erspart 20 Einzelbestätigungen. */
function renderCleanup(unused) {
    const box = document.getElementById('cleanup');
    if (unused.length < 3) { box.innerHTML = ''; return; }
    box.innerHTML = `<div class="cleanup-bar">
        <span><strong>${unused.length} Kategorien</strong> hängen an keiner einzigen Position.</span>
        <button class="cleanup-do">Alle löschen</button>
    </div>`;
    box.querySelector('.cleanup-do').onclick = async () => {
        const ok = await askConfirm({
            title: `${unused.length} leere Kategorien löschen?`,
            text: 'Betroffen sind nur Kategorien ohne jede Position. Anlegen kannst du sie jederzeit wieder.',
            ok: 'Löschen', danger: true,
        });
        if (!ok) return;
        let done = 0;
        for (const c of unused) {
            try { await AUSGABEN_API.deleteCategory(c.id); done++; } catch (e) { /* weiter */ }
        }
        showToast(`${done} Kategorien gelöscht`, 'success');
        await Promise.all([loadCategories(), loadRules()]);
    };
}

function categoryFormHtml(c) {
    return `<div class="form-grid">
        <div>
            <label for="cfName">Name</label>
            <input type="text" id="cfName" value="${escAttr(c.name || '')}" placeholder="z.B. Käse" style="margin:0">
        </div>
        <div class="row2">
            <div>
                <label for="cfIcon">Icon</label>
                <input type="text" id="cfIcon" value="${escAttr(c.icon || '')}" placeholder="🧀" maxlength="3" style="margin:0">
            </div>
            <div>
                <label for="cfColor">Farbe</label>
                <input type="color" id="cfColor" value="${escAttr(c.color || '#3b82f6')}" style="margin:0;height:42px;padding:2px">
            </div>
        </div>
    </div>`;
}

function openAddModal() {
    const modal = openModal('Neue Kategorie', `
        ${categoryFormHtml({ color: '#3b82f6' })}
        <div class="modal-actions">
            <button class="cancel">Abbrechen</button>
            <button class="save primary">Anlegen</button>
        </div>
    `);
    modal.root.querySelector('.cancel').onclick = () => modal.close();
    modal.root.querySelector('#cfName').focus();
    modal.root.querySelector('.save').onclick = async () => {
        const name = modal.root.querySelector('#cfName').value.trim();
        if (!name) { showToast('Name erforderlich', 'error'); return; }
        try {
            await AUSGABEN_API.createCategory({
                name,
                icon: modal.root.querySelector('#cfIcon').value || null,
                color: modal.root.querySelector('#cfColor').value,
            });
            modal.close();
            showToast('Angelegt', 'success', 1200);
            await loadCategories();
        } catch (e) { showToast('Fehler: ' + e.message, 'error'); }
    };
}

function openEditModal(c) {
    const u = usage[c.id] || { count: 0, total: 0 };
    const others = categories.filter(x => x.id !== c.id);
    const modal = openModal(`${c.icon || '🏷️'} ${escHtml(c.name)}`, `
        <p class="page-sub" style="margin:0 0 1rem">${u.count
            ? `${u.count} Position${u.count === 1 ? '' : 'en'} · ${fmtEur(u.total)} insgesamt`
            : 'Diese Kategorie hängt an keiner Position.'}</p>
        ${categoryFormHtml(c)}
        ${others.length ? `<div style="margin-top:1rem">
            <label for="cfMerge">In andere Kategorie zusammenführen</label>
            <select id="cfMerge" style="margin:0">
                <option value="">– nicht zusammenführen –</option>
                ${others.map(t => `<option value="${t.id}">${escHtml((t.icon || '') + ' ' + t.name)}</option>`).join('')}
            </select>
            <p class="page-sub" style="margin:0.375rem 0 0;font-size:0.75rem">Alle Positionen und Regeln
            wandern in die gewählte Kategorie, „${escHtml(c.name)}" wird danach gelöscht.</p>
        </div>` : ''}
        <div class="modal-actions">
            <button class="del danger">Löschen</button>
            <button class="cancel">Abbrechen</button>
            <button class="save primary">Speichern</button>
        </div>
    `);
    modal.root.querySelector('.cancel').onclick = () => modal.close();

    modal.root.querySelector('.save').onclick = async () => {
        const mergeSel = modal.root.querySelector('#cfMerge');
        const targetId = mergeSel ? +mergeSel.value : 0;
        try {
            if (targetId) {
                const res = await AUSGABEN_API.mergeCategory(c.id, targetId);
                modal.close();
                showToast(`${res.moved_items} Positionen verschoben`, 'success', 2500);
            } else {
                await AUSGABEN_API.updateCategory(c.id, {
                    name: modal.root.querySelector('#cfName').value.trim(),
                    icon: modal.root.querySelector('#cfIcon').value,
                    color: modal.root.querySelector('#cfColor').value,
                });
                modal.close();
                showToast('Gespeichert', 'success', 1200);
            }
            await Promise.all([loadCategories(), loadRules()]);
        } catch (e) { showToast('Fehler: ' + e.message, 'error'); }
    };

    modal.root.querySelector('.del').onclick = async () => {
        const ok = await askConfirm({
            title: `„${c.name}" löschen?`,
            text: u.count
                ? `${u.count} Position${u.count === 1 ? ' behält ihren' : 'en behalten ihre'} Wert${u.count === 1 ? '' : 'e'}, verliert nur die Zuordnung.`
                : 'Die Kategorie wird nirgends verwendet.',
            ok: 'Löschen', danger: true,
        });
        if (!ok) return;
        try {
            await AUSGABEN_API.deleteCategory(c.id);
            modal.close();
            showToast('Gelöscht', 'success', 1200);
            await Promise.all([loadCategories(), loadRules()]);
        } catch (e) { showToast('Fehler: ' + e.message, 'error'); }
    };
}

async function loadRules() {
    const wrap = document.getElementById('rules');
    const countEl = document.getElementById('rulesCount');
    wrap.innerHTML = '<div class="empty-note">Lade …</div>';
    try {
        const rules = await AUSGABEN_API.rules();
        countEl.textContent = rules.length ? `${rules.length} gelernt` : '';
        if (!rules.length) {
            wrap.innerHTML = '<div class="empty-note">Noch keine Regeln gelernt.</div>';
            return;
        }
        // loadRules() laeuft parallel zu loadCategories() -- beim ersten Aufruf
        // kann die Liste hier also noch leer sein.
        const cats = categories.length ? categories : (await AUSGABEN_API.categories().catch(() => []));
        const catMap = Object.fromEntries(cats.map(c => [c.id, c]));
        wrap.innerHTML = rules.map(r => {
            const cat = catMap[r.category_id];
            return `<div class="rule-row">
                <span class="rule-kw">${escHtml(r.keyword)}</span>
                <span class="rule-arrow">→</span>
                <span class="rule-cat" style="color:${cat ? escAttr(cat.color) : 'inherit'}">${cat ? escHtml((cat.icon || '') + ' ' + cat.name) : '?'}</span>
                <span class="rule-hits">${r.hit_count}× gelernt</span>
                <button data-id="${r.id}" title="Regel löschen" aria-label="Regel löschen">✕</button>
            </div>`;
        }).join('');
        wrap.querySelectorAll('button[data-id]').forEach(btn => {
            btn.onclick = async () => {
                try { await AUSGABEN_API.deleteRule(+btn.dataset.id); loadRules(); showToast('Regel gelöscht', 'success', 1200); }
                catch (e) { showToast('Fehler: ' + e.message, 'error'); }
            };
        });
    } catch (e) {
        wrap.innerHTML = `<div class="empty-note">Fehler: ${escHtml(e.message)}</div>`;
    }
}

init();
