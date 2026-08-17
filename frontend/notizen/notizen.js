/* Notizen-Modul — Vexbob */

const NOTES_API = {
    list:   (archived) => apiCall('/api/notes' + (archived ? '?archived=true' : '')),
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

const DRAFT_KEY = 'vexbob_notes_draft';

let state = {
    notes: [],          // alle geladenen Notizen (aktuell aktive oder archivierte je nach Ansicht)
    showArchived: false,
    query: '',
    activeTag: null,
    composerColor: 'default',
    lastDeleted: null,  // für Undo
    saveTimer: null,
};

// ---------- Auth Bootstrap ----------
async function boot() {
    if (!isLoggedIn()) { window.location.href = '/private/login.html'; return; }
    try {
        const me = await fetchMe(true);
        document.getElementById('userLabel').textContent = '👤 ' + me.username;
    } catch (e) { return; }
    document.body.classList.add('ready');
    document.getElementById('logoutBtn').onclick = () => { clearToken(); location.reload(); };
    document.getElementById('themeBtn').onclick = toggleTheme;
    bindUI();
    restoreDraft();
    renderColorPicker();
    await loadNotes();
}

// ---------- UI Bindings ----------
function bindUI() {
    const $ = (id) => document.getElementById(id);
    $('cSave').onclick = saveNote;
    $('cTitle').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); $('cContent').focus(); }
        if (e.key === 'Escape') { e.preventDefault(); resetComposer(); }
    });
    $('cContent').addEventListener('keydown', (e) => {
        if (e.key === 'Escape') { e.preventDefault(); resetComposer(); }
        // Strg/Cmd+Enter = speichern
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); saveNote(); }
    });
    $('cTitle').addEventListener('input', scheduleDraft);
    $('cContent').addEventListener('input', updateComposerMeta);
    $('cContent').addEventListener('input', scheduleDraft);
    $('cTags').addEventListener('input', scheduleDraft);

    $('search').addEventListener('input', (e) => {
        state.query = e.target.value.trim().toLowerCase();
        render();
    });
    $('archiveBtn').onclick = async () => {
        state.showArchived = !state.showArchived;
        $('archiveBtn').classList.toggle('active', state.showArchived);
        $('archiveBtn').textContent = state.showArchived ? '📋 Aktiv' : '🗄️ Archiv';
        await loadNotes();
    };

    // Globale Tastatur: 'n' = neue Notiz fokussieren
    document.addEventListener('keydown', (e) => {
        const tag = (e.target.tagName || '').toLowerCase();
        const typing = tag === 'input' || tag === 'textarea';
        if (typing) return;
        if (e.key === 'n' || e.key === 'N') {
            e.preventDefault();
            $('cTitle').focus();
        }
    });
}

function renderColorPicker() {
    const wrap = document.getElementById('cColors');
    wrap.innerHTML = '';
    COLORS.forEach(c => {
        const b = document.createElement('button');
        b.type = 'button';
        b.title = c.key;
        b.style.background = c.hex;
        b.dataset.color = c.key;
        if (c.key === state.composerColor) b.classList.add('sel');
        b.onclick = () => {
            state.composerColor = c.key;
            wrap.querySelectorAll('button').forEach(x => x.classList.remove('sel'));
            b.classList.add('sel');
            scheduleDraft();
        };
        wrap.appendChild(b);
    });
}

function updateComposerMeta() {
    const txt = document.getElementById('cContent').value;
    const words = txt.trim() ? txt.trim().split(/\s+/).length : 0;
    const chars = txt.length;
    document.getElementById('cMeta').textContent = `${words} Wörter · ${chars} Zeichen`;
}

