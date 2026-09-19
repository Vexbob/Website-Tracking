/* naehrwerte.js — v1.98.0
 *
 * Der Ernaehrungs-Tracker. Er stellt die andere Frage als das Essenstagebuch:
 * wie viel wovon, und was steckt drin?
 *
 * Die Trennung ist keine Einstellung mehr, sondern die Wahl des Moduls -- und
 * sie steht in der Datenbank: ``food_log`` hat keine Stufe, ``food_diary``
 * keine Menge. Bis v1.96.0 war beides eine Seite mit einem Umschalter, und ein
 * hier eingetragenes "100 g" stand danach auch im Tagebuch.
 *
 * Drei Entscheidungen tragen die Seite:
 *
 *   1. **Der Ring zeigt eine Zahl, keine Spanne.** Ein Gericht wird in
 *      Portionen eingetragen (0,5 / 1 / 1,5), ein Lebensmittel in einer
 *      Menge. Frueher stand am Gericht eine Grobstufe, und daraus wurde eine
 *      Spanne -- das ist jetzt Sache des Tagebuchs, das gar keine Zahlen
 *      behauptet.
 *   2. **Das Ziel steht am Ring**, nicht in einem Reiter daneben. Wer keines
 *      gesetzt hat, liest dort, woran gerade gemessen wird, und kommt mit
 *      einem Tipp hin.
 *   3. **Eine Luecke ist keine Null.** Fehlt einer Zutat eine Angabe, ist der
 *      Wert unvollstaendig -- der Ring bekommt eine gestrichelte Spur statt
 *      einer Zahl, die Vollstaendigkeit behauptet.
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
    tag:      (d)  => apiCall('/api/food/track/day' + (d ? '?date=' + d : '')),
    eintragen:(d)  => apiCall('/api/food/track/log', { method: 'POST', body: d }),
    eintragAendern: (id, d) =>
        apiCall('/api/food/track/log/' + id, { method: 'PATCH', body: d }),
    eintragWeg: (id) => apiCall('/api/food/track/log/' + id, { method: 'DELETE' }),
    ziele:    ()   => apiCall('/api/food/track/targets'),
    zieleSetzen: (d) => apiCall('/api/food/track/targets', { method: 'PUT', body: d }),
    verlauf:  (qs) => apiCall('/api/food/track/history' + qs),
    haeufig:  ()   => apiCall('/api/food/track/frequent'),
    bruecke:  ()   => apiCall('/api/food/track/bridge'),
    brueckeWeg: (label) => apiCall('/api/food/track/bridge/dismiss',
                                    { method: 'POST', body: { label } }),
    fotoHochladen: (id, datei) => {
        const fd = new FormData();
        fd.append('file', datei);
        return apiCall('/api/food/dishes/' + id + '/photo',
                       { method: 'POST', body: fd });
    },
    fotoWeg: (id) => apiCall('/api/food/dishes/' + id + '/photo', { method: 'DELETE' }),
};

/* Die Zeichen an den Bedienelementen kommen aus VexIkon (js/ikon.js) und
   nicht mehr als Emoji: ein Emoji traegt eine Farbe, die niemand gewaehlt
   hat, und faellt dort, wo die Schrift es nicht kennt, auf einen leeren
   Kasten zurueck -- auf den Vorschaubildern war genau das zu sehen. */
const ICON = {
    lupe:   VexIkon.svg('lupe', 17),
    muell:  VexIkon.svg('muell', 17),
    kamera: VexIkon.svg('kamera', 17),
};

/* Vier Reiter, ohne Emoji. Fuenf mit Emoji passten bei 390 px nicht in die
   Leiste: der letzte lag hinter dem rechten Rand, und wer ihn waehlte, sah
   nicht einmal mehr, DASS er gewaehlt war. Die Ziele sind dafuer dorthin
   gewandert, wo man sie sucht -- an den Ring, der sie misst (Dialog statt
   Reiter, DESIGN 6d: was man selten tut, steht nicht dauerhaft da). */
const REITER = [
    { key: 'tag', label: 'Tag' },
    { key: 'verlauf', label: 'Verlauf' },
    { key: 'gerichte', label: 'Gerichte' },
    { key: 'vorrat', label: 'Lebensmittel' },
];
const ALLE_REITER = REITER.map(r => r.key);

// Die beiden Einheiten, in denen die Naehrwerte stehen. Alles andere ist
// eine eigene Groesse des Lebensmittels und traegt ihren Namen als
// Schluessel -- "Scheibe", "Laib", "Becher".
const BASIS = ['g', 'ml'];
// Die drei kleinen Ringe neben dem Kalorienring. Ballaststoffe kommen dazu,
// sobald dafuer ein eigenes Ziel steht -- vier Ringe ohne Anlass waeren einer
// zu viel.
const MAKRO_RINGE = ['protein_g', 'carbs_g', 'fat_g'];
const RING_TON = { protein_g: '--chart-1', carbs_g: '--chart-2',
                   fat_g: '--chart-3', fiber_g: '--chart-4' };

const state = {
    ziele: null, bestand: [], groessenVorschlaege: [],
    katalog: null, katalogLaeuft: false, katalogGeholt: false,
    formGroessen: [],
    tag: null, datum: null, gerichte: [], haeufig: [],
    dialog: null, dlg: null, zieleDlg: null,
    bruecke: null,
    verlauf: null, range: null, rangeMount: null,
    charts: { eins: null, zwei: null },
    entwurf: { id: null, name: '', items: [] },
    reiter: 'tag',
};

/* ------------------------------------------------------------- Werkzeug */

const heute = () => {
    const d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0')
        + '-' + String(d.getDate()).padStart(2, '0');
};

const jetzt = () => {
    const d = new Date();
    return String(d.getHours()).padStart(2, '0') + ':'
        + String(d.getMinutes()).padStart(2, '0');
};

const esc = (v) => String(v == null ? '' : v)
    .replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const figurFarbe = () => cssVar('--figure') || cssVar('--m-naehrwerte');

function melde(text, art, versuche) {
    if (window.Toast) { Toast[art || 'info'](text); return; }
    const offen = versuche == null ? 10 : versuche;
    if (offen > 0) setTimeout(() => melde(text, art, offen - 1), 200);
    else if (art === 'error') askAlert({ title: 'Das ging nicht', text: text });
}

const zahlKurz = (v) => Math.round(v || 0).toLocaleString('de-DE');
const mengeKurz = (v) => String(Number(v)).replace('.', ',');

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
const MONATE = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli',
                'August', 'September', 'Oktober', 'November', 'Dezember'];

/* Ausgeschrieben, ohne Wochentag -- den setzt der Kopf davor, wenn er nicht
   ohnehin im grossen Namen steht. */
function datumLang(iso) {
    const d = new Date(iso + 'T12:00:00');
    if (isNaN(d.getTime())) return iso;
    return d.getDate() + '. ' + MONATE[d.getMonth()] + ' ' + d.getFullYear();
}

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

const VERALTET = 'Diesen Teil kennt der Server noch nicht. Auf dem Server läuft '
    + 'vermutlich noch die vorherige Fassung des Backends — dort fehlt ein Neustart.';

function fehlerText(err) {
    const roh = (err && err.message) || '';
    if (/404|not found|405|method not allowed/i.test(roh)) return VERALTET;
    if (/netzwerkfehler/i.test(roh)) {
        return 'Keine Verbindung zum Server. Sobald er wieder antwortet, hilft ein '
            + 'Klick auf „Erneut versuchen“.';
    }
    return 'Das ließ sich nicht laden' + (roh ? ' (' + roh + ').' : '.');
}

function zeigeTagFehler(text) {
    document.getElementById('nwTagInhalt').hidden = true;
    const el = document.getElementById('nwTagFehler');
    el.hidden = false;
    el.innerHTML = `<div class="stat-card"><div class="empty is-error">
        <span class="empty-mark" aria-hidden="true">⚠️</span>
        <p class="empty-text">${esc(text)}</p>
        <button type="button" class="v-btn v-btn--primary" id="nwNochmal">Erneut versuchen</button>
    </div></div>`;
    const knopf = document.getElementById('nwNochmal');
    if (knopf) knopf.addEventListener('click', () => {
        knopf.classList.add('is-loading');
        ladeTag(state.datum);
    });
}

/* Der Dialog liegt seit v2.1.0 in /js/modal.js -- eine Fassung fuer alle
   Module, mit gesperrtem Hintergrund, Fokus im Kasten und role="dialog".
   Der Name hier bleibt, damit die Aufrufstellen unveraendert bleiben. */
function openModal(titel, inhalt, opts) {
    return VexModal.open(titel, inhalt, opts || {});
}


/* Welche Mahlzeit jetzt gemeint sein duerfte. Die Grenzen kommen vom Server,
   damit hier kein zweiter Satz Zahlen steht: angezeigt wird derselbe
   Vorschlag, den der Server beim Speichern trifft. */
function mahlzeitJetzt() {
    if ((state.datum || heute()) !== heute()) return null;
    const grenzen = (state.tag && state.tag.meal_hours) || {};
    const h = new Date().getHours();
    for (const m of ['fruehstueck', 'mittag', 'abend']) {
        if (grenzen[m] != null && h < grenzen[m]) return m;
    }
    return 'snack';
}

/* ---------------------------------------------------------------- Reiter */

function zeichneReiter() {
    const leiste = document.getElementById('nwTabs');
    leiste.innerHTML = REITER.map(r =>
        `<button type="button" class="tab-btn${r.key === state.reiter ? ' active' : ''}"
            data-tab="${r.key}">${r.label}</button>`).join('');
    leiste.querySelectorAll('.tab-btn').forEach(b =>
        b.addEventListener('click', () => activateTab(b.dataset.tab)));
}

