/* Notizen — v1.18.0 WYSIWYG Rewrite
 * Speicherformat: HTML (format='html' via NoteBody).
 * Editor: contenteditable mit robusten Enter/Task-Handlern.
 * Task-Items: eigene <div class="nz-task" data-done="…"> Blöcke mit
 * klickbaren Box-Spans (KEIN <input>). Damit sind Cursor- und
 * Fokus-Probleme aus v1.14-v1.16 komplett vermieden.
 * Alte Markdown-Notizen (v1.17) werden beim Öffnen client-side gerendert
 * und beim nächsten Save als HTML zurückgeschrieben.
 */

const NOTES_API = {
    list:   (archived) => apiCall('/api/notes' + (archived ? '?archived=true' : '')),
    get:    (id) => apiCall(`/api/notes/${id}`),
    create: (b) => apiCall('/api/notes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }),
    update: (id, b) => apiCall(`/api/notes/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }),
    remove: (id) => apiCall(`/api/notes/${id}`, { method: 'DELETE' }),
};

const COLORS = [
    { key: 'default', hex: '#9ca3af', label: 'Standard' },
    { key: 'red',     hex: '#ef4444', label: 'Rot' },
    { key: 'orange',  hex: '#f59e0b', label: 'Orange' },
    { key: 'yellow',  hex: '#eab308', label: 'Gelb' },
    { key: 'green',   hex: '#22c55e', label: 'Grün' },
    { key: 'blue',    hex: '#3b82f6', label: 'Blau' },
    { key: 'purple',  hex: '#8b5cf6', label: 'Lila' },
    { key: 'pink',    hex: '#ec4899', label: 'Pink' },
];

const state = {
    notes: [],
    selectedId: null,
    query: '',
    sortMode: 'updated',
    showArchived: false,
    saveTimer: null,
    saveToken: 0,
    status: 'idle',
    statusTimer: null,
    justCreated: new Set(),
};

// ==========================================================
// Boot
// ==========================================================
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
    const m = location.hash.match(/^#note-(\d+)$/);
    if (m && state.notes.some(n => n.id === Number(m[1]))) selectNote(Number(m[1]));
    window.addEventListener('hashchange', onHashChange);
    window.addEventListener('beforeunload', () => { flushSave(); });
}

function bindUI() {
    document.getElementById('nzNew').onclick = newNote;
    document.getElementById('nzDeCta').onclick = newNote;
    document.getElementById('nzSearch').addEventListener('input', (e) => {
        state.query = e.target.value.trim().toLowerCase();
        renderSidebar();
    });
    document.getElementById('nzSort').addEventListener('change', (e) => {
        state.sortMode = e.target.value;
        renderSidebar();
    });
    document.querySelectorAll('.nz-side-tab').forEach(btn => {
        btn.addEventListener('click', async () => {
            const scope = btn.dataset.scope;
            const wantArchived = scope === 'archived';
            if (wantArchived === state.showArchived) return;
            await flushSave();
            await cleanupEmptyJustCreated();
            state.showArchived = wantArchived;
            document.querySelectorAll('.nz-side-tab').forEach(b => b.classList.toggle('active', b === btn));
            state.selectedId = null;
            history.replaceState(null, '', location.pathname);
            await loadNotes();
        });
    });
    document.getElementById('nzBack').onclick = backToList;
    document.getElementById('nzDTitle').addEventListener('input', onTitleInput);

    const editor = document.getElementById('nzDEditor');
    editor.addEventListener('input', onContentInput);
    editor.addEventListener('keydown', onEditorKeydown);
    editor.addEventListener('beforeinput', onEditorBeforeInput);
    editor.addEventListener('click', onEditorClick);
    editor.addEventListener('paste', onEditorPaste);

    document.querySelectorAll('.nz-tb').forEach(btn => {
        btn.addEventListener('mousedown', (e) => e.preventDefault());
        btn.addEventListener('click', (e) => { e.preventDefault(); applyToolbarCmd(btn.dataset.cmd); });
    });
    document.getElementById('nzDPin').onclick = () => togglePin(state.selectedId);
    document.getElementById('nzDArchive').onclick = () => toggleArchive(state.selectedId);
    document.getElementById('nzDDelete').onclick = () => deleteNote(state.selectedId);

    const cwrap = document.getElementById('nzDColor');
    COLORS.forEach(c => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'nz-d-swatch';
        b.style.background = c.hex;
        b.dataset.color = c.key;
        b.title = c.label;
        b.onclick = () => setColor(c.key);
        cwrap.appendChild(b);
    });

    document.addEventListener('keydown', onGlobalKeydown);
}

// ==========================================================
// Loading / Sidebar
// ==========================================================
async function loadNotes() {
    try {
        state.notes = await NOTES_API.list(state.showArchived);
    } catch (e) {
        showToast('Laden fehlgeschlagen: ' + e.message, true);
        state.notes = [];
    }
    state.notes.forEach(n => {
        if (n.format === 'markdown' && n.content) {
            n.content = markdownToHtml(n.content);
            n._needsFormatSave = true;
        }
    });
    renderSidebar();
    renderDetail();
}

function renderSidebar() {
    const list = document.getElementById('nzList');
    const q = state.query;
    let notes = state.notes.slice();
    if (q) {
        notes = notes.filter(n => {
            const hay = ((n.title || '') + ' ' + textFromHtml(n.content || '')).toLowerCase();
            return hay.includes(q);
        });
    }
    const sortFn = {
        updated: (a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''),
        created: (a, b) => (b.created_at || '').localeCompare(a.created_at || ''),
        title:   (a, b) => (a.title || '').localeCompare(b.title || '', 'de', { sensitivity: 'base' }),
    }[state.sortMode] || (() => 0);
    notes.sort(sortFn);

    if (!notes.length) {
        const msg = state.query
            ? 'Keine Treffer für <strong>' + escapeHtml(state.query) + '</strong>.'
            : state.showArchived ? 'Kein archiviertes Element.' : 'Noch keine Notizen. Leg oben eine an.';
        list.innerHTML = `<div class="nz-list-empty">${msg}</div>`;
        return;
    }

    const pinned = notes.filter(n => n.pinned && !state.showArchived);
    const rest = notes.filter(n => !n.pinned || state.showArchived);
    let html = '';
    if (pinned.length) {
        html += '<div class="nz-section">📌 Angepinnt</div>';
        html += pinned.map(renderNoteItem).join('');
    }
    if (rest.length) {
        if (pinned.length) html += `<div class="nz-section">${state.showArchived ? 'Archiv' : 'Alle Notizen'}</div>`;
        html += rest.map(renderNoteItem).join('');
    }
    list.innerHTML = html;
    list.querySelectorAll('.nz-item').forEach(el => {
        el.addEventListener('click', () => selectNote(Number(el.dataset.id)));
    });
}

function renderNoteItem(n) {
    const active = state.selectedId === n.id ? ' active' : '';
    const color = 'nz-color-' + (n.color || 'default');
    const title = escapeHtml(n.title || '');
    const preview = escapeHtml(previewText(n.content || ''));
    const pin = n.pinned ? '<span class="nz-item-pin">📌</span>' : '';
    const badges = n.archived ? '<span class="nz-item-badge">Archiv</span>' : '';
    return `<div class="nz-item ${color}${active}" data-id="${n.id}">
        <div class="nz-item-main">
            <div class="nz-item-title">${title || '<span style="color:var(--text-faint)">(Ohne Titel)</span>'}</div>
            <div class="nz-item-preview">${preview || '<span style="color:var(--text-faint)">Leer</span>'}</div>
            <div class="nz-item-meta"><span>${relTime(n.updated_at)}</span>${badges}</div>
        </div>${pin}</div>`;
}

function textFromHtml(html) {
    if (!html) return '';
    const d = document.createElement('div');
    d.innerHTML = html;
    return (d.textContent || '').replace(/\s+/g, ' ').trim();
}
function previewText(html) { return textFromHtml(html).slice(0, 120); }


// ==========================================================
// Detail / Editor-Setup
// ==========================================================
function renderDetail() {
    const empty = document.getElementById('nzDetailEmpty');
    const edit = document.getElementById('nzDetailEdit');
    const n = state.notes.find(x => x.id === state.selectedId);
    if (!n) {
        empty.style.display = '';
        edit.style.display = 'none';
        document.getElementById('nzApp').classList.remove('nz-mobile-detail');
        return;
    }
    empty.style.display = 'none';
    edit.style.display = 'flex';
    document.getElementById('nzApp').classList.add('nz-mobile-detail');
    document.getElementById('nzDTitle').value = n.title || '';
    const editor = document.getElementById('nzDEditor');
    editor.innerHTML = n.content || '';
    normalizeTasks(editor);
    document.getElementById('nzDPin').classList.toggle('active-pin', !!n.pinned);
    document.getElementById('nzDPin').textContent = n.pinned ? '📌 Angepinnt' : '📍 Pin';
    document.getElementById('nzDArchive').textContent = n.archived ? '📤 Wiederherstellen' : '🗄️ Archiv';
    document.querySelectorAll('.nz-d-swatch').forEach(s => {
        s.classList.toggle('active', s.dataset.color === (n.color || 'default'));
    });
    setStatus('idle');
}

async function selectNote(id) {
    if (id === state.selectedId) return;
    await flushSave();
    await cleanupEmptyJustCreated(id);
    state.selectedId = id;
    if (id) location.hash = 'note-' + id;
    else history.replaceState(null, '', location.pathname);
    renderSidebar();
    renderDetail();
    const n = state.notes.find(x => x.id === id);
    if (n && n._needsFormatSave) {
        n._needsFormatSave = false;
        scheduleSave();
    }
}

function backToList() {
    state.selectedId = null;
    history.replaceState(null, '', location.pathname);
    document.getElementById('nzApp').classList.remove('nz-mobile-detail');
    renderSidebar();
    renderDetail();
}

// ==========================================================
// Neue Notiz / Löschen / Archiv / Pin / Farbe
// ==========================================================
async function newNote() {
    await flushSave();
    try {
        const n = await NOTES_API.create({ title: '', content: '', color: 'default', pinned: false, format: 'html' });
        state.notes.unshift(n);
        state.justCreated.add(n.id);
        state.selectedId = n.id;
        location.hash = 'note-' + n.id;
        renderSidebar();
        renderDetail();
        setTimeout(() => document.getElementById('nzDTitle').focus(), 30);
    } catch (e) { showToast('Anlegen fehlgeschlagen: ' + e.message, true); }
}

async function cleanupEmptyJustCreated(exceptId) {
    for (const id of Array.from(state.justCreated)) {
        if (id === exceptId) continue;
        const n = state.notes.find(x => x.id === id);
        if (!n) { state.justCreated.delete(id); continue; }
        const empty = !((n.title || '').trim()) && !textFromHtml(n.content || '').trim();
        if (empty) {
            try { await NOTES_API.remove(id); } catch (e) {}
            state.notes = state.notes.filter(x => x.id !== id);
        }
        state.justCreated.delete(id);
    }
}

async function togglePin(id) {
    const n = state.notes.find(x => x.id === id);
    if (!n) return;
    const want = !n.pinned;
    try {
        await NOTES_API.update(id, { pinned: want });
        n.pinned = want;
        renderSidebar();
        renderDetail();
        showToast(want ? 'Angepinnt' : 'Pin entfernt');
    } catch (e) { showToast('Fehler: ' + e.message, true); }
}

async function toggleArchive(id) {
    const n = state.notes.find(x => x.id === id);
    if (!n) return;
    const wantArchive = !n.archived;
    try {
        await NOTES_API.update(id, { archived: wantArchive });
        state.notes = state.notes.filter(x => x.id !== id);
        state.selectedId = null;
        history.replaceState(null, '', location.pathname);
        renderSidebar();
        renderDetail();
        showUndoToast(wantArchive ? 'Archiviert' : 'Wiederhergestellt', async () => {
            await NOTES_API.update(id, { archived: !wantArchive });
            await loadNotes();
        });
    } catch (e) { showToast('Fehler: ' + e.message, true); }
}

async function deleteNote(id) {
    const n = state.notes.find(x => x.id === id);
    if (!n) return;
    const snapshot = { ...n };
    if (!confirm('Notiz "' + (n.title || '(ohne Titel)') + '" wirklich löschen?')) return;
    try {
        await NOTES_API.remove(id);
        state.notes = state.notes.filter(x => x.id !== id);
        state.selectedId = null;
        state.justCreated.delete(id);
        history.replaceState(null, '', location.pathname);
        renderSidebar();
        renderDetail();
        showUndoToast('Notiz gelöscht', async () => {
            const restored = await NOTES_API.create({
                title: snapshot.title || '', content: snapshot.content || '',
                color: snapshot.color || 'default', pinned: !!snapshot.pinned, format: 'html',
            });
            state.notes.unshift(restored);
            state.selectedId = restored.id;
            location.hash = 'note-' + restored.id;
            renderSidebar();
            renderDetail();
        });
    } catch (e) { showToast('Löschen fehlgeschlagen: ' + e.message, true); }
}

async function setColor(color) {
    const n = state.notes.find(x => x.id === state.selectedId);
    if (!n) return;
    n.color = color;
    document.querySelectorAll('.nz-d-swatch').forEach(s => s.classList.toggle('active', s.dataset.color === color));
    const item = document.querySelector(`.nz-item[data-id="${n.id}"]`);
    if (item) item.className = item.className.replace(/\bnz-color-\w+\b/g, '') + ' nz-color-' + color;
    try { await NOTES_API.update(n.id, { color }); }
    catch (e) { showToast('Farbe speichern fehlgeschlagen: ' + e.message, true); }
}


// ==========================================================
// Auto-Save
// ==========================================================
function onTitleInput() {
    const n = state.notes.find(x => x.id === state.selectedId);
    if (!n) return;
    n.title = document.getElementById('nzDTitle').value;
    const item = document.querySelector(`.nz-item[data-id="${n.id}"] .nz-item-title`);
    if (item) item.textContent = n.title || '';
    scheduleSave();
}

function onContentInput() {
    const n = state.notes.find(x => x.id === state.selectedId);
    if (!n) return;
    const editor = document.getElementById('nzDEditor');
    n.content = editor.innerHTML;
    const item = document.querySelector(`.nz-item[data-id="${n.id}"] .nz-item-preview`);
    if (item) item.textContent = previewText(n.content) || 'Leer';
    scheduleSave();
}

function scheduleSave() {
    setStatus('saving');
    clearTimeout(state.saveTimer);
    state.saveTimer = setTimeout(() => { flushSave(); }, 700);
}

async function flushSave() {
    clearTimeout(state.saveTimer);
    state.saveTimer = null;
    const id = state.selectedId;
    if (!id) return;
    const n = state.notes.find(x => x.id === id);
    if (!n) return;
    const token = ++state.saveToken;
    try {
        await NOTES_API.update(id, {
            title: n.title || '',
            content: n.content || '',
            format: 'html',
        });
        if (token === state.saveToken) {
            n.updated_at = new Date().toISOString();
            setStatus('saved');
            clearTimeout(state.statusTimer);
            state.statusTimer = setTimeout(() => setStatus('idle'), 1500);
            if (state.justCreated.has(id) && (n.title.trim() || textFromHtml(n.content).trim())) {
                state.justCreated.delete(id);
            }
        }
    } catch (e) {
        if (token === state.saveToken) {
            setStatus('idle');
            showToast('Speichern fehlgeschlagen: ' + e.message, true);
        }
    }
}

function setStatus(s) {
    state.status = s;
    const el = document.getElementById('nzDStatus');
    if (!el) return;
    el.className = 'nz-d-status ' + s;
    const txt = { idle: '', saving: 'Speichere…', saved: 'Gespeichert ✓' }[s] || '';
    el.querySelector('.txt').textContent = txt;
}


// ==========================================================
// Task-Toggle & Editor-Events
// ==========================================================
function onEditorClick(e) {
    const box = e.target.closest('.nz-task-box');
    if (box) {
        e.preventDefault();
        const task = box.closest('.nz-task');
        if (!task) return;
        const isDone = task.dataset.done === 'true';
        task.dataset.done = isDone ? 'false' : 'true';
        if (typeof haptic === 'function') haptic('tap');
        onContentInput();
    }
}

function normalizeTasks(root) {
    // Alle .nz-task-Blöcke normalisieren: data-done sicherstellen, Struktur reparieren
    root.querySelectorAll('.nz-task').forEach(t => {
        if (t.dataset.done !== 'true') t.dataset.done = 'false';
        let box = t.querySelector('.nz-task-box');
        if (!box) {
            box = document.createElement('span');
            box.className = 'nz-task-box';
            box.contentEditable = 'false';
            t.prepend(box);
        } else {
            box.contentEditable = 'false';
        }
        let txt = t.querySelector('.nz-task-txt');
        if (!txt) {
            txt = document.createElement('span');
            txt.className = 'nz-task-txt';
            const kids = Array.from(t.childNodes).filter(c => c !== box);
            kids.forEach(k => txt.appendChild(k));
            t.appendChild(txt);
        }
    });
}

function newTaskBlock(text) {
    const div = document.createElement('div');
    div.className = 'nz-task';
    div.dataset.done = 'false';
    const box = document.createElement('span');
    box.className = 'nz-task-box';
    box.contentEditable = 'false';
    const txt = document.createElement('span');
    txt.className = 'nz-task-txt';
    txt.textContent = text || '';
    div.appendChild(box);
    div.appendChild(txt);
    return div;
}

// Enter in Task-Block sauber abfangen (Apple-Notes-Verhalten)
function onEditorBeforeInput(e) {
    if (e.inputType !== 'insertParagraph' && e.inputType !== 'insertLineBreak') return;
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return;
    const range = sel.getRangeAt(0);
    let node = range.startContainer;
    const editor = document.getElementById('nzDEditor');
    const task = node.nodeType === 1 ? node.closest('.nz-task') : (node.parentNode && node.parentNode.closest('.nz-task'));
    if (task && editor.contains(task)) {
        e.preventDefault();
        const txtEl = task.querySelector('.nz-task-txt');
        const txt = (txtEl?.textContent || '').trim();
        if (!txt) {
            const p = document.createElement('p');
            p.appendChild(document.createElement('br'));
            task.replaceWith(p);
            placeCaretInside(p);
        } else {
            const nt = newTaskBlock('');
            task.after(nt);
            placeCaretInside(nt.querySelector('.nz-task-txt'));
        }
        onContentInput();
    }
}

function placeCaretInside(el) {
    const r = document.createRange();
    r.selectNodeContents(el);
    r.collapse(true);
    const s = window.getSelection();
    s.removeAllRanges();
    s.addRange(r);
    if (el.focus) el.focus();
}


// ==========================================================
// Toolbar-Kommandos
// ==========================================================
function applyToolbarCmd(cmd) {
    const editor = document.getElementById('nzDEditor');
    editor.focus();
    switch (cmd) {
        case 'bold':      document.execCommand('bold'); break;
        case 'italic':    document.execCommand('italic'); break;
        case 'underline': document.execCommand('underline'); break;
        case 'strike':    document.execCommand('strikeThrough'); break;
        case 'code':      wrapInlineTag('CODE'); break;
        case 'h1':        applyBlockFormat('H1'); break;
        case 'h2':        applyBlockFormat('H2'); break;
        case 'h3':        applyBlockFormat('H3'); break;
        case 'ul':        document.execCommand('insertUnorderedList'); break;
        case 'ol':        document.execCommand('insertOrderedList'); break;
        case 'quote':     applyBlockFormat('BLOCKQUOTE'); break;
        case 'hr':        document.execCommand('insertHorizontalRule'); break;
        case 'task':      insertTaskAtCursor(); break;
        case 'link': {
            const url = prompt('Link-URL:', 'https://');
            if (url) document.execCommand('createLink', false, url);
            break;
        }
    }
    onContentInput();
}

function applyBlockFormat(tag) {
    document.execCommand('formatBlock', false, tag);
}

function wrapInlineTag(tag) {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return;
    const range = sel.getRangeAt(0);
    if (range.collapsed) {
        const el = document.createElement(tag);
        el.textContent = '\u200B';
        range.insertNode(el);
        placeCaretInside(el);
        return;
    }
    const el = document.createElement(tag);
    el.appendChild(range.extractContents());
    range.insertNode(el);
    sel.removeAllRanges();
}

function insertTaskAtCursor() {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return;
    const range = sel.getRangeAt(0);
    const editor = document.getElementById('nzDEditor');
    const currentBlock = closestBlock(range.startContainer, editor);
    if (currentBlock && currentBlock !== editor && currentBlock.textContent.trim()) {
        const t = newTaskBlock(currentBlock.textContent);
        currentBlock.replaceWith(t);
        placeCaretInside(t.querySelector('.nz-task-txt'));
    } else {
        const t = newTaskBlock('');
        if (currentBlock && currentBlock !== editor) currentBlock.replaceWith(t);
        else range.insertNode(t);
        placeCaretInside(t.querySelector('.nz-task-txt'));
    }
}

function closestBlock(node, boundary) {
    while (node && node !== boundary) {
        if (node.nodeType === 1) {
            const d = getComputedStyle(node).display;
            if (['block','list-item','flex'].includes(d)) return node;
        }
        node = node.parentNode;
    }
    return null;
}


// ==========================================================
// Keyboard-Shortcuts + Markdown-Live-Umwandlung
// ==========================================================
function onEditorKeydown(e) {
    if (e.key === ' ') {
        maybeApplyMarkdownShortcut(e);
    }
    if (!(e.metaKey || e.ctrlKey)) return;
    const k = e.key.toLowerCase();
    if (k === 'b') { e.preventDefault(); applyToolbarCmd('bold'); }
    else if (k === 'i') { e.preventDefault(); applyToolbarCmd('italic'); }
    else if (k === 'u') { e.preventDefault(); applyToolbarCmd('underline'); }
    else if (k === 'k') { e.preventDefault(); applyToolbarCmd('link'); }
    else if (e.shiftKey && (k === '7' || k === '&')) { e.preventDefault(); applyToolbarCmd('task'); }
    else if (e.shiftKey && (k === '8' || k === '(')) { e.preventDefault(); applyToolbarCmd('ul'); }
    else if (e.shiftKey && (k === '9' || k === ')')) { e.preventDefault(); applyToolbarCmd('ol'); }
}

function maybeApplyMarkdownShortcut(e) {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return;
    const range = sel.getRangeAt(0);
    if (!range.collapsed) return;
    const editor = document.getElementById('nzDEditor');
    const block = closestBlock(range.startContainer, editor);
    if (!block || block === editor) return;
    if (block.classList && block.classList.contains('nz-task')) return;
    const txt = block.textContent || '';
    const rules = [
        { re: /^# $/,        action: () => applyBlockFormat('H1') },
        { re: /^## $/,       action: () => applyBlockFormat('H2') },
        { re: /^### $/,      action: () => applyBlockFormat('H3') },
        { re: /^- \[ ?\] $/, action: () => convertBlockToTask(block, false) },
        { re: /^- \[x\] $/i, action: () => convertBlockToTask(block, true) },
        { re: /^- $/,        action: () => document.execCommand('insertUnorderedList') },
        { re: /^\* $/,       action: () => document.execCommand('insertUnorderedList') },
        { re: /^1\. $/,      action: () => document.execCommand('insertOrderedList') },
        { re: /^> $/,        action: () => applyBlockFormat('BLOCKQUOTE') },
    ];
    for (const r of rules) {
        if (r.re.test(txt)) {
            e.preventDefault();
            block.textContent = '';
            r.action();
            onContentInput();
            return;
        }
    }
}

function convertBlockToTask(block, done) {
    const t = newTaskBlock('');
    if (done) t.dataset.done = 'true';
    block.replaceWith(t);
    placeCaretInside(t.querySelector('.nz-task-txt'));
}

function onEditorPaste(e) {
    e.preventDefault();
    const text = (e.clipboardData || window.clipboardData).getData('text/plain');
    if (!text) return;
    document.execCommand('insertText', false, text);
}

function onGlobalKeydown(e) {
    const isMod = e.metaKey || e.ctrlKey;
    if (!isMod) return;
    const k = e.key.toLowerCase();
    if (k === 'n' && !e.shiftKey) {
        const tag = (document.activeElement?.tagName || '').toLowerCase();
        if (tag !== 'input' && tag !== 'textarea' && !document.activeElement?.isContentEditable) {
            e.preventDefault();
            newNote();
        }
    }
}

// ==========================================================
// Hash-Deep-Link
// ==========================================================
function onHashChange() {
    const m = location.hash.match(/^#note-(\d+)$/);
    const id = m ? Number(m[1]) : null;
    if (id === state.selectedId) return;
    if (id && state.notes.some(n => n.id === id)) selectNote(id);
    else if (!id) { state.selectedId = null; renderSidebar(); renderDetail(); }
}


// ==========================================================
// Markdown → HTML (nur für Migration alter v1.17-Notizen)
// ==========================================================
function markdownToHtml(md) {
    if (!md) return '';
    // Fenced code blocks
    const codes = [];
    md = md.replace(/```([a-z0-9]*)\n([\s\S]*?)```/gi, (_, lang, code) => {
        codes.push(`<pre><code>${escapeHtml(code)}</code></pre>`);
        return `\u0000C${codes.length - 1}\u0000`;
    });
    const lines = md.split('\n');
    const out = [];
    let i = 0;
    while (i < lines.length) {
        const line = lines[i];
        if (/^\s*$/.test(line)) { i++; continue; }
        const h = line.match(/^(#{1,3})\s+(.*)$/);
        if (h) { out.push(`<h${h[1].length}>${mdInline(h[2])}</h${h[1].length}>`); i++; continue; }
        if (/^(?:---|\*\*\*|___)\s*$/.test(line)) { out.push('<hr>'); i++; continue; }
        if (/^>\s?/.test(line)) {
            const buf = [];
            while (i < lines.length && /^>\s?/.test(lines[i])) {
                buf.push(lines[i].replace(/^>\s?/, ''));
                i++;
            }
            out.push('<blockquote>' + mdInline(buf.join('<br>')) + '</blockquote>');
            continue;
        }
        // Task-Zeilen
        if (/^\s*[-*+]\s*\[[ xX]\]\s*/.test(line)) {
            while (i < lines.length && /^\s*[-*+]\s*\[[ xX]\]\s*/.test(lines[i])) {
                const m = lines[i].match(/^\s*[-*+]\s*\[([ xX])\]\s*(.*)$/);
                const done = m[1].toLowerCase() === 'x';
                out.push(`<div class="nz-task" data-done="${done}"><span class="nz-task-box" contenteditable="false"></span><span class="nz-task-txt">${mdInline(m[2])}</span></div>`);
                i++;
            }
            continue;
        }
        if (/^\s*(?:[-*+]|\d+\.)\s+/.test(line)) {
            const isOrdered = /^\s*\d+\.\s+/.test(line);
            const items = [];
            while (i < lines.length && /^\s*(?:[-*+]|\d+\.)\s+/.test(lines[i]) && !/^\s*[-*+]\s*\[[ xX]\]\s*/.test(lines[i])) {
                const m = lines[i].match(/^\s*(?:[-*+]|\d+\.)\s+(.*)$/);
                items.push('<li>' + mdInline(m[1]) + '</li>');
                i++;
            }
            out.push(`<${isOrdered ? 'ol' : 'ul'}>${items.join('')}</${isOrdered ? 'ol' : 'ul'}>`);
            continue;
        }
        // Absatz
        const buf = [line];
        i++;
        while (i < lines.length && !/^\s*$/.test(lines[i])
                && !/^(#{1,3}\s|>|\s*(?:[-*+]|\d+\.)\s|---|\*\*\*|___)/.test(lines[i])) {
            buf.push(lines[i]); i++;
        }
        out.push('<p>' + mdInline(buf.join('<br>')) + '</p>');
    }
    let html = out.join('\n');
    html = html.replace(/\u0000C(\d+)\u0000/g, (_, idx) => codes[+idx] || '');
    return html;
}

function mdInline(s) {
    s = escapeHtml(s);
    const codes = [];
    s = s.replace(/`([^`\n]+)`/g, (_, c) => {
        codes.push(`<code>${c}</code>`);
        return `\u0001C${codes.length - 1}\u0001`;
    });
    s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>');
    s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener">$1</a>');
    s = s.replace(/\u0001C(\d+)\u0001/g, (_, idx) => codes[+idx] || '');
    return s;
}

// ==========================================================
// Helpers
// ==========================================================
function escapeHtml(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

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

// ==========================================================
// Toast
// ==========================================================
let toastEl = null, toastTimer = null;
function showToast(msg, isError, ms) {
    if (toastEl) { toastEl.remove(); clearTimeout(toastTimer); }
    toastEl = document.createElement('div');
    toastEl.className = 'nz-toast';
    toastEl.innerHTML = `<span>${escapeHtml(msg)}</span>`;
    document.body.appendChild(toastEl);
    requestAnimationFrame(() => toastEl.classList.add('show'));
    toastTimer = setTimeout(() => {
        if (!toastEl) return;
        toastEl.classList.remove('show');
        setTimeout(() => { if (toastEl) { toastEl.remove(); toastEl = null; } }, 250);
    }, ms || 2500);
    if (typeof haptic === 'function') haptic(isError ? 'error' : 'tap');
}

function showUndoToast(msg, onUndo, ms) {
    if (toastEl) { toastEl.remove(); clearTimeout(toastTimer); }
    toastEl = document.createElement('div');
    toastEl.className = 'nz-toast';
    toastEl.innerHTML = `<span>${escapeHtml(msg)}</span><button class="nz-undo-btn" type="button">↺ Rückgängig</button>`;
    document.body.appendChild(toastEl);
    let done = false;
    const cleanup = () => {
        toastEl.classList.remove('show');
        setTimeout(() => { if (toastEl) { toastEl.remove(); toastEl = null; } }, 250);
    };
    toastEl.querySelector('.nz-undo-btn').onclick = async () => {
        if (done) return; done = true; cleanup();
        try { await onUndo(); showToast('Rückgängig gemacht'); }
        catch (e) { showToast('Rückgängig fehlgeschlagen: ' + e.message, true); }
    };
    requestAnimationFrame(() => toastEl.classList.add('show'));
    toastTimer = setTimeout(() => { if (!done) cleanup(); }, ms || 5000);
    if (typeof haptic === 'function') haptic('tap');
}

boot();

