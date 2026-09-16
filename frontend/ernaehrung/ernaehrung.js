/* ernaehrung.js — v1.95.0
 *
 * Das Ernaehrungs-Modul, in zwei Betriebsarten auf EINEM Tagebuch.
 *
 *   📓 Tagebuch (locker)
 *      Was gab es, und war es normal oder uebermaessig viel? Mehr wird nicht
 *      gefragt. Ein Eintrag darf ein frei getippter Name sein -- "Pizza beim
 *      Italiener" steht in keinem Bestand und soll trotzdem im Tag stehen.
 *
 *   📊 Tracker (ausfuehrlich)
 *      Mengen in eigenen Einheiten, Naehrwerte als Spanne, eigene Tagesziele
 *      und ein Verlauf ueber den Zeitraum. Dazu die Werkstatt: Gerichte,
 *      Bestand, Scanner.
 *
 * Der Aufbau der Seite (v1.95.0, nach dem zweiten Anlauf):
 *
 *   1. **Der Tag IST die Seite.** Eine Karte, oben der Tag, darunter die
 *      Mahlzeiten mit dem, was darin steht. Vorher lagen Eingabefeld,
 *      Vorschlagsliste, Tagesbild und Eintragsliste als vier Kloetze
 *      untereinander -- das Wichtigste, naemlich was man heute gegessen hat,
 *      stand damit unter dem Bildschirmrand.
 *   2. **Eingetragen wird aus der Mahlzeit heraus**, im Dialog. Dadurch
 *      faellt die Chipreihe weg, die fragte, wohin der naechste Eintrag
 *      gehoert: wo man getippt hat, sagt das schon.
 *   3. **Eine Zeile, eine Hauptsache.** In der Vorschlagsliste ist die ganze
 *      Zeile der Knopf fuer "normal"; "uebermaessig" steht klein daneben.
 *      Zwei gleich grosse Knoepfe je Zeile waren bei acht Vorschlaegen
 *      sechzehn gleichberechtigte Ziele.
 *   4. **Formulare, die man selten braucht, stehen nicht offen.** Gericht
 *      anlegen und Lebensmittel von Hand anlegen sind Dialoge; der Reiter
 *      zeigt die Liste, um die es geht.
 *
 * Drei Regeln zu den Zahlen, die davon unberuehrt bleiben:
 *   * Was geschaetzt ist, bleibt eine Spanne.
 *   * Eine Luecke ist keine Null.
 *   * Fremde Daten (Open Food Facts) bleiben als fremd erkennbar.
 */

const API = {
    barcode:  (c)  => apiCall('/api/food/barcode/' + encodeURIComponent(c)),
    suche:    (q)  => apiCall('/api/food/search?q=' + encodeURIComponent(q)),
    bestand:  ()   => apiCall('/api/food/items'),
    aufnehmen:(d)  => apiCall('/api/food/items', { method: 'POST', body: d }),
    entfernen:(id) => apiCall('/api/food/items/' + id, { method: 'DELETE' }),
    gerichte: ()   => apiCall('/api/food/dishes'),
    gericht:  (d)  => apiCall('/api/food/dishes', { method: 'POST', body: d }),
    gerichtWeg: (id) => apiCall('/api/food/dishes/' + id, { method: 'DELETE' }),
    katalog:  ()   => apiCall('/api/food/catalog'),
    katalogEinspielen: (datei) => {
        const fd = new FormData();
        fd.append('file', datei);
        return apiCall('/api/food/catalog', { method: 'POST', body: fd });
    },
    tag:      (d)  => apiCall('/api/food/day' + (d ? '?date=' + d : '')),
    eintragen:(d)  => apiCall('/api/food/log', { method: 'POST', body: d }),
    eintragAendern: (id, d) =>
        apiCall('/api/food/log/' + id, { method: 'PATCH', body: d }),
    eintragWeg: (id) => apiCall('/api/food/log/' + id, { method: 'DELETE' }),
    einstellungen: () => apiCall('/api/food/settings'),
    setzen:   (d)  => apiCall('/api/food/settings', { method: 'PUT', body: d }),
    verlauf:  (qs) => apiCall('/api/food/history' + qs),
    haeufig:  ()   => apiCall('/api/food/frequent'),
};

// Welche Reiter es gibt, haengt am Modus. Das Tagebuch braucht keinen
// Bestand und keine Rezepte -- ihm zwei Reiter hinzustellen, die er nie
// oeffnet, waere genau die Ueberfrachtung, gegen die der Modus gebaut ist.
const REITER = {
    locker: [
        { key: 'tag', label: '📓 Tagebuch' },
        { key: 'verlauf', label: '📈 Verlauf' },
    ],
    ausfuehrlich: [
        { key: 'tag', label: '🍽️ Tag' },
        { key: 'verlauf', label: '📈 Verlauf' },
        { key: 'gerichte', label: '📖 Gerichte' },
        { key: 'vorrat', label: '🥫 Lebensmittel' },
    ],
};
const ALLE_REITER = ['tag', 'verlauf', 'gerichte', 'vorrat'];

// Die beiden Einheiten, in denen die Naehrwerte stehen. Alles andere ist
// eine eigene Groesse des Lebensmittels und traegt ihren Namen als
// Schluessel -- "Scheibe", "Laib", "Becher".
const BASIS = ['g', 'ml'];

const state = {
    modus: 'locker', einstellungen: null,
    bestand: [], groessenVorschlaege: [],
    katalog: null, katalogLaeuft: false,
    formGroessen: [],
    tag: null, datum: null, gerichte: [], haeufig: [],
    dialog: null, dlg: null,
    verlauf: null, range: null, rangeMount: null,
    charts: { eins: null, zwei: null },
    entwurf: { id: null, name: '', items: [] },
    reiter: 'tag',
};

/* ------------------------------------------------------------- Werkzeug */

const heute = () => {
    // Aus den lokalen Feldern gebaut, nicht mit toISOString: das rechnet nach
    // UTC um, und oestlich von Greenwich waere "heute" abends schon morgen.
    const d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0')
        + '-' + String(d.getDate()).padStart(2, '0');
};

const esc = (v) => String(v == null ? '' : v)
    .replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const figurFarbe = () => cssVar('--figure') || cssVar('--m-ernaehrung');

function melde(text, art, versuche) {
    if (window.Toast) { Toast[art || 'info'](text); return; }
    // ui.js wird von nav-switcher.js nachgeladen. In der ersten Sekunde ist
    // es womoeglich noch nicht da -- eine Fehlermeldung darf deshalb nicht
    // einfach verschwinden, sondern wartet kurz.
    const offen = versuche == null ? 10 : versuche;
    if (offen > 0) {
        setTimeout(() => melde(text, art, offen - 1), 200);
    } else if (art === 'error') {
        askAlert({ title: 'Das ging nicht', text: text });
    }
}

const zahlKurz = (v) => Math.round(v || 0).toLocaleString('de-DE');

// Naehrwerte in der Reihenfolge, in der sie gelesen werden. "fehlt" ist ein
// eigener Zustand -- nicht 0.
const WERTE = [
    { key: 'kcal',      label: 'kcal',          einheit: '' },
    { key: 'protein_g', label: 'Eiweiß',        einheit: ' g' },
    { key: 'fiber_g',   label: 'Ballaststoffe', einheit: ' g' },
    { key: 'carbs_g',   label: 'Kohlenhydrate', einheit: ' g' },
    { key: 'fat_g',     label: 'Fett',          einheit: ' g' },
];
const EINHEIT = { kcal: '', protein_g: ' g', fiber_g: ' g', carbs_g: ' g', fat_g: ' g' };

const zahl = (v, einheit) => v == null
    ? '<span class="ern-fehlt">keine Angabe</span>'
    : v.toLocaleString('de-DE', { maximumFractionDigits: 1 }) + einheit;

function naehrwertZeile(p) {
    return `<div class="ern-werte">${WERTE.map(w => `
        <div class="ern-wert">
            <div class="ern-wert-lbl">${w.label}</div>
            <div class="ern-wert-num">${zahl(p[w.key], w.einheit)}</div>
        </div>`).join('')}</div>
        <p class="ern-note">je 100 g${p.portion_g ? ` · übliche Portion ${p.portion_g} g` : ''}</p>`;
}

const HERKUNFT = { katalog: 'eigener Katalog', off: 'Open Food Facts' };

const TAG_NAMEN = ['Sonntag', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag',
                   'Freitag', 'Samstag'];

function datumKurz(iso) {
    const d = new Date(iso + 'T12:00:00');
    return isNaN(d.getTime()) ? iso
        : d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

function leerKarte(mark, text, knopf) {
    return `<div class="empty">
        <span class="empty-mark" aria-hidden="true">${mark}</span>
        <p class="empty-text">${text}</p>
        ${knopf || ''}
    </div>`;
}

/* Aus der Meldung des Servers einen Satz machen, der weiterhilft. Ein
   fehlender Endpunkt heisst hier fast immer dasselbe: das Frontend liegt
   schon neu auf dem Server, das Backend laeuft noch in der alten Fassung. */
function fehlerText(err) {
    const roh = (err && err.message) || '';
    if (/404|not found|405|method not allowed/i.test(roh)) return VERALTET;
    if (/netzwerkfehler/i.test(roh)) {
        return 'Keine Verbindung zum Server. Sobald er wieder antwortet, hilft ein '
            + 'Klick auf „Erneut versuchen".';
    }
    return 'Das ließ sich nicht laden' + (roh ? ' (' + roh + ').' : '.');
}

const VERALTET = 'Diesen Teil kennt der Server noch nicht. Auf dem Server läuft '
    + 'vermutlich noch die vorherige Fassung des Backends — dort fehlt ein Neustart.';

/* Ein Ladezustand, der nie endet, sieht aus wie ein kaputter Browser: man
   wartet auf etwas, das nicht mehr kommt. Deshalb tritt der Tag beiseite und
   es steht ein Satz da, der sagt was los ist, mit einem Knopf, der es noch
   einmal versucht. */
function zeigeTagFehler(text) {
    document.getElementById('ernTagInhalt').hidden = true;
    const el = document.getElementById('ernTagFehler');
    el.hidden = false;
    el.innerHTML = `<div class="stat-card"><div class="empty is-error">
        <span class="empty-mark" aria-hidden="true">⚠️</span>
        <p class="empty-text">${esc(text)}</p>
        <button type="button" class="v-btn v-btn--primary" id="ernNochmal">Erneut versuchen</button>
    </div></div>`;
    const knopf = document.getElementById('ernNochmal');
    if (knopf) knopf.addEventListener('click', () => {
        knopf.classList.add('is-loading');
        ladeTag(state.datum);
    });
}

/* --------------------------------------------------------------- Dialog
 *
 * Dasselbe Muster wie im Schach- und Ausgaben-Modul: Overlay, Kopf, Koerper,
 * Escape und Klick daneben schliessen. Alles, was man selten tut -- ein
 * Gericht anlegen, ein Lebensmittel von Hand pflegen, etwas eintragen --
 * liegt hier drin, statt dauerhaft Platz auf der Seite zu nehmen.
 */
function openModal(titel, inhalt, opts) {
    const o = opts || {};
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `<div class="modal-box${o.breit ? ' wide' : ''}">
        <div class="modal-head"><h3>${titel}</h3>
            <button class="modal-close" aria-label="Schließen">✕</button></div>
        <div class="modal-body">${inhalt}</div>
    </div>`;
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('show'));
    const close = () => {
        overlay.classList.remove('show');
        setTimeout(() => overlay.remove(), 200);
        document.removeEventListener('keydown', onKey);
        if (typeof o.beimSchliessen === 'function') o.beimSchliessen();
    };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    overlay.querySelector('.modal-close').addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    document.addEventListener('keydown', onKey);
    return { close, el: overlay };
}

