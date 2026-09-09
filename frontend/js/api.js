const API_BASE = 'https://vexbob-production.up.railway.app';

function getToken() { return localStorage.getItem('token'); }
function setToken(token) { localStorage.setItem('token', token); }
function clearToken() { localStorage.removeItem('token'); localStorage.removeItem('me'); }
function isLoggedIn() { return !!getToken(); }

async function apiCall(path, options = {}) {
    const token = getToken();
    const headers = { ...(options.headers || {}) };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    // v1.33.0: Content-Type + Body-Serialisierung intelligent ableiten.
    // Alt: Body wurde immer als form-urlencoded verschickt, egal was drinsteht
    // -- neue Aufrufe mit Plain-Objekten landeten still in 422-Fehlern.
    // Neu:
    //   - FormData / Blob / URLSearchParams / string -> unveraendert lassen
    //     (Browser setzt Content-Type mit Boundary etc. selbst korrekt),
    //   - Plain-Object -> JSON.stringify + application/json,
    //   - Content-Type vom Aufrufer wird IMMER respektiert.
    let body = options.body;
    if (body != null && !headers['Content-Type']) {
        const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
        const isBlob = typeof Blob !== 'undefined' && body instanceof Blob;
        const isUsp = typeof URLSearchParams !== 'undefined' && body instanceof URLSearchParams;
        const isString = typeof body === 'string';
        if (isFormData || isBlob) {
            // Browser setzt Content-Type selbst -> nichts tun.
        } else if (isUsp) {
            headers['Content-Type'] = 'application/x-www-form-urlencoded';
        } else if (isString) {
            headers['Content-Type'] = 'application/x-www-form-urlencoded';
        } else if (typeof body === 'object') {
            body = JSON.stringify(body);
            headers['Content-Type'] = 'application/json';
        }
    }

    let res;
    try {
        res = await fetch(`${API_BASE}${path}`, { ...options, body, headers });
    } catch (e) {
        throw new Error('Netzwerkfehler');
    }
    if (res.status === 401) {
        clearToken();
        if (!location.pathname.endsWith('/login.html')) {
            location.href = '/private/login.html';
        }
        throw new Error('Nicht eingeloggt');
    }
    if (options.raw) return res;
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
    return data;
}

async function login(username, password) {
    const body = new URLSearchParams({ username, password });
    const data = await apiCall('/token', { method: 'POST', body });
    setToken(data.access_token);
    return data;
}

// Cached user info (id, username, is_admin)
async function fetchMe(force = false) {
    if (!force) {
        const cached = localStorage.getItem('me');
        if (cached) {
            try { return JSON.parse(cached); } catch (e) {}
        }
    }
    const me = await apiCall('/api/me');
    localStorage.setItem('me', JSON.stringify(me));
    return me;
}

function isAdmin() {
    try {
        const me = JSON.parse(localStorage.getItem('me') || 'null');
        return !!(me && me.is_admin);
    } catch (e) { return false; }
}

/* ---------- Dialoge ----------
 * Native confirm()/prompt()/alert() sind aus der App verbannt: sie brechen
 * optisch aus und sehen auf jedem Geraet anders aus. Die gestalteten
 * Gegenstuecke stehen in ui.js, das nav-switcher.js asynchron nachlaedt --
 * bis dahin faellt es hier auf das native Fenster zurueck, damit ein Klick
 * nie ins Leere laeuft. */
async function askConfirm(opts) {
    opts = opts || {};
    if (window.Confirm) return await Confirm.ask(opts);
    return confirm([opts.title, opts.text].filter(Boolean).join('\n\n'));
}
async function askPrompt(opts) {
    opts = opts || {};
    if (window.Prompt) return await Prompt.ask(opts);
    const v = prompt([opts.title, opts.text].filter(Boolean).join('\n\n'), opts.value || '');
    return v && v.trim() ? v.trim() : null;
}
async function askAlert(opts) {
    opts = opts || {};
    if (window.Confirm) return await Confirm.alert(opts);
    alert([opts.title, opts.text].filter(Boolean).join('\n\n'));
}

