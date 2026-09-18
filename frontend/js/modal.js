/* modal.js — v2.1.0
 *
 * Der Dialog, an einer Stelle. Bis hierher lag `openModal` VIERMAL kopiert in
 * den Modulen (ausgaben, essen, naehrwerte, schach), und die vier Fassungen
 * waren auseinandergelaufen:
 *
 *   - keine sperrte das Scrollen hinter dem Dialog. Auf dem Handy scrollt man
 *     die Liste im Dialog nach unten, stoesst ans Ende -- und die Seite
 *     DAHINTER laeuft weiter. Beim Schliessen steht man woanders.
 *   - keine setzte `role="dialog"` / `aria-modal`, obwohl die geteilten
 *     Dialoge in ui.js das seit Langem tun.
 *   - keine holte den Tastaturfokus herein; mit offenem Dialog wandert Tab
 *     durch die Seite dahinter.
 *   - ausgaben.js entfernte den Escape-Horcher nur im Escape-Zweig: wer auf
 *     das Kreuz klickte, liess ihn stehen. Nach zehn Dialogen lagen zehn
 *     Horcher auf dem Dokument.
 *
 * Die Aufrufstellen bleiben unveraendert: jedes Modul behaelt seine Funktion
 * `openModal` und leitet in einer Zeile hierher -- dasselbe Vorgehen wie bei
 * bild.js (v1.99.0). Die Optionen gibt es deshalb unter beiden Namen, die in
 * den Modulen gewachsen sind (`breit`/`wide`, `beimSchliessen`/`onClose`).
 *
 * Aufbau und Aussehen stehen in css/style.css (.modal-overlay/.modal-box),
 * das Muster in design.html. Hier steht nur das Verhalten.
 */
(function () {
    if (window.VexModal) return;

    /* Wie viele Dialoge gerade offen sind. Ein Zaehler und nicht ein Merker:
       im Naehrwerte-Modul oeffnet ein Dialog den naechsten (ein Katalogtreffer
       fuehrt in die Lebensmittel-Maske), und der innere darf beim Schliessen
       nicht die Sperre des aeusseren aufheben. */
    let offen = 0;
    let vorherigesOverflow = '';

    function sperreHintergrund() {
        if (offen === 0) {
            vorherigesOverflow = document.body.style.overflow;
            document.body.style.overflow = 'hidden';
        }
        offen += 1;
    }

    function gibHintergrundFrei() {
        offen = Math.max(0, offen - 1);
        if (offen === 0) document.body.style.overflow = vorherigesOverflow;
    }

    const FOKUSSIERBAR = [
        'a[href]', 'button:not([disabled])', 'input:not([disabled])',
        'select:not([disabled])', 'textarea:not([disabled])',
        '[tabindex]:not([tabindex="-1"])',
    ].join(',');

    function offeneZiele(box) {
        return Array.prototype.filter.call(
            box.querySelectorAll(FOKUSSIERBAR),
            el => el.offsetParent !== null || el === document.activeElement);
    }

    function open(titel, inhalt, opts) {
        const o = opts || {};
        const breit = o.breit || o.wide;
        const beimSchliessen = o.beimSchliessen || o.onClose;
        const vorherFokus = document.activeElement;

        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.innerHTML = '<div class="modal-box' + (breit ? ' wide' : '')
            + (o.voll ? ' modal-box--voll' : '') + '" tabindex="-1">'
            + '<div class="modal-head"><h3>' + titel + '</h3>'
            + '<button class="modal-close" aria-label="Schließen">✕</button></div>'
            + '<div class="modal-body">' + inhalt + '</div></div>';

        const box = overlay.querySelector('.modal-box');
        // Die Ueberschrift benennt den Dialog auch fuer Vorleseprogramme --
        // aus dem Text, der ohnehin dasteht, statt aus einem zweiten.
        const kopf = overlay.querySelector('.modal-head h3');
        if (kopf) overlay.setAttribute('aria-label', kopf.textContent || '');

        document.body.appendChild(overlay);
        sperreHintergrund();
        requestAnimationFrame(() => overlay.classList.add('show'));

        let zu = false;
        const close = () => {
            // Zweimal schliessen darf nicht zweimal freigeben -- sonst zieht
            // ein doppelter Klick die Sperre unter einem noch offenen
            // Dialog weg.
            if (zu) return;
            zu = true;
            overlay.classList.remove('show');
            document.removeEventListener('keydown', onKey, true);
            gibHintergrundFrei();
            setTimeout(() => overlay.remove(), 200);
            // Zurueck auf das Element, von dem aus geoeffnet wurde: sonst
            // faengt Tab nach dem Schliessen wieder ganz oben an.
            if (vorherFokus && typeof vorherFokus.focus === 'function') {
                try { vorherFokus.focus({ preventScroll: true }); } catch (e) {}
            }
            if (typeof beimSchliessen === 'function') beimSchliessen();
        };

        const onKey = (e) => {
            if (e.key === 'Escape') { close(); return; }
            if (e.key !== 'Tab') return;
            // Der Fokus bleibt im Dialog. Ohne das laeuft Tab in die Seite
            // dahinter, die man gerade nicht bedienen kann.
            const ziele = offeneZiele(box);
            if (!ziele.length) { e.preventDefault(); box.focus(); return; }
            const erstes = ziele[0], letztes = ziele[ziele.length - 1];
            if (!e.shiftKey && document.activeElement === letztes) {
                e.preventDefault(); erstes.focus();
            } else if (e.shiftKey && (document.activeElement === erstes
                                      || document.activeElement === box)) {
                e.preventDefault(); letztes.focus();
            }
        };

        overlay.querySelector('.modal-close').addEventListener('click', close);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
        // In der Erfassungsphase, damit der oberste Dialog die Taste zuerst
        // sieht, wenn zwei uebereinanderliegen.
        document.addEventListener('keydown', onKey, true);

        // Nur der Kasten bekommt den Fokus, nicht das erste Feld darin: auf
        // dem Handy risse ein fokussiertes Eingabefeld sofort die Tastatur
        // hoch und verdeckte die halbe Liste. Wer ein Feld vorn haben will,
        // setzt den Fokus selbst -- die Module tun das bewusst nur am
        // Rechner.
        box.focus({ preventScroll: true });

        return { close, el: overlay, box: box,
                 root: overlay.querySelector('.modal-body') };
    }

    window.VexModal = { open };
})();
