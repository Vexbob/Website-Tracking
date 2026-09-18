/* essen.js — v1.97.0
 *
 * Das Essenstagebuch. Es stellt eine einzige Frage: was gab es, und war es
 * normal oder uebermaessig viel?
 *
 * Was es NICHT kann, ist die Haelfte seiner Gestalt: keine Mengen, keine
 * Naehrwerte, keine Ziele, kein Bestand, kein Strichcode, kein Verlauf, keine
 * Einstellungen. Der Tracker nebenan kann das alles -- und schreibt in eine
 * andere Tabelle. Bis v1.96.0 war beides eine Seite mit einem Umschalter, und
 * ein im Tracker eingetragenes "100 g" stand danach auch im Tagebuch.
 *
 * Drei Entscheidungen tragen die Seite:
 *
 *   1. **Der Tag ist alles.** Eine Karte: Datum, Schnellwahl, Mahlzeiten.
 *      Kein Reiter, kein Diagramm. Ein Statistikteil, den man ansehen kann,
 *      aber nicht braucht, ist Ballast -- die Zeit gehoert dem Eintragen.
 *   2. **Ein Tipp reicht.** Die Schnellwahl traegt die sechs haeufigsten
 *      Namen als Knopf. Antippen = eingetragen, als "normal", in die
 *      Mahlzeit, die zur Uhrzeit passt. Alles andere geht ueber das Plus.
 *   3. **Geraten wird sichtbar.** Die Uhrzeit geht als "HH:MM" an den Server
 *      (der laeuft in UTC und darf seine eigene Uhr nicht befragen), er
 *      entscheidet, und die Zeile weiss, dass sie eine Vermutung ist.
 */

const API = {
    tag:       (d)     => apiCall('/api/food/diary/day' + (d ? '?date=' + d : '')),
    eintragen: (d)     => apiCall('/api/food/diary/log', { method: 'POST', body: d }),
    aendern:   (id, d) => apiCall('/api/food/diary/log/' + id, { method: 'PATCH', body: d }),
    weg:       (id)    => apiCall('/api/food/diary/log/' + id, { method: 'DELETE' }),
    haeufig:   ()      => apiCall('/api/food/diary/frequent'),
};

/* Die Zeichen an den Bedienelementen kommen aus VexIkon (js/ikon.js) und
   nicht mehr als Emoji -- siehe den Kopf jener Datei. */
const ICON = {
    lupe:  VexIkon.svg('lupe', 17),
    muell: VexIkon.svg('muell', 17),
};

const state = {
    tag: null, datum: null, haeufig: [],
    dialog: null, dlg: null,
};

/* ------------------------------------------------------------- Werkzeug */

