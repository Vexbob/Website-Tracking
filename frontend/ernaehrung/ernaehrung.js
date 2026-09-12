/* ernaehrung.js — v1.85.0
 *
 * Das Ernaehrungs-Modul. Bisher gebaut: der Lebensmittel-Bestand und wie er
 * sich fuellt -- ueber den Strichcode oder die Textsuche bei Open Food Facts.
 * Gerichte und das Tagebuch folgen; die leeren Zustaende dort sagen, woran
 * es noch fehlt.
 *
 * Drei Entscheidungen, die das Modul tragen:
 *
 *   1. **Stufen fuer Gerichte, Mengen fuer Lebensmittel.** Wie viel von
 *      den eigenen Wraps auf dem Teller lag, weiss niemand in Gramm --
 *      dort wird "normal" oder "uebermaessig" erfasst und daraus eine
 *      Spanne. Was einzeln dasteht, weiss man dagegen genau genug: 100 g,
 *      zwei Scheiben, eine Packung. Die Einheiten dafuer stehen als eigene
 *      Groessen am Lebensmittel, beliebig viele.
 *   2. **Fremde Daten bleiben fremd.** Was von Open Food Facts kommt, ist
 *      ein Vorschlag: aenderbar, als Herkunft erkennbar, und fehlende
 *      Angaben bleiben leer. Eine 0 bei Ballaststoffen liefe in jeder
 *      Tagessumme mit, ohne zu stimmen.
 *   3. **Der eigene Bestand geht vor.** Derselbe Artikel zum zweiten Mal
 *      gescannt zeigt die eigenen, vielleicht korrigierten Werte.
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
    tag:      (d)  => apiCall('/api/food/day' + (d ? '?date=' + d : '')),
    eintragen:(d)  => apiCall('/api/food/log', { method: 'POST', body: d }),
    eintragWeg: (id) => apiCall('/api/food/log/' + id, { method: 'DELETE' }),
};

const TABS = ['heute', 'gerichte', 'scanner'];

// Die beiden Einheiten, in denen die Naehrwerte stehen. Alles andere ist
// eine eigene Groesse des Lebensmittels und traegt ihren Namen als
// Schluessel -- "Scheibe", "Laib", "Becher".
const BASIS = ['g', 'ml'];

const state = {
    bestand: [], vorschlag: null, groessenVorschlaege: [],
    // Die Groessen-Zeilen des Formulars: [{label, grams}]
    formGroessen: [],
    tag: null, datum: null, gerichte: [], schnellSuche: '',
    // Das Gericht, das gerade gebaut wird: {id, name, items:[{item_id, name, grams}]}
    entwurf: { id: null, name: '', items: [] },
};

const heute = () => new Date().toISOString().slice(0, 10);

const esc = (v) => String(v == null ? '' : v)
    .replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

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

// Naehrwerte in der Reihenfolge, in der sie gelesen werden. "fehlt" ist ein
// eigener Zustand -- nicht 0.
const WERTE = [
    { key: 'kcal',      label: 'kcal',          einheit: '' },
    { key: 'protein_g', label: 'Eiweiß',        einheit: ' g' },
    { key: 'fiber_g',   label: 'Ballaststoffe', einheit: ' g' },
    { key: 'carbs_g',   label: 'Kohlenhydrate', einheit: ' g' },
    { key: 'fat_g',     label: 'Fett',          einheit: ' g' },
];

const zahl = (v, einheit) => v == null
    ? '<span class="ern-fehlt">keine Angabe</span>'
    : v.toLocaleString('de-DE', { maximumFractionDigits: 1 }) + einheit;

function naehrwertZeile(p) {
    return `<div class="ern-werte">${WERTE.map(w => `
        <div class="ern-wert">
            <div class="ern-wert-lbl">${w.label}</div>
            <div class="ern-wert-num">${zahl(p[w.key], w.einheit)}</div>
        </div>`).join('')}</div>
        <p class="ern-klein">je 100 g${p.portion_g ? ` · übliche Portion ${p.portion_g} g` : ''}</p>`;
}

const HERKUNFT = {
    katalog: 'eigener Katalog',
    off: 'Open Food Facts',
};

/* Wie alt der Katalog ist, gehoert auf den Bildschirm: ein Nachschlagewerk,
   dessen Stand man nicht sieht, wird irgendwann geglaubt, obwohl es nicht
   mehr stimmt. */