/* ---------------------------------------------------------------- Modus */

const istLocker = () => state.modus === 'locker';

function zeichneModus() {
    document.querySelectorAll('[data-modus]').forEach(b => {
        const aktiv = b.dataset.modus === state.modus;
        b.classList.toggle('is-active', aktiv);
        b.setAttribute('aria-pressed', aktiv ? 'true' : 'false');
    });

    const reiter = REITER[state.modus];
    const leiste = document.getElementById('ernTabs');
    leiste.innerHTML = reiter.map(r =>
        `<button type="button" class="tab-btn${r.key === state.reiter ? ' active' : ''}"
            data-tab="${r.key}">${r.label}</button>`).join('');
    leiste.querySelectorAll('.tab-btn').forEach(b =>
        b.addEventListener('click', () => activateTab(b.dataset.tab)));

    // Steht man auf einem Reiter, den es im neuen Modus nicht gibt, landet
    // man auf dem ersten -- und nicht auf einer leeren Seite.
    if (!reiter.some(r => r.key === state.reiter)) activateTab(reiter[0].key);
    else activateTab(state.reiter);

    document.getElementById('ernZieleKarte').hidden = istLocker();
}

async function modusWechseln(modus) {
    if (modus === state.modus) return;
    state.modus = modus;
    zeichneModus();
    zeichneTag();
    if (state.verlauf) zeichneVerlauf();
    try {
        state.einstellungen = await API.setzen({ mode: modus });
    } catch (err) {
        // Die Umschaltung gilt trotzdem -- sie nur deshalb zurueckzunehmen,
        // weil der Server gerade nicht antwortet, waere die schlechtere
        // Ueberraschung. Beim naechsten Laden steht wieder der alte Modus.
        melde('Der Modus gilt für jetzt, konnte aber nicht gespeichert werden.', 'error');
    }
}

function activateTab(tab) {
    if (ALLE_REITER.indexOf(tab) < 0) tab = 'tag';
    state.reiter = tab;
    document.querySelectorAll('#ernTabs .tab-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.tab === tab));
    ALLE_REITER.forEach(t => {
        const el = document.getElementById('tab-' + t);
        if (el) el.hidden = t !== tab;
    });
    if (tab === 'verlauf') mountRange();
}

/* ------------------------------------------------------------------ Tag */

function tagVerschieben(tage) {
    const d = new Date((state.datum || heute()) + 'T12:00:00');
    d.setDate(d.getDate() + tage);
    const neu = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0')
        + '-' + String(d.getDate()).padStart(2, '0');
    // Nicht in die Zukunft: was morgen gegessen wird, weiss heute niemand.
    if (neu > heute()) return;
    ladeTag(neu);
}

function zeichneTagKopf() {
    const datum = state.datum || heute();
    const d = new Date(datum + 'T12:00:00');
    const istHeute = datum === heute();
    const gestern = new Date(Date.now() - 86400000);
    const gesternIso = gestern.getFullYear() + '-'
        + String(gestern.getMonth() + 1).padStart(2, '0') + '-'
        + String(gestern.getDate()).padStart(2, '0');
    document.getElementById('ernTagName').textContent =
        istHeute ? 'Heute' : (datum === gesternIso ? 'Gestern' : TAG_NAMEN[d.getDay()]);
    document.getElementById('ernTagDatum').textContent = datumKurz(datum);
    document.getElementById('ernTagVor').disabled = istHeute;
}

/* Das Tagesbild steht im Kopf der Tageskarte, nicht in einer eigenen:
   im Tagebuch als eine Zeile aus Zahl und Stufen, im Tracker als
   Kalorienspanne mit vier schmalen Makro-Kacheln daneben. Vorher waren das
   zwei Karten und fuenf Balken ueber die ganze Breite -- viel Flaeche fuer
   eine Auskunft, die man im Vorbeigehen liest. */
function zeichneTagBild() {
    const ziel = document.getElementById('ernTagBild');
    const t = state.tag;
    if (!t) { ziel.innerHTML = '<span class="skel skel-block"></span>'; return; }

    const c = t.counts;
    if (!c.entries) {
        ziel.innerHTML = `<p class="ern-tagleer">${istLocker()
            ? 'Für diesen Tag steht noch nichts da — ein Wort reicht.'
            : 'Für diesen Tag ist noch nichts eingetragen.'}</p>`;
        return;
    }

    const stufen = `<span class="ern-stufenzeile">
        <span class="ern-punkt is-normal" aria-hidden="true"></span> ${c.normal} normal
        <span class="ern-punkt is-viel" aria-hidden="true"></span> ${c.viel} übermäßig
        ${c.exact ? `<span class="ern-punkt is-exakt" aria-hidden="true"></span> ${c.exact} abgewogen` : ''}
        ${c.unknown ? `<span class="v-tag v-tag--warn">${c.unknown} ohne Nährwerte</span>` : ''}
    </span>`;

    const kcal = t.totals.kcal;
    const bekannt = c.entries - c.unknown;

    if (istLocker()) {
        // Eine Kalorienzahl kann es im Tagebuch gar nicht geben -- die
        // Auskunft ist die Zahl der Eintraege und ihre Verteilung. Wenn zu
        // einigen doch Naehrwerte bekannt sind, steht das als Nebensatz da.
        ziel.innerHTML = `<div class="ern-tagzeile">
            <div class="ern-gross"><span>${c.entries}</span>
                <span class="ern-einheit">${c.entries === 1 ? 'Eintrag' : 'Einträge'}</span></div>
            ${stufen}
        </div>
        ${bekannt ? `<p class="ern-note">Grob gerechnet ${zahlKurz(kcal.min)}–${zahlKurz(kcal.max)} kcal
            aus ${bekannt} von ${c.entries} Einträgen.</p>` : ''}`;
        return;
    }

    const rest = kcal.remaining_max > 0
        ? (kcal.remaining_min === kcal.remaining_max
            ? `noch ${zahlKurz(kcal.remaining_min)} kcal bis zum ${kcal.own_target ? 'Ziel' : 'Richtwert'}`
            : `noch ${zahlKurz(kcal.remaining_min)}–${zahlKurz(kcal.remaining_max)} kcal bis zum ${kcal.own_target ? 'Ziel' : 'Richtwert'}`)
        : `${kcal.own_target ? 'Zielwert' : 'Richtwert'} von ${zahlKurz(kcal.reference)} kcal erreicht`;

    ziel.innerHTML = `<div class="ern-tagzeile">
            <div class="ern-gross">
                <span>${zahlKurz(kcal.min)}</span>
                ${kcal.min === kcal.max ? '' : `<span class="ern-bis">bis</span>
                <span>${zahlKurz(kcal.max)}</span>`}
                <span class="ern-einheit">kcal</span>
            </div>
            ${stufen}
        </div>
        <p class="ern-note">${rest}${kcal.incomplete
            ? ' · die Spanne ist eine Untergrenze, zu manchen Einträgen fehlen Angaben' : ''}</p>
        <div class="ern-makros">${t.macros.filter(m => m !== 'kcal')
            .map(m => makroKachel(m, t.totals[m])).join('')}</div>`;
}

/* Eine schmale Kachel je Naehrwert. Die Spur reicht bis zum Anderthalbfachen
   des Massstabs, der Massstab selbst steht als Strich darin; gefuellt ist
   genau der Bereich zwischen unterer und oberer Schaetzung -- die Breite des
   Balkens IST die Unsicherheit. */
function makroKachel(makro, d) {
    const links = Math.min(100, (d.share_min / 1.5) * 100);
    const breite = Math.max(2, Math.min(100 - links, ((d.share_max - d.share_min) / 1.5) * 100));
    const e = EINHEIT[makro] || '';
    return `<div class="ern-makro${d.incomplete ? ' is-unvollstaendig' : ''}">
        <div class="ern-makro-kopf">
            <span class="ern-makro-lbl">${esc(d.label)}</span>
            <span class="ern-makro-wert">${d.incomplete ? 'mind. ' : ''}${zahlKurz(d.min)}${
                d.min === d.max ? '' : '–' + zahlKurz(d.max)}${e}</span>
        </div>
        <div class="ern-makro-spur" role="img"
             aria-label="${esc(d.label)}: ${zahlKurz(d.min)} bis ${zahlKurz(d.max)}${e}, ${
                d.own_target ? 'Ziel' : 'Richtwert'} ${zahlKurz(d.reference)}${e}">
            <span class="ern-makro-marke" style="left:66.7%"></span>
            <span class="ern-makro-fuell" style="left:${links.toFixed(1)}%;width:${breite.toFixed(1)}%"></span>
        </div>
        <div class="ern-makro-fuss">${d.own_target ? 'Ziel' : 'Richtwert'} ${zahlKurz(d.reference)}${e}</div>
    </div>`;
}

/* Der Tag nach Mahlzeiten -- und jede Mahlzeit traegt ihr eigenes Plus.
   "Mittag" ist die Auskunft, die man geben kann; eine Uhrzeit waere eine,
   die man erfinden muesste. Leere Mahlzeiten bleiben als schmale Zeile
   stehen: sie sind der kuerzeste Weg zum naechsten Eintrag. */
function zeichneMahlzeitenBloecke() {
    const ziel = document.getElementById('ernTagMahlzeiten');
    const t = state.tag;
    if (!t) { ziel.innerHTML = '<span class="skel skel-block"></span>'; return; }

    ziel.innerHTML = t.meals.map(m => {
        const eigene = t.entries.filter(e => e.meal === m.key);
        // "Ohne Zuordnung" steht nur da, wenn wirklich etwas darin liegt --
        // sonst waere es eine fuenfte Mahlzeit, die niemand hat.
        if (m.key === 'ohne' && !eigene.length) return '';

        const summe = eigene.reduce((a, e) => ({
            min: a.min + (e.kcal_min || 0), max: a.max + (e.kcal_max || 0),
            offen: a.offen || !e.has_nutrition,
        }), { min: 0, max: 0, offen: false });
        const kcalText = istLocker() || !(summe.max > 0) ? ''
            : `<span class="ern-mz-summe">${summe.offen ? 'mind. ' : ''}${
                zahlKurz(summe.min)}${summe.min === summe.max ? '' : '–' + zahlKurz(summe.max)} kcal</span>`;

        const plus = m.key === 'ohne' ? ''
            : `<button type="button" class="ern-mz-plus" data-add="${esc(m.key)}"
                   aria-label="Zu ${esc(m.label)} eintragen" title="Zu ${esc(m.label)} eintragen">＋</button>`;

        return `<div class="ern-mz${eigene.length ? '' : ' is-leer'}">
            <div class="ern-mz-kopf">
                <span class="ern-mz-name">${esc(m.label)}</span>
                ${kcalText}
                ${plus}
            </div>
            ${eigene.length ? eigene.map(eintragZeile).join('') : ''}
        </div>`;
    }).join('');

    ziel.querySelectorAll('[data-add]').forEach(b =>
        b.addEventListener('click', () => eintragDialog(b.dataset.add)));
    ziel.querySelectorAll('[data-eintrag-weg]').forEach(b =>
        b.addEventListener('click', () => eintragEntfernen(Number(b.dataset.eintragWeg))));
    ziel.querySelectorAll('[data-stufe-um]').forEach(b =>
        b.addEventListener('click', () => stufeUmschalten(
            Number(b.dataset.stufeUm), b.dataset.stufeNeu)));
}

function eintragZeile(e) {
    // Eine falsch geratene Stufe laesst sich antippen statt loeschen und neu
    // eintragen. Bei einer gewogenen Menge geht das nicht: dort steht die
    // Menge, und die ist keine Stufe.
    const stufe = e.level && !e.amount_label
        ? `<button type="button" class="ern-stufe is-${esc(e.level)}"
               data-stufe-um="${e.id}" data-stufe-neu="${e.level === 'viel' ? 'normal' : 'viel'}"
               title="Umstellen auf ${e.level === 'viel' ? 'normal' : 'übermäßig'}">${
               esc(e.level_label || '')}</button>`
        : (e.amount_label ? `<span class="ern-stufe is-exakt">${esc(e.amount_label)}</span>` : '');

    const meta = [
        e.kind === 'free' ? 'frei notiert' : esc(e.sub || ''),
        istLocker() ? '' : (e.has_nutrition && e.kcal_min != null
            ? (e.kcal_min === e.kcal_max
                ? `${zahlKurz(e.kcal_min)} kcal`
                : `${zahlKurz(e.kcal_min)}–${zahlKurz(e.kcal_max)} kcal`)
            : 'ohne Nährwerte'),
        e.assumed_portion ? 'Portion mit 100 g angenommen' : '',
    ].filter(Boolean);

    return `<div class="ern-zeile">
        <span class="ern-punkt is-${e.amount_label ? 'exakt' : esc(e.level || 'normal')}"
              aria-hidden="true"></span>
        <div class="ern-zeile-text">
            <div class="ern-zeile-kopf"><strong>${esc(e.name)}</strong>${stufe}</div>
            <div class="ern-note">${meta.join(' · ')}</div>
        </div>
        <button type="button" class="v-btn v-btn--icon" data-eintrag-weg="${e.id}"
                aria-label="Eintrag entfernen" title="Entfernen">🗑️</button>
    </div>`;
}

function zeichneTag() {
    zeichneTagKopf();
    zeichneTagBild();
    zeichneMahlzeitenBloecke();
}

async function ladeTag(datum) {
    state.datum = datum || state.datum || heute();
    let tag;
    try {
        tag = await API.tag(state.datum);
    } catch (err) {
        zeigeTagFehler(fehlerText(err));
        return;
    }
    // Eine Antwort ohne ``counts`` und ``meals`` kommt aus einer aelteren
    // Fassung des Backends. Sie hier durchzulassen hiesse, die Seite mitten
    // im Zeichnen an einem fehlenden Feld abbrechen zu lassen -- und was man
    // dann saehe, waere eine halbe Seite ohne Grund.
    if (!tag || !tag.counts || !tag.meals) {
        zeigeTagFehler(VERALTET);
        return;
    }
    state.tag = tag;
    document.getElementById('ernTagFehler').hidden = true;
    document.getElementById('ernTagInhalt').hidden = false;
    zeichneTag();
}

async function ladeHaeufig() {
    try {
        const res = await API.haeufig();
        state.haeufig = res.suggestions || [];
    } catch (e) {
        state.haeufig = [];
    }
    if (state.dlg) zeichneDlgListe();
}

/* ----------------------------------------------------- Eintragen-Dialog
 *
 * Alles, was zum Eintragen gehoert, liegt hier drin: die Mahlzeit, das
 * Suchfeld und die Vorschlaege. Auf der Seite selbst stand das vorher
 * dauerhaft und schob den Tag nach unten -- dabei tippt man dort nur ein
 * paar Sekunden am Tag.
 */

/* Welche Mahlzeit gemeint ist, wenn man den grossen Knopf drueckt. Nur fuer
   heute geraten: bei einem vergangenen Tag waere "es ist jetzt Abend" kein
   Argument dafuer, was damals auf dem Teller lag. */
function mahlzeitJetzt() {
    if ((state.datum || heute()) !== heute()) return null;
    const h = new Date().getHours();
    if (h < 11) return 'fruehstueck';
    if (h < 15) return 'mittag';
    if (h < 21) return 'abend';
    return 'snack';
}

function eintragDialog(mahlzeit) {
    if (!state.tag) return;
    state.dlg = { mahlzeit: mahlzeit || null, eingabe: '', zuletzt: [], tippen: null,
                  liste: [] };

    const titel = (state.datum || heute()) === heute()
        ? 'Eintragen · heute' : 'Eintragen · ' + datumKurz(state.datum);
    const inhalt = `
        <div class="ern-dlg-mahlzeiten" id="ernDlgMahlzeiten"></div>
        <label class="ern-suche">
            <span class="ern-suche-ico" aria-hidden="true">🔎</span>
            <input type="search" id="ernDlgSuche" autocomplete="off"
                   aria-label="Was gab es?" placeholder="${istLocker()
                    ? 'Tippen, was es gab — „Pizza", „Müsli"'
                    : 'Gericht oder Lebensmittel suchen'}">
        </label>
        <div id="ernDlgListe"></div>
        <div class="ern-dlg-fuss">
            <span class="ern-note" id="ernDlgZuletzt"></span>
            <button type="button" class="v-btn v-btn--primary" id="ernDlgFertig">Fertig</button>
        </div>`;

    state.dialog = openModal(titel, inhalt, {
        breit: true,
        beimSchliessen: () => {
            if (state.dlg) clearTimeout(state.dlg.tippen);
            state.dialog = null;
            state.dlg = null;
        },
    });

    zeichneDlgMahlzeiten();
    zeichneDlgListe();

    const feld = document.getElementById('ernDlgSuche');
    feld.addEventListener('input', (e) => {
        clearTimeout(state.dlg.tippen);
        const wert = e.target.value;
        state.dlg.tippen = setTimeout(() => {
            state.dlg.eingabe = wert;
            zeichneDlgListe();
        }, 160);
    });
    // Enter traegt den ersten Vorschlag normal ein -- der haeufigste Fall,
    // und er soll ohne Maus gehen.
    feld.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        clearTimeout(state.dlg.tippen);
        state.dlg.eingabe = e.target.value;
        zeichneDlgListe();
        const erste = document.querySelector('#ernDlgListe [data-log-normal], #ernDlgListe [data-log-menge]');
        if (erste) erste.click();
    });
    document.getElementById('ernDlgFertig')
        .addEventListener('click', () => state.dialog && state.dialog.close());
    // Auf dem Handy oeffnet der Fokus die Tastatur und verdeckt die Liste;
    // auf dem Rechner ist er genau das, was man will.
    if (window.matchMedia('(min-width: 720px)').matches) feld.focus();
}