const heute = () => {
    // Aus den lokalen Feldern gebaut, nicht mit toISOString: das rechnet nach
    // UTC um, und oestlich von Greenwich waere "heute" abends schon morgen.
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

function melde(text, art, versuche) {
    if (window.Toast) { Toast[art || 'info'](text); return; }
    // ui.js wird von nav-switcher.js nachgeladen und ist in der ersten
    // Sekunde womoeglich noch nicht da. Eine Fehlermeldung darf deshalb nicht
    // einfach verschwinden, sondern wartet kurz.
    const offen = versuche == null ? 10 : versuche;
    if (offen > 0) setTimeout(() => melde(text, art, offen - 1), 200);
    else if (art === 'error') askAlert({ title: 'Das ging nicht', text: text });
}

const TAG_NAMEN = ['Sonntag', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag',
                   'Freitag', 'Samstag'];

function datumKurz(iso) {
    const d = new Date(iso + 'T12:00:00');
    return isNaN(d.getTime()) ? iso
        : d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

/* Aus der Meldung des Servers einen Satz machen, der weiterhilft. Ein
   fehlender Endpunkt heisst hier fast immer dasselbe: das Frontend liegt
   schon neu auf dem Server, das Backend laeuft noch in der alten Fassung. */
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

/* Ein Ladezustand, der nie endet, sieht aus wie ein kaputter Browser: man
   wartet auf etwas, das nicht mehr kommt. */
function zeigeFehler(text) {
    document.getElementById('esInhalt').hidden = true;
    const el = document.getElementById('esFehler');
    el.hidden = false;
    el.innerHTML = `<div class="stat-card"><div class="empty is-error">
        <span class="empty-mark" aria-hidden="true">⚠️</span>
        <p class="empty-text">${esc(text)}</p>
        <button type="button" class="v-btn v-btn--primary" id="esNochmal">Erneut versuchen</button>
    </div></div>`;
    const knopf = document.getElementById('esNochmal');
    if (knopf) knopf.addEventListener('click', () => {
        knopf.classList.add('is-loading');
        ladeTag(state.datum);
    });
}

/* Dasselbe Dialog-Muster wie in den anderen Modulen: Overlay, Kopf, Koerper,
   Escape und Klick daneben schliessen. */
/* Der Dialog liegt seit v2.1.0 in /js/modal.js -- eine Fassung fuer alle
   Module, mit gesperrtem Hintergrund, Fokus im Kasten und role="dialog".
   Der Name hier bleibt, damit die Aufrufstellen unveraendert bleiben. */
function openModal(titel, inhalt, opts) {
    return VexModal.open(titel, inhalt, opts || {});
}


/* Welche Mahlzeit jetzt gemeint sein duerfte. Die Grenzen kommen vom Server
   (``meal_hours``), damit hier kein zweiter Satz Zahlen steht: angezeigt wird
   derselbe Vorschlag, den der Server beim Speichern trifft. */
function mahlzeitJetzt() {
    if ((state.datum || heute()) !== heute()) return null;
    const grenzen = (state.tag && state.tag.meal_hours) || {};
    const h = new Date().getHours();
    const reihe = ['fruehstueck', 'mittag', 'abend'];
    for (const m of reihe) {
        if (grenzen[m] != null && h < grenzen[m]) return m;
    }
    return 'snack';
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

function zeichneKopf() {
    const datum = state.datum || heute();
    const d = new Date(datum + 'T12:00:00');
    const istHeute = datum === heute();
    const gestern = new Date(Date.now() - 86400000);
    const gesternIso = gestern.getFullYear() + '-'
        + String(gestern.getMonth() + 1).padStart(2, '0') + '-'
        + String(gestern.getDate()).padStart(2, '0');
    document.getElementById('esTagName').textContent =
        istHeute ? 'Heute' : (datum === gesternIso ? 'Gestern' : TAG_NAMEN[d.getDay()]);
    document.getElementById('esTagDatum').textContent = datumKurz(datum);
    document.getElementById('esVor').disabled = istHeute;
    // Die Auswahl steht auf dem gezeigten Tag und reicht nicht in die
    // Zukunft -- dieselbe Grenze wie am Pfeil daneben.
    const wahl = document.getElementById('esDatumWahl');
    wahl.value = datum;
    wahl.max = heute();
}

/* Die Schnellwahl. Sie ist der ganze Punkt dieser Seite: nach ein paar Tagen
   steht hier genau das, was man wirklich isst, und ein Tipp genuegt. Bewusst
   immer "normal" -- ein Knopf, der mal das eine und mal das andere tut, waere
   schneller und unbrauchbar. Wer "uebermaessig" meint, tippt die Stufe in der
   Zeile darunter an. */
function zeichneSchnell() {
    const ziel = document.getElementById('esSchnell');
    const liste = (state.tag && state.tag.quick) || [];
    ziel.hidden = !liste.length;
    if (!liste.length) return;
    ziel.innerHTML = liste.map((q, i) =>
        `<button type="button" class="es-chip" data-schnell="${i}"
            title="${esc(q.label)} eintragen — ${q.count}× notiert">${esc(q.label)}</button>`
    ).join('');
    ziel.querySelectorAll('[data-schnell]').forEach(b =>
        b.addEventListener('click', () => {
            const q = liste[Number(b.dataset.schnell)];
            if (q) eintragen({ label: q.label, level: 'normal' }, b);
        }));
}

/* Der Tag nach Mahlzeiten, jede mit ihrem eigenen Plus. Wo man tippt, sagt
   schon, wohin der Eintrag gehoert -- eine Chipreihe, die dieselbe Frage
   stellt, waere ueberfluessig. Leere Mahlzeiten bleiben als schmale Zeile
   stehen: sie sind der kuerzeste Weg zum naechsten Eintrag. */
function zeichneMahlzeiten() {
    const ziel = document.getElementById('esMahlzeiten');
    const t = state.tag;
    if (!t) { ziel.innerHTML = '<span class="skel skel-block"></span>'; return; }

    ziel.innerHTML = t.meals.map(m => {
        const eigene = t.entries.filter(e => e.meal === m.key);
        // "Ohne Zuordnung" steht nur da, wenn wirklich etwas darin liegt --
        // sonst waere es eine fuenfte Mahlzeit, die niemand hat.
        if (m.key === 'ohne' && !eigene.length) return '';
        const plus = m.key === 'ohne' ? ''
            : `<button type="button" class="es-mz-plus" data-add="${esc(m.key)}"
                   aria-label="Zu ${esc(m.label)} eintragen"
                   title="Zu ${esc(m.label)} eintragen">＋</button>`;
        return `<div class="es-mz${eigene.length ? '' : ' is-leer'}">
            <div class="es-mz-kopf">
                <span class="es-mz-name">${esc(m.label)}</span>
                ${plus}
            </div>
            ${eigene.map(zeile).join('')}
        </div>`;
    }).join('');

    ziel.querySelectorAll('[data-add]').forEach(b =>
        b.addEventListener('click', () => eintragDialog(b.dataset.add)));
    ziel.querySelectorAll('[data-stufe]').forEach(b =>
        b.addEventListener('click', () => stufeUmschalten(
            Number(b.dataset.stufe), b.dataset.neu)));
    ziel.querySelectorAll('[data-oeffnen]').forEach(b =>
        b.addEventListener('click', () => eintragDialogAendern(Number(b.dataset.oeffnen))));
}

/* Zwei Bedienelemente je Zeile, nicht drei. Der Papierkorb stand bis v2.3.0
   daneben -- 44 Pixel fuer den seltensten Handgriff, direkt neben dem
   haeufigsten, und ohne Rueckfrage. „Entfernen“ steht im Aenderungs-Dialog,
   den derselbe Name mit einem Tipp oeffnet: einen Griff tiefer, dafuer nicht
   mehr aus Versehen. Die Zeile hat den Platz an den Namen zurueckgegeben, der
   vorher umbrach. */
function zeile(e) {
    const gegen = e.level === 'viel' ? 'normal' : 'viel';
    const meta = [
        e.logged_time || '',
        e.note ? esc(e.note) : '',
    ].filter(Boolean).join(' · ');
    return `<div class="es-zeile"${e.meal_auto
            ? ' title="Mahlzeit automatisch nach Uhrzeit — Namen antippen zum Ändern"' : ''}>
        <span class="es-punkt is-${esc(e.level)}" aria-hidden="true"></span>
        <button type="button" class="es-zeile-name" data-oeffnen="${e.id}">
            <strong>${esc(e.label)}</strong>
            ${meta ? `<span class="es-zeile-meta">${meta}</span>` : ''}
        </button>
        <button type="button" class="es-stufe is-${esc(e.level)}"
                data-stufe="${e.id}" data-neu="${gegen}"
                title="Umstellen auf ${gegen === 'viel' ? 'übermäßig' : 'normal'}"
            >${esc(e.level_label)}</button>
    </div>`;
}

function zeichneFuss() {
    const c = state.tag && state.tag.counts;
    const el = document.getElementById('esFuss');
    if (!c || !c.entries) {
        el.textContent = state.tag
            ? 'Für diesen Tag steht noch nichts da — ein Wort reicht.' : '';
        return;
    }
    el.innerHTML = `<span class="es-punkt is-normal" aria-hidden="true"></span> ${c.normal} normal`
        + ` <span class="es-punkt is-viel" aria-hidden="true"></span> ${c.viel} übermäßig`
        + ` · ${c.entries} ${c.entries === 1 ? 'Eintrag' : 'Einträge'}`;
}

function zeichneTag() {
    zeichneKopf();
    zeichneSchnell();
    zeichneMahlzeiten();
    zeichneFuss();
}

async function ladeTag(datum) {
    state.datum = datum || state.datum || heute();
    let tag;
    try {
        tag = await API.tag(state.datum);
    } catch (err) {
        zeigeFehler(fehlerText(err));
        return;
    }
    // Eine Antwort ohne ``counts`` und ``meals`` kommt aus einer aelteren
    // Fassung des Backends. Sie durchzulassen hiesse, die Seite mitten im
    // Zeichnen an einem fehlenden Feld abbrechen zu lassen -- und was man
    // dann saehe, waere eine halbe Seite ohne Grund.
    if (!tag || !tag.counts || !tag.meals) { zeigeFehler(VERALTET); return; }
    state.tag = tag;
    document.getElementById('esFehler').hidden = true;
    document.getElementById('esInhalt').hidden = false;
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
                  zuletzt: [], liste: [] };

    const titel = (state.datum || heute()) === heute()
        ? 'Eintragen · heute' : 'Eintragen · ' + datumKurz(state.datum);
    // Mahlzeit und Suchfeld kleben oben: sie sind der Kopf des Vorgangs und
    // duerfen nicht unter dem Daumen wegwandern, waehrend die Liste darunter
    // waechst und schrumpft.
    const inhalt = `
        <div class="es-dlg-kopf">
            <div class="es-dlg-mahlzeiten" id="esDlgMahlzeiten"></div>
            <label class="es-suche">
                <span class="es-suche-ico" aria-hidden="true">${ICON.lupe}</span>
                <input type="search" id="esDlgSuche" autocomplete="off"
                       aria-label="Was gab es?"
                       placeholder="Tippen, was es gab — „Pizza“, „Müsli“">
            </label>
        </div>
        <div id="esDlgListe"></div>
        <div class="es-dlg-fuss">
            <span class="es-note" id="esDlgZuletzt"></span>
            <button type="button" class="v-btn v-btn--primary" id="esDlgFertig">Fertig</button>
        </div>`;

    state.dialog = openModal(titel, inhalt, {
        // voll: auf dem Handy das ganze Bild. Ein mittig zentrierter Kasten
        // rueckt bei JEDER Aenderung seiner Hoehe um die halbe Differenz --
        // und die Hoehe aendert sich hier bei jedem getippten Zeichen, weil
        // die Vorschlagsliste mitwaechst. Das war das Ruckeln: nicht die
        // Liste sprang, der Rahmen sprang.
        breit: true, voll: true,
        beimSchliessen: () => {
            state.dialog = null;
            state.dlg = null;
        },
    });

    zeichneDlgMahlzeiten();
    zeichneDlgListe();

    const feld = document.getElementById('esDlgSuche');
    feld.addEventListener('input', (e) => {
        // Sofort. Die Liste steht im Speicher, es gibt hier keine Anfrage,
        // auf deren Ruhe man warten muesste -- der Taktgeber, der bis v2.3.0
        // hier stand, verzoegerte nichts Teures, sondern nur die Antwort auf
        // den eigenen Finger.
        state.dlg.eingabe = e.target.value;
        zeichneDlgListe();
    });
    // Enter traegt den ersten Vorschlag normal ein -- der haeufigste Fall,
    // und er soll ohne Maus gehen.
    feld.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        state.dlg.eingabe = e.target.value;
        zeichneDlgListe();
        const erste = document.querySelector('#esDlgListe [data-normal]');
        if (erste) erste.click();
    });
    document.getElementById('esDlgFertig')
        .addEventListener('click', () => state.dialog && state.dialog.close());
    // Auf dem Handy oeffnet der Fokus die Tastatur und verdeckt die Liste;
    // am Rechner ist er genau das, was man will.
    if (window.matchMedia('(min-width: 720px)').matches) feld.focus();
}

