/* einstellungen.js — v1.59.0
 * Die Einstellungsseite. Sie definiert nichts selbst: Modul-Liste, Icons und
 * der Tab-Leisten-Dialog kommen aus nav-switcher.js (window.VexNav), damit es
 * keine zweite Liste gibt, die mit der Zeit auseinanderlaeuft.
 *
 * Gespeichert wird ueber /api/ui/prefs. Eine kuenftige Einstellung braucht
 * dort einen Pruefer und hier eine Karte — sonst nichts.
 */

const SET = { modules: [], order: [], hidden: new Set(), alle: [], aus: new Set() };

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

/* Welche Module dieses Konto ueberhaupt benutzt. Anders als das Auge in der
   Karte darunter nimmt der Schalter ein Modul aus der GANZEN Navigation --
   Leiste, Punkte-Menue, Tab-Leiste und Dashboard. Gespeichert wird sofort:
   ein Speichern-Knopf fuer einen einzelnen Schalter ist ein Klick, der nur
   fragt, ob man es wirklich gemeint hat. */
/* v2.30.0: Eine Zeile je Modul, die ganze Zeile ist der Schalter. Bis
   dahin trug jede Zeile einen roten Knopf „Benutze ich“ -- dreizehnmal
   dieselbe laute Fläche, und ob sie den Zustand meinte oder das, was beim
   Tippen passiert, sah man ihr nicht an. */
function renderModuleList() {
    const box = document.getElementById('modList');
    if (!box) return;
    box.innerHTML = SET.alle.map(m => {
        const an = !SET.aus.has(m.href);
        const name = m.label.split(' ').slice(1).join(' ');
        const ton = m.tone ? ' style="--tone:var(' + m.tone + ')"' : '';
        return '<button type="button" class="v-schalt-zeile set-mod" role="switch"' +
                   ' aria-checked="' + an + '" data-href="' + m.href + '">' +
                   '<span class="set-mod-ico"' + ton + '>' + VexNav.iconSvg(m) + '</span>' +
                   '<span class="v-schalt-text"><span class="v-schalt-name">' + escHtml(name) + '</span>' +
                       '<span class="v-schalt-sub">' + escHtml(an ? (m.sub || '') : 'Ausgeschaltet') + '</span></span>' +
                   '<span class="v-schalter" aria-hidden="true"></span>' +
               '</button>';
    }).join('');
}

async function toggleModule(href, btn) {
    const warAus = SET.aus.has(href);
    warAus ? SET.aus.delete(href) : SET.aus.add(href);
    // Der Schalter springt sofort um; das Neuladen danach zieht Leiste und
    // Menüs nach.
    btn.setAttribute('aria-checked', String(warAus));
    btn.disabled = true;
    try {
        await VexPrefs.set(VexNav.MODULE_OFF_PREF, [...SET.aus]);
        // Neu laden statt an vier Stellen nachzuzeichnen: Leiste, Menue,
        // Tab-Leiste und Dashboard lesen die Liste beim Aufbau. Ein halb
        // nachgezogener Zustand waere schlechter als ein kurzer Moment.
        location.reload();
    } catch (e) {
        warAus ? SET.aus.add(href) : SET.aus.delete(href);
        renderModuleList();
        if (window.Toast) Toast.error(e.message || String(e));
    }
}

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

/* ---------- Erinnerungen auf der Startseite (v2.42.0) ----------
 * Wann eine faellig ist, rechnet js/erinnerungen.js (VexErinnerung) --
 * dieselbe Rechnung wie auf der Startseite. Hier wird nur bearbeitet. */
