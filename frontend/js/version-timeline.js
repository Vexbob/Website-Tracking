/* version-timeline.js — v1.38.0
 * Klick auf .version-tag oeffnet ein Modal mit einem vertikalen
 * Zeitstrahl (Changelog) aller Releases. Idempotent.
 */
(function () {
    if (window.__vexbobVersionTimeline) return;
    window.__vexbobVersionTimeline = true;

    const STYLE_ID = 'vexbob-vtl-style';
    function injectStyle() {
        if (document.getElementById(STYLE_ID)) return;
        const s = document.createElement('style');
        s.id = STYLE_ID;
        s.textContent = `
.version-tag { cursor: pointer; user-select: none; }
.version-tag:hover { color: var(--text); }
.vtl-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 2100;
    display: flex; align-items: center; justify-content: center; padding: 1rem;
    opacity: 0; transition: opacity .18s; }
.vtl-overlay.show { opacity: 1; }
.vtl-box { background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius-lg); box-shadow: var(--shadow-lg);
    width: 100%; max-width: 560px; max-height: calc(100vh - 2rem);
    display: flex; flex-direction: column; overflow: hidden;
    transform: translateY(8px) scale(0.98); transition: transform .18s; }
.vtl-overlay.show .vtl-box { transform: none; }
.vtl-head { display: flex; align-items: center; justify-content: space-between;
    padding: 0.9rem 1.1rem; border-bottom: 1px solid var(--border); }
.vtl-head h3 { margin: 0; font-size: 1.05rem; font-weight: 700; letter-spacing: -0.01em; }
.vtl-head .vtl-sub { font-size: 0.75rem; color: var(--text-faint); margin-top: 2px; }
.vtl-close { background: transparent; border: none; color: var(--text-muted);
    font-size: 1.15rem; cursor: pointer; width: 32px; height: 32px;
    border-radius: 8px; margin: 0; padding: 0; display: flex; align-items: center; justify-content: center; }
.vtl-close:hover { background: var(--surface-2); color: var(--text); }
.vtl-body { padding: 1rem 1.1rem 1.25rem; overflow-y: auto; }
.vtl-list { position: relative; padding-left: 22px; list-style: none; margin: 0; }
.vtl-list::before { content: ''; position: absolute; left: 6px; top: 6px; bottom: 6px; width: 2px;
    background: linear-gradient(180deg, var(--border-strong), var(--border) 30%, transparent);
    border-radius: 1px; }
.vtl-item { position: relative; padding: 0 0 1.1rem; }
.vtl-item:last-child { padding-bottom: 0; }
.vtl-dot { position: absolute; left: -22px; top: 6px; width: 14px; height: 14px;
    border-radius: 50%; background: var(--surface); border: 2px solid var(--text-faint);
    box-shadow: 0 0 0 3px var(--surface); }
.vtl-item.current .vtl-dot { background: var(--accent); border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--surface), 0 0 0 5px rgba(233,69,96,0.18); }
.vtl-vhdr { display: flex; align-items: baseline; gap: 0.5rem; flex-wrap: wrap; }
.vtl-ver { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 0.8125rem;
    font-weight: 700; color: var(--text); background: var(--surface-2);
    border: 1px solid var(--border); padding: 1px 6px; border-radius: 6px; }
.vtl-item.current .vtl-ver { background: var(--accent); color: #fff; border-color: var(--accent); }
.vtl-date { font-size: 0.72rem; color: var(--text-faint); font-variant-numeric: tabular-nums; }
.vtl-title { font-size: 0.95rem; font-weight: 600; margin: 0.2rem 0 0.35rem;
    color: var(--text); letter-spacing: -0.01em; }
.vtl-notes { margin: 0; padding-left: 1rem; font-size: 0.825rem; color: var(--text-muted); line-height: 1.5; }
.vtl-notes li { margin: 0.15rem 0; }
.vtl-empty { color: var(--text-muted); font-size: 0.875rem; text-align: center; padding: 1.5rem 0.5rem; }
@media (max-width: 500px) {
    .vtl-box { max-height: calc(100vh - 1rem); }
    .vtl-head { padding: 0.75rem 0.9rem; }
    .vtl-body { padding: 0.75rem 0.9rem 1rem; }
}`;
        document.head.appendChild(s);
    }

    function currentAppVersion() {
        try { return typeof APP_VERSION !== 'undefined' ? APP_VERSION : ''; } catch (e) { return ''; }
    }
    function escapeHtml(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
            {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
        ));
    }
    function fmtDate(iso) {
        if (!iso) return '';
        try { return new Date(iso + 'T00:00:00').toLocaleDateString('de-DE', { year:'numeric', month:'short', day:'2-digit' }); }
        catch (e) { return iso; }
    }

    function loadChangelog() {
        return new Promise((resolve) => {
            if (Array.isArray(window.VEXBOB_CHANGELOG)) return resolve(window.VEXBOB_CHANGELOG);
            const existing = document.querySelector('script[data-vexbob-changelog]');
            if (existing) { existing.addEventListener('load', () => resolve(window.VEXBOB_CHANGELOG || [])); return; }
            const s = document.createElement('script');
            s.src = '/js/changelog.js'; s.defer = true;
            s.setAttribute('data-vexbob-changelog', '1');
            s.onload = () => resolve(window.VEXBOB_CHANGELOG || []);
            s.onerror = () => resolve([]);
            document.head.appendChild(s);
        });
    }


    function renderList(entries, currentV) {
        if (!entries || !entries.length) return '<div class="vtl-empty">Keine Versions-Historie verfuegbar.</div>';
        const cur = (currentV || '').trim();
        const items = entries.map(e => {
            const isCur = e.v === cur;
            const notes = Array.isArray(e.notes) && e.notes.length
                ? '<ul class="vtl-notes">' + e.notes.map(n => '<li>' + escapeHtml(n) + '</li>').join('') + '</ul>'
                : '';
            return '<li class="vtl-item' + (isCur ? ' current' : '') + '">' +
                '<span class="vtl-dot"></span>' +
                '<div class="vtl-vhdr">' +
                    '<span class="vtl-ver">' + escapeHtml(e.v) + '</span>' +
                    '<span class="vtl-date">' + escapeHtml(fmtDate(e.date)) + (isCur ? ' · aktuell' : '') + '</span>' +
                '</div>' +
                '<div class="vtl-title">' + escapeHtml(e.title || '') + '</div>' +
                notes +
            '</li>';
        }).join('');
        return '<ol class="vtl-list">' + items + '</ol>';
    }

    async function openTimeline() {
        injectStyle();
        const cur = currentAppVersion();
        const entries = await loadChangelog();

        const overlay = document.createElement('div');
        overlay.className = 'vtl-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-label', 'Versions-Historie');
        overlay.innerHTML =
            '<div class="vtl-box">' +
                '<div class="vtl-head">' +
                    '<div>' +
                        '<h3>Versions-Historie</h3>' +
                        '<div class="vtl-sub">Was seit dem ersten Commit alles passiert ist</div>' +
                    '</div>' +
                    '<button type="button" class="vtl-close" aria-label="Schliessen">✕</button>' +
                '</div>' +
                '<div class="vtl-body">' + renderList(entries, cur) + '</div>' +
            '</div>';

        document.body.appendChild(overlay);
        const prevOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';

        const close = () => {
            overlay.classList.remove('show');
            document.removeEventListener('keydown', onKey);
            setTimeout(() => {
                overlay.remove();
                document.body.style.overflow = prevOverflow;
            }, 200);
        };
        const onKey = (e) => { if (e.key === 'Escape') close(); };
        document.addEventListener('keydown', onKey);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
        overlay.querySelector('.vtl-close').addEventListener('click', close);
        requestAnimationFrame(() => overlay.classList.add('show'));
    }

    function attach() {
        injectStyle();
        document.addEventListener('click', (e) => {
            const t = e.target.closest && e.target.closest('.version-tag');
            if (!t) return;
            e.preventDefault();
            openTimeline();
        });
        function markAccessible() {
            document.querySelectorAll('.version-tag').forEach(el => {
                if (el.dataset.vtlHooked) return;
                el.dataset.vtlHooked = '1';
                el.setAttribute('role', 'button');
                el.setAttribute('tabindex', '0');
                el.setAttribute('title', 'Versions-Historie ansehen');
                el.setAttribute('aria-label', 'Versions-Historie ansehen');
                el.addEventListener('keydown', (ev) => {
                    if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); openTimeline(); }
                });
            });
        }
        markAccessible();
        try {
            new MutationObserver(markAccessible).observe(document.body, { childList: true, subtree: true });
        } catch (e) {}
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', attach);
    } else {
        attach();
    }
    window.openVersionTimeline = openTimeline;
})();