async function katalogStand() {
    const el = document.getElementById('ernKatalogStand');
    let stand;
    try { stand = await API.katalog(); } catch (e) { return; }
    if (!stand.count) {
        el.textContent = 'kein eigener Katalog — es wird direkt bei Open Food Facts gefragt';
        return;
    }
    const alter = stand.newest
        ? new Date(stand.newest * 1000).toLocaleDateString('de-DE',
            { day: '2-digit', month: '2-digit', year: 'numeric' })
        : null;
    el.textContent = `eigener Katalog: ${stand.count.toLocaleString('de-DE')} Produkte`
        + (alter ? ` · Stand ${alter}` : '');
}

function zeichneTreffer(ziel, produkt, bekannt, notiz, herkunft) {
    state.vorschlag = produkt;
    const el = document.getElementById(ziel);
    if (!produkt && bekannt) {
        el.innerHTML = `<div class="v-row ern-treffer">
            <div class="ern-kopf"><strong>${esc(bekannt.name)}</strong>
                <span class="ern-herkunft">schon im Bestand</span></div>
            ${naehrwertZeile(bekannt)}
            ${notiz ? `<p class="ern-klein">${esc(notiz)}</p>` : ''}
        </div>`;
        return;
    }
    if (!produkt) { el.innerHTML = ''; return; }
    el.innerHTML = `<div class="v-row ern-treffer">
        <div class="ern-kopf">
            <strong>${esc(produkt.name)}</strong>
            ${produkt.brand ? `<span class="ern-marke">${esc(produkt.brand)}</span>` : ''}
            <span class="ern-herkunft">${esc(HERKUNFT[herkunft] || 'Open Food Facts')}</span>
        </div>
        ${naehrwertZeile(produkt)}
        ${bekannt ? '<p class="ern-klein">Dieses Lebensmittel ist bereits im Bestand — Übernehmen aktualisiert die Werte.</p>' : ''}
        ${produkt.missing && produkt.missing.length
            ? `<p class="ern-klein">Dort fehlen: ${produkt.missing.length} Angabe(n). Du kannst sie nach dem Übernehmen von der Packung nachtragen.</p>`
            : ''}
        <div class="ern-tasten">
            <button type="button" class="v-btn v-btn--primary" id="ernUebernehmen">In den Bestand</button>
        </div>
    </div>`;
    const knopf = document.getElementById('ernUebernehmen');
    if (knopf) knopf.addEventListener('click', () => uebernehmen(produkt));
}

/* ----------------------------------------------------------------- Tag
 *
 * Die Anzeige zeigt SPANNEN, keine Einzelwerte. Wer "Wraps, uebermaessig"
 * eintraegt, hat keine 612 kcal gegessen -- er hat irgendetwas zwischen
 * anderthalb und doppelt so viel wie eine Portion gegessen. Genau das steht
 * da: ein Balken mit Anfang und Ende, keine Scheibe eines Kreises.
 *
 * Das uebliche Halbkreis-Design der Ernaehrungs-Apps setzt eine genaue Zahl
 * und ein festes Ziel voraus. Beides gibt es hier nicht -- ein Ring, der zu
 * 73 % gefuellt ist, waere zwei Behauptungen auf einmal.
 */

const TAG_NAMEN = ['Sonntag', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag',
                   'Freitag', 'Samstag'];

const zahlKurz = (v) => Math.round(v).toLocaleString('de-DE');

function tagVerschieben(tage) {
    const d = new Date((state.datum || heute()) + 'T12:00:00');
    d.setDate(d.getDate() + tage);
    const neu = d.toISOString().slice(0, 10);
    // Nicht in die Zukunft: was morgen gegessen wird, weiss heute niemand.
    if (neu > heute()) return;
    ladeTag(neu);
}

function zeichneTagKopf() {
    const datum = state.datum || heute();
    const d = new Date(datum + 'T12:00:00');
    const istHeute = datum === heute();
    const gestern = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
    document.getElementById('ernTagName').textContent =
        istHeute ? 'Heute' : (datum === gestern ? 'Gestern' : TAG_NAMEN[d.getDay()]);
    document.getElementById('ernTagDatum').textContent =
        d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
    document.getElementById('ernTagVor').disabled = istHeute;
}

