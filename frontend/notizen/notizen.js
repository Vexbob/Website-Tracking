/* Notizen — v1.17.0 Rewrite
 * Speicherformat: Markdown (statt v1.16 HTML). Alte HTML-Notizen werden
 * beim ersten Laden client-side zu Markdown migriert und beim naechsten
 * Save mit ``format='markdown'`` zurueckgeschrieben.
 *
 * Editor: <textarea> (statt contenteditable). Live-Preview per klick-
 * barem HTML-Render mit echt funktionierenden Task-Checkboxen —
 * die Klicks schreiben ``- [ ]`` <-> ``- [x]`` im Textarea-Content zurueck.
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
    mode: 'edit',             // 'edit' | 'preview'
    saveTimer: null,
    saveToken: 0,
    status: 'idle',           // idle | saving | saved
    statusTimer: null,
    justCreated: new Set(),   // IDs leerer Notizen, die beim Verlassen geloescht werden
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
    document.querySelectorAll('.nz-mode-btn').forEach(btn => {
        btn.addEventListener('click', () => setMode(btn.dataset.mode));
    });
    document.querySelectorAll('.nz-tb').forEach(btn => {
        btn.addEventListener('click', (e) => { e.preventDefault(); applyMarkdown(btn.dataset.md); });
    });
    document.getElementById('nzDPin').onclick = () => togglePin(state.selectedId);
    document.getElementById('nzDArchive').onclick = () => toggleArchive(state.selectedId);
    document.getElementById('nzDDelete').onclick = () => deleteNote(state.selectedId);

    // Preview: Klicks auf Task-Checkboxen fangen und im Markdown zurueckschreiben
    document.getElementById('nzDPreview').addEventListener('click', onPreviewClick);
    // Preview: Links in neuem Tab
    document.getElementById('nzDPreview').addEventListener('click', (e) => {
        const a = e.target.closest('a[href]');
        if (a) { e.preventDefault(); window.open(a.href, '_blank', 'noopener'); }
    });

    // Farb-Swatches im Footer
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

    // Globale Shortcuts
    document.addEventListener('keydown', onGlobalKeydown);
}

// ==========================================================
// Loading
// ==========================================================
async function loadNotes() {
    try {
        state.notes = await NOTES_API.list(state.showArchived);
    } catch (e) {
        showToast('Laden fehlgeschlagen: ' + e.message, true);
        state.notes = [];
    }
    // Client-side Migration: alte HTML-Notizen zu Markdown umwandeln.
    // Der eigentliche Save passiert erst wenn der User die Notiz oeffnet
    // oder aendert — hier nur in-memory konvertieren, damit die Suche/
    // Vorschau bereits sauber arbeiten.
    state.notes.forEach(n => {
        if (n.format === 'html' && n.content) {
            n.content = htmlToMarkdown(n.content);
            n._needsFormatSave = true;   // Marker: beim naechsten Save format='markdown' senden
        }
    });
    renderSidebar();
    renderDetail();
}

// ==========================================================
// Sidebar
// ==========================================================
function renderSidebar() {
    const list = document.getElementById('nzList');
    const q = state.query;
    let notes = state.notes.slice();
    if (q) {
        notes = notes.filter(n => {
            const hay = ((n.title || '') + ' ' + (n.content || '')).toLowerCase();
            return hay.includes(q);
        });
    }
    // Sort
    const sortFn = {
        updated: (a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''),
        created: (a, b) => (b.created_at || '').localeCompare(a.created_at || ''),
        title:   (a, b) => (a.title || '').localeCompare(b.title || '', 'de', { sensitivity: 'base' }),
    }[state.sortMode] || ((a, b) => 0);
    notes.sort(sortFn);

    if (!notes.length) {
        const msg = state.query
            ? 'Keine Treffer für <strong>' + escapeHtml(state.query) + '</strong>.'
            : state.showArchived
                ? 'Kein archiviertes Element.'
                : 'Noch keine Notizen. Leg oben eine an.';
        list.innerHTML = `<div class="nz-list-empty">${msg}</div>`;
        return;
    }

    // Pinned zuerst, Rest darunter — jeweils mit Section-Header
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

    // Klick-Handler
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
    const badges = [];
    if (n.archived) badges.push('<span class="nz-item-badge">Archiv</span>');
    return `<div class="nz-item ${color}${active}" data-id="${n.id}">
        <div class="nz-item-main">
            <div class="nz-item-title">${title}</div>
            <div class="nz-item-preview">${preview}</div>
            <div class="nz-item-meta">
                <span>${relTime(n.updated_at)}</span>
                ${badges.join('')}
            </div>
        </div>
        ${pin}
    </div>`;
}

function previewText(md) {
    if (!md) return '';
    // Erste sinnvolle Zeile aus Markdown extrahieren.
    const lines = md.split('\n');
    for (const raw of lines) {
        const l = raw.trim();
        if (!l) continue;
        // Markdown-Zeichen weglassen fuer die Vorschau
        return l.replace(/^#+\s*/, '')                      // Ueberschriften
                .replace(/^[-*+]\s*\[[ x]\]\s*/i, '☐ ')      // Task
                .replace(/^[-*+]\s+/, '• ')                  // Bullet
                .replace(/^\d+\.\s+/, '')                    // Ordered
                .replace(/^>\s*/, '❝ ')                      // Quote
                .replace(/[*_`]/g, '');                      // inline
    }
    return '';
}


// ==========================================================
// Detail (Editor / Preview)
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
    document.getElementById('nzDEditor').value = n.content || '';
    updatePreview();
    document.getElementById('nzDPin').classList.toggle('active-pin', !!n.pinned);
    document.getElementById('nzDPin').textContent = n.pinned ? '📌 Angepinnt' : '📍 Pin';
    document.getElementById('nzDArchive').textContent = n.archived ? '📤 Wiederherstellen' : '🗄️ Archiv';
    document.querySelectorAll('.nz-d-swatch').forEach(s => {
        s.classList.toggle('active', s.dataset.color === (n.color || 'default'));
    });
    applyModeUI();
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

async function newNote() {
    await flushSave();
    try {
        const created = await NOTES_API.create({
            title: '', content: '', color: 'default', format: 'markdown',
        });
        state.notes.unshift(created);
        state.justCreated.add(created.id);
        state.selectedId = created.id;
        location.hash = 'note-' + created.id;
        renderSidebar();
        renderDetail();
        setTimeout(() => document.getElementById('nzDTitle').focus(), 50);
    } catch (e) { showToast('Anlegen fehlgeschlagen: ' + e.message, true); }
}


// ==========================================================
// Input / Save
// ==========================================================
function onTitleInput() {
    const n = state.notes.find(x => x.id === state.selectedId);
    if (!n) return;
    n.title = document.getElementById('nzDTitle').value;
    const el = document.querySelector(`.nz-item[data-id="${n.id}"] .nz-item-title`);
    if (el) el.textContent = n.title;
    scheduleSave();
}

function onContentInput() {
    const n = state.notes.find(x => x.id === state.selectedId);
    if (!n) return;
    n.content = document.getElementById('nzDEditor').value;
    if (state.mode === 'preview') updatePreview();
    const el = document.querySelector(`.nz-item[data-id="${n.id}"] .nz-item-preview`);
    if (el) el.textContent = previewText(n.content || '');
    scheduleSave();
}

function scheduleSave() {
    if (state.saveTimer) clearTimeout(state.saveTimer);
    setStatus('saving');
    state.saveTimer = setTimeout(doSave, 600);
}

async function doSave() {
    const n = state.notes.find(x => x.id === state.selectedId);
    if (!n) return;
    const token = ++state.saveToken;
    try {
        const body = {
            title: n.title || '',
            content: n.content || '',
            format: 'markdown',
        };
        const updated = await NOTES_API.update(n.id, body);
        if (token !== state.saveToken) return;
        Object.assign(n, updated);
        if ((n.title || '').trim() || (n.content || '').trim()) {
            state.justCreated.delete(n.id);
        }
        setStatus('saved');
    } catch (e) {
        setStatus('idle');
        showToast('Speichern fehlgeschlagen: ' + e.message, true);
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
    el.classList.remove('saving', 'saved');
    const txt = el.querySelector('.txt');
    if (s === 'saving') { el.classList.add('saving'); txt.textContent = 'Speichern…'; }
    else if (s === 'saved') { el.classList.add('saved'); txt.textContent = 'Gespeichert ✓'; }
    else txt.textContent = '';
    if (state.statusTimer) clearTimeout(state.statusTimer);
    if (s === 'saved') {
        state.statusTimer = setTimeout(() => { if (state.status === 'saved') setStatus('idle'); }, 2000);
    }
}

async function cleanupEmptyJustCreated(exceptId) {
    const toDelete = [];
    state.justCreated.forEach(id => {
        if (id === exceptId) return;
        const n = state.notes.find(x => x.id === id);
        if (!n) { state.justCreated.delete(id); return; }
        if (!(n.title || '').trim() && !(n.content || '').trim()) toDelete.push(id);
        else state.justCreated.delete(id);
    });
    for (const id of toDelete) {
        try { await NOTES_API.remove(id); } catch (_) {}
        state.notes = state.notes.filter(n => n.id !== id);
        state.justCreated.delete(id);
    }
}


// ==========================================================
// Actions: pin / archive / delete / color
// ==========================================================
async function togglePin(id) {
    const n = state.notes.find(x => x.id === id);
    if (!n) return;
    const wantPin = !n.pinned;
    try {
        const updated = await NOTES_API.update(id, { pinned: wantPin });
        Object.assign(n, updated);
        renderSidebar();
        renderDetail();
        showToast(wantPin ? 'Angepinnt' : 'Pin entfernt');
    } catch (e) { showToast('Fehler: ' + e.message, true); }
}

async function toggleArchive(id) {
    const n = state.notes.find(x => x.id === id);
    if (!n) return;
    const wantArchive = !n.archived;
    try {
        await NOTES_API.update(id, { archived: wantArchive });
        // Aus aktueller Ansicht rausnehmen
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
    const snapshot = { ...n };  // fuer Undo
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
                title: snapshot.title || '',
                content: snapshot.content || '',
                color: snapshot.color || 'default',
                pinned: !!snapshot.pinned,
                format: 'markdown',
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
    document.querySelectorAll('.nz-d-swatch').forEach(s => {
        s.classList.toggle('active', s.dataset.color === color);
    });
    // Sidebar-Farbstreifen live nachziehen
    const item = document.querySelector(`.nz-item[data-id="${n.id}"]`);
    if (item) {
        item.className = item.className.replace(/\bnz-color-\w+\b/g, '') + ' nz-color-' + color;
    }
    try { await NOTES_API.update(n.id, { color }); }
    catch (e) { showToast('Farbe speichern fehlgeschlagen: ' + e.message, true); }
}

// ==========================================================
// Mode-Switch (Editor / Preview)
// ==========================================================
function setMode(m) {
    if (m !== 'edit' && m !== 'preview') return;
    state.mode = m;
    applyModeUI();
    if (m === 'preview') updatePreview();
    else setTimeout(() => document.getElementById('nzDEditor').focus(), 20);
}

function applyModeUI() {
    document.querySelectorAll('.nz-mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === state.mode));
    document.querySelector('.nz-d-body').setAttribute('data-mode', state.mode);
    // Toolbar nur im Edit-Modus sinnvoll — im Preview trotzdem zeigen (User sieht Buttons, die tun nix
    // → einfacher: bei Preview verstecken)
    document.getElementById('nzToolbar').style.display = state.mode === 'edit' ? '' : 'none';
}

function updatePreview() {
    const md = document.getElementById('nzDEditor').value || '';
    document.getElementById('nzDPreview').innerHTML = renderMarkdown(md);
}


// ==========================================================
// Markdown-Renderer (schlank, mit Task-Checkboxen)
// ==========================================================
function renderMarkdown(md) {
    if (!md) return '<div style="color:var(--text-faint);font-style:italic">Nichts geschrieben.</div>';
    // 1) Fenced Codeblocks ``` extrahieren und durch Platzhalter ersetzen
    const codeBlocks = [];
    md = md.replace(/```([a-z0-9]*)\n([\s\S]*?)```/gi, (_, lang, code) => {
        const idx = codeBlocks.length;
        codeBlocks.push(`<pre><code>${escapeHtml(code)}</code></pre>`);
        return `\u0000CODE${idx}\u0000`;
    });
    const lines = md.split('\n');
    const out = [];
    let i = 0;
    while (i < lines.length) {
        const line = lines[i];
        if (/^\s*$/.test(line)) { i++; continue; }
        // Ueberschriften
        const h = line.match(/^(#{1,3})\s+(.*)$/);
        if (h) { out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }
        // Trennlinie
        if (/^(?:---|\*\*\*|___)\s*$/.test(line)) { out.push('<hr>'); i++; continue; }
        // Blockquote
        if (/^>\s?/.test(line)) {
            const buf = [];
            while (i < lines.length && /^>\s?/.test(lines[i])) {
                buf.push(lines[i].replace(/^>\s?/, ''));
                i++;
            }
            out.push('<blockquote>' + inline(buf.join('<br>')) + '</blockquote>');
            continue;
        }
        // Listen (unordered / ordered / task)
        if (/^\s*(?:[-*+]|\d+\.)\s+/.test(line)) {
            const isOrdered = /^\s*\d+\.\s+/.test(line);
            const isTaskList = /^\s*[-*+]\s*\[[ xX]\]\s*/.test(line);
            const items = [];
            while (i < lines.length && /^\s*(?:[-*+]|\d+\.)\s+/.test(lines[i])) {
                const l = lines[i];
                const task = l.match(/^\s*[-*+]\s*\[([ xX])\]\s*(.*)$/);
                if (task) {
                    const done = task[1].toLowerCase() === 'x';
                    items.push(
                        `<li class="nz-task${done ? ' done' : ''}" data-line="${i}">` +
                        `<input type="checkbox"${done ? ' checked' : ''}>` +
                        `<span class="nz-task-txt">${inline(task[2])}</span></li>`
                    );
                } else {
                    const m = l.match(/^\s*(?:[-*+]|\d+\.)\s+(.*)$/);
                    items.push('<li>' + inline(m[1]) + '</li>');
                }
                i++;
            }
            const tag = isOrdered ? 'ol' : 'ul';
            const cls = isTaskList ? ' class="nz-task-list"' : '';
            out.push(`<${tag}${cls}>${items.join('')}</${tag}>`);
            continue;
        }
        // Absatz
        const buf = [line];
        i++;
        while (i < lines.length && !/^\s*$/.test(lines[i])
                && !/^(#{1,3}\s|>|\s*(?:[-*+]|\d+\.)\s|---|\*\*\*|___)/.test(lines[i])) {
            buf.push(lines[i]); i++;
        }
        out.push('<p>' + inline(buf.join('<br>')) + '</p>');
    }
    let html = out.join('\n');
    html = html.replace(/\u0000CODE(\d+)\u0000/g, (_, idx) => codeBlocks[+idx] || '');
    return html;
}

/** Inline-Formatierung: **fett**, *kursiv*, `code`, [Link](url), Autolinks */
function inline(s) {
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
    s = s.replace(/(^|[\s(])((?:https?:\/\/)[^\s<]+)/g,
        '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
    s = s.replace(/\u0001C(\d+)\u0001/g, (_, idx) => codes[+idx] || '');
    return s;
}

/** Preview-Click: Task-Checkbox → Zeile im Textarea umschreiben. */
function onPreviewClick(e) {
    const cb = e.target;
    if (cb.tagName !== 'INPUT' || cb.type !== 'checkbox') return;
    const li = cb.closest('.nz-task');
    if (!li) return;
    const lineNo = parseInt(li.dataset.line, 10);
    if (isNaN(lineNo)) return;
    const editor = document.getElementById('nzDEditor');
    const lines = editor.value.split('\n');
    if (lineNo < 0 || lineNo >= lines.length) return;
    const l = lines[lineNo];
    const wantChecked = cb.checked;
    const replaced = l.replace(/^(\s*[-*+]\s*\[)([ xX])(\]\s*)/,
        (_, pre, mid, post) => pre + (wantChecked ? 'x' : ' ') + post);
    if (replaced === l) return;
    lines[lineNo] = replaced;
    editor.value = lines.join('\n');
    li.classList.toggle('done', wantChecked);
    const n = state.notes.find(x => x.id === state.selectedId);
    if (n) { n.content = editor.value; scheduleSave(); }
    haptic('tap');
}


// ==========================================================
// Toolbar-Aktionen (Markdown in Textarea einfuegen)
// ==========================================================
function applyMarkdown(cmd) {
    const ta = document.getElementById('nzDEditor');
    if (!ta) return;
    if (state.mode !== 'edit') setMode('edit');
    ta.focus();
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const val = ta.value;
    const selected = val.substring(start, end);

    const wrap = (before, after, placeholder) => {
        const text = selected || placeholder || '';
        const insert = before + text + after;
        ta.value = val.substring(0, start) + insert + val.substring(end);
        const cursorStart = start + before.length;
        const cursorEnd = cursorStart + text.length;
        ta.setSelectionRange(cursorStart, cursorEnd);
    };

    const linePrefix = (prefix, placeholder) => {
        const lineStart = val.lastIndexOf('\n', start - 1) + 1;
        const lineEnd = val.indexOf('\n', end);
        const effectiveEnd = lineEnd === -1 ? val.length : lineEnd;
        const block = val.substring(lineStart, effectiveEnd);
        const linesOut = (block || placeholder).split('\n').map(l => {
            const stripped = l.replace(/^#{1,3}\s*/, '')
                              .replace(/^[-*+]\s*(?:\[[ xX]\]\s*)?/, '')
                              .replace(/^\d+\.\s+/, '')
                              .replace(/^>\s?/, '');
            return prefix + stripped;
        });
        const insert = linesOut.join('\n');
        ta.value = val.substring(0, lineStart) + insert + val.substring(effectiveEnd);
        const newCursor = lineStart + insert.length;
        ta.setSelectionRange(newCursor, newCursor);
    };

    switch (cmd) {
        case 'bold':   wrap('**', '**', 'fetter Text'); break;
        case 'italic': wrap('*',  '*',  'kursiver Text'); break;
        case 'code':   wrap('`',  '`',  'code'); break;
        case 'h1':     linePrefix('# ',   'Überschrift'); break;
        case 'h2':     linePrefix('## ',  'Überschrift'); break;
        case 'h3':     linePrefix('### ', 'Überschrift'); break;
        case 'ul':     linePrefix('- ',   'Punkt'); break;
        case 'ol':     linePrefix('1. ',  'Punkt'); break;
        case 'task':   linePrefix('- [ ] ', 'Neue Aufgabe'); break;
        case 'quote':  linePrefix('> ',   'Zitat'); break;
        case 'hr': {
            const insert = (val[start-1] && val[start-1] !== '\n' ? '\n' : '') + '---\n';
            ta.value = val.substring(0, start) + insert + val.substring(end);
            ta.setSelectionRange(start + insert.length, start + insert.length);
            break;
        }
        case 'link': {
            const url = prompt('URL:', selected.startsWith('http') ? selected : 'https://');
            if (!url) return;
            const label = selected && !selected.startsWith('http') ? selected : 'Link';
            const insert = `[${label}](${url})`;
            ta.value = val.substring(0, start) + insert + val.substring(end);
            const cursor = start + 1;
            ta.setSelectionRange(cursor, cursor + label.length);
            break;
        }
        default: return;
    }
    ta.dispatchEvent(new Event('input'));
}


// ==========================================================
// Keydown im Editor: Cmd/Ctrl-Shortcuts + smart Enter in Listen
// ==========================================================
function onEditorKeydown(e) {
    const isMod = e.metaKey || e.ctrlKey;
    if (!isMod) {
        if (e.key === 'Enter') {
            const ta = e.currentTarget;
            const pos = ta.selectionStart;
            const lineStart = ta.value.lastIndexOf('\n', pos - 1) + 1;
            const line = ta.value.substring(lineStart, pos);
            const taskMatch = line.match(/^(\s*)([-*+])\s+\[[ xX]\]\s*/);
            const bulletMatch = line.match(/^(\s*)([-*+])\s+/);
            const orderedMatch = line.match(/^(\s*)(\d+)\.\s+/);
            const doExit = (match) => {
                // Prefix entfernen, Cursor bleibt auf leerer Zeile
                e.preventDefault();
                ta.value = ta.value.substring(0, lineStart) + ta.value.substring(pos);
                ta.setSelectionRange(lineStart, lineStart);
                ta.dispatchEvent(new Event('input'));
            };
            const doContinue = (insert) => {
                e.preventDefault();
                ta.value = ta.value.substring(0, pos) + insert + ta.value.substring(pos);
                ta.setSelectionRange(pos + insert.length, pos + insert.length);
                ta.dispatchEvent(new Event('input'));
            };
            if (taskMatch) {
                if (line.replace(taskMatch[0], '').trim() === '') return doExit();
                return doContinue('\n' + taskMatch[1] + taskMatch[2] + ' [ ] ');
            }
            if (bulletMatch) {
                if (line.replace(bulletMatch[0], '').trim() === '') return doExit();
                return doContinue('\n' + bulletMatch[1] + bulletMatch[2] + ' ');
            }
            if (orderedMatch) {
                if (line.replace(orderedMatch[0], '').trim() === '') return doExit();
                const next = parseInt(orderedMatch[2], 10) + 1;
                return doContinue('\n' + orderedMatch[1] + next + '. ');
            }
        }
        return;
    }
    // Modifier-Shortcuts
    const k = e.key.toLowerCase();
    if (k === 'b') { e.preventDefault(); applyMarkdown('bold'); }
    else if (k === 'i') { e.preventDefault(); applyMarkdown('italic'); }
    else if (k === 'k') { e.preventDefault(); applyMarkdown('link'); }
    else if (k === '`') { e.preventDefault(); applyMarkdown('code'); }
    else if (k === 'e') { e.preventDefault(); setMode(state.mode === 'edit' ? 'preview' : 'edit'); }
    else if (e.shiftKey && (k === '7' || k === '&')) { e.preventDefault(); applyMarkdown('task'); }
    else if (e.shiftKey && (k === '8' || k === '(')) { e.preventDefault(); applyMarkdown('ul'); }
    else if (e.shiftKey && (k === '9' || k === ')')) { e.preventDefault(); applyMarkdown('ol'); }
}

// ==========================================================
// Globale Shortcuts (funktionieren wenn nicht in Input/Textarea)
// ==========================================================
function onGlobalKeydown(e) {
    const isMod = e.metaKey || e.ctrlKey;
    if (!isMod) return;
    const k = e.key.toLowerCase();
    if (k === 'n' && !e.shiftKey) {
        const tag = (document.activeElement?.tagName || '').toLowerCase();
        if (tag !== 'input' && tag !== 'textarea') {
            e.preventDefault();
            newNote();
        }
    }
}


// ==========================================================
// HTML → Markdown Migration (v1.14-v1.16 contenteditable-Output)
// ==========================================================
function htmlToMarkdown(html) {
    if (!html) return '';
    const doc = document.implementation.createHTMLDocument('');
    doc.body.innerHTML = html;
    const walker = (node) => {
        if (node.nodeType === 3) return node.nodeValue;
        if (node.nodeType !== 1) return '';
        const tag = node.tagName.toLowerCase();
        const kids = Array.from(node.childNodes).map(walker).join('');
        switch (tag) {
            case 'br': return '\n';
            case 'strong': case 'b': return `**${kids}**`;
            case 'em': case 'i': return `*${kids}*`;
            case 'code': return `\`${kids}\``;
            case 'a': {
                const href = node.getAttribute('href') || '';
                return href ? `[${kids}](${href})` : kids;
            }
            case 'h1': return `\n# ${kids}\n\n`;
            case 'h2': return `\n## ${kids}\n\n`;
            case 'h3': return `\n### ${kids}\n\n`;
            case 'ul': case 'ol': {
                let idx = 1;
                const items = Array.from(node.children)
                    .filter(c => c.tagName.toLowerCase() === 'li')
                    .map(li => {
                        const prefix = tag === 'ol' ? `${idx++}. ` : '- ';
                        const inner = Array.from(li.childNodes).map(walker).join('').trim();
                        return prefix + inner;
                    });
                return '\n' + items.join('\n') + '\n\n';
            }
            case 'blockquote': return '\n' + kids.split('\n').map(l => '> ' + l).join('\n') + '\n\n';
            case 'hr': return '\n---\n\n';
            case 'div': {
                if (node.classList.contains('nz-task')) {
                    const done = node.classList.contains('done');
                    const txtEl = node.querySelector('.nz-task-txt');
                    const txt = txtEl ? txtEl.textContent : node.textContent;
                    return `- [${done ? 'x' : ' '}] ${txt.trim()}\n`;
                }
                return kids + '\n';
            }
            case 'p': return kids + '\n\n';
            default: return kids;
        }
    };
    let md = Array.from(doc.body.childNodes).map(walker).join('');
    md = md.replace(/\n{3,}/g, '\n\n').trim();
    md = md.replace(/\u00a0/g, ' ');
    return md;
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
// Helper
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
// Toast (mit optionalem Undo-Button)
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