// ---------- Draft (localStorage) ----------
function scheduleDraft() {
    clearTimeout(state.saveTimer);
    state.saveTimer = setTimeout(persistDraft, 400);
}
function persistDraft() {
    const draft = {
        title: document.getElementById('cTitle').value,
        content: document.getElementById('cContent').value,
        tags: document.getElementById('cTags').value,
        color: state.composerColor,
    };
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(draft)); } catch (e) {}
}
function restoreDraft() {
    try {
        const raw = localStorage.getItem(DRAFT_KEY);
        if (!raw) return;
        const d = JSON.parse(raw);
        if (!d) return;
        document.getElementById('cTitle').value = d.title || '';
        document.getElementById('cContent').value = d.content || '';
        document.getElementById('cTags').value = d.tags || '';
        state.composerColor = d.color || 'default';
        updateComposerMeta();
    } catch (e) {}
}
function clearDraft() {
    try { localStorage.removeItem(DRAFT_KEY); } catch (e) {}
}

function resetComposer() {
    document.getElementById('cTitle').value = '';
    document.getElementById('cContent').value = '';
    document.getElementById('cTags').value = '';
    state.composerColor = 'default';
    renderColorPicker();
    updateComposerMeta();
    clearDraft();
    document.getElementById('cTitle').focus();
}

// ---------- Notizen laden/speichern ----------
async function loadNotes() {
    try {
        state.notes = await NOTES_API.list(state.showArchived);
    } catch (e) {
        showToast('Laden fehlgeschlagen: ' + e.message, true);
        return;
    }
    render();
}

async function saveNote() {
    const title = document.getElementById('cTitle').value.trim();
    const content = document.getElementById('cContent').value.trim();
    const tagsRaw = document.getElementById('cTags').value;
    if (!title && !content) {
        showToast('Titel oder Inhalt darf nicht leer sein', true);
        return;
    }
    const tags = parseTagsInput(tagsRaw);
    const body = { title, content, color: state.composerColor, tags };
    const saveBtn = document.getElementById('cSave');
    saveBtn.disabled = true;
    saveBtn.textContent = '…';
    try {
        const created = await NOTES_API.create(body);
        state.notes.unshift(created);
        resetComposer();
        render();
        haptic('success');
    } catch (e) {
        showToast('Speichern fehlgeschlagen: ' + e.message, true);
    } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Speichern';
    }
}