function zeichneDlgMahlzeiten() {
    const ziel = document.getElementById('ernDlgMahlzeiten');
    if (!ziel) return;
    const liste = (state.tag && state.tag.meals) || [];
    ziel.innerHTML = liste.map(m =>
        `<button type="button" class="v-chip${
            (state.dlg.mahlzeit || 'ohne') === m.key ? ' is-active' : ''}"
            data-mahlzeit="${esc(m.key)}">${esc(m.label)}</button>`).join('');
    ziel.querySelectorAll('[data-mahlzeit]').forEach(b => b.addEventListener('click', () => {
        state.dlg.mahlzeit = b.dataset.mahlzeit === 'ohne' ? null : b.dataset.mahlzeit;
        zeichneDlgMahlzeiten();
    }));
}

/* Woraus die Liste besteht:
     1. der frei getippte Text -- der Weg, der ohne Bestand auskommt,
     2. was im Bestand dazu passt (Gerichte, Lebensmittel),
     3. was man oft eintraegt, aus dem Tagebuch selbst gezaehlt.
   Im Tagebuch steht 1 obenan, im Tracker 2: dort tippt man einen Namen, um
   etwas zu finden, hier, um etwas hinzuschreiben. */
function dlgVorschlaege() {
    const text = (state.dlg.eingabe || '').trim();
    const suche = text.toLowerCase();
    const passt = (n) => !suche || String(n || '').toLowerCase().includes(suche);

    const frei = !text ? [] : [{
        kind: 'free', name: text, neu: true,
        sub: istLocker() ? 'so hinschreiben — braucht keinen Bestand'
                         : 'frei notieren, ohne Nährwerte',
    }];

    const gerichte = state.gerichte.filter(g => passt(g.name)).map(g => ({
        kind: 'dish', dish_id: g.id, name: g.name,
        sub: g.portion && g.portion.kcal != null
            ? `Gericht · ${zahlKurz(g.portion.kcal)} kcal je Portion`
            : 'Gericht · Nährwerte unvollständig',
    }));

    const lebensmittel = istLocker() ? [] : state.bestand
        .filter(p => passt(p.name) || passt(p.brand))
        .map(p => ({
            kind: 'item', item_id: p.id, item: p, name: p.name,
            sub: (p.brand ? p.brand + ' · ' : '')
                + ((p.sizes || []).length
                    ? (p.sizes || []).map(g =>
                        `${g.label} = ${g.grams} ${p.base_unit || 'g'}`).join(' · ')
                    : 'keine eigene Größe — wird in ' + (p.base_unit || 'g') + ' eingetragen'),
        }));

    // Was man oft eintraegt. Doppelt zeigen brauchen wir es nicht: was schon
    // als Gericht oder Lebensmittel in der Liste steht, faellt hier weg.
    const schon = new Set(gerichte.map(g => 'd' + g.dish_id)
        .concat(lebensmittel.map(l => 'i' + l.item_id)));
    const haeufig = state.haeufig
        .filter(h => passt(h.name))
        .filter(h => !schon.has((h.dish_id ? 'd' + h.dish_id : (h.item_id ? 'i' + h.item_id : 'x'))))
        .map(h => ({
            kind: h.kind, dish_id: h.dish_id, item_id: h.item_id,
            item: h.item_id ? state.bestand.find(p => p.id === h.item_id) : null,
            name: h.name,
            sub: `${h.count}× notiert · zuletzt ${datumKurz(h.last)}`,
        }));

    return istLocker()
        ? frei.concat(haeufig, gerichte)
        : frei.concat(gerichte, lebensmittel, haeufig);
}

/* Eine Zeile, eine Hauptsache: die ganze Zeile ist der Knopf fuer "normal",
   "uebermaessig" steht klein daneben. Nur ein Lebensmittel im Tracker bekommt
   statt der Stufen ein Mengenfeld -- dort ist die Menge die Angabe. */
function dlgZeile(v, i) {
    const mengenFeld = !istLocker() && v.kind === 'item' && v.item;
    if (mengenFeld) {
        const einheiten = v.item.units
            || [{ key: v.item.base_unit || 'g', label: v.item.base_unit || 'g' }];
        const eigene = einheiten.filter(e => !BASIS.includes(e.key));
        const start = eigene.length ? eigene[0] : einheiten[0];
        return `<div class="ern-w is-menge">
            <div class="ern-w-text">
                <span class="ern-w-name">${esc(v.name)}</span>
                <span class="ern-w-sub">${esc(v.sub || '')}</span>
            </div>
            <div class="ern-menge">
                <input type="number" min="0" step="0.25" inputmode="decimal"
                       value="${eigene.length ? 1 : 100}"
                       data-menge="${i}" aria-label="Menge für ${esc(v.name)}">
                <select class="v-select v-select--sm" data-einheit="${i}"
                        aria-label="Einheit für ${esc(v.name)}">
                    ${einheiten.map(e => `<option value="${esc(e.key)}"${
                        e.key === start.key ? ' selected' : ''}>${esc(e.label)}</option>`).join('')}
                </select>
                <button type="button" class="v-btn v-btn--sm v-btn--primary"
                        data-log-menge="${i}">Eintragen</button>
            </div>
        </div>`;
    }
    return `<div class="ern-w${v.neu ? ' is-neu' : ''}">
        <button type="button" class="ern-w-haupt" data-log-normal="${i}">
            <span class="ern-w-name">${esc(v.name)}</span>
            <span class="ern-w-sub">${esc(v.sub || '')}</span>
        </button>
        <button type="button" class="ern-w-viel" data-log-viel="${i}"
                title="Als übermäßig eintragen">übermäßig</button>
    </div>`;
}