const escE = (v) => String(v == null ? '' : v).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function renderErinnerungen() {
    const box = document.getElementById('erinListe');
    if (!box || !window.VexErinnerung) return;
    const E = VexErinnerung;
    const liste = E.liste();
    const module = window.VexNav ? VexNav.modules() : [];
    box.innerHTML = liste.length ? liste.map(e => {
        const m = module.find(x => x.href === e.href);
        const naechster = E.naechsterTermin(e);
        const status = E.faellig(e) ? 'fällig seit ' + E.datumLang(E.letzterTermin(e))
            : (naechster ? 'nächster Termin ' + E.datumLang(naechster) : '');
        return `<button type="button" class="rec-row" data-erin="${escE(e.id)}" style="--tone:var(${m && m.tone ? m.tone : '--accent'})">
            <span class="rec-mark">${m && window.VexNav ? VexNav.iconSvg(m) : ''}</span>
            <span class="rec-main"><span class="rec-title">${escE(e.text)}</span>
                <span class="rec-meta">${escE(E.beschreibung(e))}${status ? ' · ' + escE(status) : ''}</span></span>
            <span class="rec-go">${window.VexIkon ? VexIkon.svg('pfeil', 16) : ''}</span>
        </button>`;
    }).join('') : '<p class="set-hint">Keine Erinnerungen. Mit „Erinnerung hinzufügen“ kommt eine dazu.</p>';
}

/* Bearbeiten und Anlegen im selben Dialog; Löschen steht darin, nicht in
   der Liste (DESIGN: Löschen ist kein Knopf in einer Liste). */
function dlgErinnerung(e) {
    const E = VexErinnerung;
    const neu = !e;
    const w = e || { id: '', text: '', href: '', rhythmus: 'monat', tag: 1, monat: 1, erledigt: null };
    const module = (window.VexNav ? VexNav.modules() : []).filter(m => m.href !== '/');
    const opt = (wert, text, an) => `<option value="${escE(wert)}"${an ? ' selected' : ''}>${escE(text)}</option>`;
    const d = VexModal.open(neu ? 'Erinnerung hinzufügen' : 'Erinnerung bearbeiten', `
        <div class="set-form">
            <label class="set-feld"><span>Text</span>
                <input type="text" id="erinText" maxlength="80" value="${escE(w.text)}" placeholder="z. B. CS2-Bestand aktualisieren"></label>
            <label class="set-feld"><span>Modul</span>
                <select id="erinModul">${opt('', 'Keins', !w.href)}${module.map(m => opt(m.href, m.short || m.label.replace(/^\S+\s/, ''), m.href === w.href)).join('')}</select></label>
            <label class="set-feld"><span>Rhythmus</span>
                <select id="erinRhythmus">${opt('monat', 'Monatlich', w.rhythmus === 'monat')}${opt('quartal', 'Quartalsweise', w.rhythmus === 'quartal')}${opt('jahr', 'Jährlich', w.rhythmus === 'jahr')}</select></label>
            <div class="set-zeile">
                <label class="set-feld"><span>Am Tag</span>
                    <input type="number" id="erinTag" min="1" max="28" step="1" inputmode="numeric" value="${escE(w.tag)}"></label>
                <label class="set-feld" id="erinMonatFeld"><span id="erinMonatLbl">Monat</span>
                    <select id="erinMonat"></select></label>
            </div>
            <p class="set-hint" id="erinVorschau"></p>
            <p class="set-fehler" id="erinFehler" hidden></p>
        </div>
        <div class="modal-fuss">
            ${neu ? '' : '<button type="button" class="v-btn v-btn--danger" data-weg>Löschen</button>'}
            <button type="button" class="v-btn" data-zu>Abbrechen</button>
            <button type="button" class="v-btn v-btn--primary" data-ok>Speichern</button>
        </div>`, { voll: true });
    const $ = (id) => d.root.querySelector('#' + id);
    const entwurf = () => ({ id: w.id || ('e' + Date.now().toString(36)), text: $('erinText').value.trim(),
        href: $('erinModul').value, rhythmus: $('erinRhythmus').value,
        tag: Number($('erinTag').value), monat: Number($('erinMonat').value || 1), erledigt: w.erledigt || null });
    const monate = () => {
        const r = $('erinRhythmus').value;
        $('erinMonatFeld').hidden = r === 'monat';
        $('erinMonatLbl').textContent = r === 'quartal' ? 'In den Monaten' : 'Monat';
        const alt = Number($('erinMonat').value || w.monat || 1);
        $('erinMonat').innerHTML = r === 'quartal'
            ? [1, 2, 3].map(m => opt(m, [0, 1, 2, 3].map(q => E.MONATE[m - 1 + 3 * q].slice(0, 3)).join(' · '), m === Math.min(alt, 3))).join('')
            : E.MONATE.map((n, i) => opt(i + 1, n, i + 1 === alt)).join('');
        vorschau();
    };
    const vorschau = () => {
        const x = entwurf();
        const ok = x.tag >= 1 && x.tag <= 28;
        const naechster = ok ? E.naechsterTermin(x) : null;
        $('erinVorschau').textContent = ok ? E.beschreibung(x) + (naechster ? ' · nächster Termin ' + E.datumLang(naechster) : '') : 'Der Tag liegt zwischen 1 und 28.';
    };
    $('erinRhythmus').addEventListener('change', monate);
    ['erinTag', 'erinMonat'].forEach(id => $(id).addEventListener('input', vorschau));
    $('erinMonat').addEventListener('change', vorschau);
    monate();
    if (window.innerWidth > 720) $('erinText').focus();
    d.root.querySelector('[data-zu]').onclick = () => d.close();
    const fehler = (t) => { $('erinFehler').hidden = false; $('erinFehler').textContent = t; };
    d.root.querySelector('[data-ok]').onclick = async (ev) => {
        const x = entwurf();
        if (!x.text) return fehler('Bitte einen Text eintragen.');
        if (!(x.tag >= 1 && x.tag <= 28) || !Number.isInteger(x.tag)) return fehler('Der Tag liegt zwischen 1 und 28.');
        const liste = E.liste();
        const i = liste.findIndex(y => y.id === x.id);
        if (i >= 0) liste[i] = x; else liste.push(x);
        ev.currentTarget.classList.add('is-loading');
        try { await E.speichern(liste); d.close(); renderErinnerungen(); if (window.Toast) Toast.success('Gespeichert'); }
        catch (err) { ev.currentTarget.classList.remove('is-loading'); fehler(err.message || String(err)); }
    };
    const weg = d.root.querySelector('[data-weg]');
    if (weg) weg.onclick = async () => {
        if (!await askConfirm({ title: 'Erinnerung löschen?', text: '„' + w.text + '“ steht dann nicht mehr auf der Startseite.', ok: 'Löschen', danger: true })) return;
        try { await E.speichern(E.liste().filter(y => y.id !== w.id)); d.close(); renderErinnerungen(); }
        catch (err) { fehler(err.message || String(err)); }
    };
}

