/* ernaehrung.js — v1.94.1
 *
 * Das Ernaehrungs-Modul, in zwei Betriebsarten auf EINEM Tagebuch.
 *
 *   📓 Tagebuch (locker)
 *      Was gab es, und war es normal oder uebermaessig viel? Mehr wird nicht
 *      gefragt. Ein Eintrag darf ein frei getippter Name sein -- "Pizza beim
 *      Italiener" steht in keinem Bestand und soll trotzdem im Tag stehen.
 *      Die Vorschlagsliste kommt aus dem Tagebuch selbst: nach ein paar
 *      Tagen steht genau das zur Auswahl, was man wirklich isst.
 *
 *   📊 Tracker (ausfuehrlich)
 *      Mengen in eigenen Einheiten, Naehrwerte als Spanne, eigene Tagesziele
 *      und ein Verlauf ueber den Zeitraum. Dazu die Werkstatt: Gerichte,
 *      Bestand, Scanner.
 *
 * Vier Entscheidungen, die das Modul tragen:
 *
 *   1. **Der Modus ist die Frage, nicht die Ansicht.** Er bestimmt, wonach
 *      gefragt wird -- Stufe oder Menge -- und deshalb auch, welche Reiter
 *      es gibt. Beide schreiben in dasselbe Tagebuch: ein locker notierter
 *      Tag laesst sich spaeter genauer machen, und ein Wechsel laesst nie
 *      etwas verschwinden.
 *   2. **Was geschaetzt ist, bleibt eine Spanne.** Aus zwei Grobstufen eine
 *      Zahl zu machen waere eine Genauigkeit, die es nie gab. Ein gewogener
 *      Eintrag ist eine Spanne der Breite null und macht den Tag schmaler.
 *   3. **Eine Luecke ist keine Null.** Ein freier Eintrag hat keine
 *      Naehrwerte; die Tagessumme sagt, dass sie ihn nicht enthaelt, statt
 *      ihn stillschweigend mit null zu verrechnen.
 *   4. **Fremde Daten bleiben fremd.** Was von Open Food Facts kommt, ist
 *      ein Vorschlag: aenderbar, als Herkunft erkennbar, mit Luecken.
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

const MODUS_SATZ = {
    locker: 'Hinschreiben, was es gab, und ob es normal oder übermäßig viel war. '
        + 'Mehr wird nicht gefragt — auch Dinge, die in keiner Liste stehen.',
    ausfuehrlich: 'Mengen, Nährwerte und eigene Tagesziele. Dazu die Werkstatt: '
        + 'Gerichte, Bestand und Scanner.',
};

// Die beiden Einheiten, in denen die Naehrwerte stehen. Alles andere ist
// eine eigene Groesse des Lebensmittels und traegt ihren Namen als
// Schluessel -- "Scheibe", "Laib", "Becher".
const BASIS = ['g', 'ml'];

const STUFEN = [
    { key: 'normal', label: 'normal' },
    { key: 'viel', label: 'übermäßig' },
];

const state = {
    modus: 'locker', einstellungen: null,
    bestand: [], vorschlag: null, groessenVorschlaege: [],
    katalog: null, katalogLaeuft: false,
    formGroessen: [],
    tag: null, datum: null, gerichte: [], haeufig: [],
    eingabe: '', mahlzeit: null, tippen: null,
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

/* ---------------------------------------------------------------- Modus */

const istLocker = () => state.modus === 'locker';

function zeichneModus() {
    document.querySelectorAll('[data-modus]').forEach(b => {
        const aktiv = b.dataset.modus === state.modus;
        b.classList.toggle('is-active', aktiv);
        b.setAttribute('aria-pressed', aktiv ? 'true' : 'false');
    });
    document.getElementById('ernModusSatz').textContent = MODUS_SATZ[state.modus];

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
    document.getElementById('ernEingabeTitel').textContent =
        istLocker() ? 'Was gab es?' : 'Eintragen';
}