function zeichneDlgListe() {
    const ziel = document.getElementById('ernDlgListe');
    if (!ziel || !state.dlg) return;
    const liste = dlgVorschlaege();
    state.dlg.liste = liste;

    if (!liste.length) {
        ziel.innerHTML = leerKarte('✏️', istLocker()
            ? 'Tipp oben hin, was es gab — „Pizza", „Müsli", „Kaffee". Es muss in keiner '
              + 'Liste stehen, und nach ein paar Tagen schlägt dir die Seite genau das vor, '
              + 'was du wirklich isst.'
            : 'Noch nichts im Bestand. Über <strong>Lebensmittel</strong> kommt etwas herein, '
              + 'unter <strong>Gerichte</strong> stellst du daraus eines zusammen.');
        return;
    }

    const MAX = 12;
    ziel.innerHTML = liste.slice(0, MAX).map(dlgZeile).join('')
        + (liste.length > MAX
            ? `<p class="ern-note">… und ${liste.length - MAX} weitere — tipp oben weiter.</p>`
            : '');

    const auswahl = (i) => state.dlg.liste[Number(i)];
    const daten = (v, stufe) => {
        const d = { level: stufe };
        if (v.kind === 'dish') d.dish_id = v.dish_id;
        else if (v.kind === 'item') d.item_id = v.item_id;
        else d.label = v.name;
        return d;
    };
    ziel.querySelectorAll('[data-log-normal]').forEach(b => b.addEventListener('click', () => {
        const v = auswahl(b.dataset.logNormal);
        if (v) eintragen(daten(v, 'normal'), b, v.name);
    }));
    ziel.querySelectorAll('[data-log-viel]').forEach(b => b.addEventListener('click', () => {
        const v = auswahl(b.dataset.logViel);
        if (v) eintragen(daten(v, 'viel'), b, v.name);
    }));
    ziel.querySelectorAll('[data-log-menge]').forEach(b => b.addEventListener('click', () => {
        const i = b.dataset.logMenge;
        const v = auswahl(i);
        const feld = ziel.querySelector(`[data-menge="${i}"]`);
        const wahl = ziel.querySelector(`[data-einheit="${i}"]`);
        const menge = Number(String(feld.value).replace(',', '.'));
        if (!(menge > 0)) { melde('Wie viel davon?', 'error'); feld.focus(); return; }
        eintragen({ item_id: v.item_id, amount: menge, unit: wahl.value }, b, v.name);
    }));
    // Die Zahl im Feld passt sich der Einheit an: 100 g, aber 1 Scheibe.
    // Ohne das steht nach dem Umschalten "100 Scheiben" da.
    ziel.querySelectorAll('[data-einheit]').forEach(w => w.addEventListener('change', () => {
        const feld = ziel.querySelector(`[data-menge="${w.dataset.einheit}"]`);
        if (feld) feld.value = BASIS.includes(w.value) ? 100 : 1;
    }));
}

async function eintragen(daten, knopf, name) {
    knopf.classList.add('is-loading');
    try {
        state.tag = await API.eintragen(Object.assign(
            { day: state.datum || heute(),
              meal: state.dlg ? state.dlg.mahlzeit : null }, daten));
        zeichneTag();
        if (state.dlg) {
            // Das Feld leeren: der naechste Eintrag faengt bei null an, und
            // ein stehengebliebener Text sieht aus, als waere nichts
            // passiert. Auch den laufenden Tipp-Takt, sonst stellt er den
            // Text 160 ms spaeter wieder als Vorschlag hin.
            clearTimeout(state.dlg.tippen);
            state.dlg.eingabe = '';
            const feld = document.getElementById('ernDlgSuche');
            if (feld) { feld.value = ''; feld.focus(); }
            if (name) state.dlg.zuletzt.push(name);
            const fuss = document.getElementById('ernDlgZuletzt');
            if (fuss) {
                fuss.textContent = state.dlg.zuletzt.length
                    ? 'Eingetragen: ' + state.dlg.zuletzt.join(', ') : '';
            }
            zeichneDlgListe();
        }
        ladeHaeufig();
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    } finally {
        knopf.classList.remove('is-loading');
    }
}

async function stufeUmschalten(id, neu) {
    try {
        state.tag = await API.eintragAendern(id, { level: neu });
        zeichneTag();
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    }
}

async function eintragEntfernen(id) {
    try {
        state.tag = await API.eintragWeg(id);
        zeichneTag();
        ladeHaeufig();
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    }
}

/* -------------------------------------------------------------- Verlauf */

function mountRange() {
    if (state.rangeMount) return;
    const host = document.getElementById('ernRange');
    if (!host) return;
    state.rangeMount = VexRange.mount(host, {
        onChange: (r) => { state.range = r; ladeVerlauf(); },
    });
}

async function ladeVerlauf() {
    const range = state.range || (state.rangeMount ? state.rangeMount.get() : null);
    const abfrage = new URLSearchParams();
    if (range && range.from) abfrage.set('from', range.from);
    if (range && range.to) abfrage.set('to', range.to);
    const qs = abfrage.toString();
    try {
        state.verlauf = await API.verlauf(qs ? '?' + qs : '');
    } catch (err) {
        state.verlauf = null;
        zerstoereCharts();
        document.getElementById('ernVerlaufKpi').innerHTML = '';
        document.getElementById('ernChart1Box').hidden = true;
        document.getElementById('ernChart1Leer').hidden = false;
        document.getElementById('ernChart2Karte').hidden = true;
        document.getElementById('ernChart1Leer').innerHTML =
            `<div class="empty is-error"><span class="empty-mark">⚠️</span>
             <p class="empty-text">${esc(fehlerText(err))}</p></div>`;
        return;
    }
    zeichneVerlauf();
}

function zerstoereCharts() {
    ['eins', 'zwei'].forEach(k => {
        if (state.charts[k]) { try { state.charts[k].destroy(); } catch (e) {} }
        state.charts[k] = null;
    });
}

function kpiKarte(icon, label, wert, sub) {
    return `<div class="stat-kpi">
        <div class="stat-kpi-icon" aria-hidden="true">${icon}</div>
        <div class="stat-kpi-label">${label}</div>
        <div class="stat-kpi-value">${wert}</div>
        <div class="stat-kpi-sub">${sub || ''}</div>
    </div>`;
}

/* Die laengste Strecke ohne Notiz. Sie ist die ehrlichste Kennzahl eines
   Tagebuchs: nicht wie viel man gegessen hat, sondern wie lueckenlos man
   ueberhaupt aufgeschrieben hat. */
function laengsteLuecke(tage) {
    let lauf = 0, beste = 0;
    tage.forEach(t => {
        lauf = t.entries ? 0 : lauf + 1;
        beste = Math.max(beste, lauf);
    });
    return beste;
}

function zeichneVerlauf() {
    const v = state.verlauf;
    if (!v) return;
    zerstoereCharts();

    document.getElementById('ernVerlaufZeitraum').textContent =
        `${datumKurz(v.from)} bis ${datumKurz(v.to)}`;
    document.getElementById('ernVerlaufSub').textContent = v.truncated
        ? 'auf 400 Tage gekürzt — länger wird die Liste breiter als jede Darstellung'
        : '';

    const z = v.summary;
    const kpi = [];
    kpi.push(kpiKarte('📅', 'Notiert', `${z.days_logged} von ${z.days}`,
        z.days_logged ? `längste Lücke: ${laengsteLuecke(v.days)} Tage` : 'noch nichts im Zeitraum'));
    kpi.push(kpiKarte('🍽️', 'Einträge', zahlKurz(z.entries),
        z.days_logged ? `Ø ${(z.entries / z.days_logged).toFixed(1)} an Tagen mit Notiz` : ''));
    kpi.push(kpiKarte('⚖️', 'Übermäßig', z.viel_share == null ? '–'
        : Math.round(z.viel_share * 100) + ' %',
        z.leveled ? `${z.viel} von ${z.leveled} Einträgen mit Stufe` : 'keine Stufe im Zeitraum'));
    kpi.push(kpiKarte('🔥', 'Kalorien Ø', z.kcal_avg_min == null ? '–'
        : `${zahlKurz(z.kcal_avg_min)}–${zahlKurz(z.kcal_avg_max)}`,
        z.complete_days
            ? `über ${z.complete_days} ${z.complete_days === 1 ? 'Tag' : 'Tage'} mit vollständigen Angaben`
            : 'kein Tag, an dem zu allem Nährwerte standen'));
    document.getElementById('ernVerlaufKpi').innerHTML = kpi.join('');

    // Ein leeres Diagramm sagt nicht, warum es leer ist. Ein Satz schon --
    // und er nennt den Grund, der hier fast immer zutrifft.
    if (!z.days_logged) {
        document.getElementById('ernChart2Karte').hidden = true;
        document.getElementById('ernChart1Box').hidden = true;
        document.getElementById('ernChart1Titel').textContent = 'Verlauf';
        document.getElementById('ernChart1Sub').textContent = '';
        document.getElementById('ernChart1Note').textContent = '';
        const leer = document.getElementById('ernChart1Leer');
        leer.hidden = false;
        leer.innerHTML = leerKarte('📈',
            `Zwischen ${datumKurz(v.from)} und ${datumKurz(v.to)} steht kein einziger
             Eintrag. Ein anderer Zeitraum oben zeigt mehr — oder du trägst unter
             <strong>${istLocker() ? 'Tagebuch' : 'Tag'}</strong> etwas ein.`);
        document.getElementById('ernZieleKarte').hidden = istLocker();
        if (!istLocker()) zeichneZiele();
        return;
    }

    document.getElementById('ernChart1Leer').hidden = true;
    document.getElementById('ernChart1Box').hidden = false;
    if (istLocker()) zeichneStreifen();
    else zeichneSpannen();

    document.getElementById('ernZieleKarte').hidden = istLocker();
    if (!istLocker()) zeichneZiele();
}

function achsenTexte(tage) {
    return {
        kurz: tage.map(t => t.day.slice(8, 10) + '.' + t.day.slice(5, 7) + '.'),
        voll: tage.map(t => VexCharts.fullDay(t.day)),
    };
}

/* Ein Tag im Diagramm ist auch ein Weg zu diesem Tag: wer sieht, dass am
   Dienstag dreimal „uebermaessig" steht, will nachsehen, was es war -- und
   nicht erst mit dem Pfeil vier Tage zurueckklicken. */
function tagOeffnen(index) {
    const tag = state.verlauf && state.verlauf.days[index];
    if (!tag) return;
    activateTab('tag');
    ladeTag(tag.day);
}

const BASIS_OPTIONEN = (texte, extra) => VexCharts.applyFullDates(Object.assign({
    maintainAspectRatio: false,
    animation: { duration: 200 },
    interaction: { mode: 'index', intersect: false },
    onClick: (evt, treffer, chart) => {
        // Auch neben einer Saeule: getroffen wird der Tag unter dem Finger,
        // nicht nur der Balken selbst -- sonst muss man zielen.
        const punkte = chart.getElementsAtEventForMode(
            evt, 'index', { intersect: false }, true);
        if (punkte && punkte.length) tagOeffnen(punkte[0].index);
    },
}, extra || {}), texte.voll);

const TOOLTIP = (extra) => Object.assign({
    backgroundColor: cssVar('--surface-3'),
    borderColor: cssVar('--line-strong'), borderWidth: 1,
    titleColor: cssVar('--text-1'), bodyColor: cssVar('--text-2'),
    cornerRadius: 12, padding: 10, displayColors: true,
}, extra || {});

const ACHSE_X = { ticks: { color: cssVar('--chart-axis'), font: { size: 11 },
                           maxRotation: 0, autoSkipPadding: 16 },
                  grid: { display: false }, border: { display: false } };