function parseTagsInput(s) {
    if (!s) return [];
    return s.split(',').map(t => t.trim().replace(/^#/, '')).filter(Boolean);
}

// ---------- Aktionen auf bestehenden Notizen ----------
async function togglePin(id) {
    const n = state.notes.find(x => x.id === id);
    if (!n) return;
    const pinned = !n.pinned;
    try {
        const upd = await NOTES_API.update(id, { pinned });
        Object.assign(n, upd);
        render();
        haptic('tap');
    } catch (e) { showToast('Fehler: ' + e.message, true); }
}

async function toggleArchive(id) {
    const n = state.notes.find(x => x.id === id);
    if (!n) return;
    const archived = !n.archived;
    try {
        const upd = await NOTES_API.update(id, { archived });
        Object.assign(n, upd);
        // Aus aktueller Liste entfernen, wenn Ansicht nicht passt.
        state.notes = state.notes.filter(x => x.id !== id);
        render();
        showToast(archived ? 'Notiz archiviert' : 'Notiz wiederhergestellt');
        haptic('tap');
    } catch (e) { showToast('Fehler: ' + e.message, true); }
}

async function setColor(id, color) {
    const n = state.notes.find(x => x.id === id);
    if (!n) return;
    try {
        const upd = await NOTES_API.update(id, { color });
        Object.assign(n, upd);
        render();
    } catch (e) { showToast('Fehler: ' + e.message, true); }
}

async function deleteNote(id) {
    const n = state.notes.find(x => x.id === id);
    if (!n) return;
    state.lastDeleted = { note: { ...n }, index: state.notes.indexOf(n) };
    state.notes = state.notes.filter(x => x.id !== id);
    render();
    showUndoToast(`„${n.title || 'Notiz'}“ gelöscht`, async () => {
        // Wiederherstellen: neu anlegen, da DELETE nicht rückgängig — Neuanlage mit alten Werten.
        try {
            const created = await NOTES_API.create({
                title: n.title, content: n.content, color: n.color,
                pinned: n.pinned, tags: n.tags || [],
            });
            state.notes.unshift(created);
            render();
        } catch (e) { showToast('Wiederherstellen fehlgeschlagen: ' + e.message, true); }
    });
    try {
        await NOTES_API.remove(id);
        haptic('tap');
    } catch (e) {
        // Löschen fehlgeschlagen → zurück in die Liste legen.
        state.notes.splice(state.lastDeleted.index, 0, state.lastDeleted.note);
        state.lastDeleted = null;
        render();
        showToast('Löschen fehlgeschlagen: ' + e.message, true);
    }
}

async function copyNote(id) {
    const n = state.notes.find(x => x.id === id);
    if (!n) return;
    const text = (n.title ? n.title + '\n\n' : '') + (n.content || '');
    try {
        await navigator.clipboard.writeText(text);
        showToast('In Zwischenablage kopiert');
    } catch (e) { showToast('Kopieren fehlgeschlagen', true); }
}

// Inline-Edit von Titel/Inhalt direkt in der Karte
function startEditCard(id, field) {
    const n = state.notes.find(x => x.id === id);
    if (!n) return;
    const card = document.querySelector(`.nz-card[data-id="${id}"]`);
    const el = card.querySelector(field === 'title' ? '.nz-card-title' : '.nz-card-body');
    el.setAttribute('contenteditable', 'true');
    el.focus();
    // Cursor ans Ende setzen
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);

    let cancelled = false;
    const finish = async () => {
        el.removeEventListener('blur', finish);
        el.removeEventListener('keydown', onKey);
        if (cancelled) { render(); return; }
        let val = el.innerText.replace(/\u00a0/g, ' ');
        if (field === 'content') val = val.replace(/\n$/, '');
        if ((field === 'title' && val === (n.title || '')) ||
            (field === 'content' && val === (n.content || ''))) {
            el.removeAttribute('contenteditable');
            return;
        }
        try {
            const upd = await NOTES_API.update(id, { [field]: val });
            Object.assign(n, upd);
            render();
        } catch (e) { showToast('Speichern fehlgeschlagen: ' + e.message, true); render(); }
    };
    const onKey = (e) => {
        if (e.key === 'Escape') { cancelled = true; el.blur(); }
        if (e.key === 'Enter' && field === 'title') { e.preventDefault(); el.blur(); }
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); el.blur(); }
    };
    el.addEventListener('blur', finish);
    el.addEventListener('keydown', onKey);
}

// Checkbox in Markdown-Task umschalten
async function toggleTask(id, idx, checked) {
    const n = state.notes.find(x => x.id === id);
    if (!n) return;
    const lines = (n.content || '').split('\n');
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
    try {
        const upd = await NOTES_API.update(id, { content: lines.join('\n') });
        Object.assign(n, upd);
        render();
    } catch (e) { showToast('Speichern fehlgeschlagen: ' + e.message, true); }
}

// ---------- Rendering ----------
function filtered() {
    let notes = state.notes;
    if (state.activeTag) {
        notes = notes.filter(n => (n.tags || []).some(t => t.toLowerCase() === state.activeTag));
    }
    if (state.query) {
        notes = notes.filter(n => {
            const hay = ((n.title || '') + ' ' + (n.content || '') + ' ' + (n.tags || []).join(' ')).toLowerCase();
            return hay.includes(state.query);
        });
    }
    return notes;
}

function render() {
    const grid = document.getElementById('grid');
    const empty = document.getElementById('empty');
    const countEl = document.getElementById('count');
    const notes = filtered();
    countEl.textContent = `${notes.length} ${notes.length === 1 ? 'Notiz' : 'Notizen'}` + (state.showArchived ? ' (Archiv)' : '');
    renderTagBar();
    grid.innerHTML = '';
    if (notes.length === 0) {
        empty.style.display = '';
        empty.querySelector('h3').textContent = state.query || state.activeTag
            ? 'Nichts gefunden' : (state.showArchived ? 'Keine archivierten Notizen' : 'Noch keine Notizen');
        return;
    }
    empty.style.display = 'none';
    notes.forEach(n => grid.appendChild(buildCard(n)));
}

