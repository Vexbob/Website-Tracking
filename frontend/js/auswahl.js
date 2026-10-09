/* auswahl.js — v2.46.0
 *
 * Eine Auswahl mit Suchfeld oben: ``VexAuswahl.suchbar(select)``.
 *
 * Gebaut fuer die Laeden in den Ausgaben. Aus dem Bank-Import kommen dort
 * leicht ein paar hundert Eintraege, und ein natives <select> laesst sich am
 * Handy nur scrollen -- „Rewe“ finden hiess, an Aldi, Amazon, Apotheke vorbei
 * zu wischen.
 *
 * Das <select> bleibt die Quelle: es steht weiter im DOM (unsichtbar), traegt
 * den Wert, bekommt seine Optionen vom Modul wie bisher und meldet ``change``
 * wie bisher. Wer ``sel.value = …`` setzt oder die Optionen neu schreibt, muss
 * nichts davon wissen -- der Knopf zieht beides nach. Damit aendert sich am
 * Modul nur der eine Aufruf.
 *
 * Optionen mit leerem Wert („Alle Läden“, „Kein Laden“) und mit einem Wert,
 * der mit ``__`` beginnt („Neuen Laden anlegen …“), sind keine Treffer, sondern
 * Wege: sie stehen immer da, die einen oben, die anderen unten.
 */