/* Tagebuch-Verlauf: gezaehlt, nicht geschaetzt. Die Hoehe der Saeule ist die
   Zahl der Eintraege, ihre Aufteilung die Stufe -- beides Dinge, die im
   lockeren Modus wirklich dastehen. Eine Kalorienkurve waere hier eine
   Kurve aus Zahlen, die es gar nicht gibt. */
function zeichneStreifen() {
    const v = state.verlauf;
    const texte = achsenTexte(v.days);
    document.getElementById('ernChart1Titel').textContent = 'Einträge je Tag';
    document.getElementById('ernChart1Sub').textContent = 'nach Stufe';
    document.getElementById('ernChart1Note').textContent =
        'Ein leerer Tag heißt: nichts notiert. Er heißt nicht, dass nichts gegessen wurde — '
        + 'das ist der Unterschied, den ein Tagebuch machen kann und eine Waage nicht. '
        + 'Einen Tag antippen öffnet ihn.';
    document.getElementById('ernChart2Karte').hidden = true;

    const reihe = (name, feld, farbe) => ({
        label: name, data: v.days.map(t => t[feld]),
        backgroundColor: farbe, borderRadius: 6, borderSkipped: false,
        maxBarThickness: 34, order: VexCharts.ORDER.VALUE,
    });

    state.charts.eins = new Chart(document.getElementById('ernChart1'), {
        type: 'bar',
        data: {
            labels: texte.kurz,
            datasets: [
                reihe('normal', 'normal', figurFarbe()),
                reihe('übermäßig', 'viel', cssVar('--warn')),
                reihe('abgewogen', 'exact', cssVar('--text-4')),
            ],
        },
        options: BASIS_OPTIONEN(texte, {
            plugins: {
                legend: { display: true, position: 'top',
                          labels: { color: cssVar('--text-3'), font: { size: 11 },
                                    boxWidth: 10, boxHeight: 10, usePointStyle: true,
                                    pointStyle: 'circle' } },
                tooltip: TOOLTIP({ callbacks: {
                    title: VexCharts.titleFrom(texte.voll),
                    label: (i) => ' ' + i.dataset.label + ': ' + i.parsed.y,
                    footer: (items) => {
                        const t = v.days[items[0].dataIndex];
                        return t.entries
                            ? `${t.entries} ${t.entries === 1 ? 'Eintrag' : 'Einträge'}`
                              + (t.unknown ? ` · ${t.unknown} ohne Nährwerte` : '')
                            : 'nichts notiert';
                    },
                } }),
            },
            scales: {
                x: Object.assign({ stacked: true }, ACHSE_X),
                y: { stacked: true, beginAtZero: true,
                     ticks: { color: cssVar('--chart-axis'), font: { size: 11 },
                              maxTicksLimit: 5, precision: 0 },
                     grid: { color: cssVar('--chart-grid') }, border: { display: false } },
            },
        }),
    });
}

/* Tracker-Verlauf: je Tag ein Balken von der unteren zur oberen Schaetzung.
   Chart.js nimmt dafuer ein Wertepaar -- und genau das ist die ehrliche
   Darstellung: die Hoehe des Balkens IST die Unsicherheit, nicht ein Punkt,
   der eine Genauigkeit behauptet. Ein Tag ohne Eintrag bleibt leer statt
   auf null zu fallen: "nichts notiert" ist nicht "nichts gegessen". */
function spannenChart(canvasId, makro, farbe, texte, titelEl, subEl, noteEl) {
    const v = state.verlauf;
    const ziel = (v.targets && v.targets[makro]) || v.reference[makro];
    const eigen = !!(v.targets && v.targets[makro]);
    const e = EINHEIT[makro] || '';

    document.getElementById(titelEl).textContent = v.macro_labels[makro] + ' je Tag';
    document.getElementById(subEl).textContent =
        `${eigen ? 'Ziel' : 'Richtwert'} ${zahlKurz(ziel)}${e}`;
    document.getElementById(noteEl).textContent =
        'Jeder Balken reicht von der unteren zur oberen Schätzung des Tages — seine Höhe '
        + 'ist die Unsicherheit. Tage ohne Eintrag bleiben leer: nichts notiert ist nicht '
        + 'nichts gegessen. Einen Tag antippen öffnet ihn.';

    return new Chart(document.getElementById(canvasId), {
        data: {
            labels: texte.kurz,
            datasets: [
                {
                    type: 'bar', label: v.macro_labels[makro],
                    data: v.days.map(t => t.entries ? [t[makro].min, t[makro].max] : null),
                    backgroundColor: farbe, borderRadius: 6, borderSkipped: false,
                    maxBarThickness: 34, order: VexCharts.ORDER.VALUE,
                },
                {
                    type: 'line', label: eigen ? 'Dein Ziel' : 'Richtwert',
                    data: v.days.map(() => ziel),
                    borderColor: cssVar('--text-2'), borderWidth: 2, borderDash: [5, 4],
                    pointRadius: 0, fill: false, order: VexCharts.ORDER.TREND,
                },
            ],
        },
        options: BASIS_OPTIONEN(texte, {
            plugins: {
                legend: { display: false },
                tooltip: TOOLTIP({ callbacks: {
                    title: VexCharts.titleFrom(texte.voll),
                    label: (i) => {
                        const t = v.days[i.dataIndex];
                        if (i.dataset.type === 'line') {
                            return ' ' + i.dataset.label + ': ' + zahlKurz(ziel) + e;
                        }
                        if (!t.entries) return ' nichts notiert';
                        return ' ' + (t[makro].incomplete ? 'mind. ' : '')
                            + zahlKurz(t[makro].min) + '–' + zahlKurz(t[makro].max) + e;
                    },
                    footer: (items) => {
                        const t = v.days[items[0].dataIndex];
                        if (!t.entries) return '';
                        return `${t.entries} ${t.entries === 1 ? 'Eintrag' : 'Einträge'}`
                            + (t.unknown ? ` · ${t.unknown} ohne Nährwerte` : '');
                    },
                } }),
            },
            scales: {
                x: ACHSE_X,
                y: { beginAtZero: true,
                     ticks: { color: cssVar('--chart-axis'), font: { size: 11 },
                              maxTicksLimit: 5 },
                     grid: { color: cssVar('--chart-grid') }, border: { display: false } },
            },
        }),
    });
}

function zeichneSpannen() {
    const texte = achsenTexte(state.verlauf.days);
    document.getElementById('ernChart2Karte').hidden = false;
    state.charts.eins = spannenChart('ernChart1', 'kcal', figurFarbe(), texte,
        'ernChart1Titel', 'ernChart1Sub', 'ernChart1Note');
    state.charts.zwei = spannenChart('ernChart2', 'protein_g', cssVar('--chart-2'), texte,
        'ernChart2Titel', 'ernChart2Sub', 'ernChart2Note');
}

/* ----------------------------------------------------------------- Ziele */

function zeichneZiele() {
    const e = state.einstellungen;
    if (!e) return;
    document.getElementById('ernZiele').innerHTML = e.macros.map(m => `
        <label class="ern-feld">
            <span>${esc(e.macro_labels[m])}${EINHEIT[m] ? ' (g)' : ''}</span>
            <input type="number" min="0" step="${m === 'kcal' ? 10 : 1}" inputmode="decimal"
                   data-ziel="${esc(m)}" value="${e.targets[m] == null ? '' : e.targets[m]}"
                   placeholder="${zahlKurz(e.defaults[m])}">
        </label>`).join('');
}

async function zieleSpeichern() {
    const knopf = document.getElementById('ernZieleSpeichern');
    const ziele = {};
    document.querySelectorAll('[data-ziel]').forEach(f => {
        const roh = String(f.value).replace(',', '.').trim();
        ziele[f.dataset.ziel] = roh ? Number(roh) : null;
    });
    knopf.classList.add('is-loading');
    try {
        state.einstellungen = await API.setzen({ targets: ziele });
        zeichneZiele();
        await ladeTag(state.datum);
        if (state.rangeMount) await ladeVerlauf();
        melde('Ziele gespeichert.', 'success');
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    } finally {
        knopf.classList.remove('is-loading');
    }
}

async function zieleZuruecksetzen() {
    const ok = await askConfirm({
        title: 'Ziele zurücksetzen?',
        text: 'Danach misst jeder Balken wieder am allgemeinen Richtwert — der üblichen '
            + 'Größenordnung für einen Tag, nicht an einem Ziel.',
        confirmText: 'Zurücksetzen',
    });
    if (!ok) return;
    document.querySelectorAll('[data-ziel]').forEach(f => { f.value = ''; });
    await zieleSpeichern();
}

/* ------------------------------------------------------------- Gerichte
 *
 * Der Reiter zeigt die Liste; angelegt und geaendert wird im Dialog. Ein
 * Rezept schreibt man selten und liest es oft -- die Maske dauerhaft ueber
 * die Liste zu legen, drehte das um.
 */

function gerichtDialog(g) {
    state.entwurf = g
        ? { id: g.id, name: g.name,
            items: g.items.map(z => ({ item_id: z.item_id, name: z.name,
                                       amount: z.amount, unit: z.unit, units: z.units })) }
        : { id: null, name: '', items: [] };

    const inhalt = `
        <label class="ern-feld">
            <span>Name</span>
            <input type="text" id="ernGerichtName" autocomplete="off"
                   placeholder="z. B. Wraps" value="${esc(state.entwurf.name)}">
        </label>
        <div id="ernZutaten"></div>
        <label class="ern-suche">
            <span class="ern-suche-ico" aria-hidden="true">➕</span>
            <input type="search" id="ernZutatSuche" autocomplete="off"
                   aria-label="Zutat aus dem Bestand suchen"
                   placeholder="Zutat aus dem Bestand suchen">
        </label>
        <div id="ernZutatTreffer"></div>
        <p class="ern-note">Gramm stehen nur hier im Rezept. Beim Eintragen sagst du danach
            nur noch <em>normal</em> oder <em>übermäßig</em>: wie viel vom eigenen Rezept auf
            dem Teller lag, weiß niemand in Gramm.</p>
        <div class="ern-tasten">
            <button type="button" class="v-btn v-btn--primary" id="ernGerichtSpeichern">${
                state.entwurf.id ? 'Änderung speichern' : 'Gericht speichern'}</button>
        </div>`;

    state.dialog = openModal(state.entwurf.id ? 'Gericht ändern' : 'Neues Gericht', inhalt, {
        breit: true,
        beimSchliessen: () => { state.dialog = null; },
    });

    zeichneEntwurf();
    document.getElementById('ernZutatSuche')
        .addEventListener('input', (e) => zutatSuchen(e.target.value));
    document.getElementById('ernGerichtSpeichern')
        .addEventListener('click', gerichtSpeichern);
}

function zeichneEntwurf() {
    const e = state.entwurf;
    const ziel = document.getElementById('ernZutaten');
    if (!ziel) return;
    ziel.innerHTML = !e.items.length
        ? '<p class="ern-note">Noch keine Zutat. Such unten etwas aus deinem Bestand.</p>'
        : e.items.map((z, i) => `
            <div class="ern-zeile">
                <div class="ern-zeile-text"><strong>${esc(z.name)}</strong></div>
                <div class="ern-menge">
                    <input type="number" min="0.25" step="0.25" value="${z.amount}"
                           data-zmenge="${i}" aria-label="Menge für ${esc(z.name)}">
                    <select class="v-select v-select--sm" data-zeinheit="${i}"
                            aria-label="Einheit für ${esc(z.name)}">
                        ${(z.units || [{ key: 'g', label: 'g' }]).map(u =>
                            `<option value="${esc(u.key)}"${u.key === z.unit ? ' selected' : ''}>${esc(u.label)}</option>`).join('')}
                    </select>
                </div>
                <button type="button" class="v-btn v-btn--icon" data-zutat-weg="${i}"
                        aria-label="Zutat entfernen" title="Entfernen">🗑️</button>
            </div>`).join('');
    ziel.querySelectorAll('[data-zmenge]').forEach(f => f.addEventListener('change', () => {
        const wert = Number(String(f.value).replace(',', '.'));
        if (wert > 0) state.entwurf.items[Number(f.dataset.zmenge)].amount = wert;
    }));
    ziel.querySelectorAll('[data-zeinheit]').forEach(f => f.addEventListener('change', () => {
        state.entwurf.items[Number(f.dataset.zeinheit)].unit = f.value;
    }));
    ziel.querySelectorAll('[data-zutat-weg]').forEach(b => b.addEventListener('click', () => {
        state.entwurf.items.splice(Number(b.dataset.zutatWeg), 1);
        zeichneEntwurf();
    }));
}