function buildCard(n) {
    const card = document.createElement('div');
    card.className = `nz-card nz-color-${n.color || 'default'}` + (n.pinned ? ' nz-pinned' : '');
    card.dataset.id = n.id;
    if (n.pinned) {
        const badge = document.createElement('span');
        badge.className = 'nz-pin-badge';
        badge.textContent = '📌';
        card.appendChild(badge);
    }

    const title = document.createElement('div');
    title.className = 'nz-card-title';
    title.textContent = n.title || '';
    title.onclick = () => startEditCard(n.id, 'title');
    card.appendChild(title);

    if (n.content) {
        const body = document.createElement('div');
        body.className = 'nz-card-body';
        body.innerHTML = renderMarkdown(n.content || '', n.id);
        body.onclick = (e) => {
            // Klick auf Checkbox oder Link nicht als Edit werten
            if (e.target.closest('.nz-task input') || e.target.closest('a')) return;
            startEditCard(n.id, 'content');
        };
        // Checkbox-Listener
        body.querySelectorAll('.nz-task input').forEach((cb, idx) => {
            cb.addEventListener('click', (e) => e.stopPropagation());
            cb.addEventListener('change', () => toggleTask(n.id, idx, cb.checked));
        });
        card.appendChild(body);
    }

    // Foot: Tags + Datum
    const foot = document.createElement('div');
    foot.className = 'nz-card-foot';
    (n.tags || []).forEach(t => {
        const chip = document.createElement('span');
        chip.className = 'nz-tag';
        chip.textContent = '#' + t;
        chip.onclick = () => { state.activeTag = (state.activeTag === t.toLowerCase()) ? null : t.toLowerCase(); render(); };
        foot.appendChild(chip);
    });
    const date = document.createElement('span');
    date.className = 'nz-date';
    date.textContent = relTime(n.updated_at);
    date.title = fmtFull(n.updated_at);
    foot.appendChild(date);
    card.appendChild(foot);

    // Actions
    const actions = document.createElement('div');
    actions.className = 'nz-card-actions';
    actions.appendChild(actionBtn(n.pinned ? '📌' : '📍', 'Pin', () => togglePin(n.id), n.pinned ? 'on' : ''));
    actions.appendChild(actionBtn('🎨', 'Farbe', () => openColorMenu(n)));
    actions.appendChild(actionBtn('📋', 'Kopieren', () => copyNote(n.id)));
    actions.appendChild(actionBtn('🗄️', 'Archiv', () => toggleArchive(n.id)));
    actions.appendChild(actionBtn('🗑️', 'Löschen', () => deleteNote(n.id)));
    card.appendChild(actions);
    return card;
}

function actionBtn(icon, title, onclick, extraClass) {
    const b = document.createElement('button');
    b.type = 'button';
    b.title = title;
    b.textContent = icon;
    if (extraClass) b.classList.add(extraClass);
    b.onclick = (e) => { e.stopPropagation(); onclick(); };
    return b;
}

function openColorMenu(n) {
    // Kleines Popover unter der Karte
    closeColorMenu();
    const card = document.querySelector(`.nz-card[data-id="${n.id}"]`);
    const menu = document.createElement('div');
    menu.className = 'nz-color-menu';
    menu.style.cssText = 'position:absolute;right:0.5rem;top:32px;display:flex;gap:0.3rem;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:0.4rem;box-shadow:var(--shadow-lg);z-index:50';
    COLORS.forEach(c => {
        const b = document.createElement('button');
        b.type = 'button';
        b.title = c.key;
        b.style.cssText = `width:20px;height:20px;border-radius:50%;border:2px solid ${c.key === n.color ? 'var(--text)' : 'transparent'};background:${c.hex};cursor:pointer;padding:0`;
        b.onclick = (e) => { e.stopPropagation(); setColor(n.id, c.key); closeColorMenu(); };
        menu.appendChild(b);
    });
    card.style.position = 'relative';
    card.appendChild(menu);
    setTimeout(() => document.addEventListener('click', closeColorMenu, { once: true }), 0);
}
function closeColorMenu() {
    document.querySelectorAll('.nz-color-menu').forEach(m => m.remove());
}

