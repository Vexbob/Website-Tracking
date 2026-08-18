/* Blog — v1.18.0 Frontend (öffentlich)
 * SPA: eine Datei, Hash-Route wählt Übersicht oder Detail.
 * Nutzt AUSSCHLIESSLICH die /api/public/blog/*-Endpoints (kein Auth).
 */

// API_BASE ist global aus /js/api.js (const)
const BLOG_API = {
    list:   (params={}) => fetch(API_BASE + '/api/public/blog/posts?' + new URLSearchParams(params).toString()).then(rsp),
    detail: (slug) => fetch(API_BASE + '/api/public/blog/posts/' + encodeURIComponent(slug)).then(rsp),
    tags:   () => fetch(API_BASE + '/api/public/blog/tags').then(rsp),
};
async function rsp(r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
}

function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function fmtDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString('de-DE', { day: '2-digit', month: 'long', year: 'numeric' });
}

function readingTime(html) {
    const txt = (new DOMParser().parseFromString(html || '', 'text/html').body.textContent || '');
    const words = txt.trim().split(/\s+/).filter(Boolean).length;
    return Math.max(1, Math.round(words / 200));
}

function sanitizeHtml(html) {
    const allowed = new Set(['P','H1','H2','H3','H4','H5','H6','UL','OL','LI','BLOCKQUOTE','PRE','CODE','STRONG','B','EM','I','U','S','A','BR','HR','IMG','DIV','SPAN']);
    const doc = new DOMParser().parseFromString(html || '', 'text/html');
    const walk = (node) => {
        Array.from(node.children).forEach(child => {
            if (!allowed.has(child.tagName)) {
                const parent = child.parentNode;
                while (child.firstChild) parent.insertBefore(child.firstChild, child);
                parent.removeChild(child);
                return;
            }
            const keep = child.tagName === 'A' ? ['href','target','rel']
                : child.tagName === 'IMG' ? ['src','alt']
                : child.tagName === 'DIV' ? ['class','data-done']
                : child.tagName === 'SPAN' ? ['class','contenteditable']
                : [];
            Array.from(child.attributes).forEach(attr => {
                if (!keep.includes(attr.name.toLowerCase())) child.removeAttribute(attr.name);
                else if (attr.name.toLowerCase() === 'href' && !/^https?:\/\/|^mailto:|^\//.test(attr.value)) child.removeAttribute('href');
            });
            if (child.tagName === 'A') { child.setAttribute('target', '_blank'); child.setAttribute('rel', 'noopener'); }
            walk(child);
        });
    };
    walk(doc.body);
    return doc.body.innerHTML;
}

// ==========================================================
// Routing
// ==========================================================
async function boot() {
    document.getElementById('themeBtn').onclick = () => (typeof toggleTheme === 'function') && toggleTheme();
    if (typeof isLoggedIn === 'function' && isLoggedIn()) {
        document.getElementById('loginLink').style.display = 'none';
        document.getElementById('homeLink').style.display = '';
    }
    window.addEventListener('hashchange', route);
    route();
}

function route() {
    const m = location.hash.match(/^#(?:post-)?([a-z0-9-]+)$/i);
    if (m) return renderDetail(m[1]);
    return renderList();
}

// ==========================================================
// Übersicht
// ==========================================================
let activeTag = null;

async function renderList() {
    document.title = 'Vexbob Blog';
    const view = document.getElementById('blogView');
    view.innerHTML = `
        <div class="blog-header">
            <h1>📰 Vexbob Blog</h1>
            <p>Test</p>
        </div>
        <div class="blog-tags" id="blogTags"></div>
        <div id="blogList"><div class="blog-loading">Lade …</div></div>`;
    try {
        const tags = await BLOG_API.tags();
        const tagsEl = document.getElementById('blogTags');
        if (tags.length) {
            const all = `<span class="blog-tag${activeTag ? '' : ' active'}" onclick="filterTag(null)">Alle</span>`;
            tagsEl.innerHTML = all + tags.map(t =>
                `<span class="blog-tag${activeTag === t.tag ? ' active' : ''}" onclick="filterTag('${escapeHtml(t.tag)}')">${escapeHtml(t.tag)} <span style="opacity:0.6">${t.count}</span></span>`
            ).join('');
        }
    } catch (e) {}
    try {
        const params = { limit: 20 };
        if (activeTag) params.tag = activeTag;
        const posts = await BLOG_API.list(params);
        const list = document.getElementById('blogList');
        if (!posts.length) {
            list.innerHTML = '<div class="blog-empty">Noch keine Beiträge veröffentlicht.</div>';
            return;
        }
        list.innerHTML = posts.map(p => `
            <a class="blog-post-card" href="#${escapeHtml(p.slug)}">
                <h2>${escapeHtml(p.title)}</h2>
                ${p.subtitle ? `<p class="subtitle">${escapeHtml(p.subtitle)}</p>` : ''}
                <div class="meta">
                    <span>${fmtDate(p.published_at)}</span>
                    <span class="dot"></span>
                    <span>${escapeHtml(p.author_name || 'Anonym')}</span>
                    ${p.view_count ? `<span class="dot"></span><span>${p.view_count} Aufrufe</span>` : ''}
                </div>
                ${p.tags && p.tags.length ? `<div class="tags-inline">${p.tags.map(t => `<span class="t">${escapeHtml(t)}</span>`).join('')}</div>` : ''}
            </a>
        `).join('');
    } catch (e) {
        document.getElementById('blogList').innerHTML = '<div class="blog-empty">Fehler beim Laden.</div>';
    }
}

function filterTag(t) { activeTag = t; renderList(); }
window.filterTag = filterTag;

// ==========================================================
// Detail
// ==========================================================
async function renderDetail(slug) {
    const view = document.getElementById('blogView');
    view.innerHTML = `
        <a class="blog-back" href="#">← Alle Beiträge</a>
        <article class="blog-post"><div class="blog-loading">Lade …</div></article>`;
    try {
        const p = await BLOG_API.detail(slug);
        document.title = `${p.title} — Vexbob Blog`;
        const rt = readingTime(p.content_html);
        view.querySelector('.blog-post').innerHTML = `
            ${p.cover_url ? `<img class="cover" src="${escapeHtml(p.cover_url)}" alt="">` : ''}
            <h1>${escapeHtml(p.title)}</h1>
            ${p.subtitle ? `<div class="subtitle">${escapeHtml(p.subtitle)}</div>` : ''}
            <div class="meta">
                <span>${fmtDate(p.published_at)}</span>
                <span class="dot"></span>
                <span>${escapeHtml(p.author_name || 'Anonym')}</span>
                <span class="dot"></span>
                <span>⏱ ${rt} min Lesezeit</span>
            </div>
            <div class="content">${sanitizeHtml(p.content_html || '')}</div>
            ${p.tags && p.tags.length ? `<div class="tags-inline">${p.tags.map(t => `<span class="t">${escapeHtml(t)}</span>`).join('')}</div>` : ''}
        `;
    } catch (e) {
        view.querySelector('.blog-post').innerHTML = '<div class="blog-empty">Beitrag nicht gefunden.</div>';
    }
}

boot();
