/* Blog-Admin — v1.18.0
 * contenteditable-Editor mit Task-Support (Version A / Notizen-Stil).
 */

const BLOG_ADMIN_API = {
    list:   () => apiCall('/api/blog/posts'),
    create: (b) => apiCall('/api/blog/posts', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    update: (id, b) => apiCall(`/api/blog/posts/${id}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(b) }),
    publish: (id) => apiCall(`/api/blog/posts/${id}/publish`, { method: 'POST' }),
    unpublish: (id) => apiCall(`/api/blog/posts/${id}/unpublish`, { method: 'POST' }),
    remove: (id) => apiCall(`/api/blog/posts/${id}`, { method: 'DELETE' }),
};

const S = { posts: [], selectedId: null, saveTimer: null, saveToken: 0 };

function escapeHtml(s){if(s==null)return'';return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fmtDate(iso){if(!iso)return'';return new Date(iso).toLocaleDateString('de-DE',{day:'2-digit',month:'2-digit',year:'2-digit'});}

async function boot() {
    if (!isLoggedIn()) { window.location.href = '/private/login.html'; return; }
    try {
        const me = await fetchMe(true);
        if (!me.is_admin) { alert('Admin-Zugriff erforderlich'); window.location.href = '/'; return; }
        document.getElementById('userLabel').textContent = '👤 ' + me.username;
    } catch (e) { window.location.href = '/private/login.html'; return; }
    document.getElementById('logoutBtn').onclick = () => { clearToken(); location.reload(); };
    document.getElementById('themeBtn').onclick = toggleTheme;
    bindUI();
    await loadPosts();
    document.body.style.visibility = 'visible';
}

function bindUI() {
    document.getElementById('baNew').onclick = newPost;
    ['baTitle','baSubtitle','baSlug','baCover','baTags'].forEach(id => {
        document.getElementById(id).addEventListener('input', scheduleSave);
    });
    const editor = document.getElementById('baContent');
    editor.addEventListener('input', scheduleSave);
    editor.addEventListener('keydown', onEditorKeydown);
    editor.addEventListener('beforeinput', onEditorBeforeInput);
    editor.addEventListener('click', onEditorClick);
    editor.addEventListener('paste', onEditorPaste);
    document.querySelectorAll('.nz-tb').forEach(btn => {
        btn.addEventListener('mousedown', (e) => e.preventDefault());
        btn.addEventListener('click', (e) => { e.preventDefault(); applyToolbarCmd(btn.dataset.cmd); });
    });
    document.getElementById('baPublish').onclick = async () => {
        await flushSave();
        const p = await BLOG_ADMIN_API.publish(S.selectedId);
        Object.assign(S.posts.find(x=>x.id===S.selectedId) || {}, p);
        renderList(); renderState();
    };
    document.getElementById('baUnpub').onclick = async () => {
        await flushSave();
        const p = await BLOG_ADMIN_API.unpublish(S.selectedId);
        Object.assign(S.posts.find(x=>x.id===S.selectedId) || {}, p);
        renderList(); renderState();
    };
    document.getElementById('baDelete').onclick = async () => {
        if (!confirm('Post wirklich löschen?')) return;
        await BLOG_ADMIN_API.remove(S.selectedId);
        S.posts = S.posts.filter(x => x.id !== S.selectedId);
        S.selectedId = null;
        renderList(); renderDetail();
    };
}

async function loadPosts() {
    try { S.posts = await BLOG_ADMIN_API.list() || []; }
    catch (e) { alert('Laden fehlgeschlagen: ' + e.message); S.posts = []; }
    renderList();
    if (S.posts.length && !S.selectedId) selectPost(S.posts[0].id);
    else renderDetail();
}

function renderList() {
    const box = document.getElementById('baList');
    if (!S.posts.length) { box.innerHTML = '<div style="color:var(--text-muted);padding:1rem;text-align:center;font-size:0.85rem">Noch keine Posts</div>'; return; }
    box.innerHTML = S.posts.map(p => `
        <div class="ba-item${S.selectedId === p.id ? ' active' : ''}" data-id="${p.id}">
            <div class="ba-item-title">${escapeHtml(p.title || '(Ohne Titel)')}</div>
            <div class="ba-item-meta">
                <span class="ba-item-badge ${p.published_at ? 'pub' : 'draft'}">${p.published_at ? 'Live' : 'Entwurf'}</span>
                <span>${fmtDate(p.updated_at)}</span>
            </div>
        </div>
    `).join('');
    box.querySelectorAll('.ba-item').forEach(el => {
        el.onclick = () => selectPost(Number(el.dataset.id));
    });
}

async function selectPost(id) {
    await flushSave();
    S.selectedId = id;
    renderList();
    renderDetail();
}

function renderDetail() {
    const p = S.posts.find(x => x.id === S.selectedId);
    if (!p) {
        document.getElementById('baEmpty').style.display = '';
        document.getElementById('baDetail').style.display = 'none';
        return;
    }
    document.getElementById('baEmpty').style.display = 'none';
    document.getElementById('baDetail').style.display = 'flex';
    document.getElementById('baTitle').value = p.title || '';
    document.getElementById('baSubtitle').value = p.subtitle || '';
    document.getElementById('baSlug').value = p.slug || '';
    document.getElementById('baCover').value = p.cover_url || '';
    document.getElementById('baTags').value = (p.tags || []).join(', ');
    document.getElementById('baContent').innerHTML = p.content_html || '';
    normalizeTasks(document.getElementById('baContent'));
    renderState();
    setStatus('idle');
}

function renderState() {
    const p = S.posts.find(x => x.id === S.selectedId);
    if (!p) return;
    const st = document.getElementById('baState');
    st.textContent = p.published_at ? `📰 Veröffentlicht am ${fmtDate(p.published_at)}` : 'Entwurf';
    st.classList.toggle('published', !!p.published_at);
    document.getElementById('baPublish').style.display = p.published_at ? 'none' : '';
    document.getElementById('baUnpub').style.display = p.published_at ? '' : 'none';
}

async function newPost() {
    await flushSave();
    try {
        const p = await BLOG_ADMIN_API.create({ title: 'Neuer Beitrag', content_html: '' });
        S.posts.unshift(p);
        S.selectedId = p.id;
        renderList();
        renderDetail();
        document.getElementById('baTitle').select();
    } catch (e) { alert('Anlegen fehlgeschlagen: ' + e.message); }
}

// ==========================================================
// Auto-Save
// ==========================================================
function scheduleSave() {
    setStatus('saving');
    clearTimeout(S.saveTimer);
    S.saveTimer = setTimeout(flushSave, 800);
}

async function flushSave() {
    clearTimeout(S.saveTimer); S.saveTimer = null;
    const id = S.selectedId;
    if (!id) return;
    const p = S.posts.find(x => x.id === id);
    if (!p) return;
    const tags = document.getElementById('baTags').value.split(',').map(t => t.trim()).filter(Boolean);
    const body = {
        title: document.getElementById('baTitle').value || '',
        subtitle: document.getElementById('baSubtitle').value || null,
        content_html: document.getElementById('baContent').innerHTML || '',
        cover_url: document.getElementById('baCover').value || null,
        tags,
    };
    const slug = document.getElementById('baSlug').value.trim();
    if (slug && slug !== p.slug) body.slug = slug;
    const token = ++S.saveToken;
    try {
        const updated = await BLOG_ADMIN_API.update(id, body);
        Object.assign(p, updated);
        if (token === S.saveToken) {
            setStatus('saved');
            renderList();
            renderState();
            // Slug ggf. aus Server nachziehen
            if (updated.slug && updated.slug !== document.getElementById('baSlug').value.trim()) {
                document.getElementById('baSlug').value = updated.slug;
            }
        }
    } catch (e) {
        if (token === S.saveToken) { setStatus('idle'); console.error('save failed:', e); }
    }
}

function setStatus(s) {
    const el = document.getElementById('baStatus');
    if (!el) return;
    el.className = 'nz-d-status ' + s;
    const txt = { idle: '', saving: 'Speichere…', saved: 'Gespeichert ✓' }[s] || '';
    el.querySelector('.txt').textContent = txt;
}


// ==========================================================
// Editor-Kernlogik (contenteditable, Task-Blocks)
// ==========================================================
function normalizeTasks(root) {
    root.querySelectorAll('.nz-task').forEach(t => {
        if (t.dataset.done !== 'true') t.dataset.done = 'false';
        let box = t.querySelector('.nz-task-box');
        if (!box) {
            box = document.createElement('span');
            box.className = 'nz-task-box';
            box.contentEditable = 'false';
            t.prepend(box);
        } else box.contentEditable = 'false';
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
    div.appendChild(box); div.appendChild(txt);
    return div;
}

function placeCaretInside(el) {
    const r = document.createRange(); r.selectNodeContents(el); r.collapse(true);
    const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    if (el.focus) el.focus();
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

function onEditorClick(e) {
    const box = e.target.closest('.nz-task-box');
    if (!box) return;
    e.preventDefault();
    const task = box.closest('.nz-task');
    if (!task) return;
    task.dataset.done = task.dataset.done === 'true' ? 'false' : 'true';
    scheduleSave();
}

function onEditorBeforeInput(e) {
    if (e.inputType !== 'insertParagraph' && e.inputType !== 'insertLineBreak') return;
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount) return;
    const range = sel.getRangeAt(0);
    let node = range.startContainer;
    const editor = document.getElementById('baContent');
    const task = node.nodeType === 1 ? node.closest('.nz-task') : (node.parentNode && node.parentNode.closest('.nz-task'));
    if (task && editor.contains(task)) {
        e.preventDefault();
        const txtEl = task.querySelector('.nz-task-txt');
        const txt = (txtEl?.textContent || '').trim();
        if (!txt) {
            const p = document.createElement('p'); p.appendChild(document.createElement('br'));
            task.replaceWith(p); placeCaretInside(p);
        } else {
            const nt = newTaskBlock(''); task.after(nt);
            placeCaretInside(nt.querySelector('.nz-task-txt'));
        }
        scheduleSave();
    }
}

function onEditorKeydown(e) {
    if (e.key === ' ') maybeApplyMarkdownShortcut(e);
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
    const editor = document.getElementById('baContent');
    const block = closestBlock(range.startContainer, editor);
    if (!block || block === editor) return;
    if (block.classList && block.classList.contains('nz-task')) return;
    const txt = block.textContent || '';
    const rules = [
        { re: /^# $/,        action: () => document.execCommand('formatBlock', false, 'H1') },
        { re: /^## $/,       action: () => document.execCommand('formatBlock', false, 'H2') },
        { re: /^### $/,      action: () => document.execCommand('formatBlock', false, 'H3') },
        { re: /^- \[ ?\] $/, action: () => convertBlockToTask(block, false) },
        { re: /^- \[x\] $/i, action: () => convertBlockToTask(block, true) },
        { re: /^- $/,        action: () => document.execCommand('insertUnorderedList') },
        { re: /^\* $/,       action: () => document.execCommand('insertUnorderedList') },
        { re: /^1\. $/,      action: () => document.execCommand('insertOrderedList') },
        { re: /^> $/,        action: () => document.execCommand('formatBlock', false, 'BLOCKQUOTE') },
    ];
    for (const r of rules) {
        if (r.re.test(txt)) {
            e.preventDefault();
            block.textContent = '';
            r.action();
            scheduleSave();
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
    if (text) document.execCommand('insertText', false, text);
}

function applyToolbarCmd(cmd) {
    const editor = document.getElementById('baContent');
    editor.focus();
    switch (cmd) {
        case 'bold': document.execCommand('bold'); break;
        case 'italic': document.execCommand('italic'); break;
        case 'underline': document.execCommand('underline'); break;
        case 'code': wrapInlineTag('CODE'); break;
        case 'h1': document.execCommand('formatBlock', false, 'H1'); break;
        case 'h2': document.execCommand('formatBlock', false, 'H2'); break;
        case 'h3': document.execCommand('formatBlock', false, 'H3'); break;
        case 'ul': document.execCommand('insertUnorderedList'); break;
        case 'ol': document.execCommand('insertOrderedList'); break;
        case 'quote': document.execCommand('formatBlock', false, 'BLOCKQUOTE'); break;
        case 'hr': document.execCommand('insertHorizontalRule'); break;
        case 'task': insertTaskAtCursor(); break;
        case 'link': {
            const url = prompt('Link-URL:', 'https://');
            if (url) document.execCommand('createLink', false, url);
            break;
        }
    }
    scheduleSave();
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
    const editor = document.getElementById('baContent');
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

boot();