/* ---------- Sparziel: Hoechstzahl an Wochenzielen (v2.36.0) ----------
 * Der Server prueft sie beim Anlegen selbst; hier wird sie nur gesetzt. */
const MAX_WZ_PREF = 'ui_sparziel_max_wochenziele';

function renderMaxWochenziele() {
    const el = document.getElementById('maxWochenziele');
    if (el) el.value = String(VexPrefs.get(MAX_WZ_PREF, 0) || 0);
}

async function saveMaxWochenziele(btn) {
    const el = document.getElementById('maxWochenziele');
    const n = el.value === '' ? 0 : Number(el.value);
    if (!Number.isInteger(n) || n < 0 || n > 50) {
        if (window.Toast) Toast.error('Eine ganze Zahl von 0 bis 50');
        return;
    }
    btn.classList.add('is-loading');
    try {
        await VexPrefs.set(MAX_WZ_PREF, n);
        if (window.Toast) Toast.success(n ? 'Höchstens ' + n + ' Wochenziele' : 'Keine Grenze für Wochenziele');
    } catch (e) {
        renderMaxWochenziele();
        if (window.Toast) Toast.error(e.message || String(e));
    } finally {
        btn.classList.remove('is-loading');
    }
}

/* ---------- Export-Voreinstellung (v2.8.0) ----------
 * Der Export-Dialog machte jedes Mal mit „Einzeln“ auf, obwohl die Antwort
 * auf „wie haettest du es gern“ bei einem persoenlichen Tracker immer
 * dieselbe ist. Die Gruppen und die Stufen holt diese Karte vom Server
 * (/api/export/sections) und fuehrt sie NICHT als zweite Liste: ein neues
 * Modul steht hier von selbst drin. */
const EXPORT_PREF = 'ui_export';
const EXP = { groups: [], kannAgg: new Set(), aggregates: [],
              aus: new Set(), wert: { aggregate: {}, compact_before: null, off: [] } };

