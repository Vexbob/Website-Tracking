/* datum.js — v2.47.0
 *
 * Jedes Datumsfeld nimmt und zeigt „TT.MM.JJJJ“ -- auf jedem Geraet.
 *
 * Warum: ein natives <input type="date"> ordnet Tag, Monat und Jahr nach der
 * Sprache des BROWSERS, nicht nach ``lang="de"`` der Seite. Ein Firefox auf
 * Englisch zeigt 10/09/2026, und das ist der 9. Oktober. Einstellen laesst
 * sich das aus der Seite heraus nicht.
 *
 * Wie: das native Feld bleibt, unsichtbar, und ist weiter die Quelle -- es
 * traegt ``id``, ``value`` (ISO), ``min``/``max`` und meldet ``input`` und
 * ``change`` wie bisher. Davor steht ein Textfeld, das deutsch liest und
 * schreibt, daneben ein Kalenderknopf, der den Kalender des Browsers oeffnet.
 * Kein Modul muss davon wissen: das Skript findet die Felder selbst, auch
 * solche, die ein Dialog spaeter einsetzt.
 *
 * Getippt wird mit oder ohne Punkte: „09102026“, „9.10.2026“, „9,10,26“.
 * Ausnahme: ``data-datum="nativ"`` -- das unsichtbare Feld ueber dem
 * Tageskopf in Essen und Naehrwerten ist kein Eingabefeld, sondern der Weg
 * zum Kalender, und seine Anzeige ist der Kopf selbst.
 */