function zeichneDlgMahlzeiten() {
    const ziel = document.getElementById('esDlgMahlzeiten');
    if (!ziel || !state.dlg) return;
    const vorschlag = mahlzeitJetzt();
    ziel.innerHTML = ((state.tag && state.tag.meals) || []).map(m => {
        const aktiv = (state.dlg.mahlzeit || 'ohne') === m.key;
        // Der Vorschlag traegt sein Wort: man sieht die Entscheidung, bevor
        // man tippt, und ein anderer Chip ueberstimmt sie mit einem Tipp.
        const jetztHin = m.key === vorschlag ? '<span class="v-chip-jetzt">jetzt</span>' : '';
        return `<button type="button" class="v-chip${aktiv ? ' is-active' : ''}"
            data-mahlzeit="${esc(m.key)}">${esc(m.label)}${jetztHin}</button>`;
    }).join('');
    ziel.querySelectorAll('[data-mahlzeit]').forEach(b => b.addEventListener('click', () => {
        // Von Hand gewaehlt schlaegt die Uhr: der Server raet nur, wo keine
        // Mahlzeit mitkommt. Die Uhrzeit geht trotzdem mit -- sie steht an
        // der Zeile und sagt, wann es war.
        state.dlg.mahlzeit = b.dataset.mahlzeit === 'ohne' ? null : b.dataset.mahlzeit;
        zeichneDlgMahlzeiten();
    }));
}