function zutatSuchen(text) {
    const ziel = document.getElementById('ernZutatTreffer');
    if (!ziel) return;
    const begriff = text.trim().toLowerCase();
    if (!begriff) { ziel.innerHTML = ''; return; }
    const treffer = state.bestand.filter(p =>
        p.name.toLowerCase().includes(begriff)
        || (p.brand || '').toLowerCase().includes(begriff)).slice(0, 6);
    ziel.innerHTML = !treffer.length
        ? `<p class="ern-note">Nichts im Bestand. Über <strong>Lebensmittel</strong> kommt es hinein.</p>`
        : treffer.map(p => `
            <button type="button" class="v-chip" data-zutat="${p.id}">
                ${esc(p.name)}${p.brand ? ' · ' + esc(p.brand) : ''}
            </button>`).join('');
    ziel.querySelectorAll('[data-zutat]').forEach(b => b.addEventListener('click', () => {
        const p = state.bestand.find(x => x.id === Number(b.dataset.zutat));
        if (!p) return;
        // Die erste eigene Groesse als Vorschlag, wenn es eine gibt:
        // "1 Stueck" trifft haeufiger als "62 g" und ist schneller zu pruefen.
        const einheiten = p.units || [{ key: p.base_unit || 'g', label: p.base_unit || 'g', grams: 1 }];
        const eigene = einheiten.find(u => !BASIS.includes(u.key));
        state.entwurf.items.push({
            item_id: p.id, name: p.name,
            amount: eigene ? 1 : 100,
            unit: eigene ? eigene.key : (p.base_unit || 'g'),
            units: einheiten,
        });
        document.getElementById('ernZutatSuche').value = '';
        ziel.innerHTML = '';
        zeichneEntwurf();
    }));
}

async function gerichtSpeichern() {
    const name = document.getElementById('ernGerichtName').value.trim();
    if (!name) { melde('Das Gericht braucht einen Namen.', 'error'); return; }
    if (!state.entwurf.items.length) { melde('Mindestens eine Zutat.', 'error'); return; }
    const knopf = document.getElementById('ernGerichtSpeichern');
    knopf.classList.add('is-loading');
    try {
        const res = await API.gericht({
            id: state.entwurf.id, name,
            items: state.entwurf.items.map(z => ({
                item_id: z.item_id, amount: z.amount, unit: z.unit })),
        });
        state.gerichte = res.dishes;
        if (state.dialog) state.dialog.close();
        zeichneGerichte();
        melde('Gericht gespeichert.', 'success');
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    } finally {
        knopf.classList.remove('is-loading');
    }
}

async function gerichtLoeschen(id) {
    const g = state.gerichte.find(x => x.id === id);
    const ok = await askConfirm({
        title: 'Gericht löschen?',
        text: `„${g ? g.name : 'Das Gericht'}" verschwindet samt Rezept. Bereits eingetragene Tage verlieren diese Einträge.`,
        confirmText: 'Löschen', danger: true,
    });
    if (!ok) return;
    try {
        await API.gerichtWeg(id);
        await ladeGerichte();
        if (state.tag) await ladeTag(state.datum);
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    }
}

function zeichneGerichte() {
    const ziel = document.getElementById('ernGerichte');
    document.getElementById('ernGerichteZahl').textContent =
        state.gerichte.length ? state.gerichte.length + ' Gerichte' : '';
    ziel.innerHTML = !state.gerichte.length
        ? leerKarte('📖', 'Noch keine Gerichte. Was du oft isst, legst du einmal an — '
            + 'danach reicht ein Tipp am Tag.')
        : state.gerichte.map(g => `
            <div class="ern-zeile">
                <div class="ern-zeile-text">
                    <strong>${esc(g.name)}</strong>
                    <div class="ern-note">${g.items.map(z => {
                        const e = (z.units || []).find(u => u.key === z.unit);
                        return esc(z.name) + ' ' + z.amount + ' ' + esc(e ? e.label : z.unit);
                    }).join(' · ')}</div>
                    <div class="ern-note">${g.portion.kcal != null
                        ? `${zahlKurz(g.portion.kcal)} kcal je Portion (${g.portion.grams} g)`
                        : 'Nährwerte unvollständig'}${g.portion.incomplete.length
                        ? ' · ohne Angabe: ' + g.portion.incomplete.length : ''}</div>
                </div>
                <div class="ern-tasten">
                    <button type="button" class="v-btn v-btn--sm" data-bearbeiten="${g.id}">Ändern</button>
                    <button type="button" class="v-btn v-btn--icon" data-gericht-weg="${g.id}"
                            aria-label="Gericht löschen" title="Löschen">🗑️</button>
                </div>
            </div>`).join('');
    ziel.querySelectorAll('[data-bearbeiten]').forEach(b =>
        b.addEventListener('click', () => {
            const g = state.gerichte.find(x => x.id === Number(b.dataset.bearbeiten));
            if (g) gerichtDialog(g);
        }));
    ziel.querySelectorAll('[data-gericht-weg]').forEach(b =>
        b.addEventListener('click', () => gerichtLoeschen(Number(b.dataset.gerichtWeg))));
}

async function ladeGerichte() {
    try {
        const res = await API.gerichte();
        state.gerichte = res.dishes;
    } catch (e) {
        state.gerichte = [];
    }
    zeichneGerichte();
}

/* ---------------------------------------------------------------- Kamera
 *
 * Zwei Wege, weil kein Browser beide hat:
 *
 *   1. ``BarcodeDetector`` steckt in Chrome und im Android-Browser fest
 *      eingebaut -- nichts nachzuladen, und es erkennt schneller.
 *   2. Safari kennt es nicht (Stand heute). Dort wird ZXing nachgeladen --
 *      erst dann, wenn es gebraucht wird: 300 KB beim Seitenaufruf fuer
 *      einen Knopf, den man selten drueckt, waeren verschenkt.
 *
 * Beide brauchen HTTPS. Auf einer Seite ueber http gibt der Browser die
 * Kamera gar nicht erst frei -- das sagt der Hinweis, statt es an einem
 * stummen Fehler scheitern zu lassen.
 */

const ZXING_CDN = 'https://cdn.jsdelivr.net/npm/@zxing/library@0.21.3/umd/index.min.js';
const FORMATE = ['ean_13', 'ean_8', 'upc_a', 'upc_e'];

const kamera = { stream: null, leser: null, laeuft: false };

function kameraHinweis(text) {
    const el = document.getElementById('ernKameraHinweis');
    if (el) el.textContent = text;
}

async function kameraStarten() {
    if (kamera.laeuft) { kameraStoppen(); return; }
    if (!window.isSecureContext) {
        melde('Die Kamera gibt der Browser nur über HTTPS frei.', 'error');
        return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        melde('Dieser Browser gibt keine Kamera frei.', 'error');
        return;
    }
    document.getElementById('ernKameraBereich').hidden = false;
    document.getElementById('ernKamera').textContent = '📷 Schließen';
    kamera.laeuft = true;
    kameraHinweis('Kamera wird geöffnet …');
    try {
        if ('BarcodeDetector' in window) await mitBarcodeDetector();
        else await mitZXing();
    } catch (err) {
        kameraStoppen();
        // Der Browser sagt selbst, woran es lag (Erlaubnis verweigert, keine
        // Kamera da) -- das ist die bessere Meldung als eine eigene.
        melde(err && err.name === 'NotAllowedError'
            ? 'Der Zugriff auf die Kamera wurde abgelehnt.'
            : (err && err.message) || 'Die Kamera ließ sich nicht öffnen.', 'error');
    }
}

async function mitBarcodeDetector() {
    const video = document.getElementById('ernVideo');
    kamera.stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' } }, audio: false });
    video.srcObject = kamera.stream;
    await video.play();
    const detektor = new window.BarcodeDetector({ formats: FORMATE });
    kameraHinweis('Strichcode ins Bild halten');
    const takt = async () => {
        if (!kamera.laeuft) return;
        try {
            const treffer = await detektor.detect(video);
            if (treffer && treffer.length) return codeGefunden(treffer[0].rawValue);
        } catch (e) { /* einzelne Bilder duerfen misslingen */ }
        // Viermal je Sekunde reicht fuer einen Strichcode und laesst dem
        // Geraet Luft; jedes Bild zu pruefen heizt nur das Telefon.
        setTimeout(takt, 250);
    };
    takt();
}

function ladeZXing() {
    if (window.ZXing) return Promise.resolve(window.ZXing);
    return new Promise((fertig, fehler) => {
        const skript = document.createElement('script');
        skript.src = ZXING_CDN;
        skript.onload = () => fertig(window.ZXing);
        skript.onerror = () => fehler(new Error('Die Scanner-Bibliothek ließ sich nicht laden.'));
        document.head.appendChild(skript);
    });
}

async function mitZXing() {
    kameraHinweis('Scanner wird geladen …');
    const Z = await ladeZXing();
    if (!Z || !Z.BrowserMultiFormatReader) {
        throw new Error('Die Scanner-Bibliothek ließ sich nicht laden.');
    }
    const hinweise = new Map();
    hinweise.set(Z.DecodeHintType.POSSIBLE_FORMATS, [
        Z.BarcodeFormat.EAN_13, Z.BarcodeFormat.EAN_8,
        Z.BarcodeFormat.UPC_A, Z.BarcodeFormat.UPC_E]);
    kamera.leser = new Z.BrowserMultiFormatReader(hinweise, 300);
    kameraHinweis('Strichcode ins Bild halten');
    await kamera.leser.decodeFromVideoDevice(
        null, 'ernVideo', (ergebnis) => {
            if (ergebnis && kamera.laeuft) codeGefunden(ergebnis.getText());
        });
}

function codeGefunden(code) {
    const ziffern = String(code || '').replace(/\D/g, '');
    if (!ziffern) return;
    kameraStoppen();
    // Der Code landet im selben Suchfeld wie ein Name -- und wird sofort
    // nachgeschlagen: wer gerade eine Packung vor die Kamera gehalten hat,
    // will das Ergebnis, nicht noch einen Knopf.
    document.getElementById('ernSuche').value = ziffern;
    suchen(ziffern);
}

function kameraStoppen() {
    kamera.laeuft = false;
    if (kamera.leser) {
        try { kamera.leser.reset(); } catch (e) {}
        kamera.leser = null;
    }
    if (kamera.stream) {
        kamera.stream.getTracks().forEach(spur => spur.stop());
        kamera.stream = null;
    }
    const video = document.getElementById('ernVideo');
    if (video) video.srcObject = null;
    document.getElementById('ernKameraBereich').hidden = true;
    document.getElementById('ernKamera').textContent = '📷 Scannen';
}

/* -------------------------------------------------------- Nachschlagen */

/* Wie alt der Katalog ist, gehoert auf den Bildschirm: ein Nachschlagewerk,
   dessen Stand man nicht sieht, wird irgendwann geglaubt, obwohl es nicht
   mehr stimmt. */