function renderTagBar() {
    const bar = document.getElementById('tagBar');
    // Alle Tags über sichtbare (ungefilterte) Notizen sammeln
    const counts = {};
    state.notes.forEach(n => (n.tags || []).forEach(t => {
        const k = t.toLowerCase();
        counts[k] = (counts[k] || 0) + 1;
    }));
    const tags = Object.keys(counts).sort((a, b) => counts[b] - counts[a] || a.localeCompare(b));
    bar.innerHTML = '';
    if (tags.length === 0) return;
    tags.forEach(t => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'nz-tag' + (state.activeTag === t ? ' active' : '');
        chip.textContent = `#${t} (${counts[t]})`;
        chip.onclick = () => { state.activeTag = (state.activeTag === t) ? null : t; render(); };
        bar.appendChild(chip);
    });
}

// ---------- Markdown-Lite (sicher per Escape) ----------
function escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderMarkdown(text, noteId) {
    // Zeilenweise, damit Task-Listen & Aufzählungen sauber gerendert werden.
    const lines = escapeHtml(text).split('\n');
    let html = '';
    let inUl = false, inOl = false, taskIdx = -1;
    const closeLists = () => { if (inUl) { html += '</ul>'; inUl = false; } if (inOl) { html += '</ol>'; inOl = false; } };
    for (const line of lines) {
        // Task-Liste: - [ ] / - [x]
        let taskMatch = line.match(/^(\s*[-*]\s*)\[( |x)\](\s.*)?$/i);
        if (taskMatch) {
            closeLists();
            taskIdx++;
            const checked = taskMatch[2].toLowerCase() === 'x';
            const txt = inlineMd((taskMatch[3] || '').trim());
            html += `<div class="nz-task${checked ? ' done' : ''}"><input type="checkbox" ${checked ? 'checked' : ''} data-idx="${taskIdx}"><span class="nz-task-txt">${txt}</span></div>`;
            continue;
        }
        // Überschrifgen # ## ###
        const hm = line.match(/^(#{1,3})\s+(.*)$/);
        if (hm) {
            closeLists();
            const lvl = hm[1].length;
            html += `<h${lvl}>${inlineMd(hm[2])}</h${lvl}>`;
            continue;
        }
        // Unordered list
        const um = line.match(/^(\s*[-*]\s+)(.*)$/);
        if (um) {
            if (inOl) { html += '</ol>'; inOl = false; }
            if (!inUl) { html += '<ul>'; inUl = true; }
            html += `<li>${inlineMd(um[2])}</li>`;
            continue;
        }
        // Ordered list
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
    // Links [text](url) — nur http(s) zulassen
    s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    // Inline-Code `…`
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Fett **…**
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    // Kursiv *…*
    s = s.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    return s;
}

// ---------- Zeit-Formatierung ----------
function relTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const now = new Date();
    const diff = (now - d) / 1000;
    if (diff < 60) return 'gerade eben';
    if (diff < 3600) return `vor ${Math.floor(diff / 60)} min`;
    if (diff < 86400) return `vor ${Math.floor(diff / 3600)} Std`;
    if (diff < 604800) return `vor ${Math.floor(diff / 86400)} Tagen`;
    return d.toLocaleDateString('de-DE', { day: '2-digit', month: 'short', year: 'numeric' });
}
function fmtFull(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' });
}

// ---------- Toast ----------
let toastEl = null, toastTimer = null;
function showToast(msg, isError, ms) {
    if (toastEl) { toastEl.remove(); clearTimeout(toastTimer); }
    toastEl = document.createElement('div');
    toastEl.className = 'nz-toast' + (isError ? '' : '');
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