/* Zwei Quellen, nicht vier: der frei getippte Text und das, was man oft
   eintraegt. Kein Bestand, keine Gerichte, keine Katalogsuche -- was es nicht
   gibt, kann auch nicht ueberfrachten. */
function dlgVorschlaege() {
    const text = (state.dlg.eingabe || '').trim();
    const suche = text.toLowerCase();
    const frei = !text ? [] : [{ label: text, neu: true,
                                 sub: 'so hinschreiben' }];
    const bekannt = state.haeufig
        .filter(h => !suche || h.label.toLowerCase().includes(suche))
        // Was man gerade tippt, steht schon oben -- nicht zweimal.
        .filter(h => h.label.toLowerCase() !== suche)
        .map(h => ({ label: h.label,
                     sub: `${h.count}× notiert · zuletzt ${datumKurz(h.last)}` }));
    return frei.concat(bekannt);
}

/* Eine Zeile, eine Hauptsache: die ganze Zeile ist der Knopf fuer "normal",
   "uebermaessig" steht klein daneben. Zwei gleich grosse Knoepfe je Zeile
   waeren bei zehn Vorschlaegen zwanzig gleichberechtigte Ziele. */
function zeichneDlgListe() {
    const ziel = document.getElementById('esDlgListe');
    if (!ziel || !state.dlg) return;
    const liste = dlgVorschlaege();
    state.dlg.liste = liste;

    if (!liste.length) {
        ziel.innerHTML = `<div class="empty">
            <span class="empty-mark" aria-hidden="true">✏️</span>
            <p class="empty-text">Tipp oben hin, was es gab — „Pizza“, „Müsli“, „Kaffee“.
            Es muss in keiner Liste stehen, und ab dem zweiten Mal schlägt die Seite es
            dir selbst vor.</p></div>`;
        return;
    }

    const MAX = 12;
    ziel.innerHTML = liste.slice(0, MAX).map((v, i) => `
        <div class="es-w${v.neu ? ' is-neu' : ''}">
            <button type="button" class="es-w-haupt" data-normal="${i}">
                <span class="es-w-name">${esc(v.label)}</span>
                <span class="es-w-sub">${esc(v.sub || '')}</span>
            </button>
            <button type="button" class="es-w-viel" data-viel="${i}"
                    title="Als übermäßig eintragen">übermäßig</button>
        </div>`).join('')
        + (liste.length > MAX
            ? `<p class="es-note">… und ${liste.length - MAX} weitere — tipp oben weiter.</p>`
            : '');

    const nimm = (i) => state.dlg.liste[Number(i)];
    ziel.querySelectorAll('[data-normal]').forEach(b => b.addEventListener('click', () => {
        const v = nimm(b.dataset.normal);
        if (v) eintragen({ label: v.label, level: 'normal' }, b);
    }));
    ziel.querySelectorAll('[data-viel]').forEach(b => b.addEventListener('click', () => {
        const v = nimm(b.dataset.viel);
        if (v) eintragen({ label: v.label, level: 'viel' }, b);
    }));
}