async function modusWechseln(modus) {
    if (modus === state.modus) return;
    state.modus = modus;
    zeichneModus();
    zeichneTag();
    zeichneVorschlaege();
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

/* Das Tagesbild. Im Tagebuch ist die Zahl der Eintraege und ihre Verteilung
   die Auskunft -- eine Kalorienzahl kann es dort gar nicht geben. Im Tracker
   steht die Spanne oben und daneben, was bis zum Ziel noch fehlt. */
function zeichneTagBild() {
    const ziel = document.getElementById('ernTagBild');
    const sub = document.getElementById('ernTagSub');
    const t = state.tag;
    if (!t) { ziel.innerHTML = '<span class="skel skel-block"></span>'; return; }

    const c = t.counts;
    if (!c.entries) {
        sub.textContent = '';
        ziel.innerHTML = leerKarte('🍽️', istLocker()
            ? 'Für diesen Tag steht noch nichts da. Oben hinschreiben, was es gab — '
              + 'ein Wort reicht.'
            : 'Für diesen Tag ist noch nichts eingetragen.');
        return;
    }

    sub.textContent = `${c.entries} ${c.entries === 1 ? 'Eintrag' : 'Einträge'}`;
    const kcal = t.totals.kcal;
    const bekannt = c.entries - c.unknown;

    // Die Kalorienzeile steht nur da, wenn wenigstens ein Eintrag Naehrwerte
    // hat -- sonst waere "0 kcal" eine Behauptung ueber einen Tag, von dem
    // wir nur die Namen kennen.
    const kcalZeile = !bekannt ? ''
        : `<div class="ern-gross">
               <span>${zahlKurz(kcal.min)}</span>
               ${kcal.min === kcal.max ? '' : `<span class="ern-bis">bis</span>
               <span>${zahlKurz(kcal.max)}</span>`}
               <span class="ern-einheit">kcal</span>
           </div>`;

    const luecke = c.unknown
        ? `<span class="v-tag v-tag--warn">${c.unknown} ohne Nährwerte</span>` : '';
    const stufen = `<span class="ern-punkt is-normal" aria-hidden="true"></span> ${c.normal} normal`
        + ` <span class="ern-punkt is-viel" aria-hidden="true"></span> ${c.viel} übermäßig`
        + (c.exact ? ` <span class="ern-punkt is-exakt" aria-hidden="true"></span> ${c.exact} abgewogen` : '');

    if (istLocker()) {
        ziel.innerHTML = `
            <div class="ern-gross"><span>${c.entries}</span>
                <span class="ern-einheit">${c.entries === 1 ? 'Eintrag' : 'Einträge'}</span></div>
            <p class="ern-stufenzeile">${stufen}</p>
            ${bekannt ? `<p class="ern-note">Grob gerechnet ${zahlKurz(kcal.min)}–${zahlKurz(kcal.max)} kcal
                aus ${bekannt} von ${c.entries} Einträgen. ${luecke}</p>`
              : `<p class="ern-note">Zu keinem dieser Einträge sind Nährwerte hinterlegt —
                 im Tagebuch ist das kein Mangel, sondern der Punkt.</p>`}`;
        return;
    }

    const rest = kcal.remaining_max > 0
        ? (kcal.remaining_min === kcal.remaining_max
            ? `Noch ${zahlKurz(kcal.remaining_min)} kcal bis zum ${kcal.own_target ? 'Ziel' : 'Richtwert'}.`
            : `Noch ${zahlKurz(kcal.remaining_min)}–${zahlKurz(kcal.remaining_max)} kcal bis zum ${kcal.own_target ? 'Ziel' : 'Richtwert'}.`)
        : `Der ${kcal.own_target ? 'Zielwert' : 'Richtwert'} von ${zahlKurz(kcal.reference)} kcal ist erreicht.`;

    ziel.innerHTML = `${kcalZeile}
        <p class="ern-stufenzeile">${stufen}</p>
        <p class="ern-note">${rest} ${kcal.incomplete
            ? 'Die Spanne ist eine Untergrenze — zu manchen Einträgen fehlen Angaben. ' : ''}${luecke}</p>`;
}

/* Ein Band je Naehrwert: die Spur reicht bis zum Anderthalbfachen des
   Massstabs, der Massstab selbst steht als Strich darin. Gefuellt ist genau
   der Bereich zwischen der unteren und der oberen Schaetzung -- die Breite
   des Balkens IST die Unsicherheit. Nur im Tracker: im Tagebuch waere ein
   Balken gegen ein Ziel eine Bewertung von Zahlen, die es nicht gibt. */
function band(makro, d) {
    const links = Math.min(100, (d.share_min / 1.5) * 100);
    const breite = Math.max(2, Math.min(100 - links, ((d.share_max - d.share_min) / 1.5) * 100));
    const e = EINHEIT[makro] || '';
    return `<div class="ern-band${d.incomplete ? ' is-unvollstaendig' : ''}">
        <div class="ern-band-kopf">
            <span class="ern-band-lbl">${esc(d.label)}</span>
            <span class="ern-band-wert">${d.incomplete ? 'mind. ' : ''}${zahlKurz(d.min)}–${zahlKurz(d.max)}${e}</span>
        </div>
        <div class="ern-band-spur" role="img"
             aria-label="${esc(d.label)}: ${zahlKurz(d.min)} bis ${zahlKurz(d.max)}${e}, ${
                d.own_target ? 'Ziel' : 'Richtwert'} ${zahlKurz(d.reference)}${e}">
            <span class="ern-band-marke" style="left:66.7%"></span>
            <span class="ern-band-fuell" style="left:${links.toFixed(1)}%;width:${breite.toFixed(1)}%"></span>
        </div>
        <div class="ern-band-fuss">${d.own_target ? 'Ziel' : 'Richtwert'} ${zahlKurz(d.reference)}${e}${
            d.incomplete ? ' · eine Zutat macht dazu keine Angabe, der Wert ist mindestens so hoch' : ''}</div>
    </div>`;
}

function zeichneBaender() {
    const ziel = document.getElementById('ernBaender');
    const t = state.tag;
    if (!t || istLocker() || !t.counts.entries) { ziel.innerHTML = ''; return; }
    const eigene = t.macros.some(m => t.totals[m].own_target);
    ziel.innerHTML = t.macros.filter(m => m !== 'kcal').map(m => band(m, t.totals[m])).join('')
        + `<p class="ern-note">Der Strich im Balken ist der Maßstab. ${
            eigene ? t.target_note + ' Wo keines gesetzt ist, gilt der allgemeine Richtwert.'
                   : t.reference_note + ' Eigene Ziele setzt du unter Verlauf.'}</p>`;
}

/* Der Tag nach Mahlzeiten. "Mittag" ist die Auskunft, die man geben kann --
   eine Uhrzeit waere eine, die man erfinden muesste. */
function zeichneEintraege() {
    const ziel = document.getElementById('ernEintraege');
    const t = state.tag;
    if (!t) { ziel.innerHTML = '<span class="skel skel-block"></span>'; return; }

    document.getElementById('ernEintraegeZahl').textContent =
        t.entries.length ? t.entries.length + ' an diesem Tag' : '';

    if (!t.entries.length) {
        ziel.innerHTML = leerKarte('🍽️', istLocker()
            ? 'Noch nichts notiert. Oben tippen, was es gab, dann <strong>normal</strong> '
              + 'oder <strong>übermäßig</strong> — fertig.'
            : 'Noch nichts eingetragen. Ein Gericht oben antippen — normal oder übermäßig. '
              + 'Bei einem einzelnen Lebensmittel sagst du, wie viel: 100 g, zwei Scheiben, '
              + 'eine Packung.');
        return;
    }

    const bloecke = t.meals.map(m => {
        const eigene = t.entries.filter(e => e.meal === m.key);
        if (!eigene.length) return '';
        const kcalSumme = eigene.reduce((a, e) => ({
            min: a.min + (e.kcal_min || 0), max: a.max + (e.kcal_max || 0),
            offen: a.offen || !e.has_nutrition,
        }), { min: 0, max: 0, offen: false });
        const summe = istLocker() || !(kcalSumme.max > 0) ? ''
            : `<span class="ern-mahlzeit-summe">${kcalSumme.offen ? 'mind. ' : ''}${
                zahlKurz(kcalSumme.min)}–${zahlKurz(kcalSumme.max)} kcal</span>`;
        return `<div class="ern-mahlzeit">
            <div class="ern-mahlzeit-kopf">
                <span class="ern-mahlzeit-name">${esc(m.label)}</span>${summe}
            </div>
            ${eigene.map(eintragZeile).join('')}
        </div>`;
    }).join('');

    ziel.innerHTML = bloecke;

    ziel.querySelectorAll('[data-eintrag-weg]').forEach(b =>
        b.addEventListener('click', () => eintragEntfernen(Number(b.dataset.eintragWeg))));
    ziel.querySelectorAll('[data-stufe-um]').forEach(b =>
        b.addEventListener('click', () => stufeUmschalten(
            Number(b.dataset.stufeUm), b.dataset.stufeNeu)));
}

function eintragZeile(e) {
    const stufe = e.level && !e.amount_label
        ? `<button type="button" class="ern-stufe is-${esc(e.level)}"
               data-stufe-um="${e.id}" data-stufe-neu="${e.level === 'viel' ? 'normal' : 'viel'}"
               title="Umstellen auf ${e.level === 'viel' ? 'normal' : 'übermäßig'}">${
               esc(e.level_label || '')}</button>`
        : (e.amount_label ? `<span class="ern-stufe is-exakt">${esc(e.amount_label)}</span>` : '');

    const meta = [
        e.kind === 'free' ? 'frei notiert' : esc(e.sub || ''),
        e.has_nutrition && e.kcal_min != null
            ? (e.kcal_min === e.kcal_max
                ? `${zahlKurz(e.kcal_min)} kcal`
                : `${zahlKurz(e.kcal_min)}–${zahlKurz(e.kcal_max)} kcal`)
            : 'ohne Nährwerte',
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

/* -------------------------------------------------------------- Eingabe */

function zeichneMahlzeiten() {
    const ziel = document.getElementById('ernMahlzeiten');
    const liste = (state.tag && state.tag.meals) || [];
    // "Ohne Zuordnung" ist der Standard und braucht keinen eigenen Chip --
    // wer nichts waehlt, hat nichts gewaehlt.
    ziel.innerHTML = liste.filter(m => m.key !== 'ohne').map(m =>
        `<button type="button" class="v-chip${state.mahlzeit === m.key ? ' is-active' : ''}"
            data-mahlzeit="${esc(m.key)}">${esc(m.label)}</button>`).join('')
        + `<button type="button" class="v-chip${state.mahlzeit ? '' : ' is-active'}"
            data-mahlzeit="">ohne</button>`;
    ziel.querySelectorAll('[data-mahlzeit]').forEach(b => b.addEventListener('click', () => {
        state.mahlzeit = b.dataset.mahlzeit || null;
        zeichneMahlzeiten();
    }));
}

/* Alle Vorschläge haben DIESELBE Zeilenform: Name links, Bedienung rechts.
   Was rechts steht, haengt am Modus und an der Art -- ein Gericht wird in
   Stufen gegessen, ein Lebensmittel im Tracker in Mengen. */
function vorschlagZeile(v) {
    const mengenFeld = !istLocker() && v.kind === 'item' && v.item;
    let rechts;
    if (mengenFeld) {
        const einheiten = v.item.units
            || [{ key: v.item.base_unit || 'g', label: v.item.base_unit || 'g' }];
        const eigene = einheiten.filter(e => !BASIS.includes(e.key));
        const start = eigene.length ? eigene[0] : einheiten[0];
        rechts = `<div class="ern-menge">
            <input type="number" min="0" step="0.25"
                   inputmode="decimal" value="${eigene.length ? 1 : 100}"
                   data-menge="${v.item.id}" aria-label="Menge für ${esc(v.name)}">
            <select class="v-select v-select--sm" data-einheit="${v.item.id}"
                    aria-label="Einheit für ${esc(v.name)}">
                ${einheiten.map(e => `<option value="${esc(e.key)}"${
                    e.key === start.key ? ' selected' : ''}>${esc(e.label)}</option>`).join('')}
            </select>
            <button type="button" class="v-btn v-btn--sm v-btn--primary"
                    data-log-item="${v.item.id}">Eintragen</button>
        </div>`;
    } else {
        rechts = `<div class="ern-stufen">${STUFEN.map(s =>
            `<button type="button" class="v-btn v-btn--sm${s.key === 'viel' ? '' : ' v-btn--primary'}"
                data-log-stufe="${s.key}" data-log-art="${esc(v.kind)}"
                data-log-id="${v.dish_id || v.item_id || ''}"
                data-log-name="${esc(v.name)}">${s.label}</button>`).join('')}</div>`;
    }
    return `<div class="ern-vorschlag${v.neu ? ' is-neu' : ''}">
        <div class="ern-zeile-text">
            <div class="ern-zeile-kopf"><strong>${esc(v.name)}</strong></div>
            <div class="ern-note">${esc(v.sub || '')}</div>
        </div>
        ${rechts}
    </div>`;
}

/* Woraus die Liste besteht:
     1. der frei getippte Text -- der Weg, der ohne Bestand auskommt,
     2. was im Bestand dazu passt (Gerichte, Lebensmittel),
     3. was man oft eintraegt, aus dem Tagebuch selbst gezaehlt.
   Im Tagebuch steht 1 obenan, im Tracker 2: dort tippt man einen Namen, um
   etwas zu finden, hier, um etwas hinzuschreiben. */
function zeichneVorschlaege() {
    const ziel = document.getElementById('ernVorschlaege');
    const sub = document.getElementById('ernEingabeSub');
    const text = (state.eingabe || '').trim();
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

    const liste = istLocker()
        ? frei.concat(haeufig, gerichte)
        : frei.concat(gerichte, lebensmittel, haeufig);

    if (!liste.length) {
        sub.textContent = '';
        ziel.innerHTML = leerKarte('✏️', istLocker()
            ? 'Tipp oben hin, was es gab — „Pizza", „Müsli", „Kaffee". Es muss in keiner '
              + 'Liste stehen, und nach ein paar Tagen schlägt dir die Seite genau das vor, '
              + 'was du wirklich isst.'
            : 'Noch nichts im Bestand. Über <strong>Lebensmittel</strong> kommt etwas herein, '
              + 'unter <strong>Gerichte</strong> stellst du daraus eines zusammen.');
        return;
    }

    const MAX = 10;
    const mahlzeiten = (state.tag && state.tag.meals) || [];
    sub.textContent = state.mahlzeit
        ? (mahlzeiten.find(m => m.key === state.mahlzeit) || {}).label || ''
        : '';
    ziel.innerHTML = liste.slice(0, MAX).map(vorschlagZeile).join('')
        + (liste.length > MAX
            ? `<p class="ern-note">… und ${liste.length - MAX} weitere — tipp oben weiter.</p>`
            : '');

    ziel.querySelectorAll('[data-log-stufe]').forEach(b => b.addEventListener('click', () => {
        const art = b.dataset.logArt;
        const daten = { level: b.dataset.logStufe };
        if (art === 'dish') daten.dish_id = Number(b.dataset.logId);
        else if (art === 'item') daten.item_id = Number(b.dataset.logId);
        else daten.label = b.dataset.logName;
        eintragen(daten, b);
    }));
    ziel.querySelectorAll('[data-log-item]').forEach(b => b.addEventListener('click', () => {
        const id = Number(b.dataset.logItem);
        const feld = ziel.querySelector(`[data-menge="${id}"]`);
        const wahl = ziel.querySelector(`[data-einheit="${id}"]`);
        const menge = Number(String(feld.value).replace(',', '.'));
        if (!(menge > 0)) { melde('Wie viel davon?', 'error'); feld.focus(); return; }
        eintragen({ item_id: id, amount: menge, unit: wahl.value }, b);
    }));
    // Die Zahl im Feld passt sich der Einheit an: 100 g, aber 1 Scheibe.
    // Ohne das steht nach dem Umschalten "100 Scheiben" da.
    ziel.querySelectorAll('[data-einheit]').forEach(w => w.addEventListener('change', () => {
        const feld = ziel.querySelector(`[data-menge="${w.dataset.einheit}"]`);
        if (feld) feld.value = BASIS.includes(w.value) ? 100 : 1;
    }));
}

async function eintragen(daten, knopf) {
    knopf.classList.add('is-loading');
    try {
        state.tag = await API.eintragen(Object.assign(
            { day: state.datum || heute(), meal: state.mahlzeit }, daten));
        // Das Feld leeren: der naechste Eintrag faengt bei null an, und ein
        // stehengebliebener Text sieht aus, als waere nichts passiert.
        // Auch den laufenden Tipp-Takt: er wuerde sonst 180 ms spaeter den
        // gerade eingetragenen Text wieder als Vorschlag hinstellen.
        clearTimeout(state.tippen);
        state.eingabe = '';
        document.getElementById('ernEingabe').value = '';
        zeichneTag();
        ladeHaeufig();
        melde('Eingetragen.', 'success');
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

function zeichneTag() {
    zeichneTagKopf();
    zeichneTagBild();
    zeichneBaender();
    zeichneEintraege();
    zeichneMahlzeiten();
    zeichneVorschlaege();
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
    zeichneVorschlaege();
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

/* ------------------------------------------------------------- Gerichte */

function zeichneEntwurf() {
    const e = state.entwurf;
    document.getElementById('ernGerichtTitel').textContent =
        e.id ? 'Gericht bearbeiten' : 'Neues Gericht';
    document.getElementById('ernGerichtNeu').hidden = !e.id;
    const ziel = document.getElementById('ernZutaten');
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
        entwurfLeeren();
        zeichneGerichte();
        zeichneVorschlaege();
        melde('Gericht gespeichert.', 'success');
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    } finally {
        knopf.classList.remove('is-loading');
    }
}

function entwurfLeeren() {
    state.entwurf = { id: null, name: '', items: [] };
    document.getElementById('ernGerichtName').value = '';
    document.getElementById('ernZutatSuche').value = '';
    document.getElementById('ernZutatTreffer').innerHTML = '';
    zeichneEntwurf();
}

function gerichtBearbeiten(id) {
    const g = state.gerichte.find(x => x.id === id);
    if (!g) return;
    state.entwurf = {
        id: g.id, name: g.name,
        items: g.items.map(z => ({
            item_id: z.item_id, name: z.name,
            amount: z.amount, unit: z.unit, units: z.units })),
    };
    document.getElementById('ernGerichtName').value = g.name;
    zeichneEntwurf();
    window.scrollTo({ top: 0, behavior: 'smooth' });
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
        b.addEventListener('click', () => gerichtBearbeiten(Number(b.dataset.bearbeiten))));
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
    zeichneVorschlaege();
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
    document.getElementById('ernKamera').textContent = '📷 Kamera schließen';
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
    document.getElementById('ernBarcode').value = ziffern;
    // Direkt nachschlagen: wer gerade eine Packung vor die Kamera gehalten
    // hat, will das Ergebnis, nicht noch einen Knopf.
    nachschlagen();
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
    document.getElementById('ernKamera').textContent = '📷 Kamera';
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

function zeichneTreffer(ziel, produkt, bekannt, notiz, herkunft) {
    state.vorschlag = produkt;
    const el = document.getElementById(ziel);
    if (!produkt && bekannt) {
        el.innerHTML = `<div class="ern-treffer">
            <div class="ern-kopf"><strong>${esc(bekannt.name)}</strong>
                <span class="ern-herkunft">schon im Bestand</span></div>
            ${naehrwertZeile(bekannt)}
            ${notiz ? `<p class="ern-note">${esc(notiz)}</p>` : ''}
        </div>`;
        return;
    }
    if (!produkt) { el.innerHTML = ''; return; }
    el.innerHTML = `<div class="ern-treffer">
        <div class="ern-kopf">
            <strong>${esc(produkt.name)}</strong>
            ${produkt.brand ? `<span class="ern-marke">${esc(produkt.brand)}</span>` : ''}
            <span class="ern-herkunft">${esc(HERKUNFT[herkunft] || 'Open Food Facts')}</span>
        </div>
        ${naehrwertZeile(produkt)}
        ${bekannt ? '<p class="ern-note">Dieses Lebensmittel ist bereits im Bestand — Übernehmen aktualisiert die Werte.</p>' : ''}
        ${produkt.missing && produkt.missing.length
            ? `<p class="ern-note">Dort fehlen ${produkt.missing.length} Angaben. Du kannst sie nach dem Übernehmen von der Packung nachtragen.</p>`
            : ''}
        <div class="ern-tasten">
            <button type="button" class="v-btn v-btn--primary" id="ernUebernehmen">In den Bestand</button>
        </div>
    </div>`;
    const knopf = document.getElementById('ernUebernehmen');
    if (knopf) knopf.addEventListener('click', () => uebernehmen(produkt));
}

async function nachschlagen(e) {
    if (e) e.preventDefault();
    const code = document.getElementById('ernBarcode').value.trim();
    if (!code) return;
    document.getElementById('ernTreffer').innerHTML = '<span class="skel skel-block"></span>';
    try {
        const res = await API.barcode(code);
        zeichneTreffer('ernTreffer', res.found ? res.product : null,
                       res.known, res.note, res.origin);
    } catch (err) {
        document.getElementById('ernTreffer').innerHTML =
            leerKarte('🔎', esc(err.message || 'Nicht gefunden.'));
    }
}

async function suchen(text) {
    const ziel = document.getElementById('ernSuchTreffer');
    if (text.length < 2) { ziel.innerHTML = ''; return; }
    ziel.innerHTML = '<span class="skel skel-block"></span>';
    try {
        const res = await API.suche(text);
        if (!res.results.length) {
            ziel.innerHTML = leerKarte('🔎',
                'Nichts gefunden. Bei Losem ohne Strichcode lohnt sich oft ein '
                + 'allgemeinerer Begriff — „Apfel" statt „Apfel Elstar".');
            return;
        }
        ziel.innerHTML = `<p class="ern-note">${res.results.length} Treffer aus
            ${esc(HERKUNFT[res.origin] || 'Open Food Facts')}</p>`
            + res.results.map((p, i) => `
            <div class="ern-treffer">
                <div class="ern-kopf"><strong>${esc(p.name)}</strong>
                    ${p.brand ? `<span class="ern-marke">${esc(p.brand)}</span>` : ''}</div>
                <p class="ern-note">${zahl(p.kcal, '')} kcal · ${zahl(p.protein_g, ' g')} Eiweiß
                    · ${zahl(p.fiber_g, ' g')} Ballaststoffe</p>
                <div class="ern-tasten">
                    <button type="button" class="v-btn v-btn--sm" data-treffer="${i}">In den Bestand</button>
                </div>
            </div>`).join('');
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
        // Statt das stillschweigend hinzunehmen, steht das Formular gleich
        // offen -- ein Feld ausfuellen ist leichter, als den Eintrag spaeter
        // wiederzufinden.
        if (neu && !(neu.sizes || []).length) {
            formFuellen(neu);
            melde('Aufgenommen. Trag noch ein, was eine Einheit wiegt — dann '
                + 'kannst du „2 × Scheibe“ eintragen statt in Gramm zu rechnen.', 'info');
        } else {
            melde('In den Bestand aufgenommen.', 'success');
        }
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    }
}

/* ------------------------------------------------- Anlegen und Aendern
 *
 * Dasselbe Formular fuer beides. Ein zweites Formular zum Bearbeiten waere
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

/* Die eigenen Groessen sind eine Liste, kein festes Feldpaar: dasselbe
   Lebensmittel hat oft mehrere (Scheibe, Laib, Packung), und wer nur eine
   hinterlegen kann, rechnet den Rest jedes Mal im Kopf. */
function zeichneGroessen() {
    const ziel = document.getElementById('fGroessen');
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
            </div>`).join('')
          + '<p class="ern-note">Die erste Zeile ist die Standardgröße.</p>';

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

let bearbeitet = null;   // id des Lebensmittels, das gerade geaendert wird

function formLeeren() {
    bearbeitet = null;
    state.formGroessen = [];
    Object.keys(FORM).forEach(id => {
        const feld = document.getElementById(id);
        if (feld) feld.value = id === 'fBase' ? 'g' : '';
    });
    zeichneGroessen();
    document.getElementById('ernFormTitel').textContent = 'Von Hand anlegen';
    document.getElementById('fSpeichern').textContent = 'Aufnehmen';
    document.getElementById('fAbbrechen').hidden = true;
}

function formFuellen(p) {
    bearbeitet = p.id;
    Object.entries(FORM).forEach(([id, feld]) => {
        const el = document.getElementById(id);
        if (el) el.value = p[feld] == null ? '' : p[feld];
    });
    document.getElementById('fBase').value = p.base_unit || 'g';
    state.formGroessen = (p.sizes || []).map(g => ({ label: g.label, grams: g.grams }));
    zeichneGroessen();
    document.getElementById('ernFormTitel').textContent = 'Lebensmittel ändern';
    document.getElementById('fSpeichern').textContent = 'Änderung speichern';
    document.getElementById('fAbbrechen').hidden = false;
    activateTab('vorrat');
    document.getElementById('ernFormTitel').scrollIntoView({ behavior: 'smooth', block: 'center' });
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
        formLeeren();
        await ladeBestand();
        await ladeGerichte();
        melde('Gespeichert.', 'success');
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    } finally {
        knopf.classList.remove('is-loading');
    }
}

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
        zeichneVorschlaege();
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
        if (p) formFuellen(p);
    }));
    zeichneVorschlaege();
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

    document.getElementById('ernEingabe').addEventListener('input', (e) => {
        clearTimeout(state.tippen);
        const wert = e.target.value;
        state.tippen = setTimeout(
            () => { state.eingabe = wert; zeichneVorschlaege(); }, 180);
    });
    // Enter traegt den ersten Vorschlag normal ein -- der haeufigste Fall,
    // und er soll ohne Maus gehen.
    document.getElementById('ernEingabe').addEventListener('keydown', (e) => {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        state.eingabe = e.target.value;
        zeichneVorschlaege();
        // Die erste Zeile und ihre Hauptaktion. Irgendeinen „normal"-Knopf
        // aus der Liste zu nehmen hiesse, etwas anderes einzutragen, als
        // oben steht.
        const erste = document.querySelector('#ernVorschlaege .ern-vorschlag');
        const knopf = erste && erste.querySelector(
            '[data-log-stufe="normal"], [data-log-item]');
        if (knopf) knopf.click();
    });

    document.getElementById('ernZieleSpeichern').addEventListener('click', zieleSpeichern);
    document.getElementById('ernZieleWeg').addEventListener('click', zieleZuruecksetzen);

    document.getElementById('ernGerichtSpeichern').addEventListener('click', gerichtSpeichern);
    document.getElementById('ernGerichtNeu').addEventListener('click', entwurfLeeren);
    document.getElementById('ernZutatSuche').addEventListener('input',
        (e) => zutatSuchen(e.target.value));

    document.getElementById('ernScanForm').addEventListener('submit', nachschlagen);
    document.getElementById('ernKamera').addEventListener('click', kameraStarten);
    document.getElementById('ernKameraStop').addEventListener('click', kameraStoppen);
    let suchTakt = null;
    document.getElementById('ernSuche').addEventListener('input', (e) => {
        clearTimeout(suchTakt);
        const wert = e.target.value.trim();
        suchTakt = setTimeout(() => suchen(wert), 400);
    });
    document.getElementById('fSpeichern').addEventListener('click', formSpeichern);
    document.getElementById('fAbbrechen').addEventListener('click', formLeeren);
    document.getElementById('fGroesseNeu').addEventListener('click', () => {
        state.formGroessen.push({ label: '', grams: null });
        zeichneGroessen();
    });
    document.getElementById('fBase').addEventListener('change', zeichneGroessen);
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
    formLeeren();
    entwurfLeeren();

    await ladeTag(heute());
    await Promise.all([ladeGerichte(), ladeBestand(), ladeHaeufig(), katalogStand()]);
});