function zeichneSumme() {
    const t = state.tag;
    const kcal = t.totals.kcal;
    const anzahl = t.entries.length;
    document.getElementById('ernSumme').innerHTML = !anzahl
        ? `<div class="ern-summe-leer">Für diesen Tag ist noch nichts eingetragen.</div>`
        : `<div class="ern-summe-zahl">
               <span>${zahlKurz(kcal.min)}</span>
               <span class="ern-summe-bis">bis</span>
               <span>${zahlKurz(kcal.max)}</span>
               <span class="ern-summe-einheit">kcal</span>
           </div>
           <div class="ern-klein">geschätzt aus ${anzahl} ${anzahl === 1 ? 'Eintrag' : 'Einträgen'} — ${
               kcal.incomplete ? 'mindestens, es fehlen Angaben' : 'zwei Grobstufen ergeben eine Spanne, keine genaue Zahl'}</div>`;
}

/* Ein Band je Naehrwert: die Spur reicht bis zum Anderthalbfachen des
   Richtwerts, der Richtwert selbst steht als Strich darin. Gefuellt ist
   genau der Bereich zwischen der unteren und der oberen Schaetzung -- die
   Breite des Balkens IST die Unsicherheit. */
function band(makro, d) {
    const links = Math.min(100, (d.share_min / 1.5) * 100);
    const breite = Math.max(2, Math.min(100 - links, ((d.share_max - d.share_min) / 1.5) * 100));
    const einheit = makro === 'kcal' ? '' : ' g';
    return `<div class="ern-band${d.incomplete ? ' is-unvollstaendig' : ''}">
        <div class="ern-band-kopf">
            <span class="ern-band-lbl">${d.label}</span>
            <span class="ern-band-wert">${d.incomplete ? 'mind. ' : ''}${zahlKurz(d.min)}–${zahlKurz(d.max)}${einheit}</span>
        </div>
        <div class="ern-band-spur" role="img"
             aria-label="${d.label}: ${zahlKurz(d.min)} bis ${zahlKurz(d.max)}${einheit}, Richtwert ${zahlKurz(d.reference)}${einheit}">
            <span class="ern-band-marke" style="left:66.7%"></span>
            <span class="ern-band-fuell" style="left:${links.toFixed(1)}%;width:${breite.toFixed(1)}%"></span>
        </div>
        ${d.incomplete ? '<div class="ern-band-fuss">Eine Zutat macht dazu keine Angabe — der Wert ist mindestens so hoch.</div>' : ''}
    </div>`;
}

function zeichneBaender() {
    const t = state.tag;
    document.getElementById('ernBaender').innerHTML = t.entries.length
        ? t.macros.filter(m => m !== 'kcal').map(m => band(m, t.totals[m])).join('')
        : '';
    document.getElementById('ernMassstab').textContent = t.entries.length
        ? 'Der Strich im Balken ist der Richtwert für einen Tag. ' + t.reference_note
        : '';
}

/* Eine genaue Menge ergibt eine Zahl, eine Stufe eine Spanne -- und das
   soll man der Zeile ansehen. "320-320 kcal" waere ein Bindestrich, der
   Unsicherheit behauptet, wo keine ist. */
function kcalText(e) {
    return e.kcal_min === e.kcal_max
        ? `${zahlKurz(e.kcal_min)} kcal`
        : `${zahlKurz(e.kcal_min)}–${zahlKurz(e.kcal_max)} kcal`;
}

function zeichneEintraege() {
    const t = state.tag;
    document.getElementById('ernEintraegeZahl').textContent =
        t.entries.length ? t.entries.length + ' an diesem Tag' : '';
    document.getElementById('ernEintraege').innerHTML = !t.entries.length
        ? `<div class="empty"><span class="empty-mark">🍽️</span>
             <p class="empty-text">Noch nichts eingetragen. Ein Gericht oben antippen —
             normal oder übermäßig, mehr wird nicht gefragt. Bei einem einzelnen
             Lebensmittel sagst du, wie viel: 100 g, zwei Scheiben, eine Packung.</p></div>`
        : t.entries.map(e => `
            <div class="v-row ern-zeile">
                <div class="ern-zeile-text">
                    <strong>${esc(e.name)}</strong>
                    ${e.amount_label
                        ? `<span class="ern-stufe is-menge">${esc(e.amount_label)}</span>`
                        : `<span class="ern-stufe is-${e.level}">${esc(e.level_label || '')}</span>`}
                    <div class="ern-klein">${esc(e.sub || '')}${
                        e.kcal_min != null ? ` · ${kcalText(e)}` : ''}${
                        e.assumed_portion ? ' · Portion mit 100 g angenommen' : ''}</div>
                </div>
                <button type="button" class="v-btn v-btn--icon" data-eintrag="${e.id}"
                        aria-label="Eintrag entfernen" title="Entfernen">🗑️</button>
            </div>`).join('');
    document.querySelectorAll('[data-eintrag]').forEach(b =>
        b.addEventListener('click', () => eintragEntfernen(Number(b.dataset.eintrag))));
}