async function katalogStand() {
    let stand;
    try { stand = await API.katalog(); } catch (e) { return; }
    state.katalog = stand;

    const alter = stand.newest
        ? new Date(stand.newest * 1000).toLocaleDateString('de-DE',
            { day: '2-digit', month: '2-digit', year: 'numeric' })
        : null;
    document.getElementById('ernKatalogStand').textContent = stand.count
        ? `eigener Katalog: ${stand.count.toLocaleString('de-DE')} Produkte`
          + (alter ? ` · Stand ${alter}` : '')
        : 'kein eigener Katalog — es wird direkt bei Open Food Facts gefragt';

    // Die Karte zum Einspielen gibt es nur, wenn der Server das Recht dazu
    // meldet -- der Katalog gehoert keinem Nutzer, sondern allen.
    const karte = document.getElementById('ernKatalogKarte');
    karte.hidden = !stand.may_import;
    if (stand.may_import) {
        document.getElementById('ernKatalogKarteSub').textContent = stand.count
            ? `${stand.count.toLocaleString('de-DE')} Produkte drin`
            : 'noch leer';
    }
}

/* Die Ablegeflaeche fuer den Katalog. Dasselbe Muster wie beim
   Ausgaben-Import: klicken, ziehen, Tastatur -- und vor dem Ersetzen steht
   da, was ersetzt wird. */
function setupKatalogDrop() {
    const drop = document.getElementById('ernKatDrop');
    const feld = document.getElementById('ernKatFile');
    if (!drop) return;

    const nimm = (datei) => { if (datei) katalogHochladen(datei); };
    drop.onclick = () => { if (!state.katalogLaeuft) feld.click(); };
    drop.onkeydown = (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); drop.onclick(); }
    };
    drop.ondragover = (e) => { e.preventDefault(); drop.classList.add('drag'); };
    drop.ondragleave = () => drop.classList.remove('drag');
    drop.ondrop = (e) => {
        e.preventDefault();
        drop.classList.remove('drag');
        if (!state.katalogLaeuft) nimm(e.dataTransfer.files && e.dataTransfer.files[0]);
    };
    feld.onchange = () => nimm(feld.files[0]);
}

async function katalogHochladen(datei) {
    const drin = (state.katalog && state.katalog.count) || 0;
    const ok = await askConfirm({
        title: 'Katalog ersetzen?',
        text: drin
            ? `Im Katalog stehen ${drin.toLocaleString('de-DE')} Produkte. `
              + `„${datei.name}" ersetzt sie vollständig — ein Abzug ist ein Stand, `
              + 'zwei nebeneinander wären später nicht zu trennen.'
            : `Der Katalog ist leer. „${datei.name}" legt ihn an.`,
        confirmText: 'Einspielen',
    });
    document.getElementById('ernKatFile').value = '';
    if (!ok) return;

    const drop = document.getElementById('ernKatDrop');
    const sub = document.getElementById('ernKatDropSub');
    state.katalogLaeuft = true;
    drop.classList.add('has-files');
    sub.textContent = `${datei.name} wird eingespielt — das dauert bis zu einer Minute …`;
    try {
        const neu = await API.katalogEinspielen(datei);
        sub.textContent = `${neu.count.toLocaleString('de-DE')} Produkte eingespielt.`;
        melde(`Katalog eingespielt: ${neu.count.toLocaleString('de-DE')} Produkte.`, 'success');
        await katalogStand();
    } catch (err) {
        drop.classList.remove('has-files');
        sub.textContent = 'off-katalog-dach.csv.gz';
        melde(err.message || 'Das Einspielen ging nicht.', 'error');
    } finally {
        state.katalogLaeuft = false;
    }
}

function trefferKarte(produkt, herkunft, bekannt, index) {
    return `<div class="ern-treffer">
        <div class="ern-kopf">
            <strong>${esc(produkt.name)}</strong>
            ${produkt.brand ? `<span class="ern-marke">${esc(produkt.brand)}</span>` : ''}
            <span class="ern-herkunft">${esc(HERKUNFT[herkunft] || 'Open Food Facts')}</span>
        </div>
        <p class="ern-note">${zahl(produkt.kcal, '')} kcal · ${zahl(produkt.protein_g, ' g')} Eiweiß
            · ${zahl(produkt.fiber_g, ' g')} Ballaststoffe · je 100 ${esc(produkt.base_unit || 'g')}</p>
        ${bekannt ? '<p class="ern-note">Schon im Bestand — Übernehmen aktualisiert die Werte.</p>' : ''}
        ${produkt.missing && produkt.missing.length
            ? `<p class="ern-note">Dort fehlen ${produkt.missing.length} Angaben. Du kannst sie nach dem Übernehmen von der Packung nachtragen.</p>`
            : ''}
        <div class="ern-tasten">
            <button type="button" class="v-btn v-btn--sm v-btn--primary"
                    data-treffer="${index}">In den Bestand</button>
        </div>
    </div>`;
}

/* Ein Suchfeld fuer beides. Ziffern sind ein Strichcode, alles andere ein
   Name -- den Nutzer vorher zu fragen, waere eine Frage nach etwas, das an
   den Zeichen schon abzulesen ist. */
const istBarcode = (t) => /^\d{6,14}$/.test(t.replace(/\s/g, ''));

async function suchen(text) {
    const ziel = document.getElementById('ernTreffer');
    const begriff = (text || '').trim();
    if (begriff.length < 2) { ziel.innerHTML = ''; return; }
    ziel.innerHTML = '<span class="skel skel-block"></span>';

    if (istBarcode(begriff)) {
        try {
            const res = await API.barcode(begriff.replace(/\s/g, ''));
            if (!res.found && res.known) {
                ziel.innerHTML = `<div class="ern-treffer">
                    <div class="ern-kopf"><strong>${esc(res.known.name)}</strong>
                        <span class="ern-herkunft">schon im Bestand</span></div>
                    ${naehrwertZeile(res.known)}
                    ${res.note ? `<p class="ern-note">${esc(res.note)}</p>` : ''}
                </div>`;
                return;
            }
            if (!res.found) { ziel.innerHTML = leerKarte('🔎', 'Zu diesem Strichcode ist nichts hinterlegt.'); return; }
            ziel.innerHTML = trefferKarte(res.product, res.origin, res.known, 0);
            ziel.querySelectorAll('[data-treffer]').forEach(b =>
                b.addEventListener('click', () => uebernehmen(res.product)));
        } catch (err) {
            ziel.innerHTML = leerKarte('🔎', esc(err.message || 'Nicht gefunden.'));
        }
        return;
    }

    try {
        const res = await API.suche(begriff);
        if (!res.results.length) {
            ziel.innerHTML = leerKarte('🔎',
                'Nichts gefunden. Bei Losem ohne Strichcode lohnt sich oft ein '
                + 'allgemeinerer Begriff — „Apfel" statt „Apfel Elstar".');
            return;
        }
        ziel.innerHTML = `<p class="ern-note">${res.results.length} Treffer aus
            ${esc(HERKUNFT[res.origin] || 'Open Food Facts')}</p>`
            + res.results.map((p, i) => trefferKarte(p, res.origin, null, i)).join('');
        ziel.querySelectorAll('[data-treffer]').forEach(b =>
            b.addEventListener('click', () => uebernehmen(res.results[Number(b.dataset.treffer)])));
    } catch (err) {
        ziel.innerHTML = `<div class="empty is-error"><span class="empty-mark">⚠️</span>
            <p class="empty-text">${esc(err.message || 'Die Suche ging nicht.')}</p></div>`;
    }
}

async function uebernehmen(produkt) {
    try {
        const antwort = await API.aufnehmen({
            name: produkt.name, brand: produkt.brand, barcode: produkt.barcode,
            source: 'off', kcal: produkt.kcal, protein_g: produkt.protein_g,
            carbs_g: produkt.carbs_g, sugar_g: produkt.sugar_g,
            fat_g: produkt.fat_g, sat_fat_g: produkt.sat_fat_g,
            fiber_g: produkt.fiber_g, salt_g: produkt.salt_g,
            portion_g: produkt.portion_g,
            // Der eigene Katalog weiss, ob sich die Angaben auf 100 g oder
            // 100 ml beziehen -- bei einem Getraenk waere "100 g" schlicht
            // falsch abgelesen.
            base_unit: produkt.base_unit || 'g',
        });
        await ladeBestand();
        const neu = antwort && antwort.item;
        // Ohne Portionsgroesse laesst sich spaeter nur "100 g" eintragen.
        // Statt das stillschweigend hinzunehmen, steht der Dialog gleich
        // offen -- ein Feld ausfuellen ist leichter, als den Eintrag spaeter
        // wiederzufinden.
        if (neu && !(neu.sizes || []).length) {
            itemDialog(neu);
            melde('Aufgenommen. Trag noch ein, was eine Einheit wiegt — dann '
                + 'kannst du „2 × Scheibe" eintragen statt in Gramm zu rechnen.', 'info');
        } else {
            melde('In den Bestand aufgenommen.', 'success');
        }
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    }
}

/* ------------------------------------------------- Anlegen und Aendern
 *
 * Derselbe Dialog fuer beides. Ein zweites Formular zum Bearbeiten waere
 * dieselbe Maske zweimal -- und zwei Stellen, an denen ein Feld fehlen kann.
 * Leere Felder bleiben leer: null heisst "keine Angabe" und ist etwas
 * anderes als 0.
 */

const FORM = {
    fName: 'name', fBrand: 'brand', fBase: 'base_unit',
    fKcal: 'kcal', fProtein: 'protein_g', fFiber: 'fiber_g',
    fCarbs: 'carbs_g', fFat: 'fat_g',
};
const ZAHLENFELDER = ['fKcal', 'fProtein', 'fFiber', 'fCarbs', 'fFat'];

let bearbeitet = null;   // id des Lebensmittels, das gerade geaendert wird

function itemDialog(p) {
    bearbeitet = p ? p.id : null;
    state.formGroessen = p ? (p.sizes || []).map(g => ({ label: g.label, grams: g.grams })) : [];

    const inhalt = `
        <div class="ern-gitter">
            <label class="ern-feld ern-feld--breit">
                <span>Name</span>
                <input type="text" id="fName" autocomplete="off" placeholder="z. B. Omas Gulasch">
            </label>
            <label class="ern-feld">
                <span>Marke oder Quelle</span>
                <input type="text" id="fBrand" autocomplete="off" placeholder="optional">
            </label>
            <label class="ern-feld">
                <span>Angaben beziehen sich auf</span>
                <select class="v-select" id="fBase">
                    <option value="g">100 g (fest)</option>
                    <option value="ml">100 ml (flüssig)</option>
                </select>
            </label>
        </div>
        <div class="ern-gitter">
            <label class="ern-feld"><span>Kalorien</span>
                <input type="number" id="fKcal" min="0" step="1" inputmode="decimal"></label>
            <label class="ern-feld"><span>Eiweiß (g)</span>
                <input type="number" id="fProtein" min="0" step="0.1" inputmode="decimal"></label>
            <label class="ern-feld"><span>Ballaststoffe (g)</span>
                <input type="number" id="fFiber" min="0" step="0.1" inputmode="decimal"></label>
            <label class="ern-feld"><span>Kohlenhydrate (g)</span>
                <input type="number" id="fCarbs" min="0" step="0.1" inputmode="decimal"></label>
            <label class="ern-feld"><span>Fett (g)</span>
                <input type="number" id="fFat" min="0" step="0.1" inputmode="decimal"></label>
        </div>
        <p class="ern-note">Leer lassen, was du nicht weißt — leer heißt „keine Angabe" und
            wird später als Lücke ausgewiesen, nicht als Null verrechnet.</p>

        <div class="ern-groessen-kopf">
            <h4>Eigene Größen</h4>
            <button type="button" class="v-btn v-btn--sm" id="fGroesseNeu">Größe hinzufügen</button>
        </div>
        <div class="ern-groessen" id="fGroessen"></div>
        <p class="ern-note">Jede Zeile ist eine Einheit, die du beim Eintragen auswählen
            kannst — „2 × Scheibe" statt „90 g". Die <strong>erste</strong> Zeile ist die
            Standardgröße.</p>

        <div class="ern-tasten">
            <button type="button" class="v-btn v-btn--primary" id="fSpeichern">${
                p ? 'Änderung speichern' : 'Aufnehmen'}</button>
        </div>`;

    state.dialog = openModal(p ? 'Lebensmittel ändern' : 'Von Hand anlegen', inhalt, {
        breit: true,
        beimSchliessen: () => { state.dialog = null; bearbeitet = null; },
    });

    Object.entries(FORM).forEach(([id, feld]) => {
        const el = document.getElementById(id);
        if (el) el.value = p && p[feld] != null ? p[feld] : (id === 'fBase' ? 'g' : '');
    });
    document.getElementById('fBase').value = (p && p.base_unit) || 'g';
    zeichneGroessen();

    document.getElementById('fGroesseNeu').addEventListener('click', () => {
        state.formGroessen.push({ label: '', grams: null });
        zeichneGroessen();
    });
    document.getElementById('fBase').addEventListener('change', zeichneGroessen);
    document.getElementById('fSpeichern').addEventListener('click', formSpeichern);
}