// Theme — seit v1.55.0 gibt es nur noch das dunkle. Das Attribut bleibt
// trotzdem gesetzt: rund 50 CSS-Selektoren und die Diagramm-Farbwahl in den
// Modulen fragen es ab. Es zu entfernen waere ein Umbau ohne Gewinn.
document.documentElement.setAttribute('data-theme', 'dark');
try { localStorage.removeItem('theme'); } catch (e) {}

/* Verlaufs-Presets — v1.74.0
 *
 * Verläufe gibt es an genau vier Stellen (docs/DESIGN.md 3); drei davon sind
 * einstellbar. Hier steht bewusst KEIN einziger Farbwert: die Verläufe sind
 * Tokens in css/style.css, und diese Datei setzt nur ein Attribut am <html> —
 * dieselbe Mechanik wie beim Theme.
 *
 * Gesetzt wird sofort aus dem localStorage-Zwischenspeicher, noch bevor die
 * Seite gezeichnet ist. Ohne das läge beim Laden für einen Moment der
 * Standardverlauf auf den Knöpfen und spränge dann um.
 */
const GRADIENT_SLOTS = [
    { pref: 'ui_grad_action',   attr: 'data-grad-action',   fallback: 'sonnenaufgang',
      label: 'Primäre Aktion',
      hint: 'Knöpfe, die den Schritt auslösen, um den es auf der Seite geht — Check-in, Speichern, Exportieren.' },
    { pref: 'ui_grad_progress', attr: 'data-grad-progress', fallback: 'sonnenaufgang',
      label: 'Fortschrittsbalken',
      hint: 'Der Balken unter einem Sparziel, in der Export-Vorschau und beim erneuten Auswerten von Bons.' },
    { pref: 'ui_grad_figure', attr: 'data-grad-figure', fallback: 'modulton',
      label: 'Zahlen und Diagramme',
      hint: 'Der Füllkreis am Sparziel, die Verlaufskurve und der gesparte Betrag. „Modulton“ lässt jedem Modul seine eigene Farbe — Sparziel grün, Ausgaben türkis.' },
    { pref: 'ui_grad_backdrop', attr: 'data-grad-backdrop', fallback: 'standard',
      label: 'Hintergrundlichter',
      hint: 'Die drei sehr leisen Lichter hinter allem. Sie tragen nie Text und dürfen deshalb frei gewählt sein.' },
];

// Die vierte Stelle kennt zusaetzlich "Modulton": jedes Modul behaelt dann
// seine Identitaetsfarbe. Das ist der Standard -- ein Thema darf sie
// ueberschreiben, aber nur, wenn man es ausdruecklich will.
const FIGURE_PRESETS = [{ key: 'modulton', label: 'Modulton' }].concat(
    [{ key: 'sonnenaufgang', label: 'Sonnenaufgang' },
     { key: 'nordlicht', label: 'Nordlicht' },
     { key: 'waldlauf', label: 'Waldlauf' },
     { key: 'abendrot', label: 'Abendrot' },
     { key: 'amethyst', label: 'Amethyst' },
     { key: 'schlicht', label: 'Schlicht' }]);

// Nur Schlüssel und Beschriftung — wie ein Preset aussieht, weiß allein die CSS.
const GRADIENT_PRESETS = [
    { key: 'sonnenaufgang', label: 'Sonnenaufgang' },
    { key: 'nordlicht',     label: 'Nordlicht' },
    { key: 'waldlauf',      label: 'Waldlauf' },
    { key: 'abendrot',      label: 'Abendrot' },
    { key: 'amethyst',      label: 'Amethyst' },
    { key: 'schlicht',      label: 'Schlicht' },
];
const BACKDROP_PRESETS = [
    { key: 'standard',  label: 'Standard' },
    { key: 'nordlicht', label: 'Nordlicht' },
    { key: 'warm',      label: 'Warm' },
    { key: 'aus',       label: 'Aus' },
];