async function eintragen(daten, knopf) {
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
            // Das Feld leeren: der naechste Eintrag faengt bei null an, und
            // ein stehengebliebener Text sieht aus, als waere nichts
            // passiert.
            state.dlg.eingabe = '';
            const feld = document.getElementById('esDlgSuche');
            if (feld) { feld.value = ''; feld.focus(); }
            state.dlg.zuletzt.push(daten.label);
            const fuss = document.getElementById('esDlgZuletzt');
            if (fuss) fuss.textContent = 'Eingetragen: ' + state.dlg.zuletzt.join(', ');
            zeichneDlgListe();
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

async function stufeUmschalten(id, neu) {
    try {
        state.tag = await API.aendern(id, { level: neu });
        zeichneTag();
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    }
}

async function entfernen(id) {
    try {
        state.tag = await API.weg(id);
        zeichneTag();
        ladeHaeufig();
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    }
}

/* ------------------------------------------------------ Eintrag ändern
 *
 * Ein Ort fuer alles, was an einer Zeile falsch sein kann: der Name, die
 * Stufe, die Mahlzeit. Die Stufe laesst sich auch in der Zeile umschalten --
 * das ist der haeufige Fall und soll ein Tipp bleiben.
 */
function eintragDialogAendern(id) {
    const e = (state.tag && state.tag.entries || []).find(x => x.id === id);
    if (!e) return;
    const inhalt = `
        <label class="es-feld">
            <span>Was gab es?</span>
            <input type="text" id="esEdName" value="${esc(e.label)}" autocomplete="off">
        </label>
        <div class="es-feld">
            <span>Wie viel?</span>
            <div class="es-ed-stufen" id="esEdStufen"></div>
        </div>
        <div class="es-feld">
            <span>Wann?</span>
            <div class="es-dlg-mahlzeiten" id="esEdMahlzeiten"></div>
        </div>
        <label class="es-feld">
            <span>Notiz</span>
            <input type="text" id="esEdNote" value="${esc(e.note || '')}"
                   autocomplete="off" placeholder="optional">
        </label>
        <div class="es-tasten">
            <button type="button" class="v-btn v-btn--primary" id="esEdOk">Übernehmen</button>
            <button type="button" class="v-btn v-btn--danger" id="esEdWeg">Entfernen</button>
        </div>`;

    const wahl = { level: e.level, meal: e.meal === 'ohne' ? null : e.meal };
    const dlg = openModal('Eintrag', inhalt);

    const zeichneStufen = () => {
        const ziel = document.getElementById('esEdStufen');
        ziel.innerHTML = ((state.tag && state.tag.levels) || []).map(s =>
            `<button type="button" class="v-chip${wahl.level === s.key ? ' is-active' : ''}"
                data-stufe="${esc(s.key)}">${esc(s.label)}</button>`).join('');
        ziel.querySelectorAll('[data-stufe]').forEach(b => b.addEventListener('click', () => {
            wahl.level = b.dataset.stufe; zeichneStufen();
        }));
    };
    const zeichneMz = () => {
        const ziel = document.getElementById('esEdMahlzeiten');
        ziel.innerHTML = ((state.tag && state.tag.meals) || []).map(m =>
            `<button type="button" class="v-chip${
                (wahl.meal || 'ohne') === m.key ? ' is-active' : ''}"
                data-mahlzeit="${esc(m.key)}">${esc(m.label)}</button>`).join('');
        ziel.querySelectorAll('[data-mahlzeit]').forEach(b => b.addEventListener('click', () => {
            wahl.meal = b.dataset.mahlzeit === 'ohne' ? null : b.dataset.mahlzeit;
            zeichneMz();
        }));
    };
    zeichneStufen();
    zeichneMz();

    document.getElementById('esEdOk').addEventListener('click', async (ev) => {
        const knopf = ev.currentTarget;
        knopf.classList.add('is-loading');
        try {
            state.tag = await API.aendern(id, {
                label: document.getElementById('esEdName').value,
                level: wahl.level,
                meal: wahl.meal === null ? 'ohne' : wahl.meal,
                note: document.getElementById('esEdNote').value,
            });
            dlg.close();
            zeichneTag();
            ladeHaeufig();
        } catch (err) {
            melde(err.message || 'Das ging nicht.', 'error');
        } finally {
            knopf.classList.remove('is-loading');
        }
    });
    document.getElementById('esEdWeg').addEventListener('click', async () => {
        dlg.close();
        await entfernen(id);
    });
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

    document.getElementById('esDatumWahl').addEventListener('change', (e) => {
        // Ein leeres Feld (die Auswahl laesst sich auch loeschen) heisst
        // nicht "kein Tag", sondern "nichts gewaehlt" -- dann bleibt alles.
        if (e.target.value) ladeTag(e.target.value);
        else e.target.value = state.datum || heute();
    });
    document.getElementById('esZurueck').addEventListener('click', () => tagVerschieben(-1));
    document.getElementById('esVor').addEventListener('click', () => tagVerschieben(1));
    document.getElementById('esAdd').addEventListener('click', () => eintragDialog(null));

    await ladeTag(heute());
    ladeHaeufig();
});
