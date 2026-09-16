/* ring.js — v1.98.0
 *
 * Der Fortschrittsring, an einer Stelle. Die Optik steht in css/style.css
 * (`.v-ring`), das Muster in design.html; hier steht nur die Rechnung davor:
 * aus Wert und Ziel werden zwei Zahlen zwischen 0 und 1, und die schreibt das
 * Skript als CSS-Variablen an das Element. Keine Farbe, kein Hex, kein
 * Aufmalen -- gezeichnet wird in CSS.
 *
 * Verwendung:
 *
 *     VexRing.set(el, { wert: 1480, ziel: 2000, einheit: 'kcal',
 *                       text: 'noch 520', unvollstaendig: false });
 *
 * ``VexRing.zaehle`` liegt hier, weil ein Ring seine eigene Zahl mitanimiert
 * und beides sonst an zwei Stellen stuende. Es respektiert
 * ``prefers-reduced-motion``: wer Bewegung abbestellt hat, bekommt den
 * Endwert sofort.
 */
(function () {
    if (window.VexRing) return;

    const MAG_BEWEGUNG = () => !(window.matchMedia
        && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

    /* Zahl von ``von`` nach ``bis`` laufen lassen. ``zeichne`` bekommt den
       Zwischenwert -- so bleibt die Formatierung beim Aufrufer, der als
       Einziger weiss, ob da Euro, Gramm oder Prozent stehen. */
    function zaehle(von, bis, dauer, zeichne) {
        if (von == null || !isFinite(von) || von === bis || !MAG_BEWEGUNG() || dauer <= 0) {
            zeichne(bis);
            return;
        }
        const start = performance.now();
        const strecke = bis - von;
        const schritt = (jetzt) => {
            const t = Math.min(1, (jetzt - start) / dauer);
            // easeOutCubic: schnell los, sanft an
            zeichne(von + strecke * (1 - Math.pow(1 - t, 3)));
            if (t < 1) requestAnimationFrame(schritt);
            else zeichne(bis);
        };
        requestAnimationFrame(schritt);
    }

    /* Den Anteil an das Element schreiben. Gedeckelt wird HIER und nicht in
       der Rechnung des Servers: ein Ring, der weiterlaeuft, sagt nichts mehr
       -- die Zahl daneben sagt es weiter. */
    function anteil(el, wert, ziel) {
        const quote = ziel > 0 ? wert / ziel : 0;
        el.style.setProperty('--ring-val', Math.max(0, Math.min(1, quote)).toFixed(4));
        // Der Ueberschuss ist bei 200 % zu Ende; darueber steht er nur noch
        // als Zahl da.
        el.style.setProperty('--ring-over', Math.max(0, Math.min(1, quote - 1)).toFixed(4));
        el.classList.toggle('is-drueber', quote > 1);
        return quote;
    }

    function set(el, o) {
        if (!el) return 0;
        o = o || {};
        const quote = anteil(el, Number(o.wert) || 0, Number(o.ziel) || 0);
        el.classList.toggle('is-unvollstaendig', !!o.unvollstaendig);

        const setzeText = (klasse, wert) => {
            const ziel = el.querySelector('.' + klasse);
            if (ziel && wert != null) ziel.textContent = wert;
        };
        setzeText('v-ring-unit', o.einheit);
        setzeText('v-ring-lbl', o.text);

        const zahlEl = el.querySelector('.v-ring-val');
        if (zahlEl && o.zahl != null) {
            // Der vorherige Stand steht am Element, nicht in einer Variablen
            // nebenan: so zaehlt auch ein neu gezeichneter Ring von da weiter,
            // wo der alte stand, statt bei null anzufangen.
            const vorher = zahlEl.dataset.wert === undefined
                ? null : Number(zahlEl.dataset.wert);
            const neu = Number(o.zahl);
            const form = typeof o.form === 'function'
                ? o.form : (v) => Math.round(v).toLocaleString('de-DE');
            zaehle(vorher, neu, o.dauer == null ? 600 : o.dauer,
                   (v) => { zahlEl.textContent = form(v); });
            zahlEl.dataset.wert = String(neu);
        }
        return quote;
    }

    /* Das Markup eines Rings. Eine Zeichenkette statt eines Bausteins, weil
       die Seiten ihre Listen ohnehin als HTML bauen -- und weil ein Ring, der
       sich selbst ins DOM haengt, schwerer an die richtige Stelle zu bekommen
       ist als einer, den man dort hinschreibt. */
    function html(opts) {
        const o = opts || {};
        const klassen = ['v-ring'].concat(o.klassen || []).join(' ');
        const stil = o.ton ? ` style="--ring-tone:${o.ton}"` : '';
        return '<div class="' + klassen + '"' + (o.id ? ' id="' + o.id + '"' : '') + stil + '>'
            + '<svg viewBox="0 0 100 100" aria-hidden="true">'
            + '<circle class="v-ring-track" cx="50" cy="50" r="42"/>'
            + '<circle class="v-ring-fill" cx="50" cy="50" r="42"/>'
            + '<circle class="v-ring-over" cx="50" cy="50" r="42"/>'
            + '</svg>'
            + '<div class="v-ring-txt">'
            + '<strong class="v-ring-val">–</strong>'
            + '<span class="v-ring-unit"></span>'
            + '<span class="v-ring-lbl"></span>'
            + '</div></div>';
    }

    window.VexRing = { set, zaehle, html };
})();