function renderExportCfg() {
    const box = document.getElementById('expCfg');
    if (!box) return;
    if (!EXP.groups.length) { box.innerHTML = ''; return; }
    const agg = EXP.wert.aggregate || {};
    const opt = (gewaehlt) => EXP.aggregates.map(a =>
        '<option value="' + a.key + '"' + (a.key === gewaehlt ? ' selected' : '') +
        '>' + a.label + '</option>').join('');
    box.innerHTML = EXP.groups.map(g => {
        const aus = EXP.aus.has(g.key);
        // Das Auswahlfeld steht nur da, wo sich überhaupt etwas zusammenfassen
        // lässt: Notizen haben kein Datum, ein Feld daneben wäre ein
        // Bedienelement, das nichts tut. Ist das Modul abgeschaltet, tritt es
        // zurück statt zu verschwinden — sonst springt die Zeile bei jedem
        // Schalter.
        const stufe = EXP.kannAgg.has(g.key)
            ? '<select data-gruppe="' + g.key + '"' + (aus ? ' disabled' : '') +
              ' aria-label="Zusammenfassung für ' + g.label + '">' +
              opt(agg[g.key] || 'none') + '</select>'
            : '';
        // Reihenfolge: Name, Stufe, Schalter. Der Schalter steht damit in
        // JEDER Zeile am selben Rand -- auch dort, wo kein Auswahlfeld
        // davorsteht, sonst rutschte er in dessen Spalte und die Karte
        // haette zwei Fluchtlinien.
        return '<div class="set-exp-row' + (aus ? ' is-schlaeft' : '') + '">' +
                   '<span class="set-exp-name">' + g.label + '</span>' +
                   stufe +
                   '<button type="button" class="v-schalt-zeile" role="switch"' +
                       ' aria-checked="' + !aus + '" data-aus="' + g.key + '"' +
                       ' aria-label="' + g.label + ' exportieren">' +
                       '<span class="v-schalter" aria-hidden="true"></span></button>' +
               '</div>';
    }).join('')
        + '<div class="set-exp-row set-exp-grenze">' +
              '<span class="set-exp-name">Alles davor monatlich zusammenfassen' +
                  '<span class="set-modsub">Leer lassen heißt: keine Grenze, ' +
                  'überall gilt die Stufe von oben.</span></span>' +
              '<input type="date" id="expGrenze" aria-label="Verdichten vor" value="' +
                  (EXP.wert.compact_before || '') + '">' +
          '</div>';
}

/* Der Schalter zeichnet nur um, gespeichert wird die Karte mit ihrem Knopf.
   Bei den ruhenden Modulen greift ein Schalter sofort; hier steht er neben
   Auswahlfeldern, die auf das Speichern warten, und zwei Verhaltensweisen in
   einer Karte kann man nicht auseinanderhalten. */
function toggleExportGruppe(key) {
    if (EXP.aus.has(key)) EXP.aus.delete(key); else EXP.aus.add(key);
    // Was in den Feldern steht, überlebt das Neuzeichnen.
    EXP.wert.aggregate = aktuelleStufen();
    const grenze = document.getElementById('expGrenze');
    if (grenze) EXP.wert.compact_before = grenze.value || null;
    renderExportCfg();
}

function aktuelleStufen() {
    const box = document.getElementById('expCfg');
    const agg = {};
    if (box) box.querySelectorAll('[data-gruppe]').forEach(s => {
        if (s.value !== 'none') agg[s.dataset.gruppe] = s.value;
    });
    return agg;
}

async function saveExportCfg(btn) {
    const box = document.getElementById('expCfg');
    if (!box) return;
    const agg = aktuelleStufen();
    const grenze = (document.getElementById('expGrenze') || {}).value || null;
    const aus = [...EXP.aus];
    // Ein Export ohne ein einziges Modul wäre eine leere Datei. Der Server
    // fängt das ebenfalls ab und nimmt dann wieder alles — hier steht es,
    // damit die Antwort nicht „gespeichert“ lautet und trotzdem etwas
    // anderes gilt.
    if (aus.length && aus.length >= EXP.groups.length) {
        if (window.Toast) Toast.error('Mindestens ein Modul muss dabei sein.');
        return;
    }
    if (btn) btn.classList.add('is-loading');
    try {
        await VexPrefs.set(EXPORT_PREF,
            { aggregate: agg, compact_before: grenze, off: aus });
        EXP.wert = { aggregate: agg, compact_before: grenze, off: aus };
        if (window.Toast) Toast.success('Voreinstellung gespeichert');
    } catch (e) {
        // Der Server hat es nicht -- die Anzeige muss zurueck auf den Stand,
        // der wirklich gespeichert ist.
        renderExportCfg();
        if (window.Toast) Toast.error(e.message || String(e));
    } finally {
        if (btn) btn.classList.remove('is-loading');
    }
}