/* Themes — v1.75.0
 *
 * Ein Thema ist nichts als eine benannte Kombination der drei Plätze oben.
 * Es gibt also keinen zweiten Speicher und keine zweite Wahrheit: wer ein
 * Thema wählt, setzt damit die drei Einstellungen, und wer eine davon
 * einzeln ändert, ist auf „Eigen" — ohne dass irgendwo etwas nachgeführt
 * werden müsste.
 *
 * Eigene Themen bestehen aus denselben Presets; frei gewählte Farben gibt es
 * bewusst nicht, sonst ließe sich der Kontrast der Beschriftung nicht mehr
 * zusichern.
 */
const THEMES = [
    { key: 'sonnenaufgang', label: 'Sonnenaufgang',
      slots: { ui_grad_action: 'sonnenaufgang', ui_grad_progress: 'sonnenaufgang',
               ui_grad_figure: 'modulton', ui_grad_backdrop: 'standard' } },
    { key: 'nordlicht', label: 'Nordlicht',
      slots: { ui_grad_action: 'nordlicht', ui_grad_progress: 'nordlicht',
               ui_grad_figure: 'nordlicht', ui_grad_backdrop: 'nordlicht' } },
    { key: 'waldlauf', label: 'Waldlauf',
      slots: { ui_grad_action: 'waldlauf', ui_grad_progress: 'waldlauf',
               ui_grad_figure: 'waldlauf', ui_grad_backdrop: 'nordlicht' } },
    { key: 'abendrot', label: 'Abendrot',
      slots: { ui_grad_action: 'abendrot', ui_grad_progress: 'abendrot',
               ui_grad_figure: 'abendrot', ui_grad_backdrop: 'warm' } },
    { key: 'amethyst', label: 'Amethyst',
      slots: { ui_grad_action: 'amethyst', ui_grad_progress: 'amethyst',
               ui_grad_figure: 'amethyst', ui_grad_backdrop: 'standard' } },
    { key: 'schlicht', label: 'Schlicht',
      slots: { ui_grad_action: 'schlicht', ui_grad_progress: 'schlicht',
               ui_grad_figure: 'modulton', ui_grad_backdrop: 'aus' } },
];
const THEMES_PREF = 'ui_themes';
const THEMES_MAX = 12;

const VexTheme = {
    // Eingebaute zuerst, danach die eigenen. `own` unterscheidet sie, damit
    // die Oberflaeche nur die eigenen zum Loeschen anbietet.
    list() {
        const own = VexPrefs.get(THEMES_PREF, []) || [];
        return THEMES.map(t => Object.assign({ own: false }, t))
            .concat(own.map((t, i) => ({
                key: 'eigen-' + i, label: t.name, own: true,
                slots: { ui_grad_action: t.action, ui_grad_progress: t.progress,
                         ui_grad_figure: t.figure || 'modulton',
                         ui_grad_backdrop: t.backdrop },
            })));
    },
    // Welches Thema gerade gilt -- oder null, wenn die drei Einstellungen zu
    // keinem passen. Das ist der Zustand "Eigen", und er braucht keinen
    // eigenen Speicher.
    current() {
        const found = VexTheme.list().find(t =>
            GRADIENT_SLOTS.every(s => VexPrefs.get(s.pref, s.fallback) === t.slots[s.pref]));
        return found ? found.key : null;
    },
    async apply(key) {
        const t = VexTheme.list().find(x => x.key === key);
        if (!t) return;
        await VexPrefs.setMany(t.slots);
    },
    // Der aktuelle Stand als eigenes Thema. Namen sind die Identitaet --
    // derselbe Name ersetzt, statt ein zweites gleichnamiges anzulegen.
    async saveOwn(name) {
        const clean = String(name || '').trim().slice(0, 40);
        if (!clean) throw new Error('Das Thema braucht einen Namen');
        const own = (VexPrefs.get(THEMES_PREF, []) || []).slice();
        const entry = {
            name: clean,
            action: VexPrefs.get('ui_grad_action', 'sonnenaufgang'),
            progress: VexPrefs.get('ui_grad_progress', 'sonnenaufgang'),
            figure: VexPrefs.get('ui_grad_figure', 'modulton'),
            backdrop: VexPrefs.get('ui_grad_backdrop', 'standard'),
        };
        const at = own.findIndex(t => t.name === clean);
        if (at >= 0) own[at] = entry;
        else {
            if (own.length >= THEMES_MAX) throw new Error('Mehr als ' + THEMES_MAX + ' eigene Themen gehen nicht');
            own.push(entry);
        }
        await VexPrefs.set(THEMES_PREF, own);
    },
    async removeOwn(key) {
        const idx = parseInt(String(key).replace('eigen-', ''), 10);
        const own = (VexPrefs.get(THEMES_PREF, []) || []).slice();
        if (!(idx >= 0 && idx < own.length)) return;
        own.splice(idx, 1);
        await VexPrefs.set(THEMES_PREF, own);
    },
};