(function () {
    if (window.VexAuswahl) return;

    const WERT = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
    const INDEX = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'selectedIndex');

    // „Café“ findet „cafe“, „Müller“ findet „muller“ und „mueller“.
    const norm = (s) => String(s || '').toLowerCase()
        .replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss')
        .normalize('NFD').replace(/[̀-ͯ]/g, '');
    const normLeicht = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
        c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const istWeg = (o) => o.value === '' || o.value.startsWith('__');

    let zaehler = 0;

    // Der sichtbare Ausschnitt um ein Element: Fenster geschnitten mit jedem
    // Vorfahr, der seinen Inhalt abschneidet. Dazu der naechste davon, der
    // selbst rollt und kleiner als das Fenster ist (ein Dialogkoerper, nicht
    // die Seitenhuelle mit ``overflow-x: hidden``).
    function ausschnitt(el) {
        let oben = 0, unten = window.innerHeight, roller = null;
        for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
            const cs = getComputedStyle(p);
            if (cs.overflowY === 'visible' && cs.overflowX === 'visible') continue;
            const r = p.getBoundingClientRect();
            oben = Math.max(oben, r.top); unten = Math.min(unten, r.bottom);
            if (!roller && (cs.overflowY === 'auto' || cs.overflowY === 'scroll') && p.clientHeight < window.innerHeight) roller = p;
        }
        return { oben, unten, roller };
    }

    function suchbar(sel, opts) {
        if (!sel || sel.dataset.suchbar) return null;
        const o = opts || {};
        sel.dataset.suchbar = '1';
        const id = 'vexAusw' + (++zaehler);

        const huelle = document.createElement('div');
        huelle.className = 'v-such';
        // Der Abstand, den die Seite dem <select> gab, gilt jetzt fuer die
        // Huelle -- im Formular 0.75rem darunter, im Filterfenster keiner.
        const cs = getComputedStyle(sel);
        huelle.style.margin = [cs.marginTop, cs.marginRight, cs.marginBottom, cs.marginLeft].join(' ');
        sel.parentNode.insertBefore(huelle, sel);
        huelle.appendChild(sel);
        sel.classList.add('v-such-nativ');
        sel.tabIndex = -1;
        sel.setAttribute('aria-hidden', 'true');

        const knopf = document.createElement('button');
        knopf.type = 'button';
        // Die kompakte Auswahl (.v-select, etwa in Werkzeugleisten) bleibt kompakt.
        knopf.className = 'v-such-knopf' + (sel.classList.contains('v-select') ? ' v-select' : '');
        knopf.setAttribute('aria-haspopup', 'listbox');
        knopf.setAttribute('aria-expanded', 'false');
        // Das <label for=…> zeigt aufs <select>; der Knopf nimmt seinen Text.
        const lbl = sel.id && document.querySelector('label[for="' + sel.id + '"]');
        const name = o.name || (lbl && lbl.textContent.trim()) || sel.getAttribute('aria-label') || 'Auswahl';
        if (lbl) { lbl.htmlFor = id + 'k'; }
        knopf.id = id + 'k';
        knopf.innerHTML = '<span class="v-such-text"></span>'
            + '<svg class="v-such-pfeil" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"'
            + ' stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9.5l6 6 6-6"/></svg>';
        huelle.appendChild(knopf);

        const panel = document.createElement('div');
        panel.className = 'v-such-panel';
        panel.hidden = true;
        panel.innerHTML = '<input type="search" class="v-such-feld" autocomplete="off" enterkeyhint="go"'
            + ' aria-label="' + esc(name) + ' suchen" placeholder="' + esc(o.platzhalter || 'Suchen …') + '"'
            + ' aria-controls="' + id + 'l">'
            + '<div class="v-such-liste" role="listbox" id="' + id + 'l" aria-label="' + esc(name) + '"></div>';
        huelle.appendChild(panel);
        // Am Handy liegt die Liste als eigene Flaeche oben (CSS); der Schleier
        // dahinter schliesst sie mit einem Tipp.
        const schleier = document.createElement('div');
        schleier.className = 'v-such-schleier';
        schleier.addEventListener('click', () => schliessen(true));
        huelle.appendChild(schleier);
        const feld = panel.querySelector('.v-such-feld');
        const liste = panel.querySelector('.v-such-liste');

        let aktiv = -1;                       // Index in den sichtbaren Zeilen
        let sichtbar = [];

        function beschriften() {
            const opt = sel.options[sel.selectedIndex];
            const text = opt ? opt.textContent.trim() : '';
            knopf.querySelector('.v-such-text').textContent = text || (o.leer || '–');
            knopf.classList.toggle('is-leer', !opt || opt.value === '');
            knopf.disabled = sel.disabled;
        }

        // ``sel.value = x`` meldet kein Ereignis. Damit der Knopf trotzdem
        // stimmt, liest das Feld beim Setzen mit (nur an diesem einen Element).
        Object.defineProperty(sel, 'value', {
            configurable: true,
            get() { return WERT.get.call(this); },
            set(v) { WERT.set.call(this, v); beschriften(); },
        });
        Object.defineProperty(sel, 'selectedIndex', {
            configurable: true,
            get() { return INDEX.get.call(this); },
            set(v) { INDEX.set.call(this, v); beschriften(); },
        });
        sel.addEventListener('change', beschriften);
        new MutationObserver(() => { beschriften(); if (!panel.hidden) zeichnen(); })
            .observe(sel, { childList: true, subtree: true, attributes: true, attributeFilter: ['selected', 'disabled'] });

        function zeichnen() {
            const q = feld.value.trim();
            const qa = norm(q), qb = normLeicht(q);
            const alle = [...sel.options].filter(x => !x.disabled || x.selected);
            const oben = alle.filter(x => x.value === '');
            const unten = alle.filter(x => x.value.startsWith('__'));
            const treffer = alle.filter(x => !istWeg(x)).filter(x => {
                if (!q) return true;
                const t = x.textContent;
                return norm(t).includes(qa) || normLeicht(t).includes(qb);
            });
            sichtbar = (q ? [] : oben).concat(treffer, unten);
            const wert = sel.value;
            liste.innerHTML = sichtbar.map((x, i) =>
                '<button type="button" role="option" tabindex="-1" class="v-such-opt'
                + (istWeg(x) ? ' is-weg' : '') + '" id="' + id + 'o' + i + '" data-i="' + i + '"'
                + ' aria-selected="' + (x.value === wert) + '">' + esc(x.textContent.trim()) + '</button>').join('')
                + (q && !treffer.length ? '<p class="v-such-nichts">Nichts zu „' + esc(q) + '“.</p>' : '');
            const gewaehlt = sichtbar.findIndex(x => x.value === wert);
            markieren(q ? (treffer.length ? sichtbar.indexOf(treffer[0]) : -1) : gewaehlt);
        }

        function markieren(i) {
            aktiv = i;
            liste.querySelectorAll('.v-such-opt').forEach((b, j) => b.classList.toggle('is-aktiv', j === i));
            const b = i >= 0 ? liste.querySelector('[data-i="' + i + '"]') : null;
            if (b) {
                feld.setAttribute('aria-activedescendant', b.id);
                // Nur die Liste rollen, nicht die Seite (kein scrollIntoView).
                if (b.offsetTop < liste.scrollTop) liste.scrollTop = b.offsetTop;
                else if (b.offsetTop + b.offsetHeight > liste.scrollTop + liste.clientHeight)
                    liste.scrollTop = b.offsetTop + b.offsetHeight - liste.clientHeight;
            } else feld.removeAttribute('aria-activedescendant');
        }

        function waehlen(i) {
            const x = sichtbar[i];
            if (!x) return;
            const vorher = sel.value;
            sel.value = x.value;
            schliessen(true);
            if (x.value !== vorher) sel.dispatchEvent(new Event('change', { bubbles: true }));
        }

        // Escape schliesst nur die Liste, nicht den Dialog oder das Filterfenster
        // darum -- die horchen am document, also hier eine Stufe frueher.
        function taste(e) {
            if (panel.hidden || e.key !== 'Escape') return;
            e.preventDefault(); e.stopPropagation();
            schliessen(true);
        }
        function draussen(e) { if (!huelle.contains(e.target)) schliessen(false); }

        function oeffnen() {
            if (!panel.hidden || sel.disabled) return;
            // Gemessen wird gegen den Behaelter, der wirklich abschneidet (im
            // Dialog dessen Koerper), nicht gegen das Fenster. Reicht es unten
            // nicht, aber oben, klappt die Liste nach oben auf; reicht beides
            // nicht, nach unten -- und der Behaelter rollt sie ins Bild.
            // Am Handy: eine Flaeche oben am Bildschirm, ueber der Tastatur --
            // unter einem Feld am Fuss eines Dialogs blieben sonst zwei Zeilen.
            if (window.matchMedia('(max-width: 720px)').matches) {
                huelle.classList.remove('is-oben');
                liste.style.maxHeight = '';
                panel.hidden = false;
                huelle.classList.add('is-offen');
            } else {
                const a = ausschnitt(huelle);
                const r = knopf.getBoundingClientRect();
                const unten = a.unten - r.bottom, oben = r.top - a.oben;
                const BRAUCHT = 240;
                const nachOben = unten < BRAUCHT && oben >= BRAUCHT;
                huelle.classList.toggle('is-oben', nachOben);
                const platz = nachOben ? oben : Math.max(unten, BRAUCHT);
                liste.style.maxHeight = Math.max(132, Math.min(288, platz - 84)) + 'px';
                panel.hidden = false;
                huelle.classList.add('is-offen');
                if (!nachOben && a.roller) {
                    const zuviel = panel.getBoundingClientRect().bottom - a.unten + 8;
                    if (zuviel > 0) a.roller.scrollTop += zuviel;
                }
            }
            knopf.setAttribute('aria-expanded', 'true');
            feld.value = '';
            zeichnen();
            feld.focus({ preventScroll: true });
            window.addEventListener('keydown', taste, true);
            document.addEventListener('pointerdown', draussen, true);
        }
        function schliessen(zurueck) {
            if (panel.hidden) return;
            panel.hidden = true;
            huelle.classList.remove('is-offen');
            knopf.setAttribute('aria-expanded', 'false');
            window.removeEventListener('keydown', taste, true);
            document.removeEventListener('pointerdown', draussen, true);
            if (zurueck) knopf.focus();
        }

        knopf.addEventListener('click', () => { panel.hidden ? oeffnen() : schliessen(true); });
        knopf.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); oeffnen(); }
        });
        feld.addEventListener('input', zeichnen);
        feld.addEventListener('keydown', (e) => {
            const n = sichtbar.length;
            if (e.key === 'ArrowDown') { e.preventDefault(); if (n) markieren((aktiv + 1) % n); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); if (n) markieren((aktiv - 1 + n) % n); }
            else if (e.key === 'Enter') { e.preventDefault(); if (aktiv >= 0) waehlen(aktiv); }
            else if (e.key === 'Tab') schliessen(false);
        });
        liste.addEventListener('click', (e) => {
            const b = e.target.closest('.v-such-opt');
            if (b) waehlen(Number(b.dataset.i));
        });
        // Ein Tipp auf eine Zeile soll das Suchfeld nicht erst verlassen
        // (am Handy klappte sonst die Tastatur weg und die Liste sprang).
        liste.addEventListener('pointerdown', (e) => { if (e.pointerType === 'mouse') e.preventDefault(); });

        beschriften();
        return { oeffnen, schliessen, beschriften };
    }

    window.VexAuswahl = { suchbar };
})();