async function ladeExportCfg() {
    try {
        const meta = await apiCall('/api/export/sections');
        // Nur Module, in denen sich ueberhaupt etwas zusammenfassen laesst.
        // Notizen haben kein Datum -- ein Auswahlfeld daneben waere ein
        // Bedienelement, das nichts tut.
        // Alle Module stehen zur Wahl — abschalten muss man auch das
        // können, was sich nicht zusammenfassen lässt. Nur das
        // Auswahlfeld daneben hängt daran.
        EXP.groups = (meta.groups || []).filter(g =>
            (meta.sections || []).some(s => s.group === g.key));
        EXP.kannAgg = new Set((meta.sections || [])
            .filter(s => s.aggregatable).map(s => s.group));
        EXP.aggregates = meta.aggregates || [];
    } catch (e) {
        EXP.groups = [];
    }
    // Vom Server holen, nicht aus dem Cache: `navReady()` steigt früh aus,
    // sobald die Leiste steht, und dann ist der localStorage hier noch der
    // Stand des letzten Besuchs. Die Karte zeigte dann leere Auswahlfelder,
    // obwohl am Konto etwas gespeichert war — und wer daraufhin speichert,
    // überschreibt seine eigene Einstellung mit den Standardwerten.
    try { await VexPrefs.load(); } catch (e) { /* offline: Cache gilt */ }
    const gespeichert = VexPrefs.get(EXPORT_PREF, null) || {};
    EXP.wert = { aggregate: gespeichert.aggregate || {},
                 compact_before: gespeichert.compact_before || null,
                 off: gespeichert.off || [] };
    EXP.aus = new Set(EXP.wert.off);
    renderExportCfg();
}

(async function init() {
    if (!isLoggedIn()) { location.href = '/private/login.html'; return; }
    try {
        const me = await fetchMe(true);
        document.getElementById('userLabel').textContent = me.username;
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

    // Die Modul-Karte listet auch die ruhenden -- sonst gaebe es keinen Weg,
    // sie wieder einzuschalten. Das Dashboard steht nicht zur Wahl.
    SET.alle = ((window.VexNav && VexNav.allModules && VexNav.allModules())
                || SET.modules).filter(m => m.href !== '/');
    // Der Blog steht zweimal in der Registry: öffentlich und als Editor für
    // den Admin. Hier ist es EIN Modul -- sonst stand „Blog“ zweimal da.
    SET.alle = SET.alle.filter(m => !(m.hideForAdmin
        && SET.alle.some(o => o !== m && o.admin && o.icon === m.icon)));
    SET.aus = new Set((window.VexNav && VexNav.readOff && VexNav.readOff()) || []);
    renderModuleList();
    const modBox = document.getElementById('modList');
    if (modBox) modBox.addEventListener('click', (e) => {
        const btn = e.target.closest('button');
        if (btn && !btn.disabled) toggleModule(btn.dataset.href, btn);
    });

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
    renderMaxWochenziele();
    document.getElementById('maxWochenzieleSave').onclick = (e) => saveMaxWochenziele(e.currentTarget);
    renderErinnerungen();
    document.addEventListener('vexnav:ready', renderErinnerungen);
    document.getElementById('erinListe').addEventListener('click', (e) => {
        const b = e.target.closest('[data-erin]');
        if (b) dlgErinnerung(VexErinnerung.liste().find(x => x.id === b.dataset.erin));
    });
    document.getElementById('erinNeu').onclick = () => dlgErinnerung(null);
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
    document.getElementById('expSave').onclick = (e) => saveExportCfg(e.currentTarget);
    document.getElementById('expCfg').addEventListener('click', (e) => {
        const b = e.target.closest('[data-aus]');
        if (b) toggleExportGruppe(b.dataset.aus);
    });
    ladeExportCfg();
})();
