/* Notizen-Modul — Master-Detail (Apple-Notes-Stil) — Vexbob */

const NOTES_API = {
    list:   (archived) => apiCall('/api/notes' + (archived ? '?archived=true' : '')),
    get:    (id) => apiCall(`/api/notes/${id}`),
    create: (b) => apiCall('/api/notes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }),
    update: (id, b) => apiCall(`/api/notes/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }),
    remove: (id) => apiCall(`/api/notes/${id}`, { method: 'DELETE' }),
};

const COLORS = [
    { key: 'default', hex: '#9ca3af' },
    { key: 'red',     hex: '#ef4444' },
    { key: 'orange',  hex: '#f59e0b' },
    { key: 'yellow',  hex: '#eab308' },
    { key: 'green',   hex: '#22c55e' },
    { key: 'blue',    hex: '#3b82f6' },
    { key: 'purple',  hex: '#8b5cf6' },
    { key: 'pink',    hex: '#ec4899' },
];

let state = {
    notes: [],
    selectedId: null,
    query: '',
    sortMode: 'updated',     // updated | created | title
    showArchived: false,
    saveTimer: null,
    saveToken: 0,            // verhindert Race-Conditions beim schnellen Wechseln
    status: 'idle',          // idle | saving | saved
    statusTimer: null,
    justCreated: new Set(),   // IDs leerer Notizen, die beim Verlassen gelöscht werden
    lastDeleted: null,       // für Undo
};

// ---------- Boot ----------
async function boot() {
    if (!isLoggedIn()) { window.location.href = '/private/login.html'; return; }
    try {
        const me = await fetchMe(true);
        document.getElementById('userLabel').textContent = '👤 ' + me.username;
    } catch (e) { return; }
    document.getElementById('logoutBtn').onclick = () => { clearToken(); location.reload(); };
    document.getElementById('themeBtn').onclick = toggleTheme;
    bindUI();
    await loadNotes();
    // Deep-Link: #note-42 öffnet die Notiz direkt
    const m = location.hash.match(/^#note-(\d+)$/);
    if (m && state.notes.some(n => n.id === Number(m[1]))) {
        selectNote(Number(m[1]));
    }
    window.addEventListener('hashchange', onHashChange);
}

function bindUI() {
    document.getElementById('nzNew').onclick = newNote;
    document.getElementById('nzSearch').addEventListener('input', (e) => {
        state.query = e.target.value.trim().toLowerCase();
        renderSidebar();
    });
    document.getElementById('nzSort').addEventListener('change', (e) => {
        state.sortMode = e.target.value;
        renderSidebar();
    });
    document.getElementById('nzArchiveBtn').onclick = async () => {
        // Vor dem View-Wechsel offene Änderungen sichern + leere Neue löschen.
        await flushSave();
        await cleanupEmptyJustCreated();
        state.showArchived = !state.showArchived;
        const btn = document.getElementById('nzArchiveBtn');
        btn.classList.toggle('active', state.showArchived);
        btn.textContent = state.showArchived ? '📋 Aktiv' : '🗄️ Archiv';
        state.selectedId = null;
        history.replaceState(null, '', location.pathname);
        await loadNotes();
    };
    document.getElementById('nzBack').onclick = backToList;
    // Detail-Aktionen
    document.getElementById('nzDTitle').addEventListener('input', onTitleInput);
    document.getElementById('nzDContent').addEventListener('input', onContentInput);
    document.getElementById('nzDPin').onclick = () => togglePin(state.selectedId);
    document.getElementById('nzDArchive').onclick = () => toggleArchive(state.selectedId);
    document.getElementById('nzDDelete').onclick = () => deleteNote(state.selectedId);
    renderColorPicker();
}

// ---------- Daten laden ----------
async function loadNotes() {
    try {
        state.notes = await NOTES_API.list(state.showArchived);
    } catch (e) {
        showToast('Laden fehlgeschlagen: ' + e.message, true);
        return;
    }
    renderSidebar();
    if (state.selectedId && !state.notes.some(n => n.id === state.selectedId)) {
        state.selectedId = null;
    }
    renderDetail();
}

// ---------- Sidebar ----------
function sortedNotes() {
    const arr = state.notes.slice();
    if (state.sortMode === 'title') {
        arr.sort((a, b) => (a.title || '').localeCompare(b.title || '', 'de') || b.id - a.id);
    } else if (state.sortMode === 'created') {
        arr.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || '') || b.id - a.id);
    } else {
        arr.sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || '') || b.id - a.id);
    }
    return arr;
}

function filteredNotes() {
    let notes = sortedNotes();
    if (state.query) {
        notes = notes.filter(n =>
            ((n.title || '') + ' ' + (n.content || '')).toLowerCase().includes(state.query));
    }
    return notes;
}

function renderSidebar() {
    const list = document.getElementById('nzList');
    const notes = filteredNotes();
    list.innerHTML = '';
    if (notes.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'nz-list-empty';
        empty.textContent = state.query
            ? 'Keine Treffer'
            : (state.showArchived ? 'Keine archivierten Notizen' : 'Noch keine Notizen');
        list.appendChild(empty);
        return;
    }
    const pinned = notes.filter(n => n.pinned);
    const others = notes.filter(n => !n.pinned);
    if (pinned.length && !state.showArchived) {
        const sec = document.createElement('div');
        sec.className = 'nz-section';
        sec.textContent = '📌 Pinniert';
        list.appendChild(sec);
        pinned.forEach(n => list.appendChild(buildItem(n)));
        if (others.length) {
            const sec2 = document.createElement('div');
            sec2.className = 'nz-section';
            sec2.textContent = 'Alle Notizen';
            list.appendChild(sec2);
        }
    }
    others.forEach(n => list.appendChild(buildItem(n)));
}

function buildItem(n) {
    const item = document.createElement('div');
    item.className = `nz-item nz-color-${n.color || 'default'}` + (n.id === state.selectedId ? ' active' : '');
    item.dataset.id = n.id;
    item.onclick = () => selectNote(n.id);

    const main = document.createElement('div');
    main.className = 'nz-item-main';
    const title = document.createElement('div');
    title.className = 'nz-item-title';
    title.textContent = n.title || '';
    main.appendChild(title);
    const prev = document.createElement('div');
    prev.className = 'nz-item-preview';
    prev.textContent = firstLine(n.content);
    main.appendChild(prev);
    const date = document.createElement('div');
    date.className = 'nz-item-date';
    date.textContent = relTime(n.updated_at);
    main.appendChild(date);
    item.appendChild(main);

    if (n.pinned) {
        const pin = document.createElement('span');
        pin.className = 'nz-item-pin';
        pin.textContent = '📌';
        item.appendChild(pin);
    }
    return item;
}

function firstLine(content) {
    if (!content) return '';
    const line = content.split('\n').find(l => l.trim());
    return line || '';
}

// ---------- Detail & Auswahl ----------
async function selectNote(id) {
    if (id === state.selectedId) return;
    // Offene Änderungen sichern, leere Neue aufräumen, bevor gewechselt wird.
    await flushSave();
    await cleanupEmptyJustCreated();
    state.selectedId = id;
    history.replaceState(null, '', `#note-${id}`);
    renderSidebar();
    renderDetail();
    document.getElementById('nzApp').classList.add('show-detail');
}

function backToList() {
    // Vor Zurück-Navigation sichern + aufräumen.
    (async () => {
        await flushSave();
        await cleanupEmptyJustCreated();
        state.selectedId = null;
        history.replaceState(null, '', location.pathname);
        renderSidebar();
        renderDetail();
        document.getElementById('nzApp').classList.remove('show-detail');
    })();
}

function renderDetail() {
    const empty = document.getElementById('nzDetailEmpty');
    const edit = document.getElementById('nzDetailEdit');
    const n = state.notes.find(x => x.id === state.selectedId);
    if (!n) {
        empty.style.display = '';
        edit.style.display = 'none';
        return;
    }
    empty.style.display = 'none';
    edit.style.display = 'flex';
    document.getElementById('nzDTitle').value = n.title || '';
    document.getElementById('nzDContent').value = n.content || '';
    updateDetailActions(n);
    renderDetailPreview();
    setStatus('idle');
    autoSizeContent();
}

function updateDetailActions(n) {
    const pinBtn = document.getElementById('nzDPin');
    pinBtn.classList.toggle('on', !!n.pinned);
    pinBtn.textContent = n.pinned ? '📌 Pinniert' : '📍 Pinnen';
    const archBtn = document.getElementById('nzDArchive');
    archBtn.textContent = n.archived ? '📋 Wiederherstellen' : '🗄️ Archivieren';
    // Farbauswahl spiegeln
    document.querySelectorAll('#nzDColor button').forEach(b => {
        b.classList.toggle('sel', b.dataset.color === (n.color || 'default'));
    });
}

function renderColorPicker() {
    const wrap = document.getElementById('nzDColor');
    wrap.innerHTML = '';
    COLORS.forEach(c => {
        const b = document.createElement('button');
        b.type = 'button';
        b.title = c.key;
        b.style.background = c.hex;
        b.dataset.color = c.key;
        b.onclick = () => setColor(state.selectedId, c.key);
        wrap.appendChild(b);
    });
}

// ---------- Auto-Save ----------
function onTitleInput() {
    const n = state.notes.find(x => x.id === state.selectedId);
    if (n) n.title = document.getElementById('nzDTitle').value;
    renderSidebarItemTitle(n);
    scheduleSave();
}
function onContentInput() {
    const n = state.notes.find(x => x.id === state.selectedId);
    if (n) n.content = document.getElementById('nzDContent').value;
    renderSidebarItemPreview(n);
    renderDetailPreview();
    autoSizeContent();
    scheduleSave();
}

function scheduleSave() {
    clearTimeout(state.saveTimer);
    setStatus('saving');
    state.saveTimer = setTimeout(doSave, 800);
}

async function doSave() {
    const n = state.notes.find(x => x.id === state.selectedId);
    if (!n) { setStatus('idle'); return; }
    const myToken = ++state.saveToken;
    const body = { title: n.title || '', content: n.content || '' };
    try {
        const upd = await NOTES_API.update(n.id, body);
        // Nur übernehmen, wenn nicht zwischenzeitlich eine neuere Save-Anfrage lief.
        if (myToken === state.saveToken) {
            Object.assign(n, { updated_at: upd.updated_at });
            setStatus('saved');
            clearTimeout(state.statusTimer);
            state.statusTimer = setTimeout(() => setStatus('idle'), 2000);
        }
    } catch (e) {
        if (myToken === state.saveToken) {
            setStatus('idle');
            showToast('Speichern fehlgeschlagen: ' + e.message, true);
        }
    }
}

async function flushSave() {
    if (state.saveTimer) {
        clearTimeout(state.saveTimer);
        state.saveTimer = null;
        await doSave();
    }
}

function setStatus(s) {
    state.status = s;
    const el = document.getElementById('nzDStatus');
    const txt = el.querySelector('.txt');
    el.classList.remove('saving', 'saved');
    if (s === 'saving') { el.classList.add('saving'); txt.textContent = 'Speichern…'; }
    else if (s === 'saved') { el.classList.add('saved'); txt.textContent = 'Gespeichert ✓'; }
    else {
        const n = state.notes.find(x => x.id === state.selectedId);
        txt.textContent = n ? 'Bearbeitet ' + relTime(n.updated_at) : '';
    }
}

// ---------- Aktionen ----------
async function newNote() {
    await flushSave();
    await cleanupEmptyJustCreated();
    try {
        const created = await NOTES_API.create({ title: '', content: '' });
        state.notes.unshift(created);
        state.justCreated.add(created.id);
        state.query = '';
        document.getElementById('nzSearch').value = '';
        await selectNote(created.id);
        document.getElementById('nzDTitle').focus();
    } catch (e) {
        showToast('Anlegen fehlgeschlagen: ' + e.message, true);
    }
}

async function togglePin(id) {
    const n = state.notes.find(x => x.id === id);
    if (!n) return;
    try {
        const upd = await NOTES_API.update(id, { pinned: !n.pinned });
        Object.assign(n, upd);
        updateDetailActions(n);
        renderSidebar();
        haptic('tap');
    } catch (e) { showToast('Fehler: ' + e.message, true); }
}

async function toggleArchive(id) {
    const n = state.notes.find(x => x.id === id);
    if (!n) return;
    const archived = !n.archived;
    await flushSave();
    try {
        const upd = await NOTES_API.update(id, { archived });
        Object.assign(n, upd);
        // Aus aktueller Ansicht entfernen, da Liste nach archiv filtert.
        state.notes = state.notes.filter(x => x.id !== id);
        state.selectedId = null;
        history.replaceState(null, '', location.pathname);
        renderSidebar();
        renderDetail();
        document.getElementById('nzApp').classList.remove('show-detail');
        showToast(archived ? 'Notiz archiviert' : 'Notiz wiederhergestellt');
    } catch (e) { showToast('Fehler: ' + e.message, true); }
}

async function setColor(id, color) {
    const n = state.notes.find(x => x.id === id);
    if (!n) return;
    try {
        const upd = await NOTES_API.update(id, { color });
        Object.assign(n, upd);
        updateDetailActions(n);
        renderSidebar();
    } catch (e) { showToast('Fehler: ' + e.message, true); }
}

async function deleteNote(id) {
    const n = state.notes.find(x => x.id === id);
    if (!n) return;
    const snap = { ...n };
    state.notes = state.notes.filter(x => x.id !== id);
    state.selectedId = null;
    state.justCreated.delete(id);
    history.replaceState(null, '', location.pathname);
    renderSidebar();
    renderDetail();
    document.getElementById('nzApp').classList.remove('show-detail');
    showUndoToast(`„${n.title || 'Notiz'}“ gelöscht`, async () => {
        try {
            const created = await NOTES_API.create({
                title: snap.title, content: snap.content, color: snap.color, pinned: snap.pinned,
            });
            state.notes.unshift(created);
            await selectNote(created.id);
        } catch (e) { showToast('Wiederherstellen fehlgeschlagen: ' + e.message, true); }
    });
    try {
        await NOTES_API.remove(id);
        haptic('tap');
    } catch (e) {
        state.notes.unshift(snap);
        renderSidebar();
        showToast('Löschen fehlgeschlagen: ' + e.message, true);
    }
}

// Leere, per „＋“ angelegte Notizen beim Verlassen automatisch entfernen (kein Müll).
async function cleanupEmptyJustCreated() {
    const ids = [...state.justCreated];
    state.justCreated.clear();
    for (const id of ids) {
        const n = state.notes.find(x => x.id === id);
        if (n && !(n.title || '').trim() && !(n.content || '').trim()) {
            try { await NOTES_API.remove(id); } catch (e) {}
            state.notes = state.notes.filter(x => x.id !== id);
        }
    }
    if (ids.length) renderSidebar();
}

// ---------- Live-Vorschau mit dynamischem Abhaken ----------
function renderDetailPreview() {
    const n = state.notes.find(x => x.id === state.selectedId);
    const pv = document.getElementById('nzDPreview');
    const hint = document.getElementById('nzDPreviewHint');
    const ta = document.getElementById('nzDContent');
    const text = ta.value;
    pv.innerHTML = text.trim() ? renderMarkdown(text) : '';
    pv.querySelectorAll('.nz-task input[type="checkbox"]').forEach((cb, idx) => {
        cb.addEventListener('click', (e) => e.stopPropagation());
        cb.addEventListener('change', () => toggleDetailTask(idx, cb.checked));
    });
    const hasTasks = pv.querySelector('.nz-task');
    hint.textContent = hasTasks
        ? 'Tipp: Aufgaben direkt in der Vorschau abhaken — wird automatisch gespeichert.'
        : (text.trim() ? 'Tipp: - [ ] für anklickbare Aufgaben, **fett**, *kursiv*, `code`' : '');
}

function toggleDetailTask(idx, checked) {
    const ta = document.getElementById('nzDContent');
    const lines = ta.value.split('\n');
    let count = -1;
    for (let i = 0; i < lines.length; i++) {
        const m = lines[i].match(/^(\s*[-*]\s*)\[( |x)\](\s.*)?$/i);
        if (m) {
            count++;
            if (count === idx) {
                lines[i] = m[1] + (checked ? '[x]' : '[ ]') + (m[3] || '');
                break;
            }
        }
    }
    ta.value = lines.join('\n');
    const n = state.notes.find(x => x.id === state.selectedId);
    if (n) n.content = ta.value;
    renderDetailPreview();
    renderSidebarItemPreview(n);
    scheduleSave();
}

// Sidebar-Einzelteile live aktualisieren, ohne komplette Liste neu zu bauen.
function renderSidebarItemTitle(n) {
    if (!n) return;
    const el = document.querySelector(`.nz-item[data-id="${n.id}"] .nz-item-title`);
    if (el) el.textContent = n.title || '';
}
function renderSidebarItemPreview(n) {
    if (!n) return;
    const el = document.querySelector(`.nz-item[data-id="${n.id}"] .nz-item-preview`);
    if (el) el.textContent = firstLine(n.content);
}

function autoSizeContent() {
    const ta = document.getElementById('nzDContent');
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.max(200, ta.scrollHeight) + 'px';
}

// ---------- Hash-Deep-Link ----------
function onHashChange() {
    const m = location.hash.match(/^#note-(\d+)$/);
    const id = m ? Number(m[1]) : null;
    if (id === state.selectedId) return;
    if (id && state.notes.some(n => n.id === id)) {
        selectNote(id);
    } else if (!id) {
        state.selectedId = null;
        renderSidebar();
        renderDetail();
    }
}

// ---------- Markdown-Lite (sicher per Escape) ----------
function escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function renderMarkdown(text) {
    const lines = escapeHtml(text).split('\n');
    let html = '';
    let inUl = false, inOl = false, taskIdx = -1;
    const closeLists = () => { if (inUl) { html += '</ul>'; inUl = false; } if (inOl) { html += '</ol>'; inOl = false; } };
    for (const line of lines) {
        // Task-Liste: - [ ] / - [x]
        const taskMatch = line.match(/^(\s*[-*]\s*)\[( |x)\](\s.*)?$/i);
        if (taskMatch) {
            closeLists();
            taskIdx++;
            const checked = taskMatch[2].toLowerCase() === 'x';
            const txt = inlineMd((taskMatch[3] || '').trim());
            html += `<div class="nz-task${checked ? ' done' : ''}"><input type="checkbox" ${checked ? 'checked' : ''}><span class="nz-task-txt">${txt}</span></div>`;
            continue;
        }
        const hm = line.match(/^(#{1,3})\s+(.*)$/);
        if (hm) { closeLists(); html += `<h${hm[1].length}>${inlineMd(hm[2])}</h${hm[1].length}>`; continue; }
        const um = line.match(/^(\s*[-*]\s+)(.*)$/);
        if (um) {
            if (inOl) { html += '</ol>'; inOl = false; }
            if (!inUl) { html += '<ul>'; inUl = true; }
            html += `<li>${inlineMd(um[2])}</li>`;
            continue;
        }
        const om = line.match(/^(\s*\d+\.\s+)(.*)$/);
        if (om) {
            if (inUl) { html += '</ul>'; inUl = false; }
            if (!inOl) { html += '<ol>'; inOl = true; }
            html += `<li>${inlineMd(om[2])}</li>`;
            continue;
        }
        closeLists();
        if (line.trim() === '') { html += '<br>'; continue; }
        html += `<p>${inlineMd(line)}</p>`;
    }
    closeLists();
    return html;
}
function inlineMd(s) {
    s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    return s;
}

// ---------- Zeit-Formatierung ----------
function relTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const diff = (new Date() - d) / 1000;
    if (diff < 60) return 'gerade eben';
    if (diff < 3600) return `vor ${Math.floor(diff / 60)} min`;
    if (diff < 86400) return `vor ${Math.floor(diff / 3600)} Std`;
    if (diff < 604800) return `vor ${Math.floor(diff / 86400)} Tagen`;
    return d.toLocaleDateString('de-DE', { day: '2-digit', month: 'short', year: 'numeric' });
}

// ---------- Toast ----------
let toastEl = null, toastTimer = null;
function showToast(msg, isError, ms) {
    if (toastEl) { toastEl.remove(); clearTimeout(toastTimer); }
    toastEl = document.createElement('div');
    toastEl.className = 'nz-toast';
    toastEl.innerHTML = `<span>${escapeHtml(msg)}</span>`;
    document.body.appendChild(toastEl);
    requestAnimationFrame(() => toastEl.classList.add('show'));
    toastTimer = setTimeout(() => {
        toastEl.classList.remove('show');
        setTimeout(() => { if (toastEl) { toastEl.remove(); toastEl = null; } }, 250);
    }, ms || 2500);
    haptic(isError ? 'error' : 'tap');
}
function showUndoToast(msg, onUndo, ms) {
    if (toastEl) { toastEl.remove(); clearTimeout(toastTimer); }
    toastEl = document.createElement('div');
    toastEl.className = 'nz-toast';
    toastEl.innerHTML = `<span>${escapeHtml(msg)}</span><button class="nz-undo-btn" type="button">↺ Rückgängig</button>`;
    document.body.appendChild(toastEl);
    let done = false;
    const cleanup = () => { toastEl.classList.remove('show'); setTimeout(() => { if (toastEl) { toastEl.remove(); toastEl = null; } }, 250); };
    toastEl.querySelector('.nz-undo-btn').onclick = async () => {
        if (done) return; done = true; cleanup();
        try { await onUndo(); showToast('Rückgängig gemacht'); }
        catch (e) { showToast('Rückgängig fehlgeschlagen: ' + e.message, true); }
    };
    requestAnimationFrame(() => toastEl.classList.add('show'));
    toastTimer = setTimeout(() => { if (!done) cleanup(); }, ms || 5000);
    haptic('tap');
}

boot();