/* Die eigenen Groessen sind eine Liste, kein festes Feldpaar: dasselbe
   Lebensmittel hat oft mehrere (Scheibe, Laib, Packung), und wer nur eine
   hinterlegen kann, rechnet den Rest jedes Mal im Kopf. */
function zeichneGroessen() {
    const ziel = document.getElementById('fGroessen');
    if (!ziel) return;
    const basis = document.getElementById('fBase').value || 'g';
    ziel.innerHTML = !state.formGroessen.length
        ? `<p class="ern-note">Noch keine eigene Größe. Ohne eine trägst du dieses
           Lebensmittel in ${basis} ein — das reicht für Loses völlig.</p>`
        : state.formGroessen.map((g, i) => `
            <div class="ern-groesse">
                <input type="text" list="ernGroessenVorschlaege" data-g-label="${i}"
                       value="${esc(g.label)}" autocomplete="off"
                       placeholder="Scheibe" aria-label="Bezeichnung der ${i + 1}. Größe">
                <span class="ern-groesse-ist" aria-hidden="true">=</span>
                <input type="number" min="0" step="0.1" inputmode="decimal"
                       data-g-gramm="${i}" value="${g.grams == null ? '' : g.grams}"
                       placeholder="45" aria-label="Gewicht der ${i + 1}. Größe">
                <span class="ern-groesse-basis">${esc(basis)}</span>
                <button type="button" class="v-btn v-btn--icon" data-g-weg="${i}"
                        aria-label="Größe entfernen" title="Entfernen">🗑️</button>
            </div>`).join('');

    // Waehrend des Tippens in den Zustand schreiben, aber NICHT neu zeichnen:
    // ein Neuaufbau bei jedem Zeichen nimmt dem Feld den Fokus.
    ziel.querySelectorAll('[data-g-label]').forEach(f => f.addEventListener('input', () => {
        state.formGroessen[Number(f.dataset.gLabel)].label = f.value;
    }));
    ziel.querySelectorAll('[data-g-gramm]').forEach(f => f.addEventListener('input', () => {
        const roh = String(f.value).replace(',', '.').trim();
        state.formGroessen[Number(f.dataset.gGramm)].grams = roh ? Number(roh) : null;
    }));
    ziel.querySelectorAll('[data-g-weg]').forEach(b => b.addEventListener('click', () => {
        state.formGroessen.splice(Number(b.dataset.gWeg), 1);
        zeichneGroessen();
    }));
}

async function formSpeichern() {
    const wert = (id) => {
        const roh = document.getElementById(id).value.trim();
        if (!roh) return null;
        return ZAHLENFELDER.includes(id) ? Number(roh.replace(',', '.')) : roh;
    };
    const daten = { source: 'eigen', user_edited: true };
    Object.entries(FORM).forEach(([id, feld]) => { daten[feld] = wert(id); });
    daten.base_unit = document.getElementById('fBase').value || 'g';
    // Leere Zeilen fallen weg; den Rest prueft der Server und sagt, was fehlt.
    daten.sizes = state.formGroessen.filter(g => (g.label || '').trim() || g.grams);
    if (!daten.name) { melde('Ohne Namen geht es nicht.', 'error'); return; }
    if (bearbeitet) daten.id = bearbeitet;

    const knopf = document.getElementById('fSpeichern');
    knopf.classList.add('is-loading');
    try {
        await API.aufnehmen(daten);
        if (state.dialog) state.dialog.close();
        await ladeBestand();
        await ladeGerichte();
        melde('Gespeichert.', 'success');
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    } finally {
        knopf.classList.remove('is-loading');
    }
}

/* ------------------------------------------------------------- Bestand */

async function ladeBestand() {
    const ziel = document.getElementById('ernBestand');
    try {
        const res = await API.bestand();
        state.bestand = res.items;
        if (res.size_suggestions) {
            state.groessenVorschlaege = res.size_suggestions;
            document.getElementById('ernGroessenVorschlaege').innerHTML =
                res.size_suggestions.map(v => `<option value="${esc(v)}"></option>`).join('');
        }
    } catch (err) {
        ziel.innerHTML = `<div class="empty is-error"><span class="empty-mark">⚠️</span>
            <p class="empty-text">Der Bestand konnte nicht geladen werden.</p></div>`;
        return;
    }
    document.getElementById('ernBestandZahl').textContent =
        state.bestand.length ? state.bestand.length + ' Lebensmittel' : '';
    if (!state.bestand.length) {
        ziel.innerHTML = leerKarte('🥫',
            'Noch nichts aufgenommen. Was einmal hier steht, bleibt — auch wenn '
            + 'Open Food Facts den Eintrag später ändert.');
        return;
    }
    ziel.innerHTML = state.bestand.map(p => `
        <div class="ern-zeile">
            <div class="ern-zeile-text">
                <div class="ern-zeile-kopf"><strong>${esc(p.name)}</strong>
                    ${p.brand ? `<span class="ern-marke">${esc(p.brand)}</span>` : ''}</div>
                <div class="ern-note">${zahl(p.kcal, '')} kcal · ${zahl(p.protein_g, ' g')} Eiweiß
                    · ${zahl(p.fiber_g, ' g')} Ballaststoffe · je 100 ${esc(p.base_unit || 'g')}</div>
                <div class="ern-note">${(p.sizes || []).length
                    ? (p.sizes || []).map(g =>
                        `${esc(g.label)} = ${g.grams} ${esc(p.base_unit || 'g')}`).join(' · ')
                    : 'keine eigene Größe — wird in ' + esc(p.base_unit || 'g') + ' eingetragen'
                }${p.user_edited ? ' · von Hand gepflegt' : ''}</div>
            </div>
            <div class="ern-tasten">
                <button type="button" class="v-btn v-btn--sm" data-aendern="${p.id}">Ändern</button>
                <button type="button" class="v-btn v-btn--icon" data-weg="${p.id}"
                        aria-label="Entfernen" title="Entfernen">🗑️</button>
            </div>
        </div>`).join('');
    ziel.querySelectorAll('[data-weg]').forEach(b =>
        b.addEventListener('click', () => entfernen(Number(b.dataset.weg))));
    ziel.querySelectorAll('[data-aendern]').forEach(b => b.addEventListener('click', () => {
        const p = state.bestand.find(x => x.id === Number(b.dataset.aendern));
        if (p) itemDialog(p);
    }));
}

async function entfernen(id) {
    const p = state.bestand.find(x => x.id === id);
    // Ein geloeschtes Lebensmittel verschwindet auch aus jedem Gericht, in
    // dem es steckt -- ohne Warnung faende man das erst wieder, wenn die
    // Naehrwerte eines Rezepts ploetzlich niedriger sind.
    const betroffen = state.gerichte.filter(g => g.items.some(z => z.item_id === id));
    const ok = await askConfirm({
        title: 'Entfernen?',
        text: `„${p ? p.name : 'Das Lebensmittel'}" wird aus dem Bestand gelöscht.`
            + (betroffen.length
                ? ` Es steckt in ${betroffen.length === 1 ? 'einem Gericht' : betroffen.length + ' Gerichten'}`
                  + ` (${betroffen.map(g => g.name).join(', ')}) und fällt dort ersatzlos heraus.`
                : ''),
        confirmText: 'Entfernen', danger: true,
    });
    if (!ok) return;
    try {
        await API.entfernen(id);
        await ladeBestand();
        // Die Gerichte haben sich mit geaendert -- ihre Naehrwerte auch.
        await ladeGerichte();
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    }
}

/* ------------------------------------------------------------------ Boot */

document.addEventListener('DOMContentLoaded', async () => {
    if (!isLoggedIn()) { location.href = '/private/login.html'; return; }
    // Freigabe direkt nach dem synchronen Login-Check (css/statistics.css
    // versteckt den Body, bis sie kommt).
    document.body.classList.add('ready');

    try {
        const me = await fetchMe();
        document.getElementById('userLabel').textContent = '👤 ' + me.username;
    } catch (e) { /* Name ist Beiwerk */ }

    document.getElementById('logoutBtn').addEventListener('click',
        () => { clearToken(); location.href = '/private/login.html'; });

    document.querySelectorAll('[data-modus]').forEach(b =>
        b.addEventListener('click', () => modusWechseln(b.dataset.modus)));

    document.getElementById('ernTagZurueck').addEventListener('click', () => tagVerschieben(-1));
    document.getElementById('ernTagVor').addEventListener('click', () => tagVerschieben(1));
    document.getElementById('ernTagAdd').addEventListener('click',
        () => eintragDialog(mahlzeitJetzt()));

    document.getElementById('ernZieleSpeichern').addEventListener('click', zieleSpeichern);
    document.getElementById('ernZieleWeg').addEventListener('click', zieleZuruecksetzen);

    document.getElementById('ernGerichtNeu').addEventListener('click', () => gerichtDialog(null));
    document.getElementById('ernItemNeu').addEventListener('click', () => itemDialog(null));

    document.getElementById('ernKamera').addEventListener('click', kameraStarten);
    document.getElementById('ernKameraStop').addEventListener('click', kameraStoppen);
    let suchTakt = null;
    const suchFeld = document.getElementById('ernSuche');
    suchFeld.addEventListener('input', (e) => {
        clearTimeout(suchTakt);
        const wert = e.target.value.trim();
        // Ein Strichcode ist fertig, sobald er da ist -- ein Name wird noch
        // getippt. Deshalb zwei Takte statt einem.
        suchTakt = setTimeout(() => suchen(wert), istBarcode(wert) ? 120 : 400);
    });
    suchFeld.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        clearTimeout(suchTakt);
        suchen(e.target.value.trim());
    });

    setupKatalogDrop();
    // Die Kamera nicht weiterlaufen lassen, wenn die Seite in den
    // Hintergrund geht -- ein laufendes Bild kostet Akku und sieht aus wie
    // ein Fehler, wenn man zurueckkommt.
    document.addEventListener('visibilitychange', () => {
        if (document.hidden && kamera.laeuft) kameraStoppen();
    });

    // Erst der Modus: er bestimmt, welche Reiter es gibt.
    try {
        state.einstellungen = await API.einstellungen();
        state.modus = state.einstellungen.mode;
    } catch (e) { /* der lockere Modus ist der Standard */ }
    zeichneModus();
    zeichneZiele();

    await ladeTag(heute());
    await Promise.all([ladeGerichte(), ladeBestand(), ladeHaeufig(), katalogStand()]);
});