function activateTab(tab) {
    if (ALLE_REITER.indexOf(tab) < 0) tab = 'tag';
    state.reiter = tab;
    document.querySelectorAll('#nwTabs .tab-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.tab === tab));
    ALLE_REITER.forEach(t => {
        const el = document.getElementById('tab-' + t);
        if (el) el.hidden = t !== tab;
    });
    // Der Reiter steht in der Adresse -- dasselbe Muster wie im Schachmodul:
    // ein Neuladen landet dort, wo man war, und ein Link auf die Ziele ist
    // ein Link auf die Ziele. Der erste Reiter bleibt ohne Anhaengsel, damit
    // die blanke Adresse die blanke Adresse bleibt.
    history.replaceState(null, '', tab === 'tag' ? location.pathname : '#' + tab);
    // Der Schwebeknopf gehört dem Tag. Im Verlauf, in den Gerichten und im
    // Bestand gibt es nichts einzutragen -- dort wäre er ein Knopf, der die
    // Seite wechselt, ohne das zu sagen.
    const fab = document.getElementById('nwFab');
    if (fab) fab.hidden = tab !== 'tag';
    if (tab === 'verlauf') mountRange();
    // Der Katalogstand beschriftet nur den Reiter „Lebensmittel“. Ihn beim
    // Laden der Seite mitzuholen, hiesse: eine Anfrage fuer eine Zeile, die
    // man am Tag nicht sieht. Einmal, beim ersten Hinsehen, genuegt.
    if (tab === 'vorrat' && !state.katalog && !state.katalogGeholt) {
        state.katalogGeholt = true;
        katalogStand();
    }
}

/* ------------------------------------------------------------------ Tag */

function tagVerschieben(tage) {
    const d = new Date((state.datum || heute()) + 'T12:00:00');
    d.setDate(d.getDate() + tage);
    const neu = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0')
        + '-' + String(d.getDate()).padStart(2, '0');
    if (neu > heute()) return;
    ladeTag(neu);
}

function zeichneKopf() {
    const datum = state.datum || heute();
    const d = new Date(datum + 'T12:00:00');
    const istHeute = datum === heute();
    const gestern = new Date(Date.now() - 86400000);
    const gesternIso = gestern.getFullYear() + '-'
        + String(gestern.getMonth() + 1).padStart(2, '0') + '-'
        + String(gestern.getDate()).padStart(2, '0');
    const nahName = istHeute ? 'Heute' : (datum === gesternIso ? 'Gestern' : null);
    document.getElementById('nwTagName').textContent = nahName || TAG_NAMEN[d.getDay()];
    // Unter dem grossen Namen steht das Datum ausgeschrieben. „Heute“ allein
    // sagt nicht, welcher Tag das ist, und „18.09.2026“ allein sagt nicht,
    // dass es heute ist -- erst beides zusammen beantwortet die Frage, die
    // ein Tageskopf beantworten soll.
    document.getElementById('nwTagDatum').textContent =
        (nahName ? TAG_NAMEN[d.getDay()] + ', ' : '') + datumLang(datum);
    document.getElementById('nwVor').disabled = istHeute;
    // Die Auswahl steht auf dem gezeigten Tag und reicht nicht in die
    // Zukunft -- dieselbe Grenze wie am Pfeil daneben.
    const wahl = document.getElementById('nwDatumWahl');
    wahl.value = datum;
    wahl.max = heute();
}

/* Der Kalorienring. Er sagt drei Dinge auf einmal: wie viel, wovon wie viel
   noch fehlt, und woran gemessen wird. Das Letzte ist der Grund, warum die
   Zielzeile hier steht und nicht im Reiter daneben -- dort hat sie zuletzt
   niemand gefunden. */
function zeichneRinge() {
    const t = state.tag;
    if (!t) return;
    const kcal = t.totals.kcal;
    const drueber = kcal.over > 0;

    VexRing.set(document.getElementById('nwRingKcal'), {
        wert: kcal.value, ziel: kcal.reference, zahl: kcal.value,
        einheit: 'kcal', unvollstaendig: kcal.incomplete,
        text: drueber ? `${zahlKurz(kcal.over)} darüber`
                      : `noch ${zahlKurz(kcal.remaining)}`,
    });

    // Ballaststoffe bekommen nur dann einen Ring, wenn dafuer ein eigenes
    // Ziel steht: vier Ringe ohne Anlass waeren einer zu viel.
    const makros = MAKRO_RINGE.concat(
        t.totals.fiber_g && t.totals.fiber_g.own_target ? ['fiber_g'] : []);
    const ziel = document.getElementById('nwMakros');
    // Neu aufgebaut wird nur, wenn sich die Reihe wirklich aendert. Sonst
    // verliert jeder Ring bei jedem Eintrag sein ``dataset.wert``, und die
    // drei kleinen Ringe zaehlen jedes Mal wieder bei null los -- waehrend
    // der grosse daneben vom vorherigen Stand weiterlaeuft. Zwei Regeln fuer
    // dieselbe Bewegung, nebeneinander, in einer Zeile sichtbar.
    const reihe = makros.join(',');
    if (ziel.dataset.reihe !== reihe) {
        ziel.dataset.reihe = reihe;
        ziel.innerHTML = makros.map(m => VexRing.html({
            id: 'nwRing_' + m, klassen: ['v-ring--sm'],
            ton: `var(--${RING_TON[m].slice(2)})`,
        })).join('');
    }
    makros.forEach(m => {
        const d = t.totals[m];
        VexRing.set(document.getElementById('nwRing_' + m), {
            wert: d.value, ziel: d.reference, zahl: d.value,
            unvollstaendig: d.incomplete,
            einheit: null, text: d.label,
            form: (v) => Math.round(v).toLocaleString('de-DE') + ' g',
        });
    });
}

/* Der Tag nach Mahlzeiten, jede mit Teilsumme und eigenem Plus. */
function zeichneMahlzeiten() {
    const ziel = document.getElementById('nwMahlzeiten');
    const t = state.tag;
    if (!t) { ziel.innerHTML = '<span class="skel skel-block"></span>'; return; }

    ziel.innerHTML = t.meals.map(m => {
        const eigene = t.entries.filter(e => e.meal === m.key);
        if (m.key === 'ohne' && !eigene.length) return '';
        const summe = t.meal_totals[m.key];
        const kcalText = summe && summe.kcal
            ? `<span class="v-mz-summe">${summe.incomplete ? 'mind. ' : ''}${
                zahlKurz(summe.kcal)} kcal</span>` : '';
        const plus = m.key === 'ohne' ? ''
            : `<button type="button" class="v-mz-plus" data-add="${esc(m.key)}"
                   aria-label="Zu ${esc(m.label)} eintragen"
                   title="Zu ${esc(m.label)} eintragen">＋</button>`;
        // Eine leere Mahlzeit laedt ein, statt blass dazustehen: die ganze
        // Flaeche ist der Knopf, und der Ort sagt schon, wohin es geht.
        const koerper = eigene.length
            ? `<div class="v-mz-koerper">${eigene.map(zeile).join('')}</div>`
            : (m.key === 'ohne' ? '' : `<button type="button" class="v-mz-leer"
                   data-add="${esc(m.key)}">＋ ${esc(m.label)} eintragen</button>`);
        return `<div class="v-mahlzeit${eigene.length ? '' : ' is-leer'}">
            <div class="v-mz-kopf">
                <span class="v-mz-name">${esc(m.label)}</span>
                ${kcalText}
                ${plus}
            </div>
            ${koerper}
        </div>`;
    }).join('');

    ziel.querySelectorAll('[data-add]').forEach(b =>
        b.addEventListener('click', () => eintragDialog(b.dataset.add)));
    ziel.querySelectorAll('[data-mz-um]').forEach(b =>
        b.addEventListener('click', () => eintragAendernDialog(Number(b.dataset.mzUm))));
}

/* Ein Bedienelement je Zeile, nicht zwei. Der Papierkorb stand bis v2.3.0
   daneben -- 44 Pixel fuer den seltensten Handgriff, ohne Rueckfrage, direkt
   neben dem Namen. „Entfernen“ steht im Aenderungs-Dialog, den derselbe
   Name mit einem Tipp oeffnet: einen Griff tiefer, dafuer nicht aus
   Versehen. */
function zeile(e) {
    const meta = [
        esc(e.sub || ''),
        e.has_nutrition ? `${zahlKurz(e.kcal)} kcal` : 'ohne Nährwerte',
        e.logged_time || '',
    ].filter(Boolean).join(' · ');
    return `<div class="v-mz-zeile"${e.meal_auto
            ? ' title="Mahlzeit automatisch nach Uhrzeit — Namen antippen zum Ändern"' : ''}>
        <button type="button" class="v-mz-zeile-name" data-mz-um="${e.id}">
            <strong>${esc(e.name)}</strong>
            <span class="v-mz-zeile-meta">${meta}</span>
        </button>
        <span class="v-mz-tag">${esc(e.amount_label)}</span>
    </div>`;
}

function zeichneTag() {
    zeichneKopf();
    zeichneRinge();
    zeichneMahlzeiten();
}

/* Die Bruecke: wer den Tracker einschaltet, hat oft schon Wochen im
   Essenstagebuch stehen. Diese Namen sind die beste Vorlage fuer einen
   Bestand, den es noch nicht gibt.

   Sie schreibt nichts um. Der Tagebuch-Eintrag von damals bleibt ein
   Tagebuch-Eintrag und wird nicht nachtraeglich zu einer Menge -- aus einer
   Stufe eine Grammzahl zu erfinden, waere die falsche Genauigkeit. Nur der
   NAECHSTE Eintrag hier profitiert. Und sie fuehrt nicht in die andere
   Richtung: beide Module laufen nebeneinander weiter. */
function zeichneBruecke() {
    const karte = document.getElementById('nwBruecke');
    if (!karte) return;
    const liste = (state.bruecke && state.bruecke.suggestions) || [];
    // Ohne Vorschlaege gar keine Karte: eine Karte ueber nichts ist eine
    // Karte zu viel.
    karte.hidden = !liste.length;
    if (!liste.length) return;

    document.getElementById('nwBrueckeSub').textContent =
        `${state.bruecke.diary_days} Tage notiert`;
    // Eine Zeile, eine Hauptsache: der breite Knopf hinterlegt die
    // Naehrwerte, das Ablehnen steht klein daneben. Zwei gleich grosse
    // Knoepfe je Zeile waeren bei fuenf Vorschlaegen zehn gleichberechtigte
    // Ziele, und keins davon staeche heraus.
    document.getElementById('nwBrueckeListe').innerHTML =
        '<div class="rec-list nw-liste nw-bruecke-liste">' + liste.map((v, i) => `
        <div class="rec-row">
            <span class="rec-mark" style="--tone:var(--nw-figur)">${esc(v.name.slice(0, 1))}</span>
            <span class="rec-main">
                <span class="rec-title">${esc(v.name)}</span>
                <span class="rec-meta">${v.count}× notiert<span class="sep">·</span>zuletzt ${
                    datumKurz(v.last)}</span>
            </span>
            <span class="nw-br-tasten">
                <button type="button" class="v-btn v-btn--sm nw-w-ok"
                        data-bruecke-an="${i}">Nährwerte hinterlegen</button>
                <button type="button" class="v-btn v-btn--icon v-btn--ghost"
                        data-bruecke-weg="${i}" title="Nicht nötig"
                        aria-label="„${esc(v.name)}“ nicht vorschlagen">✕</button>
            </span>
        </div>`).join('') + '</div>';

    karte.querySelectorAll('[data-bruecke-an]').forEach(b =>
        b.addEventListener('click', () => {
            const v = liste[Number(b.dataset.brueckeAn)];
            activateTab('vorrat');
            // Mit vorausgefuelltem Namen: was man 43-mal notiert hat, soll
            // man nicht noch einmal tippen muessen.
            itemDialog(null, v.name);
        }));
    karte.querySelectorAll('[data-bruecke-weg]').forEach(b =>
        b.addEventListener('click', async () => {
            const v = liste[Number(b.dataset.brueckeWeg)];
            b.classList.add('is-loading');
            try {
                state.bruecke = await API.brueckeWeg(v.name);
                zeichneBruecke();
            } catch (err) {
                melde(err.message || 'Das ging nicht.', 'error');
            }
        }));
}

async function ladeBruecke() {
    try {
        state.bruecke = await API.bruecke();
    } catch (e) {
        state.bruecke = null;
    }
    zeichneBruecke();
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
    if (!tag || !tag.totals || !tag.meals || !tag.meal_totals) {
        zeigeTagFehler(VERALTET);
        return;
    }
    state.tag = tag;
    document.getElementById('nwTagFehler').hidden = true;
    document.getElementById('nwTagInhalt').hidden = false;
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

/* ----------------------------------------------------- Eintragen-Dialog */

function eintragDialog(mahlzeit) {
    if (!state.tag) return;
    state.dlg = { mahlzeit: mahlzeit || mahlzeitJetzt(), eingabe: '',
                  zuletzt: [], liste: [],
                  // Der Katalog laeuft neben der eigenen Liste her: eigener
                  // Takt, eigener Zustand, eigene Trefferliste.
                  katTakt: null, katalog: [], katalogLaeuft: false,
                  katalogFuer: '' };

    const titel = (state.datum || heute()) === heute()
        ? 'Eintragen · heute' : 'Eintragen · ' + datumKurz(state.datum);
    // Mahlzeit und Suchfeld kleben oben: sie sind der Kopf des Vorgangs und
    // duerfen nicht unter dem Daumen wegwandern, waehrend die Liste darunter
    // waechst und schrumpft.
    const inhalt = `
        <div class="nw-dlg-kopf">
            <div class="v-mzwahl" id="nwDlgMahlzeiten"></div>
            <label class="ern-suche">
                <span class="ern-suche-ico" aria-hidden="true">${ICON.lupe}</span>
                <input type="search" id="nwDlgSuche" autocomplete="off"
                       aria-label="Gericht oder Lebensmittel suchen"
                       placeholder="Gericht oder Lebensmittel suchen">
            </label>
        </div>
        <div id="nwDlgListe"></div>
        <div id="nwDlgKat"></div>
        <div class="ern-dlg-fuss">
            <span class="ern-note" id="nwDlgZuletzt"></span>
            <button type="button" class="v-btn" id="nwDlgFertig">Fertig</button>
        </div>`;

    state.dialog = openModal(titel, inhalt, {
        // voll: auf dem Handy das ganze Bild. Ein mittig zentrierter Kasten
        // rueckt bei JEDER Aenderung seiner Hoehe um die halbe Differenz --
        // und die Hoehe aendert sich hier bei jedem getippten Zeichen, weil
        // die Vorschlagsliste mitwaechst. Das war das Ruckeln: nicht die
        // Liste sprang, der Rahmen sprang.
        breit: true, voll: true,
        beimSchliessen: () => {
            if (state.dlg) clearTimeout(state.dlg.katTakt);
            state.dialog = null;
            state.dlg = null;
        },
    });

    zeichneDlgMahlzeiten();
    zeichneDlgListe();

    const feld = document.getElementById('nwDlgSuche');
    feld.addEventListener('input', (e) => {
        clearTimeout(state.dlg.katTakt);
        const wert = e.target.value;
        // Die eigene Liste liegt im Speicher -- sie filtert SOFORT. Der
        // Taktgeber, der bis v2.3.0 auch hier stand, verzoegerte nichts
        // Teures, er verzoegerte nur die Antwort auf den eigenen Finger.
        state.dlg.eingabe = wert;
        zeichneDlgListe();
        // Der Katalog ist eine Anfrage und wartet, bis das Tippen zur Ruhe
        // kommt. Er zeichnet in seinen EIGENEN Behaelter -- vorher riss
        // seine Antwort die Liste darueber mit ab, und mit ihr die Menge,
        // die man gerade hineingeschrieben hatte.
        state.dlg.katTakt = setTimeout(() => dlgKatalog(wert), 400);
    });
    document.getElementById('nwDlgFertig')
        .addEventListener('click', () => state.dialog && state.dialog.close());
    if (window.matchMedia('(min-width: 720px)').matches) feld.focus();
}

function zeichneDlgMahlzeiten() {
    const ziel = document.getElementById('nwDlgMahlzeiten');
    if (!ziel || !state.dlg) return;
    const vorschlag = mahlzeitJetzt();
    const gewaehlt = state.dlg.mahlzeit || 'ohne';
    ziel.innerHTML = `<select aria-label="Mahlzeit">${
        ((state.tag && state.tag.meals) || []).map(m =>
            `<option value="${esc(m.key)}"${m.key === gewaehlt ? ' selected' : ''}>${
                esc(m.label)}${m.key === vorschlag ? ' · jetzt' : ''}</option>`
        ).join('')}</select>`;
    ziel.querySelector('select').addEventListener('change', (e) => {
        // Von Hand gewaehlt schlaegt die Uhr: der Server raet nur, wo keine
        // Mahlzeit mitkommt.
        state.dlg.mahlzeit = e.target.value === 'ohne' ? null : e.target.value;
    });
}

/* Woraus die Liste besteht: Gerichte, Lebensmittel und was man oft eintraegt.
   Einen frei getippten Namen gibt es hier nicht -- ohne Naehrwerte kann der
   Tracker mit ihm nichts anfangen, und genau dafuer ist das Tagebuch da. */
function dlgVorschlaege() {
    const text = (state.dlg.eingabe || '').trim().toLowerCase();
    const passt = (n) => !text || String(n || '').toLowerCase().includes(text);

    const gerichte = state.gerichte.filter(g => passt(g.name)).map(g => ({
        kind: 'dish', dish_id: g.id, name: g.name, dish: g,
        sub: g.portion && g.portion.kcal != null
            ? `Gericht · ${zahlKurz(g.portion.kcal)} kcal je Portion`
            : 'Gericht · Nährwerte unvollständig',
    }));

    const lebensmittel = state.bestand
        .filter(p => passt(p.name) || passt(p.brand))
        .map(p => ({
            kind: 'item', item_id: p.id, item: p, name: p.name,
            sub: (p.brand ? p.brand + ' · ' : '')
                + ((p.sizes || []).length
                    ? (p.sizes || []).map(g =>
                        `${g.label} = ${g.grams} ${p.base_unit || 'g'}`).join(' · ')
                    : 'keine eigene Größe — wird in ' + (p.base_unit || 'g') + ' eingetragen'),
        }));

    // Was oft eingetragen wird, steht oben -- aber nur, solange nicht gesucht
    // wird: wer tippt, sucht etwas Bestimmtes.
    if (text) return gerichte.concat(lebensmittel);
    const rang = new Map();
    state.haeufig.forEach((h, i) => {
        rang.set((h.dish_id ? 'd' : 'i') + (h.dish_id || h.item_id), i);
    });
    const schluessel = (v) => (v.dish_id ? 'd' : 'i') + (v.dish_id || v.item_id);
    return gerichte.concat(lebensmittel).sort((a, b) => {
        const ra = rang.has(schluessel(a)) ? rang.get(schluessel(a)) : 999;
        const rb = rang.has(schluessel(b)) ? rang.get(schluessel(b)) : 999;
        return ra - rb;
    });
}

function dlgZeile(v, i) {
    if (v.kind === 'dish') {
        // Ein Gericht wird in Portionen eingetragen. Der Stepper ist kein
        // Zahlenfeld: halbe, ganze, anderthalb Portionen sind die Faelle, und
        // fuer die muss niemand eine Tastatur oeffnen.
        return `<div class="ern-w">
            <div class="ern-w-text">
                <span class="ern-w-name">${esc(v.name)}</span>
                <span class="ern-w-sub">${esc(v.sub || '')}</span>
            </div>
            <div class="ern-menge ern-menge--stepper">
                <div class="nw-stepper">
                    <button type="button" data-schritt="${i}" data-um="-0.5"
                            aria-label="Weniger">−</button>
                    <output data-menge="${i}" data-wert="1">1 Portion</output>
                    <button type="button" data-schritt="${i}" data-um="0.5"
                            aria-label="Mehr">＋</button>
                </div>
                <button type="button" class="v-btn v-btn--sm nw-w-ok"
                        data-log-dish="${i}">Eintragen</button>
            </div>
        </div>`;
    }
    const einheiten = v.item.units
        || [{ key: v.item.base_unit || 'g', label: v.item.base_unit || 'g' }];
    const eigene = einheiten.filter(e => !BASIS.includes(e.key));
    const start = eigene.length ? eigene[0] : einheiten[0];
    // Ein Auswahlfeld mit genau einem Eintrag ist kein Bedienelement, sondern
    // eine Beschriftung, die aussieht wie eines. Gibt es nichts zu waehlen,
    // steht die Einheit als Beschriftung da — und die Zeile hat ein
    // Bedienelement weniger, das nichts tut.
    const wahl = einheiten.length > 1
        ? `<select class="v-select v-select--sm" data-item-einheit="${i}"
                    aria-label="Einheit für ${esc(v.name)}">
                ${einheiten.map(e => `<option value="${esc(e.key)}"${
                    e.key === start.key ? ' selected' : ''}>${esc(e.label)}</option>`).join('')}
            </select>`
        : `<span class="ern-menge-fest">${esc(start.label)}</span>
           <input type="hidden" data-item-einheit="${i}" value="${esc(start.key)}">`;
    return `<div class="ern-w">
        <div class="ern-w-text">
            <span class="ern-w-name">${esc(v.name)}</span>
            <span class="ern-w-sub">${esc(v.sub || '')}</span>
        </div>
        <div class="ern-menge">
            <input type="number" min="0" step="0.25" inputmode="decimal"
                   value="${eigene.length ? 1 : 100}"
                   data-item-menge="${i}" aria-label="Menge für ${esc(v.name)}">
            ${wahl}
            <button type="button" class="v-btn v-btn--sm nw-w-ok"
                    data-log-item="${i}">Eintragen</button>
        </div>
    </div>`;
}

/* Was der eigene Bestand nicht hat, holt der Katalog -- im selben Feld.

   Ohne das endet der Weg, den man jeden Tag geht, genau dort, wo er anfaengt:
   man tippt einen Namen, findet nichts, schliesst den Dialog, wechselt in den
   Reiter "Lebensmittel", sucht dort noch einmal, nimmt auf, wechselt zurueck,
   oeffnet den Dialog und tippt den Namen ein drittes Mal. Der
   Gerichte-Dialog hat diesen Reiterwechsel seit v1.99.0 nicht mehr; hier
   stand er noch. */
async function dlgKatalog(text) {
    if (!state.dlg) return;
    const begriff = (text || '').trim();
    state.dlg.katalogFuer = begriff;
    if (begriff.length < 2) {
        state.dlg.katalog = [];
        state.dlg.katalogLaeuft = false;
        zeichneDlgKatalog();
        return;
    }
    state.dlg.katalogLaeuft = true;
    zeichneDlgKatalog();

    let treffer = [];
    try {
        const res = await API.suche(begriff);
        treffer = res.results || [];
    } catch (e) {
        treffer = [];
    }
    // Eine Antwort auf eine aeltere Eingabe verwerfen: sonst ueberholt die
    // langsamere Suche die neuere Liste, und unter dem Wort steht das
    // Ergebnis zum Wort davor.
    if (!state.dlg || state.dlg.katalogFuer !== begriff) return;
    const drin = new Set(state.bestand.map(p => String(p.name).toLowerCase()));
    state.dlg.katalog = treffer
        .filter(p => !drin.has(String(p.name).toLowerCase())).slice(0, 6);
    state.dlg.katalogLaeuft = false;
    zeichneDlgKatalog();
    zeichneDlgListe();          // nur wegen des leeren Zustands darueber
}

/* Der Katalogblock unter der eigenen Liste. Dieselbe Zeile wie im
   Gerichte-Dialog (`.nw-g-treffer`): derselbe Vorgang, dieselbe Gestalt.

   Er zeichnet seit v2.4.0 in seinen EIGENEN Behaelter. Vorher hing sein
   Ergebnis am selben `innerHTML` wie die eigene Liste -- und weil die
   Katalogantwort 400 bis 900 ms nach dem letzten Zeichen kommt, riss sie
   genau in dem Moment die Liste ab, in dem man die Menge hineinschrieb:
   Feld weg, Tastatur zu, Zahl weg. Das war kein Ruckeln, das war
   Datenverlust, der wie Ruckeln aussah. */
function zeichneDlgKatalog() {
    const ziel = document.getElementById('nwDlgKat');
    const d = state.dlg;
    if (!ziel || !d) return;

    if (d.katalogLaeuft) {
        ziel.innerHTML = `<div class="nw-dlg-kat">
            <p class="ern-note">Im Katalog suchen …</p>
            <span class="skel skel-block"></span></div>`;
        return;
    }
    if (!d.katalog.length) { ziel.innerHTML = ''; return; }
    ziel.innerHTML = `<div class="nw-dlg-kat">
        <p class="ern-note">Nicht in deinem Bestand — ein Tipp nimmt es auf:</p>
        ${d.katalog.map((p, i) => `<button type="button" class="nw-g-treffer" data-kat="${i}">
            <span class="nw-g-treffer-text">
                <span class="ern-w-name">${esc(p.name)}</span>
                <span class="ern-w-sub">${esc((p.brand ? p.brand + ' · ' : '')
                    + zahl(p.kcal, '') + ' kcal je 100 ' + (p.base_unit || 'g'))}</span>
            </span>
            <span class="ern-herkunft">Katalog</span>
        </button>`).join('')}
    </div>`;

    ziel.querySelectorAll('[data-kat]').forEach(b => b.addEventListener('click', async () => {
        const p = (state.dlg.katalog || [])[Number(b.dataset.kat)];
        if (!p) return;
        b.classList.add('is-loading');
        try {
            await katalogAufnehmen(p);
            if (!state.dlg) return;
            // Aufgenommen heisst noch nicht eingetragen -- wie viel davon,
            // weiss nur der Nutzer. Das Lebensmittel steht nach dem Zeichnen
            // oben in der eigenen Liste, mit Mengenfeld: ein Tipp weiter.
            state.dlg.katalog = state.dlg.katalog.filter(x => x !== p);
            zeichneDlgKatalog();
            zeichneDlgListe();
            melde('Aufgenommen — jetzt die Menge.', 'success');
        } catch (err) {
            b.classList.remove('is-loading');
            melde(err.message || 'Das ging nicht.', 'error');
        }
    }));
}

function zeichneDlgListe() {
    const ziel = document.getElementById('nwDlgListe');
    if (!ziel || !state.dlg) return;
    const liste = dlgVorschlaege();
    state.dlg.liste = liste;
    const d = state.dlg;

    const MAX = 12;
    let html = liste.slice(0, MAX).map(dlgZeile).join('')
        + (liste.length > MAX
            ? `<p class="ern-note">… und ${liste.length - MAX} weitere — tipp oben weiter.</p>`
            : '');
    if (!liste.length) {
        // Solange der Katalog laeuft oder etwas hat, waere „nichts da“ falsch:
        // da kommt gerade etwas. Erst wenn beide Quellen leer sind, ist die
        // Auskunft eine Auskunft.
        html = (d.katalogLaeuft || d.katalog.length)
            ? '' : leerKarte('🥫', state.dlg.eingabe
            ? 'Weder im Bestand noch im Katalog. Bei Losem ohne Strichcode lohnt '
              + 'ein allgemeinerer Begriff — „Apfel“ statt „Apfel Elstar“. '
              + 'Unter <strong>Lebensmittel</strong> geht es auch von Hand.'
            : 'Noch nichts im Bestand. Tipp einfach einen Namen — gesucht wird '
              + 'auch im Katalog, und ein Tipp nimmt den Treffer auf.');
    }
    ziel.innerHTML = html;

    const nimm = (i) => state.dlg.liste[Number(i)];
    ziel.querySelectorAll('[data-schritt]').forEach(b => b.addEventListener('click', () => {
        const feld = ziel.querySelector(`[data-menge="${b.dataset.schritt}"]`);
        if (!feld) return;
        // Eine halbe Portion ist die kleinste sinnvolle Einheit; darunter
        // raet man mehr, als man misst.
        const neu = Math.max(0.5, Number(feld.dataset.wert) + Number(b.dataset.um));
        feld.dataset.wert = String(neu);
        feld.textContent = mengeKurz(neu) + ' Portion' + (neu === 1 ? '' : 'en');
    }));
    ziel.querySelectorAll('[data-log-dish]').forEach(b => b.addEventListener('click', () => {
        const i = b.dataset.logDish;
        const v = nimm(i);
        const feld = ziel.querySelector(`[data-menge="${i}"]`);
        eintragen({ dish_id: v.dish_id, amount: Number(feld.dataset.wert) }, b, v.name);
    }));
    ziel.querySelectorAll('[data-log-item]').forEach(b => b.addEventListener('click', () => {
        const i = b.dataset.logItem;
        const v = nimm(i);
        const feld = ziel.querySelector(`[data-item-menge="${i}"]`);
        const wahl = ziel.querySelector(`[data-item-einheit="${i}"]`);
        const menge = Number(String(feld.value).replace(',', '.'));
        if (!(menge > 0)) { melde('Wie viel davon?', 'error'); feld.focus(); return; }
        eintragen({ item_id: v.item_id, amount: menge, unit: wahl.value }, b, v.name);
    }));
    // Die Zahl im Feld passt sich der Einheit an: 100 g, aber 1 Scheibe.
    ziel.querySelectorAll('[data-item-einheit]').forEach(w => w.addEventListener('change', () => {
        const feld = ziel.querySelector(`[data-item-menge="${w.dataset.itemEinheit}"]`);
        if (feld) feld.value = BASIS.includes(w.value) ? 100 : 1;
    }));
}

async function eintragen(daten, knopf, name) {
    if (knopf) knopf.classList.add('is-loading');
    const body = Object.assign({
        day: state.datum || heute(),
        at: jetzt(),
        meal: state.dlg ? state.dlg.mahlzeit : null,
    }, daten);
    try {
        state.tag = await API.eintragen(body);
        zeichneTag();
        if (state.dlg) {
            state.dlg.zuletzt.push(name);
            const fuss = document.getElementById('nwDlgZuletzt');
            if (fuss) fuss.textContent = 'Eingetragen: ' + state.dlg.zuletzt.join(', ');
        } else {
            melde('Eingetragen.', 'success');
        }
        ladeHaeufig();
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    } finally {
        if (knopf) knopf.classList.remove('is-loading');
    }
}

async function entfernenEintrag(id) {
    try {
        state.tag = await API.eintragWeg(id);
        zeichneTag();
        ladeHaeufig();
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    }
}

/* Die Mahlzeit einer Zeile richtigstellen. Die Menge steht nicht zur Wahl:
   sie nachtraeglich zu aendern hiesse, die Umrechnung von damals zu
   wiederholen -- dafuer gibt es Entfernen und neu eintragen. */
/* Ein Eintrag richtigstellen: Menge, Mahlzeit, Notiz.

   Die Menge stand hier bis v2.1.0 nicht, und darunter stand ein Absatz, der
   das begruendete ("sie wurde beim Eintragen umgerechnet"). Die Begruendung
   war falsch: kcal und Makros holt der Server bei jedem Aufruf frisch aus dem
   Lebensmittel, eingefroren ist allein das Gramm-Gewicht -- und das ist aus
   Menge und Einheit dieselbe Rechnung wie beim ersten Mal. Es fehlte eine
   Funktion, kein Grund.

   Ein Erklaerabsatz vor einem Bedienelement ist ohnehin das Zeichen, dass das
   Bedienelement nicht stimmt. Hier war es das Zeichen, dass es fehlte. */
function eintragAendernDialog(id) {
    const e = ((state.tag && state.tag.entries) || []).find(x => x.id === id);
    if (!e) return;

    const istGericht = e.kind === 'dish';
    const vorrat = istGericht ? null
        : state.bestand.find(p => p.id === e.item_id);
    // Ist das Lebensmittel nicht mehr im Bestand, bleibt wenigstens die
    // Einheit, die an der Zeile steht -- eine leere Auswahl waere schlimmer
    // als eine mit genau einem Eintrag.
    const einheiten = (vorrat && vorrat.units && vorrat.units.length)
        ? vorrat.units : [{ key: e.unit, label: e.unit }];

    const mengeFeld = istGericht
        ? `<div class="nw-stepper nw-stepper--breit">
               <button type="button" id="nwEdMinus" aria-label="Weniger">−</button>
               <output id="nwEdMenge" data-wert="${e.amount}">${
                   mengeKurz(e.amount)} Portion${e.amount === 1 ? '' : 'en'}</output>
               <button type="button" id="nwEdPlus" aria-label="Mehr">＋</button>
           </div>`
        : `<div class="ern-menge">
               <input type="number" min="0" step="0.25" inputmode="decimal"
                      id="nwEdMenge" value="${e.amount}"
                      aria-label="Menge">
               <select class="v-select v-select--sm" id="nwEdEinheit"
                       aria-label="Einheit">
                   ${einheiten.map(u => `<option value="${esc(u.key)}"${
                       u.key === e.unit ? ' selected' : ''}>${esc(u.label)}</option>`).join('')}
               </select>
           </div>`;

    const inhalt = `
        <p class="ern-note" style="margin-top:0">${esc(e.name)}${
            e.has_nutrition ? ` · ${zahlKurz(e.kcal)} kcal` : ' · ohne Nährwerte'}</p>
        <div class="ern-feld">
            <span>Wie viel?</span>
            ${mengeFeld}
        </div>
        <div class="ern-feld">
            <span>Wann?</span>
            <div class="ern-dlg-mahlzeiten" id="nwEdMahlzeiten"></div>
        </div>
        <label class="ern-feld">
            <span>Notiz</span>
            <input type="text" id="nwEdNote" value="${esc(e.note || '')}"
                   autocomplete="off" placeholder="optional">
        </label>
        <div class="ern-tasten">
            <button type="button" class="v-btn v-btn--primary" id="nwEdOk">Übernehmen</button>
            <button type="button" class="v-btn v-btn--danger" id="nwEdWeg">Entfernen</button>
        </div>`;

    const wahl = { meal: e.meal === 'ohne' ? null : e.meal };
    const dlg = openModal('Eintrag', inhalt);

    const zeichne = () => {
        const ziel = document.getElementById('nwEdMahlzeiten');
        ziel.innerHTML = ((state.tag && state.tag.meals) || []).map(m =>
            `<button type="button" class="v-chip${
                (wahl.meal || 'ohne') === m.key ? ' is-active' : ''}"
                data-mahlzeit="${esc(m.key)}">${esc(m.label)}</button>`).join('');
        ziel.querySelectorAll('[data-mahlzeit]').forEach(b => b.addEventListener('click', () => {
            wahl.meal = b.dataset.mahlzeit === 'ohne' ? null : b.dataset.mahlzeit;
            zeichne();
        }));
    };
    zeichne();

    if (istGericht) {
        const feld = document.getElementById('nwEdMenge');
        const um = (schritt) => {
            // Eine halbe Portion ist die kleinste sinnvolle Einheit -- wie im
            // Eintragen-Dialog, damit dieselbe Handlung dieselbe Stufe hat.
            const neu = Math.max(0.5, Number(feld.dataset.wert) + schritt);
            feld.dataset.wert = String(neu);
            feld.textContent = mengeKurz(neu) + ' Portion' + (neu === 1 ? '' : 'en');
        };
        document.getElementById('nwEdMinus').addEventListener('click', () => um(-0.5));
        document.getElementById('nwEdPlus').addEventListener('click', () => um(0.5));
    } else {
        // Die Zahl passt sich der Einheit an: 100 g, aber 1 Scheibe.
        document.getElementById('nwEdEinheit').addEventListener('change', (ev) => {
            document.getElementById('nwEdMenge').value =
                BASIS.includes(ev.target.value) ? 100 : 1;
        });
    }

    document.getElementById('nwEdOk').addEventListener('click', async (ev) => {
        const knopf = ev.currentTarget;
        const feld = document.getElementById('nwEdMenge');
        const menge = istGericht
            ? Number(feld.dataset.wert)
            : Number(String(feld.value).replace(',', '.'));
        if (!(menge > 0)) { melde('Wie viel davon?', 'error'); feld.focus(); return; }

        const aenderung = {
            meal: wahl.meal === null ? 'ohne' : wahl.meal,
            note: document.getElementById('nwEdNote').value,
        };
        // Die Menge nur mitschicken, wenn sie sich wirklich geaendert hat:
        // sonst wuerde jedes Übernehmen die Gramm neu rechnen, auch wenn nur
        // die Notiz angefasst wurde.
        const einheit = istGericht ? e.unit
            : document.getElementById('nwEdEinheit').value;
        if (menge !== e.amount || einheit !== e.unit) {
            aenderung.amount = menge;
            aenderung.unit = einheit;
        }

        knopf.classList.add('is-loading');
        try {
            state.tag = await API.eintragAendern(id, aenderung);
            dlg.close();
            zeichneTag();
        } catch (err) {
            melde(err.message || 'Das ging nicht.', 'error');
        } finally {
            knopf.classList.remove('is-loading');
        }
    });
    document.getElementById('nwEdWeg').addEventListener('click', async () => {
        dlg.close();
        await entfernenEintrag(id);
    });
}

/* -------------------------------------------------------------- Verlauf */

function mountRange() {
    if (state.rangeMount) return;
    const host = document.getElementById('nwRange');
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
        document.getElementById('nwVerlaufKpi').innerHTML = '';
        document.getElementById('nwChart1Box').hidden = true;
        document.getElementById('nwChart2Karte').hidden = true;
        const leer = document.getElementById('nwChart1Leer');
        leer.hidden = false;
        leer.innerHTML = `<div class="empty is-error"><span class="empty-mark">⚠️</span>
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

/* Ohne Bildzeichen. Auf den Bedienelementen sind die Emoji in v2.5.0
   verschwunden, weil jedes Geraet ein anderes Bild zeichnet -- auf den
   Kennzahlen blieben sie stehen und sahen daneben aus wie ein Rest. Die
   Beschriftung sagt ohnehin, was die Zahl ist. */
function kpiKarte(label, wert, sub) {
    return `<div class="stat-kpi">
        <div class="stat-kpi-label">${label}</div>
        <div class="stat-kpi-value">${wert}</div>
        <div class="stat-kpi-sub">${sub || ''}</div>
    </div>`;
}

function zeichneVerlauf() {
    const v = state.verlauf;
    if (!v) return;
    zerstoereCharts();

    document.getElementById('nwVerlaufZeitraum').textContent =
        `${datumKurz(v.from)} bis ${datumKurz(v.to)}`;
    document.getElementById('nwVerlaufSub').textContent = v.truncated
        ? 'auf 400 Tage gekürzt — länger wird die Liste breiter als jede Darstellung'
        : '';

    const z = v.summary;
    const kpi = [
        kpiKarte('Notiert', `${z.days_logged} von ${z.days}`,
                 z.days_logged ? '' : 'noch nichts im Zeitraum'),
        kpiKarte('Kalorien Ø', z.kcal_avg == null ? '–' : zahlKurz(z.kcal_avg),
                 z.complete_days
                     ? `über ${z.complete_days} ${z.complete_days === 1 ? 'Tag' : 'Tage'} mit vollständigen Angaben`
                     : 'kein Tag, an dem zu allem Nährwerte standen'),
        kpiKarte('Eiweiß Ø', z.protein_avg == null ? '–' : zahlKurz(z.protein_avg) + ' g', ''),
        kpiKarte('Im Ziel', z.complete_days ? `${z.target_hit_days} von ${z.complete_days}` : '–',
                 'Tage unter dem Kalorien-Maßstab'),
    ];
    document.getElementById('nwVerlaufKpi').innerHTML = kpi.join('');

    if (!z.days_logged) {
        document.getElementById('nwChart2Karte').hidden = true;
        document.getElementById('nwChart1Box').hidden = true;
        document.getElementById('nwChart1Note').textContent = '';
        const leer = document.getElementById('nwChart1Leer');
        leer.hidden = false;
        leer.innerHTML = leerKarte('📈',
            `Zwischen ${datumKurz(v.from)} und ${datumKurz(v.to)} steht kein einziger
             Eintrag. Ein anderer Zeitraum oben zeigt mehr — oder du trägst unter
             <strong>Tag</strong> etwas ein.`);
        return;
    }

    document.getElementById('nwChart1Leer').hidden = true;
    document.getElementById('nwChart1Box').hidden = false;
    document.getElementById('nwChart2Karte').hidden = false;
    const texte = achsenTexte(v.days);
    state.charts.eins = tagesChart('nwChart1', 'kcal', figurFarbe(), texte,
                                   'nwChart1Titel', 'nwChart1Sub', 'nwChart1Note',
                                   'Tage ohne Eintrag bleiben leer: nichts notiert ist '
                                   + 'nicht nichts gegessen. Einen Tag antippen öffnet ihn.');
    state.charts.zwei = tagesChart('nwChart2', 'protein_g', cssVar('--chart-1'), texte,
                                   'nwChart2Titel', 'nwChart2Sub', 'nwChart2Note');
}

function achsenTexte(tage) {
    return {
        kurz: tage.map(t => t.day.slice(8, 10) + '.' + t.day.slice(5, 7) + '.'),
        voll: tage.map(t => VexCharts.fullDay(t.day)),
    };
}

function tagOeffnen(index) {
    const tag = state.verlauf && state.verlauf.days[index];
    if (!tag) return;
    activateTab('tag');
    ladeTag(tag.day);
}

const TOOLTIP = (extra) => Object.assign({
    backgroundColor: cssVar('--surface-3'),
    borderColor: cssVar('--line-strong'), borderWidth: 1,
    titleColor: cssVar('--text-1'), bodyColor: cssVar('--text-2'),
    cornerRadius: 12, padding: 10, displayColors: true,
}, extra || {});

/* Ein Balken je Tag gegen die Ziellinie. Ein Tag ohne Eintrag bleibt leer
   statt auf null zu fallen: "nichts notiert" ist nicht "nichts gegessen". */
function tagesChart(canvasId, makro, farbe, texte, titelEl, subEl, noteEl, notiz) {
    const v = state.verlauf;
    const ziel = (v.targets && v.targets[makro]) || v.reference[makro];
    const eigen = !!(v.targets && v.targets[makro]);
    const e = EINHEIT[makro] || '';

    document.getElementById(titelEl).textContent = v.macro_labels[makro] + ' je Tag';
    document.getElementById(subEl).textContent =
        `${eigen ? 'Ziel' : 'Richtwert'} ${zahlKurz(ziel)}${e}`;
    // Nur einmal je Seite. Derselbe Satz unter beiden Diagrammen las sich
    // wie eine Fussnote, die man zweimal gedruckt hat.
    document.getElementById(noteEl).textContent = notiz || '';

    return new Chart(document.getElementById(canvasId), {
        data: {
            labels: texte.kurz,
            datasets: [
                {
                    type: 'bar', label: v.macro_labels[makro],
                    data: v.days.map(t => t.entries ? t[makro].value : null),
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
        options: VexCharts.applyFullDates({
            maintainAspectRatio: false,
            animation: { duration: 200 },
            interaction: { mode: 'index', intersect: false },
            onClick: (evt, treffer, chart) => {
                // Auch neben einer Saeule: getroffen wird der Tag unter dem
                // Finger, nicht nur der Balken -- sonst muss man zielen.
                const punkte = chart.getElementsAtEventForMode(
                    evt, 'index', { intersect: false }, true);
                if (punkte && punkte.length) tagOeffnen(punkte[0].index);
            },
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
                            + zahlKurz(t[makro].value) + e;
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
                x: { ticks: { color: cssVar('--chart-axis'), font: { size: 11 },
                              maxRotation: 0, autoSkipPadding: 16 },
                     grid: { display: false }, border: { display: false } },
                y: { beginAtZero: true,
                     ticks: { color: cssVar('--chart-axis'), font: { size: 11 },
                              maxTicksLimit: 5 },
                     grid: { color: cssVar('--chart-grid') }, border: { display: false } },
            },
        }, texte.voll),
    });
}

/* ----------------------------------------------------------------- Ziele
 *
 * Bis v2.3.0 ein eigener Reiter. Das war der zweite Versuch -- davor hingen
 * die Ziele unter einem Diagramm, wo sie niemand fand. Beide Male wurde die
 * falsche Frage beantwortet: nicht WO auf der Seite, sondern ob ueberhaupt
 * auf der Seite. Ein Tagesziel setzt man einmal und danach im Jahr vielleicht
 * zweimal; was man selten tut, steht nicht dauerhaft da (DESIGN 6d). Dabei
 * hat es einen staendigen Platz in der Reiterleiste belegt -- einen von
 * fuenf, und fuenf passten bei 390 px nicht nebeneinander.
 *
 * Jetzt liegt es hinter dem Knopf am Ring, der es misst. Das ist die Stelle,
 * an der die Frage ueberhaupt aufkommt: man sieht die Zahl, an der gemessen
 * wird, und fasst sie dort an.
 */

function zieleFelder() {
    const e = state.ziele;
    if (!e) return '<span class="skel skel-block"></span>';
    return e.macros.map(m => `
        <label class="ern-feld">
            <span>${esc(e.macro_labels[m])}${EINHEIT[m] ? ' (g)' : ''}</span>
            <input type="number" min="0" step="${m === 'kcal' ? 10 : 1}" inputmode="decimal"
                   data-ziel="${esc(m)}" value="${e.targets[m] == null ? '' : e.targets[m]}"
                   placeholder="${zahlKurz(e.defaults[m])}">
        </label>`).join('');
}

/* Ein Feld leer zu lassen ist hier die Haelfte der Bedienung, also steht das
   AM Feld und nicht als Absatz darunter: der Platzhalter zeigt den Richtwert,
   der dann gilt. Der dreisaetzige Absatz faellt damit weg -- wo drei Saetze
   erklaeren, wie ein Bedienelement gemeint ist, fehlte meist das
   Bedienelement. */
function zieleDialog() {
    const inhalt = `
        <div class="ern-ziele" id="nwZiele">${zieleFelder()}</div>
        <p class="ern-note">Leer heißt: weiter am Richtwert messen — der grauen Zahl
            im Feld. Niemand muss fünf Ziele haben.</p>
        <div class="ern-tasten">
            <button type="button" class="v-btn v-btn--primary" id="nwZieleSpeichern">Ziele speichern</button>
            <button type="button" class="v-btn" id="nwZieleWeg">Alle zurücksetzen</button>
        </div>`;

    state.zieleDlg = openModal('Tagesziele', inhalt, {
        beimSchliessen: () => { state.zieleDlg = null; },
    });
    document.getElementById('nwZieleSpeichern').addEventListener('click', zieleSpeichern);
    document.getElementById('nwZieleWeg').addEventListener('click', zieleZuruecksetzen);
}

async function ladeZiele() {
    try {
        state.ziele = await API.ziele();
    } catch (e) {
        state.ziele = null;
    }
    // Steht der Dialog gerade offen, bekommt er die frischen Werte; sonst
    // gibt es nichts zu zeichnen -- die Felder entstehen erst mit ihm.
    const ziel = document.getElementById('nwZiele');
    if (ziel) ziel.innerHTML = zieleFelder();
}

async function zieleSpeichern() {
    const knopf = document.getElementById('nwZieleSpeichern');
    const ziele = {};
    document.querySelectorAll('[data-ziel]').forEach(f => {
        const roh = String(f.value).replace(',', '.').trim();
        ziele[f.dataset.ziel] = roh ? Number(roh) : null;
    });
    knopf.classList.add('is-loading');
    try {
        state.ziele = await API.zieleSetzen({ targets: ziele });
        // Der Dialog geht zu: was er zu tun hatte, ist getan, und dahinter
        // steht der Ring, der die neue Zahl gerade bekommen hat.
        if (state.zieleDlg) state.zieleDlg.close();
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
        text: 'Danach misst jeder Ring wieder am allgemeinen Richtwert — der üblichen '
            + 'Größenordnung für einen Tag, nicht an einem Ziel.',
        confirmText: 'Zurücksetzen',
    });
    if (!ok) return;
    document.querySelectorAll('[data-ziel]').forEach(f => { f.value = ''; });
    await zieleSpeichern();
}

/* ------------------------------------------------------------- Gerichte
 *
 * Ein Rezept anzulegen war der unbequemste Teil dieses Moduls, und auf dem
 * Handy scheiterte es an vier Dingen: das Suchfeld stand UNTER der
 * Zutatenliste, jede Zutat war eine Zeile aus drei Bedienelementen, die
 * Einheit ein natives Auswahlrad -- und eine Zutat, die nicht im Bestand
 * stand, zwang in einen anderen Reiter, also aus dem Dialog heraus, also von
 * vorn.
 *
 * Jetzt: zwei Schritte in einem Blatt, das auf dem Handy das ganze Bild
 * einnimmt. Das Suchfeld klebt OBEN und sucht in einem Rutsch ueber Bestand
 * UND Katalog -- damit faellt der Reiterwechsel weg, und das ist die groesste
 * einzelne Vereinfachung. Unten laeuft die Summe mit: man sieht das Rezept
 * entstehen.
 */

function entwurfSumme() {
    let gramm = 0, kcal = 0, eiweiss = 0, luecke = false;
    state.entwurf.items.forEach(z => {
        const p = state.bestand.find(x => x.id === z.item_id);
        const e = (z.units || []).find(u => u.key === z.unit);
        const g = Number(z.amount) * (e && e.grams ? Number(e.grams) : 1);
        gramm += g;
        if (!p || p.kcal == null) luecke = true;
        else {
            kcal += Number(p.kcal) * g / 100;
            if (p.protein_g != null) eiweiss += Number(p.protein_g) * g / 100;
        }
    });
    return { gramm, kcal, eiweiss, luecke };
}

function zeichneEntwurfFuss() {
    const el = document.getElementById('nwGSumme');
    if (!el) return;
    if (!state.entwurf.items.length) {
        el.textContent = 'Noch keine Zutat';
        return;
    }
    const s = entwurfSumme();
    // "mind." statt einer Zahl, die Vollstaendigkeit behauptet: fehlt einer
    // Zutat die Angabe, ist die Summe unvollstaendig und nicht niedriger.
    el.innerHTML = `<strong>1 Portion</strong> ≈ ${s.luecke ? 'mind. ' : ''}`
        + `${zahlKurz(s.kcal)} kcal · ${zahlKurz(s.eiweiss)} g Eiweiß`
        + `<span class="nw-g-gramm">${zahlKurz(s.gramm)} g</span>`;
}

function gerichtDialog(g) {
    state.entwurf = g
        ? { id: g.id, name: g.name, foto: null, hatFoto: !!g.has_photo,
            items: g.items.map(z => ({ item_id: z.item_id, name: z.name,
                                       amount: z.amount, unit: z.unit, units: z.units })) }
        : { id: null, name: '', foto: null, hatFoto: false, items: [] };

    const inhalt = `
        <div id="nwG1">
            <label class="ern-feld">
                <span>Was gab es?</span>
                <input type="text" id="nwGName" class="nw-g-name" autocomplete="off"
                       placeholder="z. B. Wraps" value="${esc(state.entwurf.name)}">
            </label>
            <div class="nw-g-foto" id="nwGFoto"></div>
            <p class="ern-note">Das Foto steht am Anfang, weil das Telefon genau dann in
                der Hand ist, wenn das Essen noch auf dem Teller liegt.</p>
        </div>

        <div id="nwG2" hidden>
            <div id="nwGZutaten"></div>
            <label class="ern-suche nw-g-suche">
                <span class="ern-suche-ico" aria-hidden="true">${ICON.lupe}</span>
                <input type="search" id="nwGSuche" autocomplete="off"
                       aria-label="Zutat suchen"
                       placeholder="Zutat suchen — Bestand und Katalog">
            </label>
            <div id="nwGTreffer"></div>
        </div>

        <div class="nw-g-fuss">
            <span class="nw-g-summe" id="nwGSumme"></span>
            ${g ? `<button type="button" class="v-btn v-btn--danger"
                           id="nwGWeg">Entfernen</button>` : ''}
            <button type="button" class="v-btn" id="nwGZurueck" hidden>Zurück</button>
            <button type="button" class="v-btn v-btn--primary" id="nwGWeiter">Weiter</button>
        </div>`;

    state.dialog = openModal(state.entwurf.id ? 'Gericht ändern' : 'Neues Gericht', inhalt, {
        breit: true, voll: true,
        beimSchliessen: () => { state.dialog = null; },
    });

    zeichneEntwurfFoto();
    zeichneEntwurf();
    zeichneEntwurfFuss();

    const weiter = document.getElementById('nwGWeiter');
    const zurueck = document.getElementById('nwGZurueck');
    const schritt = (nr) => {
        document.getElementById('nwG1').hidden = nr !== 1;
        document.getElementById('nwG2').hidden = nr !== 2;
        zurueck.hidden = nr === 1;
        weiter.textContent = nr === 1 ? 'Weiter'
            : (state.entwurf.id ? 'Änderung speichern' : 'Gericht speichern');
        weiter.dataset.schritt = String(nr);
        document.getElementById('nwGSumme').hidden = nr === 1;
    };
    schritt(state.entwurf.items.length ? 2 : 1);

    weiter.addEventListener('click', () => {
        if (weiter.dataset.schritt === '1') {
            const name = document.getElementById('nwGName').value.trim();
            if (!name) { melde('Das Gericht braucht einen Namen.', 'error'); return; }
            state.entwurf.name = name;
            schritt(2);
            if (window.matchMedia('(min-width: 720px)').matches) {
                document.getElementById('nwGSuche').focus();
            }
            return;
        }
        gerichtSpeichern(weiter);
    });
    zurueck.addEventListener('click', () => schritt(1));
    // Entfernen steht hier und nicht mehr als Papierkorb in der Liste --
    // siehe itemDialog.
    const gWeg = document.getElementById('nwGWeg');
    if (gWeg) gWeg.addEventListener('click', async () => {
        if (state.dialog) state.dialog.close();
        await gerichtLoeschen(g.id);
    });

    let takt = null;
    document.getElementById('nwGSuche').addEventListener('input', (e) => {
        clearTimeout(takt);
        const wert = e.target.value;
        // Der Bestand ist sofort da, der Katalog braucht eine Anfrage --
        // deshalb erst das Eigene zeigen und das Fremde nachreichen.
        zutatTreffer(wert, null);
        takt = setTimeout(() => zutatKatalog(wert), 320);
    });
}

/* Das Foto: ein Knopf, ein Bild, ein Weg es wieder loszuwerden. Aufgenommen
   wird mit ``capture`` -- auf dem Handy oeffnet das direkt die Kamera. */
function zeichneEntwurfFoto() {
    const ziel = document.getElementById('nwGFoto');
    if (!ziel) return;
    const e = state.entwurf;
    const url = e.foto ? URL.createObjectURL(e.foto) : null;

    ziel.innerHTML = (url
        ? `<img class="v-bild" id="nwGBild" src="${url}" alt="Foto des Gerichts">`
        : (e.hatFoto && e.id
            ? `<img class="v-bild" id="nwGBild" alt="Foto des Gerichts">`
            : `<div class="v-bild-leer" aria-hidden="true">🍽️</div>`))
        + `<div class="ern-tasten">
               <button type="button" class="v-btn v-btn--sm" id="nwGFotoWahl">
                   ${ICON.kamera} ${url || e.hatFoto ? 'Anderes Foto' : 'Foto'}</button>
               ${url || e.hatFoto
                   ? '<button type="button" class="v-btn v-btn--sm" id="nwGFotoWeg">Ohne Foto</button>'
                   : ''}
               <input type="file" id="nwGFotoDatei" accept="image/*"
                      capture="environment" hidden>
           </div>`;

    if (!url && e.hatFoto && e.id) {
        // Das gespeicherte Foto braucht den Anmelde-Kopf -- ein nacktes
        // <img src> schickt keinen mit.
        VexBild.alsBlobUrl('/api/food/dishes/' + e.id + '/thumb')
            .then(u => { const b = document.getElementById('nwGBild'); if (b) b.src = u; })
            .catch(() => {});
    }

    const datei = document.getElementById('nwGFotoDatei');
    document.getElementById('nwGFotoWahl').addEventListener('click', () => datei.click());
    datei.addEventListener('change', async () => {
        const f = datei.files && datei.files[0];
        if (!f) return;
        try {
            state.entwurf.foto = await VexBild.komprimieren(f);
            state.entwurf.hatFoto = true;
            zeichneEntwurfFoto();
        } catch (err) {
            melde(err.message || 'Das Bild ließ sich nicht lesen.', 'error');
        }
    });
    const weg = document.getElementById('nwGFotoWeg');
    if (weg) weg.addEventListener('click', async () => {
        state.entwurf.foto = null;
        state.entwurf.hatFoto = false;
        if (state.entwurf.id) {
            try { await API.fotoWeg(state.entwurf.id); } catch (e) { /* war keins da */ }
        }
        zeichneEntwurfFoto();
    });
}

/* Die Zutaten stehen UEBER dem Suchfeld: was man gerade hinzugefuegt hat,
   soll man sehen, ohne zu scrollen. Die Menge ist ein Stepper -- eine Zahl
   zu tippen kostet auf dem Handy eine Tastatur. */
function zeichneEntwurf() {
    const e = state.entwurf;
    const ziel = document.getElementById('nwGZutaten');
    if (!ziel) return;
    ziel.innerHTML = !e.items.length
        ? '<p class="ern-note">Noch keine Zutat — such unten danach. Was nicht in deinem '
          + 'Bestand steht, wird beim Antippen aufgenommen.</p>'
        : e.items.map((z, i) => {
            const eh = (z.units || []).find(u => u.key === z.unit);
            const basis = BASIS.includes(z.unit);
            return `<div class="nw-g-zutat">
                <span class="nw-g-zutat-name">${esc(z.name)}</span>
                <div class="nw-stepper">
                    <button type="button" data-zschritt="${i}" data-um="-1"
                            aria-label="Weniger">−</button>
                    <output data-zmenge="${i}">${mengeKurz(z.amount)} ${esc(
                        eh ? eh.label : z.unit)}</output>
                    <button type="button" data-zschritt="${i}" data-um="1"
                            aria-label="Mehr">＋</button>
                </div>
                <button type="button" class="nw-g-einheit" data-zeinheit="${i}"
                        title="Einheit wechseln">${basis ? esc(z.unit) : '⇄'}</button>
                <button type="button" class="v-btn v-btn--icon" data-zutat-weg="${i}"
                        aria-label="Zutat entfernen" title="Entfernen">✕</button>
            </div>`;
        }).join('');

    ziel.querySelectorAll('[data-zschritt]').forEach(b => b.addEventListener('click', () => {
        const i = Number(b.dataset.zschritt);
        const z = state.entwurf.items[i];
        // Bei g/ml in Zehnerschritten, bei benannten Groessen in ganzen
        // Einheiten: "105 g" tippt niemand, "1 Scheibe mehr" schon.
        const um = Number(b.dataset.um) * (BASIS.includes(z.unit) ? 10 : 1);
        z.amount = Math.max(BASIS.includes(z.unit) ? 10 : 1, Number(z.amount) + um);
        zeichneEntwurf();
        zeichneEntwurfFuss();
    }));
    ziel.querySelectorAll('[data-zeinheit]').forEach(b => b.addEventListener('click', () => {
        einheitBlatt(Number(b.dataset.zeinheit));
    }));
    ziel.querySelectorAll('[data-zutat-weg]').forEach(b => b.addEventListener('click', () => {
        state.entwurf.items.splice(Number(b.dataset.zutatWeg), 1);
        zeichneEntwurf();
        zeichneEntwurfFuss();
    }));
}

/* Die Einheit als Blatt statt als Auswahlrad: angeboten wird nur, was am
   Lebensmittel hinterlegt ist -- ein Feld mit "Packung", das dann 100 g
   rechnet, waere geraten. */
function einheitBlatt(index) {
    const z = state.entwurf.items[index];
    if (!z) return;
    const liste = z.units || [];
    const dlg = openModal('Einheit für ' + esc(z.name),
        `<div class="ern-dlg-mahlzeiten">${liste.map(u =>
            `<button type="button" class="v-chip${u.key === z.unit ? ' is-active' : ''}"
                data-einheit="${esc(u.key)}">${esc(u.label)}${
                BASIS.includes(u.key) ? '' : ` <span class="nw-g-gramm">${u.grams} g</span>`
            }</button>`).join('')}</div>`);
    dlg.el.querySelectorAll('[data-einheit]').forEach(b => b.addEventListener('click', () => {
        const neu = b.dataset.einheit;
        // Die Zahl passt sich der Einheit an: 100 g, aber 1 Scheibe.
        z.amount = BASIS.includes(neu) ? 100 : 1;
        z.unit = neu;
        dlg.close();
        zeichneEntwurf();
        zeichneEntwurfFuss();
    }));
}

function zutatHinzufuegen(p) {
    const einheiten = p.units
        || [{ key: p.base_unit || 'g', label: p.base_unit || 'g', grams: 1 }];
    const eigene = einheiten.find(u => !BASIS.includes(u.key));
    state.entwurf.items.push({
        item_id: p.id, name: p.name,
        amount: eigene ? 1 : 100,
        unit: eigene ? eigene.key : (p.base_unit || 'g'),
        units: einheiten,
    });
    const feld = document.getElementById('nwGSuche');
    if (feld) feld.value = '';
    const treffer = document.getElementById('nwGTreffer');
    if (treffer) treffer.innerHTML = '';
    zeichneEntwurf();
    zeichneEntwurfFuss();
}

/* Erst der eigene Bestand, dann der Katalog. Ein Katalog-Treffer wird beim
   Antippen still aufgenommen und ist danach eine ganz normale Zutat -- das
   ist der Reiterwechsel, der hier wegfaellt. */
function zutatTreffer(text, katalog) {
    const ziel = document.getElementById('nwGTreffer');
    if (!ziel) return;
    const begriff = (text || '').trim().toLowerCase();
    if (!begriff) { ziel.innerHTML = ausTagHtml(); bindeAusTag(ziel); return; }

    const eigen = state.bestand.filter(p =>
        p.name.toLowerCase().includes(begriff)
        || (p.brand || '').toLowerCase().includes(begriff)).slice(0, 8);

    const zeile = (name, sub, marke, attr) =>
        `<button type="button" class="nw-g-treffer" ${attr}>
            <span class="nw-g-treffer-text">
                <span class="ern-w-name">${esc(name)}</span>
                <span class="ern-w-sub">${esc(sub || '')}</span>
            </span>
            <span class="ern-herkunft">${esc(marke)}</span>
        </button>`;

    let html = eigen.map(p => zeile(
        p.name,
        (p.brand ? p.brand + ' · ' : '') + zahl(p.kcal, '') + ' kcal je 100 '
            + (p.base_unit || 'g'),
        'Bestand', `data-eigen="${p.id}"`)).join('');

    if (katalog === null) {
        html += '<p class="ern-note">Suche im Katalog läuft …</p>';
    } else if (katalog && katalog.length) {
        html += katalog.map((p, i) => zeile(
            p.name, (p.brand ? p.brand + ' · ' : '') + zahl(p.kcal, '') + ' kcal je 100 g',
            'Katalog', `data-katalog="${i}"`)).join('');
    } else if (!eigen.length) {
        html = leerKarte('🔎', 'Nichts gefunden — weder im Bestand noch im Katalog. '
            + 'Unter <strong>Lebensmittel</strong> lässt es sich von Hand anlegen.');
    }
    ziel.innerHTML = html;

    ziel.querySelectorAll('[data-eigen]').forEach(b => b.addEventListener('click', () => {
        const p = state.bestand.find(x => x.id === Number(b.dataset.eigen));
        if (p) zutatHinzufuegen(p);
    }));
    ziel.querySelectorAll('[data-katalog]').forEach(b => b.addEventListener('click', async () => {
        const p = (katalog || [])[Number(b.dataset.katalog)];
        // Erst pruefen, dann den Knopf laden lassen: andersherum bleibt er
        // haengen, wenn es den Treffer nicht mehr gibt.
        if (!p) return;
        b.classList.add('is-loading');
        try {
            const neu = await katalogAufnehmen(p);
            if (neu) zutatHinzufuegen(neu);
        } catch (err) {
            melde(err.message || 'Das ging nicht.', 'error');
        } finally {
            b.classList.remove('is-loading');
        }
    }));
}

async function zutatKatalog(text) {
    const begriff = (text || '').trim();
    if (begriff.length < 2) { zutatTreffer(begriff, []); return; }
    try {
        const res = await API.suche(begriff);
        // Was schon im Bestand steht, nicht zweimal anbieten.
        const drin = new Set(state.bestand.map(p => p.name.toLowerCase()));
        zutatTreffer(begriff, (res.results || [])
            .filter(p => !drin.has(String(p.name).toLowerCase())).slice(0, 6));
    } catch (e) {
        zutatTreffer(begriff, []);
    }
}

/* Der schnellste Weg zu einem Rezept ist das, was ohnehin schon eingetragen
   ist: wer gerade gekocht und die Zutaten einzeln notiert hat, baut daraus in
   fuenf Sekunden ein Gericht. */
function ausTagHtml() {
    const heutige = ((state.tag && state.tag.entries) || [])
        .filter(e => e.kind === 'item');
    if (!heutige.length) return '';
    return `<div class="nw-g-austag">
        <p class="ern-note">Aus dem heutigen Tag übernehmen:</p>
        ${heutige.map((e, i) => `<button type="button" class="v-chip"
            data-austag="${i}">${esc(e.name)} · ${esc(e.amount_label)}</button>`).join('')}
    </div>`;
}

function bindeAusTag(ziel) {
    const heutige = ((state.tag && state.tag.entries) || [])
        .filter(e => e.kind === 'item');
    ziel.querySelectorAll('[data-austag]').forEach(b => b.addEventListener('click', () => {
        const e = heutige[Number(b.dataset.austag)];
        const p = e && state.bestand.find(x => x.name === e.name);
        if (p) zutatHinzufuegen(p);
    }));
}

async function gerichtSpeichern(knopf) {
    const name = (state.entwurf.name || '').trim();
    if (!name) { melde('Das Gericht braucht einen Namen.', 'error'); return; }
    if (!state.entwurf.items.length) { melde('Mindestens eine Zutat.', 'error'); return; }
    knopf.classList.add('is-loading');
    try {
        const res = await API.gericht({
            id: state.entwurf.id, name,
            items: state.entwurf.items.map(z => ({
                item_id: z.item_id, amount: z.amount, unit: z.unit })),
        });
        state.gerichte = res.dishes;
        // Das Foto erst danach: vorher gibt es noch keine ID, an die es
        // gehoeren koennte.
        if (state.entwurf.foto && res.dish_id) {
            try {
                await API.fotoHochladen(res.dish_id, state.entwurf.foto);
                await ladeGerichte();
            } catch (err) {
                melde('Das Gericht ist gespeichert, das Foto nicht: '
                      + (err.message || ''), 'error');
            }
        }
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
        text: `„${g ? g.name : 'Das Gericht'}“ verschwindet samt Rezept. Bereits `
            + 'eingetragene Tage verlieren diese Einträge. Dein Essenstagebuch bleibt '
            + 'davon unberührt.',
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

/* Die Liste der Gerichte. Sie war bis v2.3.0 eine eigene Zeilenform mit
   Foto, drei Textbloecken und zwei Knoepfen rechts -- bei 390 px blieben
   fuer den Namen rund achtzig Pixel, und „Wraps mit Haehnchen“ brach mitten
   im Wort um. Jetzt ist es die geteilte `.rec-list` (DESIGN 6c): das Foto
   steht an der Stelle der Marke, die ganze Zeile oeffnet das Gericht, und
   „Entfernen“ liegt im Dialog dahinter -- eine Zeile, eine Hauptsache. */
function zeichneGerichte() {
    const ziel = document.getElementById('ernGerichte');
    document.getElementById('ernGerichteZahl').textContent =
        state.gerichte.length
            ? state.gerichte.length + (state.gerichte.length === 1 ? ' Gericht' : ' Gerichte')
            : '';
    if (!state.gerichte.length) {
        ziel.innerHTML = leerKarte('📖',
            'Noch keine Gerichte. Was du oft isst, legst du einmal an — '
            + 'danach reicht ein Tipp am Tag.');
        return;
    }
    ziel.innerHTML = '<div class="rec-list nw-liste">' + state.gerichte.map(g => {
        const zutaten = g.items.map(z => {
            const e = (z.units || []).find(u => u.key === z.unit);
            return esc(z.name) + ' ' + z.amount + ' ' + esc(e ? e.label : z.unit);
        }).join(' · ');
        // „mind.“ statt einer Zahl, die Vollständigkeit behauptet — dieselbe
        // Sprache wie bei der Mahlzeitensumme. Es steht am WERT und nicht in
        // der Meta-Zeile: die wird gekürzt, diese Auskunft darf es nicht.
        const luecke = g.portion.incomplete.length;
        return `<button type="button" class="rec-row" data-bearbeiten="${g.id}">
            <span class="rec-mark rec-mark--bild" style="--tone:var(--nw-figur)">${
                g.has_photo ? `<img data-foto="${g.id}" alt="">`
                            : '<span aria-hidden="true">🍽️</span>'}</span>
            <span class="rec-main">
                <span class="rec-title">${esc(g.name)}</span>
                <span class="rec-meta">${zutaten || 'ohne Zutaten'}</span>
            </span>
            <span class="rec-side">
                <span class="rec-val">${g.portion.kcal != null
                    ? (luecke ? 'mind. ' : '') + zahlKurz(g.portion.kcal) + ' kcal'
                    : 'ohne Nährwerte'}</span>
                <span class="rec-sub">je Portion</span>
            </span>
            <span class="rec-go" aria-hidden="true">›</span>
        </button>`;
    }).join('') + '</div>';

    ziel.querySelectorAll('[data-bearbeiten]').forEach(b =>
        b.addEventListener('click', () => {
            const g = state.gerichte.find(x => x.id === Number(b.dataset.bearbeiten));
            if (g) gerichtDialog(g);
        }));
    // Die Bilder brauchen den Anmelde-Kopf, ein nacktes <img src> schickt
    // keinen mit. Deshalb einzeln nachladen -- und nur das kleine: zwanzig
    // Vollbilder waeren zwanzig Anfragen fuer eine Liste, die man
    // ueberfliegt. Das grosse steht im Dialog, den die Zeile oeffnet.
    ziel.querySelectorAll('[data-foto]').forEach(bild => {
        VexBild.alsBlobUrl('/api/food/dishes/' + Number(bild.dataset.foto) + '/thumb')
            .then(u => { bild.src = u; })
            .catch(() => { bild.replaceWith(Object.assign(
                document.createElement('span'), { textContent: '🍽️' })); });
    });
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
    document.getElementById('ernKamera').innerHTML = ICON.kamera + ' Schließen';
    kamera.laeuft = true;
    kameraHinweis('Kamera wird geöffnet …');
    try {
        if ('BarcodeDetector' in window) await mitBarcodeDetector();
        else await mitZXing();
    } catch (err) {
        kameraStoppen();
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
    document.getElementById('ernKamera').innerHTML = ICON.kamera + ' Scannen';
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

    const karte = document.getElementById('ernKatalogKarte');
    karte.hidden = !stand.may_import;
    if (stand.may_import) {
        document.getElementById('ernKatalogKarteSub').textContent = stand.count
            ? `${stand.count.toLocaleString('de-DE')} Produkte drin`
            : 'noch leer';
    }
}

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
              + `„${datei.name}“ ersetzt sie vollständig — ein Abzug ist ein Stand, `
              + 'zwei nebeneinander wären später nicht zu trennen.'
            : `Der Katalog ist leer. „${datei.name}“ legt ihn an.`,
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
            if (!res.found) {
                ziel.innerHTML = leerKarte('🔎', 'Zu diesem Strichcode ist nichts hinterlegt.');
                return;
            }
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
                + 'allgemeinerer Begriff — „Apfel“ statt „Apfel Elstar“.');
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

/* Aus einem Katalogtreffer ein eigenes Lebensmittel machen. Die Feldliste
   stand an zwei Stellen; mit dem Eintragen-Dialog waeren es drei geworden --
   und ein Feld, das man an einer davon vergisst, fehlt still: das
   Lebensmittel landet ohne Ballaststoffe im Bestand und der Tag ist
   unvollstaendig, ohne dass jemand einen Fehler sieht. */
async function katalogAufnehmen(p) {
    const antwort = await API.aufnehmen({
        name: p.name, brand: p.brand, barcode: p.barcode, source: 'off',
        kcal: p.kcal, protein_g: p.protein_g, carbs_g: p.carbs_g,
        sugar_g: p.sugar_g, fat_g: p.fat_g, sat_fat_g: p.sat_fat_g,
        fiber_g: p.fiber_g, salt_g: p.salt_g, portion_g: p.portion_g,
        base_unit: p.base_unit || 'g',
    });
    await ladeBestand();
    return (antwort && antwort.item)
        || state.bestand.find(x => x.name === p.name) || null;
}

async function uebernehmen(produkt) {
    try {
        const neu = await katalogAufnehmen(produkt);
        // Ohne Portionsgroesse laesst sich spaeter nur "100 g" eintragen.
        if (neu && !(neu.sizes || []).length) {
            itemDialog(neu);
            melde('Aufgenommen. Trag noch ein, was eine Einheit wiegt — dann '
                + 'kannst du „2 × Scheibe“ eintragen statt in Gramm zu rechnen.', 'info');
        } else {
            melde('In den Bestand aufgenommen.', 'success');
        }
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    }
}

/* ------------------------------------------------- Anlegen und Aendern */

const FORM = {
    fName: 'name', fBrand: 'brand', fBase: 'base_unit',
    fKcal: 'kcal', fProtein: 'protein_g', fFiber: 'fiber_g',
    fCarbs: 'carbs_g', fFat: 'fat_g',
};
const ZAHLENFELDER = ['fKcal', 'fProtein', 'fFiber', 'fCarbs', 'fFat'];

let bearbeitet = null;   // id des Lebensmittels, das gerade geaendert wird

function itemDialog(p, nameVorgabe) {
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
        <p class="ern-note">Leer lassen, was du nicht weißt — leer heißt „keine Angabe“ und
            wird später als Lücke ausgewiesen, nicht als Null verrechnet.</p>

        <div class="ern-groessen-kopf">
            <h4>Eigene Größen</h4>
            <button type="button" class="v-btn v-btn--sm" id="fGroesseNeu">Größe hinzufügen</button>
        </div>
        <div class="ern-groessen" id="fGroessen"></div>
        <p class="ern-note">Jede Zeile ist eine Einheit, die du beim Eintragen auswählen
            kannst — „2 × Scheibe“ statt „90 g“. Die <strong>erste</strong> Zeile ist die
            Standardgröße.</p>

        <div class="ern-tasten">
            <button type="button" class="v-btn v-btn--primary" id="fSpeichern">${
                p ? 'Änderung speichern' : 'Aufnehmen'}</button>
            ${p ? `<button type="button" class="v-btn v-btn--danger"
                           id="fWeg">Entfernen</button>` : ''}
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
    if (!p && nameVorgabe) document.getElementById('fName').value = nameVorgabe;
    zeichneGroessen();

    document.getElementById('fGroesseNeu').addEventListener('click', () => {
        state.formGroessen.push({ label: '', grams: null });
        zeichneGroessen();
    });
    document.getElementById('fBase').addEventListener('change', zeichneGroessen);
    document.getElementById('fSpeichern').addEventListener('click', formSpeichern);
    // Entfernen steht hier und nicht mehr als Papierkorb in der Liste: es
    // ist der seltenste Handgriff am Bestand, und daneben getippt hiesse,
    // ein Lebensmittel samt seiner Groessen zu verlieren.
    const weg = document.getElementById('fWeg');
    if (weg) weg.addEventListener('click', async () => {
        if (state.dialog) state.dialog.close();
        await entfernenItem(p.id);
    });
}

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
                        aria-label="Größe entfernen" title="Entfernen">${ICON.muell}</button>
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
        // Der Vorschlag faellt von selbst weg, sobald es das Lebensmittel
        // gibt -- dafuer muss niemand ein Haekchen setzen.
        ladeBruecke();
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
    // Dieselbe `.rec-list` wie bei den Gerichten. Vorher standen hier drei
    // Textbloecke und zwei Knoepfe nebeneinander; bei 390 px brach jeder
    // Block um, und aus einem Lebensmittel wurden fuenf Zeilen. Die Angaben
    // sind dieselben, sie stehen nur dort, wo sie hingehoeren: die eigene
    // Groesse ist das, was man beim Eintragen waehlt -- sie steht am Rand,
    // nicht in der dritten Zeile.
    ziel.innerHTML = '<div class="rec-list nw-liste">' + state.bestand.map(p => {
        const basis = esc(p.base_unit || 'g');
        // Die Meta-Zeile wird auf EINE Zeile gekürzt. Deshalb steht vorn,
        // was man beim Eintragen braucht — die eigenen Größen —, und erst
        // danach die Makros. Fehlt eine Angabe, fällt sie weg: dreimal
        // „keine Angabe“ nebeneinander war eine Zeile, die nichts sagte.
        const groessen = (p.sizes || []).map(g =>
            `${esc(g.label)} = ${g.grams} ${basis}`).join(' · ');
        const meta = [groessen || 'keine eigene Größe']
            .concat(p.protein_g != null ? [zahl(p.protein_g, ' g') + ' Eiweiß'] : [])
            .concat(p.fiber_g != null ? [zahl(p.fiber_g, ' g') + ' Ballaststoffe'] : [])
            .concat(p.user_edited ? ['von Hand gepflegt'] : []);
        return `<button type="button" class="rec-row" data-aendern="${p.id}">
            <span class="rec-mark" style="--tone:var(--nw-figur)">${esc(p.name.slice(0, 1))}</span>
            <span class="rec-main">
                <span class="rec-title">${esc(p.name)}${p.brand
                    ? ` <span class="ern-marke">${esc(p.brand)}</span>` : ''}</span>
                <span class="rec-meta">${meta.join('<span class="sep">·</span>')}</span>
            </span>
            <span class="rec-side">
                <span class="rec-val">${p.kcal != null
                    ? zahl(p.kcal, '') + ' kcal' : 'ohne Nährwerte'}</span>
                <span class="rec-sub">je 100 ${basis}</span>
            </span>
            <span class="rec-go" aria-hidden="true">›</span>
        </button>`;
    }).join('') + '</div>';
    ziel.querySelectorAll('[data-aendern]').forEach(b => b.addEventListener('click', () => {
        const p = state.bestand.find(x => x.id === Number(b.dataset.aendern));
        if (p) itemDialog(p);
    }));
}

async function entfernenItem(id) {
    const p = state.bestand.find(x => x.id === id);
    // Ein geloeschtes Lebensmittel verschwindet auch aus jedem Gericht, in
    // dem es steckt -- ohne Warnung faende man das erst wieder, wenn die
    // Naehrwerte eines Rezepts ploetzlich niedriger sind.
    const betroffen = state.gerichte.filter(g => g.items.some(z => z.item_id === id));
    const ok = await askConfirm({
        title: 'Entfernen?',
        text: `„${p ? p.name : 'Das Lebensmittel'}“ wird aus dem Bestand gelöscht.`
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
        await ladeGerichte();
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    }
}

/* ------------------------------------------------------------------ Boot */

document.addEventListener('DOMContentLoaded', async () => {
    if (!isLoggedIn()) { location.href = '/private/login.html'; return; }
    document.body.classList.add('ready');

    // Ruht das Modul, steht der Grund oben auf der Seite. Eine Seite, die in
    // keiner Leiste auftaucht und dann kommentarlos normal aussieht, waere die
    // schlechtere Ueberraschung -- und gesperrt ist hier nichts.
    // Erst bei ``vexnav:ready`` fragen, nicht jetzt: ``VexNav.istAus`` liest
    // aus dem Einstellungs-Cache im localStorage, und der ist beim ersten
    // Besuch eines Geraets leer -- dann gilt die Werkseinstellung, und die
    // laesst dieses Modul ruhen. Wer es am Handy eingeschaltet hat und am
    // Rechner herkommt, bekaeme sonst „Dieses Modul ruht“ samt einem Knopf,
    // der etwas einschalten will, das schon an ist. Das Signal faellt, wenn
    // der Serverstand da ist; die Karte ist bis dahin ohnehin verborgen.
    document.addEventListener('vexnav:ready', () => {
        if (!(window.VexNav && VexNav.istAus && VexNav.istAus('/naehrwerte/'))) return;
        const karte = document.getElementById('nwRuht');
        karte.hidden = false;
        document.getElementById('nwEinschalten').addEventListener('click', async (e) => {
            e.currentTarget.classList.add('is-loading');
            try {
                const aus = (VexNav.readOff() || []).filter(h => h !== '/naehrwerte/');
                await VexPrefs.set(VexNav.MODULE_OFF_PREF, aus);
                location.reload();
            } catch (err) {
                melde(err.message || 'Das ging nicht.', 'error');
            }
        });
    });

    try {
        const me = await fetchMe();
        document.getElementById('userLabel').textContent = '👤 ' + me.username;
    } catch (e) { /* Name ist Beiwerk */ }

    document.getElementById('logoutBtn').addEventListener('click',
        () => { clearToken(); location.href = '/private/login.html'; });

    document.getElementById('nwDatumWahl').addEventListener('change', (e) => {
        if (e.target.value) ladeTag(e.target.value);
        else e.target.value = state.datum || heute();
    });
    document.getElementById('nwZurueck').addEventListener('click', () => tagVerschieben(-1));
    document.getElementById('nwVor').addEventListener('click', () => tagVerschieben(1));
    // Zwei Knoepfe, eine Handlung: der eine steht am Rechner im Tageskopf,
    // der andere schwebt am Handy über der Tab-Leiste. Beide rufen dasselbe.
    ['nwAdd', 'nwFab'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('click', () => eintragDialog(null));
    });

    // Der Kalorienring öffnet das Tagesziel. Bis v2.6.0 stand darunter eine
    // Zeile „Richtwert 2.400 kcal“ — die Zahl steht aber schon im Ring (Wert
    // plus Rest ergibt sie) und im Zielfenster selbst, und dreimal dieselbe
    // Auskunft ist zweimal zu viel.
    const ring = document.getElementById('nwRingKcal');
    if (ring) {
        ring.addEventListener('click', zieleDialog);
        ring.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); zieleDialog(); }
        });
    }

    document.getElementById('ernGerichtNeu').addEventListener('click', () => gerichtDialog(null));
    document.getElementById('ernItemNeu').addEventListener('click', () => itemDialog(null));

    document.getElementById('ernSucheIco').innerHTML = ICON.lupe;
    const kameraKnopf = document.getElementById('ernKamera');
    kameraKnopf.innerHTML = ICON.kamera + ' Scannen';
    kameraKnopf.addEventListener('click', kameraStarten);
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
    document.addEventListener('visibilitychange', () => {
        if (document.hidden && kamera.laeuft) kameraStoppen();
    });

    zeichneReiter();
    const anker = (location.hash || '').replace('#', '');
    activateTab(anker);
    await ladeZiele();
    // „/naehrwerte/#ziele“ war einmal ein Reiter und ist jetzt ein Dialog.
    // Die Adresse bleibt gueltig: wer sie gespeichert hat, landet weiter bei
    // den Zielen -- nur eben im Kasten davor statt in einer eigenen Seite.
    if (anker === 'ziele') zieleDialog();
    await ladeTag(heute());
    await Promise.all([ladeGerichte(), ladeBestand(), ladeHaeufig(),
                       ladeBruecke()]);
});