(function () {
    if (window.VexDatum) return;

    const WERT = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    const pad = (n) => String(n).padStart(2, '0');
    let zaehler = 0;

    function isoZuDe(iso) {
        const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
        return m ? m[3] + '.' + m[2] + '.' + m[1] : '';
    }

    /* „9.10.2026“ → „2026-10-09“, sonst null. Zweistellige Jahre sind 20xx. */
    function deZuIso(text) {
        const t = String(text || '').trim();
        let m = /^(\d{1,2})\D+(\d{1,2})\D+(\d{2}|\d{4})$/.exec(t) || /^(\d{2})(\d{2})(\d{4})$/.exec(t);
        if (!m) return null;
        const tag = Number(m[1]), monat = Number(m[2]);
        let jahr = Number(m[3]);
        if (m[3].length === 2) jahr += 2000;
        const d = new Date(jahr, monat - 1, tag);
        if (d.getFullYear() !== jahr || d.getMonth() !== monat - 1 || d.getDate() !== tag) return null;
        return jahr + '-' + pad(monat) + '-' + pad(tag);
    }

    /* Beim Tippen am Ende: Ziffern in Tag/Monat/Jahr gliedern, Trenner
       vereinheitlichen und nach zwei Ziffern den Punkt selbst setzen. */
    function gliedern(roh) {
        const teile = [''];
        for (const z of String(roh)) {
            const i = teile.length - 1;
            if (/\d/.test(z)) {
                if (i < 2 && teile[i].length === 2) teile.push(z);
                else if (teile[i].length < (i < 2 ? 2 : 4)) teile[i] += z;
            } else if (teile[i] !== '' && i < 2) teile.push('');
        }
        let text = teile.join('.');
        const letzter = teile.length - 1;
        if (letzter < 2 && teile[letzter].length === 2) text += '.';
        return text;
    }

    function erweitern(nativ) {
        if (nativ.dataset.datum === 'nativ' || nativ.dataset.datumFertig) return;
        if (nativ.closest('.v-tagkopf-mitte')) return;
        nativ.dataset.datumFertig = '1';
        const id = 'vexDatum' + (++zaehler);

        const huelle = document.createElement('span');
        huelle.className = 'v-datum';
        // Der Platz, den die Seite dem Feld gab, gilt fuer die Huelle.
        const cs = getComputedStyle(nativ);
        huelle.style.margin = [cs.marginTop, cs.marginRight, cs.marginBottom, cs.marginLeft].join(' ');
        if (cs.gridArea && cs.gridArea !== 'auto') huelle.style.gridArea = cs.gridArea;
        if (cs.flexGrow !== '0') huelle.style.flex = cs.flex;
        nativ.parentNode.insertBefore(huelle, nativ);

        const feld = document.createElement('input');
        feld.type = 'text';
        // Klassen bleiben am nativen Feld: Module suchen ihre Felder auch
        // darueber, und zwei Treffer waeren einer zu viel.
        feld.className = 'v-datum-feld';
        feld.id = id;
        feld.inputMode = 'numeric';
        feld.autocomplete = 'off';
        feld.placeholder = 'TT.MM.JJJJ';
        feld.maxLength = 10;
        feld.spellcheck = false;
        const lbl = nativ.id && document.querySelector('label[for="' + nativ.id + '"]');
        if (lbl) lbl.htmlFor = id;
        else if (nativ.getAttribute('aria-label')) feld.setAttribute('aria-label', nativ.getAttribute('aria-label'));
        // Ein <label> um das Feld herum (Export-Dialog) bleibt gueltig: das
        // Textfeld steht ja darin.
        huelle.appendChild(feld);
        huelle.appendChild(nativ);

        const knopf = document.createElement('button');
        knopf.type = 'button';
        knopf.className = 'v-datum-kal';
        knopf.tabIndex = -1;
        knopf.setAttribute('aria-label', 'Kalender öffnen');
        knopf.innerHTML = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.7"'
            + ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="5.5" width="16" height="14.5" rx="2"/>'
            + '<path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/></svg>';
        huelle.appendChild(knopf);

        nativ.classList.add('v-datum-nativ');
        nativ.tabIndex = -1;
        nativ.setAttribute('aria-hidden', 'true');

        let eigenes = false;           // wir setzen gerade selbst -- nicht zurueckschreiben
        const zeigen = () => {
            feld.value = isoZuDe(WERT.get.call(nativ));
            feld.classList.remove('is-falsch');
            feld.removeAttribute('aria-invalid');
        };
        const spiegeln = () => {
            feld.disabled = nativ.disabled;
            feld.required = nativ.required;
            feld.readOnly = nativ.readOnly;
            knopf.disabled = nativ.disabled || nativ.readOnly;
        };

        // ``nativ.value = …`` aus dem Modul meldet kein Ereignis -- das
        // Textfeld liest beim Setzen mit (nur an diesem einen Element).
        Object.defineProperty(nativ, 'value', {
            configurable: true,
            get() { return WERT.get.call(this); },
            set(v) { WERT.set.call(this, v); if (!eigenes) zeigen(); },
        });
        // Wer das Feld fokussiert (Fehlermeldung „Der Tag fehlt“), meint das sichtbare.
        nativ.focus = (o) => feld.focus(o);
        nativ.addEventListener('input', () => { if (!eigenes) zeigen(); });
        nativ.addEventListener('change', () => { if (!eigenes) zeigen(); });
        new MutationObserver(spiegeln).observe(nativ, { attributes: true, attributeFilter: ['disabled', 'required', 'readonly'] });

        const imRahmen = (iso) => (!nativ.min || iso >= nativ.min) && (!nativ.max || iso <= nativ.max);
        const setzen = (iso) => {
            if (WERT.get.call(nativ) === iso) return;
            eigenes = true;
            WERT.set.call(nativ, iso);
            nativ.dispatchEvent(new Event('input', { bubbles: true }));
            nativ.dispatchEvent(new Event('change', { bubbles: true }));
            eigenes = false;
        };

        feld.addEventListener('input', (e) => {
            const amEnde = feld.selectionStart === feld.value.length;
            if (amEnde && !(e.inputType || '').startsWith('delete')) feld.value = gliedern(feld.value);
            const text = feld.value.trim();
            if (!text) { setzen(''); feld.classList.remove('is-falsch'); return; }
            const iso = deZuIso(text);
            const ok = !!iso && imRahmen(iso);
            // Rot erst, wenn es vollstaendig aussieht -- nicht nach der ersten Ziffer.
            const fertig = /\d{4}$/.test(text) || /^\d{8}$/.test(text);
            feld.classList.toggle('is-falsch', fertig && !ok);
            if (fertig && !ok) feld.setAttribute('aria-invalid', 'true'); else feld.removeAttribute('aria-invalid');
            if (ok) setzen(iso);
        });
        // Beim Verlassen gilt, was im nativen Feld steht: ein halbes oder
        // falsches Datum faellt auf den letzten gueltigen Stand zurueck,
        // statt still etwas anderes zu bedeuten, als dasteht.
        feld.addEventListener('blur', () => {
            const iso = deZuIso(feld.value);
            if (feld.value.trim() && iso && imRahmen(iso)) setzen(iso);
            zeigen();
        });

        knopf.addEventListener('click', () => {
            try { nativ.showPicker(); }
            catch (e) { try { nativ.click(); } catch (e2) { /* kein Kalender */ } }
        });

        zeigen();
        spiegeln();
    }

    function einsetzen(wurzel) {
        const r = wurzel || document;
        if (r.matches && r.matches('input[type="date"]')) { erweitern(r); return; }
        if (r.querySelectorAll) r.querySelectorAll('input[type="date"]').forEach(erweitern);
    }

    // Felder, die spaeter kommen (Dialoge, Filterfenster), findet der
    // Beobachter -- kein Modul muss etwas aufrufen.
    function start() {
        einsetzen(document);
        new MutationObserver((liste) => {
            for (const m of liste) m.addedNodes.forEach(n => { if (n.nodeType === 1) einsetzen(n); });
        }).observe(document.documentElement, { childList: true, subtree: true });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();

    window.VexDatum = { einsetzen, isoZuDe, deZuIso };
})();