/* Schnelleintrag: je Gericht eine Zeile mit zwei Knoepfen. Ein Tipp, fertig --
   erst eine Auswahlliste zu oeffnen und dann die Menge zu waehlen, waere der
   Weg, den man nach einer Woche nicht mehr geht. */
const SCHNELL_MAX = 12;

/* Gerichte zuerst, danach einzelne Lebensmittel -- und alles durchsuchbar.
   Vorher waren nur acht Lebensmittel MIT hinterlegter Portion zu sehen: alles
   frisch Gescannte fehlte in der Liste, ohne dass man den Grund sah. */
function zeichneSchnell() {
    const ziel = document.getElementById('ernSchnell');
    const suche = (state.schnellSuche || '').toLowerCase();
    const passt = (name, marke) => !suche
        || name.toLowerCase().includes(suche)
        || (marke || '').toLowerCase().includes(suche);

    if (!state.gerichte.length && !state.bestand.length) {
        ziel.innerHTML = `<div class="empty"><span class="empty-mark">📖</span>
            <p class="empty-text">Noch nichts zum Eintragen da. Über den <strong>Scanner</strong>
            kommen Lebensmittel herein, unter <strong>Gerichte</strong> stellst du daraus
            eines zusammen — danach steht beides hier.</p></div>`;
        return;
    }

    const rahmen = (name, sub, innen) => `
        <div class="v-row ern-schnell">
            <div class="ern-zeile-text">
                <strong>${esc(name)}</strong>
                <div class="ern-klein">${esc(sub)}</div>
            </div>
            ${innen}
        </div>`;

    // Ein Gericht: zwei Knoepfe, ein Tipp. Die Stufe ist hier die ehrliche
    // Angabe -- wie viel vom eigenen Rezept auf dem Teller lag, weiss
    // niemand in Gramm.
    const gerichtZeile = (g) => rahmen(g.name,
        g.portion.kcal != null
            ? `${zahlKurz(g.portion.kcal)} kcal je Portion`
            : 'Nährwerte unvollständig',
        `<div class="ern-schnell-tasten">
            <button type="button" class="v-btn v-btn--sm" data-dish="${g.id}" data-stufe="normal">normal</button>
            <button type="button" class="v-btn v-btn--sm" data-dish="${g.id}" data-stufe="viel">übermäßig</button>
        </div>`);

    // Ein einzelnes Lebensmittel: die Menge, wie sie dasteht. Vorbelegt ist
    // die erste eigene Groesse (meist die, die man nimmt), sonst 100 g.
    const itemZeile = (p) => {
        const einheiten = p.units || [{ key: p.base_unit || 'g', label: p.base_unit || 'g' }];
        const eigene = einheiten.filter(e => !BASIS.includes(e.key));
        const start = eigene.length ? eigene[0] : einheiten[0];
        const menge = eigene.length ? 1 : 100;
        return rahmen(p.name,
            (p.brand ? esc(p.brand) + ' · ' : '')
            + (eigene.length
                ? eigene.map(e => `1 ${e.label} = ${e.grams} ${p.base_unit || 'g'}`).join(' · ')
                : `keine eigene Größe hinterlegt`),
            `<div class="ern-menge">
                <input type="number" class="ern-menge-zahl" min="0" step="0.25"
                       inputmode="decimal" value="${menge}" data-menge="${p.id}"
                       aria-label="Menge für ${esc(p.name)}">
                <select class="v-select v-select--sm" data-einheit="${p.id}"
                        aria-label="Einheit für ${esc(p.name)}">
                    ${einheiten.map(e => `<option value="${esc(e.key)}"${
                        e.key === start.key ? ' selected' : ''}>${esc(e.label)}</option>`).join('')}
                </select>
                <button type="button" class="v-btn v-btn--sm" data-item="${p.id}">Eintragen</button>
            </div>`);
    };

    const gerichte = state.gerichte.filter(g => passt(g.name, ''));
    // Lebensmittel mit eigener Groesse zuerst: dort geht das Eintragen mit
    // einer Zahl, bei den anderen steht erst einmal 100 g im Feld.
    const lebensmittel = state.bestand
        .filter(p => passt(p.name, p.brand))
        .sort((a, b) => ((b.sizes || []).length ? 1 : 0) - ((a.sizes || []).length ? 1 : 0));

    const zeilen = gerichte.map(gerichtZeile).concat(lebensmittel.map(itemZeile));

    ziel.innerHTML = zeilen.length
        ? zeilen.slice(0, SCHNELL_MAX).join('')
          + (zeilen.length > SCHNELL_MAX
             ? `<p class="ern-klein">… und ${zeilen.length - SCHNELL_MAX} weitere — such oben danach.</p>`
             : '')
        : `<p class="ern-klein">Nichts gefunden, das zu „${esc(state.schnellSuche)}“ passt.</p>`;

    ziel.querySelectorAll('[data-stufe]').forEach(b => b.addEventListener('click', () =>
        eintragen({ dish_id: Number(b.dataset.dish), level: b.dataset.stufe }, b)));
    ziel.querySelectorAll('[data-item]').forEach(b => b.addEventListener('click', () => {
        const id = Number(b.dataset.item);
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
        state.tag = await API.eintragen(
            Object.assign({ day: state.datum || heute() }, daten));
        zeichneTag();
        melde('Eingetragen.', 'success');
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    } finally {
        knopf.classList.remove('is-loading');
    }
}

async function eintragEntfernen(id) {
    try {
        state.tag = await API.eintragWeg(id);
        zeichneTag();
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    }
}

function zeichneTag() {
    zeichneTagKopf();
    zeichneSumme();
    zeichneBaender();
    zeichneEintraege();
}

async function ladeTag(datum) {
    state.datum = datum || state.datum || heute();
    try {
        state.tag = await API.tag(state.datum);
    } catch (err) {
        melde(err.message || 'Der Tag konnte nicht geladen werden.', 'error');
        return;
    }
    zeichneTag();
}

/* ------------------------------------------------------------- Gerichte */

function zeichneEntwurf() {
    const e = state.entwurf;
    document.getElementById('ernGerichtTitel').textContent =
        e.id ? 'Gericht bearbeiten' : 'Neues Gericht';
    document.getElementById('ernGerichtNeu').hidden = !e.id;
    document.getElementById('ernZutaten').innerHTML = !e.items.length
        ? '<p class="ern-klein">Noch keine Zutat. Such unten etwas aus deinem Bestand.</p>'
        : e.items.map((z, i) => `
            <div class="v-row ern-zutat">
                <div class="ern-zeile-text"><strong>${esc(z.name)}</strong></div>
                <label class="ern-gramm">
                    <input type="number" min="0.25" step="0.25" value="${z.amount}" data-menge="${i}"
                           aria-label="Menge für ${esc(z.name)}">
                    <select class="v-select v-select--sm" data-einheit="${i}"
                            aria-label="Einheit für ${esc(z.name)}">
                        ${(z.units || [{ key: 'g', label: 'g' }]).map(u =>
                            `<option value="${u.key}"${u.key === z.unit ? ' selected' : ''}>${esc(u.label)}</option>`).join('')}
                    </select>
                </label>
                <button type="button" class="v-btn v-btn--icon" data-zutat-weg="${i}"
                        aria-label="Zutat entfernen" title="Entfernen">🗑️</button>
            </div>`).join('');
    document.querySelectorAll('[data-menge]').forEach(f => f.addEventListener('change', () => {
        const wert = Number(String(f.value).replace(',', '.'));
        if (wert > 0) state.entwurf.items[Number(f.dataset.menge)].amount = wert;
    }));
    document.querySelectorAll('[data-einheit]').forEach(f => f.addEventListener('change', () => {
        state.entwurf.items[Number(f.dataset.einheit)].unit = f.value;
    }));
    document.querySelectorAll('[data-zutat-weg]').forEach(b => b.addEventListener('click', () => {
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
        ? `<p class="ern-klein">Nichts im Bestand. Über den <strong>Scanner</strong> kommt es hinein.</p>`
        : treffer.map(p => `
            <button type="button" class="v-chip ern-zutat-treffer" data-zutat="${p.id}">
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
        zeichneSchnell();
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
        ? `<div class="empty"><span class="empty-mark">📖</span>
             <p class="empty-text">Noch keine Gerichte. Was du oft isst, legst du einmal an —
             danach reicht ein Tipp am Tag.</p></div>`
        : state.gerichte.map(g => `
            <div class="v-row ern-gericht">
                <div class="ern-zeile-text">
                    <strong>${esc(g.name)}</strong>
                    <div class="ern-klein">${g.items.map(z => {
                        const e = (z.units || []).find(u => u.key === z.unit);
                        return esc(z.name) + ' ' + z.amount + ' ' + esc(e ? e.label : z.unit);
                    }).join(' · ')}</div>
                    <div class="ern-klein">${g.portion.kcal != null
                        ? `${zahlKurz(g.portion.kcal)} kcal je Portion (${g.portion.grams} g)`
                        : 'Nährwerte unvollständig'}${g.portion.incomplete.length
                        ? ' · ohne Angabe: ' + g.portion.incomplete.length : ''}</div>
                </div>
                <div class="ern-schnell-tasten">
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
    zeichneSchnell();
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
            `<div class="empty"><span class="empty-mark">🔎</span>
             <p class="empty-text">${esc(err.message || 'Nicht gefunden.')}</p></div>`;
    }
}

async function suchen(text) {
    const ziel = document.getElementById('ernSuchTreffer');
    if (text.length < 2) { ziel.innerHTML = ''; return; }
    ziel.innerHTML = '<span class="skel skel-block"></span>';
    try {
        const res = await API.suche(text);
        if (!res.results.length) {
            ziel.innerHTML = `<div class="empty"><span class="empty-mark">🔎</span>
                <p class="empty-text">Nichts gefunden. Bei Losem ohne Strichcode lohnt sich
                oft ein allgemeinerer Begriff — „Apfel" statt „Apfel Elstar".</p></div>`;
            return;
        }
        ziel.innerHTML = `<p class="ern-klein">${res.results.length} Treffer aus
            ${esc(HERKUNFT[res.origin] || 'Open Food Facts')}</p>`
            + res.results.map((p, i) => `
            <div class="v-row ern-treffer">
                <div class="ern-kopf"><strong>${esc(p.name)}</strong>
                    ${p.brand ? `<span class="ern-marke">${esc(p.brand)}</span>` : ''}</div>
                <p class="ern-klein">${zahl(p.kcal, '')} kcal · ${zahl(p.protein_g, ' g')} Eiweiß
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
        ? `<p class="ern-klein">Noch keine eigene Größe. Ohne eine trägst du dieses
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
          + '<p class="ern-klein">Die erste Zeile ist die Standardgröße.</p>';

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
    activateTab('scanner');
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
        ziel.innerHTML = `<div class="empty"><span class="empty-mark">🥫</span>
            <p class="empty-text">Noch nichts aufgenommen. Was einmal hier steht, bleibt —
            auch wenn Open Food Facts den Eintrag später ändert.</p></div>`;
        return;
    }
    ziel.innerHTML = state.bestand.map(p => `
        <div class="v-row ern-zeile">
            <div class="ern-zeile-text">
                <strong>${esc(p.name)}</strong>
                ${p.brand ? `<span class="ern-marke">${esc(p.brand)}</span>` : ''}
                <div class="ern-klein">${zahl(p.kcal, '')} kcal · ${zahl(p.protein_g, ' g')} Eiweiß
                    · ${zahl(p.fiber_g, ' g')} Ballaststoffe · je 100 ${esc(p.base_unit || 'g')}</div>
                <div class="ern-klein">${(p.sizes || []).length
                    ? (p.sizes || []).map(g =>
                        `${esc(g.label)} = ${g.grams} ${esc(p.base_unit || 'g')}`).join(' · ')
                    : 'keine eigene Größe — wird in ' + esc(p.base_unit || 'g') + ' eingetragen'
                }${p.user_edited ? ' · von Hand gepflegt' : ''}</div>
            </div>
            <div class="ern-schnell-tasten">
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
}

async function entfernen(id) {
    const p = state.bestand.find(x => x.id === id);
    // Ein geloeschtes Lebensmittel verschwindet auch aus jedem Gericht, in
    // dem es steckt -- ohne Warnung faende man das erst wieder, wenn die
    // Naehrwerte eines Rezepts ploetzlich niedriger sind.
    const betroffen = state.gerichte.filter(g =>
        g.items.some(z => z.item_id === id));
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

function activateTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.tab === tab));
    TABS.forEach(t => {
        const el = document.getElementById('tab-' + t);
        if (el) el.hidden = t !== tab;
    });
}

/* ------------------------------------------------------------------ Boot */

document.addEventListener('DOMContentLoaded', async () => {
    if (!isLoggedIn()) { location.href = '/private/login.html'; return; }
    // Freigabe direkt nach dem synchronen Login-Check: ab hier steht fest,
    // dass diese Seite bleibt. Haenge sie an eine Serverantwort, sieht man
    // bei einer haengenden Antwort nur den Seitenhintergrund.
    document.body.classList.add('ready');

    try {
        const me = await fetchMe();
        document.getElementById('userLabel').textContent = '👤 ' + me.username;
    } catch (e) { /* Name ist Beiwerk */ }

    document.getElementById('logoutBtn').addEventListener('click',
        () => { clearToken(); location.href = '/private/login.html'; });

    document.querySelectorAll('.tab-btn').forEach(b =>
        b.addEventListener('click', () => activateTab(b.dataset.tab)));

    document.getElementById('ernScanForm').addEventListener('submit', nachschlagen);
    document.getElementById('ernKamera').addEventListener('click', kameraStarten);
    document.getElementById('ernKameraStop').addEventListener('click', kameraStoppen);
    // Beim Verlassen der Seite die Kamera freigeben -- sonst bleibt das
    // Lichtlein an, bis der Tab geschlossen wird.
    window.addEventListener('pagehide', kameraStoppen);
    let tippen = null;
    document.getElementById('ernSuche').addEventListener('input', (e) => {
        clearTimeout(tippen);
        const wert = e.target.value.trim();
        // Erst tippen lassen: Open Food Facts wird ehrenamtlich betrieben,
        // eine Abfrage je Tastenanschlag waere unhoeflich.
        tippen = setTimeout(() => suchen(wert), 400);
    });

    document.getElementById('ernTagZurueck').addEventListener('click', () => tagVerschieben(-1));
    document.getElementById('ernTagVor').addEventListener('click', () => tagVerschieben(1));
    document.getElementById('ernGerichtSpeichern').addEventListener('click', gerichtSpeichern);
    document.getElementById('ernGerichtNeu').addEventListener('click', entwurfLeeren);
    document.getElementById('ernZutatSuche').addEventListener('input',
        (e) => zutatSuchen(e.target.value));

    document.getElementById('fSpeichern').addEventListener('click', formSpeichern);
    document.getElementById('fAbbrechen').addEventListener('click', formLeeren);
    document.getElementById('fGroesseNeu').addEventListener('click', () => {
        state.formGroessen.push({ label: '', grams: null });
        zeichneGroessen();
        const felder = document.querySelectorAll('[data-g-label]');
        if (felder.length) felder[felder.length - 1].focus();
    });
    // Die Einheit hinter den Groessen ist die Basis -- wechselt sie von g auf
    // ml, muss dort auch ml stehen.
    document.getElementById('fBase').addEventListener('change', zeichneGroessen);
    // Die Eingabefelder stehen bewusst in keinem <form> (ein Absenden waere
    // ein Seitenwechsel) -- die Enter-Taste soll trotzdem das tun, was jeder
    // erwartet.
    Object.keys(FORM).forEach(id => {
        const feld = document.getElementById(id);
        if (feld && feld.tagName === 'INPUT') {
            feld.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); formSpeichern(); }
            });
        }
    });
    let schnellTippen = null;
    document.getElementById('ernSchnellSuche').addEventListener('input', (e) => {
        clearTimeout(schnellTippen);
        const wert = e.target.value;
        schnellTippen = setTimeout(() => {
            state.schnellSuche = wert.trim();
            zeichneSchnell();
        }, 150);
    });

    zeichneEntwurf();
    formLeeren();
    katalogStand();
    await ladeBestand();
    await ladeGerichte();
    await ladeTag(heute());
});