function applyGradients(prefs) {
    const root = document.documentElement;
    GRADIENT_SLOTS.forEach(slot => {
        const value = (prefs && prefs[slot.pref]) || slot.fallback;
        root.setAttribute(slot.attr, value);
    });
}

// Angewendet wird weiter unten, sobald VexPrefs den Zwischenspeicher kennt --
// immer noch vor dem ersten Zeichnen, weil diese Datei synchron im <head> steht.

// German locale helpers
const _eurFmt = new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', minimumFractionDigits: 2, maximumFractionDigits: 2 });
const _numFmt = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 2 });
function fmtEur(n) { return _eurFmt.format(Number(n) || 0); }
function fmtNum(n, digits) {
    if (digits != null) return new Intl.NumberFormat('de-DE', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Number(n) || 0);
    return _numFmt.format(Number(n) || 0);
}

/* Oberflaechen-Einstellungen — v1.60.0
 *
 * Sie liegen am Konto (``/api/ui/prefs``, Tabelle ``user_prefs``), damit sie
 * auf jedem Geraet dieselben sind. Der localStorage ist NUR ein Cache: er
 * sorgt dafuer, dass eine Seite sofort in der richtigen Einstellung aufbaut,
 * statt nach der Serverantwort umzuspringen. Wer eine Einstellung liest,
 * nimmt ``get`` mit einem sinnvollen Standardwert — ein leerer Cache ist
 * der Normalfall, kein Fehler.
 *
 * nav-switcher.js ruft ``load()`` einmal pro Seite. Wer den Cache selbst
 * fuellen muss (frueh im Seitenaufbau), ruft ihn ebenfalls — er ist
 * idempotent.
 */
