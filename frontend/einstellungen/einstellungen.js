/* einstellungen.js — v1.59.0
 * Die Einstellungsseite. Sie definiert nichts selbst: Modul-Liste, Icons und
 * der Tab-Leisten-Dialog kommen aus nav-switcher.js (window.VexNav), damit es
 * keine zweite Liste gibt, die mit der Zeit auseinanderlaeuft.
 *
 * Gespeichert wird ueber /api/ui/prefs. Eine kuenftige Einstellung braucht
 * dort einen Pruefer und hier eine Karte — sonst nichts.
 */

const SET = { modules: [], order: [], hidden: new Set() };

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

/* Auge offen / durchgestrichen -- der Zustand steht im Icon, nicht in einem
 * Wort, damit die Zeile schmal bleibt. */
const EYE = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" ' +
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/>' +
    '<circle cx="12" cy="12" r="3"/></svg>';
const EYE_OFF = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" ' +
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M4 4l16 16"/><path d="M9.9 5.9A9.5 9.5 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-3 3.8"/>' +
    '<path d="M6.5 8.2A17 17 0 0 0 2.5 12S6 18.5 12 18.5c1 0 1.9-.2 2.7-.5"/>' +
    '<path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>';

function renderDesktopList() {
    const box = document.getElementById('deskList');
    const byHref = new Map(SET.modules.map(m => [m.href, m]));
    // Nur sichtbare Module bekommen eine Positionsnummer -- eine "3." neben
    // einem ausgeblendeten Eintrag waere eine Reihenfolge, die niemand sieht.
    let pos = 0;
    box.innerHTML = SET.order.map((href, i) => {
        const m = byHref.get(href);
        if (!m) return '';
        const off = SET.hidden.has(href);
        if (!off) pos++;
        const name = m.label.split(' ').slice(1).join(' ');
        const up = '<button type="button" class="navcfg-mini" data-act="up" data-href="' + href + '"' +
            (i === 0 ? ' disabled' : '') + ' aria-label="Nach vorn">↑</button>';
        const down = '<button type="button" class="navcfg-mini" data-act="down" data-href="' + href + '"' +
            (i === SET.order.length - 1 ? ' disabled' : '') + ' aria-label="Nach hinten">↓</button>';
        const eye = '<button type="button" class="navcfg-mini set-eye' + (off ? ' is-off' : '') +
            '" data-act="toggle" data-href="' + href + '" aria-pressed="' + (off ? 'true' : 'false') +
            '" title="' + (off ? 'In der Leiste zeigen' : 'Aus der Leiste nehmen') +
            '" aria-label="' + (off ? 'In der Leiste zeigen' : 'Aus der Leiste nehmen') + '">' +
            (off ? EYE_OFF : EYE) + '</button>';
        return '<div class="navcfg-row' + (off ? ' is-off' : '') + '">' +
                   '<span class="set-pos">' + (off ? '–' : pos) + '</span>' +
                   '<span class="navcfg-ico">' + VexNav.iconSvg(m) + '</span>' +
                   '<span class="navcfg-name">' + name + '</span>' +
                   '<span class="navcfg-btns">' + up + down + eye + '</span>' +
               '</div>';
    }).join('');
}

function toggleHidden(href) {
    SET.hidden.has(href) ? SET.hidden.delete(href) : SET.hidden.add(href);
    renderDesktopList();
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
        await VexPrefs.set(VexNav.DESKTOP_PREF, SET.order);
        await VexPrefs.set(VexNav.HIDDEN_PREF, [...SET.hidden]);
        VexNav.redrawDesktop();
        if (window.Toast) Toast.success('Leiste gespeichert');
    } catch (e) {
        if (window.Toast) Toast.error(e.message || String(e));
    } finally { btn.disabled = false; }
}

async function resetDesktop(btn) {
    btn.disabled = true;
    try {
        await VexPrefs.reset(VexNav.DESKTOP_PREF);
        await VexPrefs.reset(VexNav.HIDDEN_PREF);
        SET.order = SET.modules.map(m => m.href);
        SET.hidden = new Set();
        VexNav.redrawDesktop();
        renderDesktopList();
        if (window.Toast) Toast.success('Standard wiederhergestellt');
    } catch (e) {
        if (window.Toast) Toast.error(e.message || String(e));
    } finally { btn.disabled = false; }
}

/* Standard-Zeitraum: dieselben Presets wie der Filter-Knopf, damit hier
 * nichts steht, was es dort nicht gibt. */
const RANGE_PREF = 'ui_default_range';

function renderRangeList() {
    const box = document.getElementById('rangeList');
    if (!box) return;
    const cur = VexPrefs.get(RANGE_PREF, VexRange.DEFAULT_PRESET);
    box.innerHTML = VexRange.PRESETS.map(p =>
        '<button type="button" class="rf-opt' + (p.key === cur ? ' is-active' : '') +
        '" data-preset="' + p.key + '">' + p.label +
        '<span class="rf-check" aria-hidden="true">✓</span></button>').join('');
}

const escHtml = (v) => String(v == null ? '' : v)
    .replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/* Verlaufs-Presets — v1.74.0
 *
 * Slots und Presets kommen aus js/api.js, die Farben aus css/style.css. Hier
 * steht nur, wie man sie anklickt. Angewendet wird sofort: VexPrefs schreibt
 * in den Zwischenspeicher, und daran haengt das Setzen der Attribute am
 * <html> — die Seite faerbt sich also noch waehrend man waehlt um, ohne dass
 * diese Datei etwas davon wissen muss.
 */
