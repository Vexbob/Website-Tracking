/* einstellungen.js — v1.59.0
 * Die Einstellungsseite. Sie definiert nichts selbst: Modul-Liste, Icons und
 * der Tab-Leisten-Dialog kommen aus nav-switcher.js (window.VexNav), damit es
 * keine zweite Liste gibt, die mit der Zeit auseinanderlaeuft.
 *
 * Gespeichert wird ueber /api/ui/prefs. Eine kuenftige Einstellung braucht
 * dort einen Pruefer und hier eine Karte — sonst nichts.
 */

const SET = { modules: [], order: [] };

/* nav-switcher.js baut die Leiste asynchron (es fragt vorher, wer man ist).
 * Wir warten auf sein Signal, statt auf gut Glueck zu pollen. */
function navReady() {
    if (window.VexNav && VexNav.modules().length) return Promise.resolve();
    return new Promise(resolve => {
        const done = () => resolve();
        document.addEventListener('vexnav:ready', done, { once: true });
        // Notausgang: ohne Signal (alte Version im Cache) nach 3 s weitermachen.
        setTimeout(done, 3000);
    });
}

function renderDesktopList() {
    const box = document.getElementById('deskList');
    const byHref = new Map(SET.modules.map(m => [m.href, m]));
    box.innerHTML = SET.order.map((href, i) => {
        const m = byHref.get(href);
        if (!m) return '';
        const name = m.label.split(' ').slice(1).join(' ');
        const up = '<button type="button" class="navcfg-mini" data-act="up" data-href="' + href + '"' +
            (i === 0 ? ' disabled' : '') + ' aria-label="Nach vorn">↑</button>';
        const down = '<button type="button" class="navcfg-mini" data-act="down" data-href="' + href + '"' +
            (i === SET.order.length - 1 ? ' disabled' : '') + ' aria-label="Nach hinten">↓</button>';
        return '<div class="navcfg-row">' +
                   '<span class="set-pos">' + (i + 1) + '</span>' +
                   '<span class="navcfg-ico">' + VexNav.iconSvg(m) + '</span>' +
                   '<span class="navcfg-name">' + name + '</span>' +
                   '<span class="navcfg-btns">' + up + down + '</span>' +
               '</div>';
    }).join('');
}

function move(href, dir) {
    const i = SET.order.indexOf(href);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= SET.order.length) return;
    SET.order.splice(j, 0, SET.order.splice(i, 1)[0]);
    renderDesktopList();
}

async function saveDesktop(btn) {
    btn.disabled = true;
    try {
        await apiCall('/api/ui/prefs', { method: 'PUT',
            body: { prefs: { [VexNav.DESKTOP_PREF]: SET.order } } });
        VexNav.applyDesktopOrder(SET.order);
        if (window.Toast) Toast.success('Reihenfolge gespeichert');
    } catch (e) {
        if (window.Toast) Toast.error(e.message || String(e));
    } finally { btn.disabled = false; }
}

async function resetDesktop(btn) {
    btn.disabled = true;
    try {
        await apiCall('/api/ui/prefs/' + VexNav.DESKTOP_PREF, { method: 'DELETE' });
        SET.order = SET.modules.map(m => m.href);
        VexNav.applyDesktopOrder(SET.order);
        renderDesktopList();
        if (window.Toast) Toast.success('Standardreihenfolge wiederhergestellt');
    } catch (e) {
        if (window.Toast) Toast.error(e.message || String(e));
    } finally { btn.disabled = false; }
}

(async function init() {
    if (!isLoggedIn()) { location.href = '/private/login.html'; return; }
    try {
        const me = await fetchMe(true);
        document.getElementById('userLabel').textContent = '👤 ' + me.username;
    } catch (e) { /* api.js schickt bei 401 selbst zum Login */ }
    document.getElementById('logoutBtn').onclick = () => { clearToken(); location.reload(); };
    document.body.style.visibility = 'visible';

    await navReady();
    SET.modules = window.VexNav ? VexNav.modules() : [];
    // Gespeicherte Wunschreihenfolge, um fehlende Module ergaenzt.
    const wish = (window.VexNav && VexNav.readDesktopOrder()) || [];
    const known = new Set(SET.modules.map(m => m.href));
    SET.order = wish.filter(h => known.has(h));
    SET.modules.forEach(m => { if (SET.order.indexOf(m.href) === -1) SET.order.push(m.href); });
    renderDesktopList();

    document.getElementById('deskList').addEventListener('click', (e) => {
        const btn = e.target.closest('button');
        if (!btn) return;
        move(btn.dataset.href, btn.dataset.act === 'up' ? -1 : 1);
    });
    document.getElementById('deskSave').onclick = (e) => saveDesktop(e.currentTarget);
    document.getElementById('deskReset').onclick = (e) => resetDesktop(e.currentTarget);
    document.getElementById('tabCfg').onclick = () => VexNav.openTabBarSettings();
    document.getElementById('expBtn').onclick = () => exportAll();
})();