const PREFS_CACHE = 'vexbob_prefs';
const VexPrefs = {
    all() {
        try { return JSON.parse(localStorage.getItem(PREFS_CACHE) || '{}') || {}; }
        catch (e) { return {}; }
    },
    get(key, fallback) {
        const v = VexPrefs.all()[key];
        return v === undefined ? fallback : v;
    },
    _write(obj) {
        try { localStorage.setItem(PREFS_CACHE, JSON.stringify(obj)); } catch (e) {}
    },
    // Ersetzt den Cache vollstaendig: eine serverseitig zurueckgesetzte
    // Einstellung soll auch hier verschwinden.
    async load() {
        const res = await apiCall('/api/ui/prefs');
        const prefs = (res && res.prefs) || {};
        VexPrefs._write(prefs);
        return prefs;
    },
    async set(key, value) {
        await apiCall('/api/ui/prefs', { method: 'PUT', body: { prefs: { [key]: value } } });
        const o = VexPrefs.all();
        o[key] = value;
        VexPrefs._write(o);
    },
    // Mehrere auf einmal -- der Endpoint nimmt ohnehin ein Objekt. Ein Thema
    // waere sonst drei Anfragen, von denen die zweite scheitern koennte und
    // einen halb gesetzten Zustand hinterliesse.
    async setMany(obj) {
        await apiCall('/api/ui/prefs', { method: 'PUT', body: { prefs: obj } });
        const o = VexPrefs.all();
        Object.keys(obj).forEach(k => { o[k] = obj[k]; });
        VexPrefs._write(o);
    },
    async reset(key) {
        await apiCall('/api/ui/prefs/' + encodeURIComponent(key), { method: 'DELETE' });
        const o = VexPrefs.all();
        delete o[key];
        VexPrefs._write(o);
        applyGradients(o);
    },
};

/* Jetzt anwenden: der Zwischenspeicher steht, gezeichnet ist noch nichts.
   `_write` ist der eine Ort, durch den jede Änderung geht (laden, setzen,
   zurücksetzen) -- daran hängt das Nachziehen, damit die Einstellungsseite
   ohne eigenes Zutun sofort umschaltet. */
const _prefsWrite = VexPrefs._write;
VexPrefs._write = function (obj) {
    _prefsWrite.call(VexPrefs, obj);
    applyGradients(obj);
};
applyGradients(VexPrefs.all());

/* Bild-Adressen aus der eigenen API — v1.62.1
 *
 * Frontend und Backend liegen auf verschiedenen Hosts. Ein
 * ``<img src="/api/public/blog/media/7">`` löst der Browser gegen den
 * FRONTEND-Host auf und findet dort nichts — das Bild bleibt kaputt, obwohl
 * der Upload geklappt hat.
 *
 * Gespeichert wird trotzdem der RELATIVE Pfad: ein Beitrag soll einen Umzug
 * des Backends überstehen, und eine im Text eingemauerte Railway-Adresse
 * würde beim nächsten Hostwechsel jeden alten Beitrag stillschweigend
 * zerlegen. Der Host kommt deshalb erst beim Anzeigen davor und vor dem
 * Speichern wieder weg.
 *
 * Bewusst als Textersetzung und nicht über den DOMParser: der würde das
 * gespeicherte Markup bei jedem Speichern neu formatieren. ``innerHTML``
 * serialisiert Attribute laut Spezifikation immer mit doppelten
 * Anführungszeichen, ``src="`` ist also verlässlich.
 */
function mediaUrl(u) {
    const s = String(u == null ? '' : u);
    return s.startsWith('/api/') ? API_BASE + s : s;
}
function absolutizeMedia(html) {
    return String(html == null ? '' : html)
        .split('src="/api/').join('src="' + API_BASE + '/api/');
}
function relativizeMedia(html) {
    return String(html == null ? '' : html)
        .split('src="' + API_BASE + '/api/').join('src="/api/');
}

// Haptic Feedback (nur wenn vom Gerät unterstützt)
function haptic(pattern) {
    try {
        if (!('vibrate' in navigator)) return;
        // pattern: 'tap' | 'success' | 'error' | Array<number>
        if (pattern === 'tap') navigator.vibrate(15);
        else if (pattern === 'success') navigator.vibrate([25, 40, 25]);
        else if (pattern === 'error') navigator.vibrate([50, 60, 50, 60, 100]);
        else if (Array.isArray(pattern)) navigator.vibrate(pattern);
    } catch(e) {}
}

// Auto-inject APP_VERSION into all .version-tag elements
document.addEventListener('DOMContentLoaded', () => {
    const v = typeof APP_VERSION !== 'undefined' ? APP_VERSION : '';
    document.querySelectorAll('.version-tag').forEach(el => { el.textContent = v; });
});