function renderGradients() {
    const box = document.getElementById('gradList');
    if (!box) return;
    box.innerHTML = GRADIENT_SLOTS.map(slot => {
        const backdrop = slot.pref === 'ui_grad_backdrop';
        const figure = slot.pref === 'ui_grad_figure';
        const presets = backdrop ? BACKDROP_PRESETS
                      : (figure ? FIGURE_PRESETS : GRADIENT_PRESETS);
        const cur = VexPrefs.get(slot.pref, slot.fallback);
        return '<div class="grad-slot">' +
            '<div class="grad-slot-head">' + escHtml(slot.label) + '</div>' +
            '<p class="grad-slot-hint">' + escHtml(slot.hint) + '</p>' +
            '<div class="grad-opts">' + presets.map(pre =>
                '<button type="button" class="grad-opt' +
                    (backdrop ? ' is-backdrop' : '') + (figure ? ' is-figure' : '') +
                    (pre.key === cur ? ' is-active' : '') +
                '" data-slot="' + slot.pref + '" data-grad="' + pre.key + '">' +
                    '<i aria-hidden="true"></i>' +
                    '<span>' + escHtml(pre.label) + '</span>' +
                '</button>').join('') +
            '</div></div>';
    }).join('');
}

function renderThemes() {
    const box = document.getElementById('themeList');
    if (!box) return;
    const cur = VexTheme.current();
    const list = VexTheme.list();
    box.innerHTML = list.map(t =>
        '<button type="button" class="grad-opt' + (t.key === cur ? ' is-active' : '') +
            '" data-theme="' + escHtml(t.key) + '"' +
            ' data-grad="' + escHtml(t.slots.ui_grad_action) + '">' +
            '<i aria-hidden="true"></i><span></span>' +
            (t.own ? '<em class="grad-own" title="Eigenes Thema entfernen" ' +
                     'data-drop="' + escHtml(t.key) + '">✕</em>' : '') +
        '</button>').join('') +
        (cur ? '' : '<span class="grad-eigen">Eigen</span>');
    // Namen als Text, nicht als Markup -- eigene Themen benennt der Nutzer.
    box.querySelectorAll('.grad-opt span').forEach((el, i) => {
        if (list[i]) el.textContent = list[i].label;
    });
}

async function applyTheme(key) {
    try {
        await VexTheme.apply(key);
        renderThemes();
        renderGradients();
    } catch (e) {
        if (window.Toast) Toast.error(e.message || String(e));
    }
}

async function saveOwnTheme() {
    const input = document.getElementById('themeName');
    try {
        await VexTheme.saveOwn(input.value);
        input.value = '';
        renderThemes();
        if (window.Toast) Toast.success('Thema gesichert');
    } catch (e) {
        if (window.Toast) Toast.error(e.message || String(e));
    }
}

async function dropOwnTheme(key) {
    const ok = await askConfirm({
        title: 'Thema entfernen?',
        text: 'Die Einstellung selbst bleibt, nur der gespeicherte Name verschwindet.',
        ok: 'Entfernen', danger: true,
    });
    if (!ok) return;
    try {
        await VexTheme.removeOwn(key);
        renderThemes();
    } catch (e) {
        if (window.Toast) Toast.error(e.message || String(e));
    }
}

async function saveGradient(pref, value) {
    try {
        await VexPrefs.set(pref, value);
        renderGradients();
        renderThemes();
        if (window.Toast) Toast.success('Gespeichert');
    } catch (e) {
        // Fehlgeschlagen heisst: der Server hat es nicht. Die Anzeige muss
        // zurueck auf den Stand, der wirklich gespeichert ist.
        renderGradients();
        if (window.Toast) Toast.error(e.message || String(e));
    }
}

async function saveRange(preset) {
    try {
        await VexPrefs.set(RANGE_PREF, preset);
        renderRangeList();
        if (window.Toast) Toast.success('Standard-Zeitraum gespeichert');
    } catch (e) {
        if (window.Toast) Toast.error(e.message || String(e));
    }
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
    SET.hidden = new Set(((window.VexNav && VexNav.readHidden()) || []).filter(h => known.has(h)));
    renderDesktopList();

    document.getElementById('deskList').addEventListener('click', (e) => {
        const btn = e.target.closest('button');
        if (!btn || btn.disabled) return;
        if (btn.dataset.act === 'toggle') return toggleHidden(btn.dataset.href);
        move(btn.dataset.href, btn.dataset.act === 'up' ? -1 : 1);
    });
    document.getElementById('deskSave').onclick = (e) => saveDesktop(e.currentTarget);
    document.getElementById('deskReset').onclick = (e) => resetDesktop(e.currentTarget);
    renderRangeList();
    document.getElementById('rangeList').addEventListener('click', (e) => {
        const b = e.target.closest('.rf-opt');
        if (b) saveRange(b.dataset.preset);
    });
    renderGradients();
    renderThemes();
    document.getElementById('gradList').addEventListener('click', (e) => {
        const b = e.target.closest('.grad-opt');
        if (b) saveGradient(b.dataset.slot, b.dataset.grad);
    });
    document.getElementById('themeList').addEventListener('click', (e) => {
        const drop = e.target.closest('[data-drop]');
        if (drop) { e.stopPropagation(); return dropOwnTheme(drop.dataset.drop); }
        const b = e.target.closest('.grad-opt');
        if (b) applyTheme(b.dataset.theme);
    });
    document.getElementById('themeSave').onclick = () => saveOwnTheme();
    document.getElementById('tabCfg').onclick = () => VexNav.openTabBarSettings();
    document.getElementById('expBtn').onclick = () => exportAll();
})();
