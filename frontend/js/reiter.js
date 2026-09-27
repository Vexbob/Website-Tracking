/* reiter.js — v2.18.0
 *
 * Die gleitende Markierung unter dem aktiven Reiter. Jede ``.tabs``-Leiste
 * bekommt EIN Element (.tabs-ind), das unter den aktiven Reiter gleitet,
 * statt dass der Reiter selbst seine Flaeche wechselt. Gesetzt wird nur Lage
 * und Groesse; wer einen Reiter aktiv macht, tut das wie bisher ueber die
 * Klasse ``active`` -- die Module muessen davon nichts wissen. Ein
 * MutationObserver sieht die Klasse, und er sieht auch, wenn ein Modul die
 * Leiste per innerHTML neu zeichnet (die Naehrwerte tun das) und die
 * Markierung dabei mitgerissen wird.
 *
 * Passt die Leiste nicht in die Breite, rollt sie (css: .tabs am Handy),
 * und der aktive Reiter wird in die Mitte geholt -- sonst laege er beim
 * Oeffnen per #anker hinter dem Rand.
 *
 * Eine eigene Datei wie modal.js und ring.js, damit auch design.html den
 * Baustein zeigen kann, ohne die ganze Navigation mitzuladen. Ohne Skript
 * bleibt die Flaeche am aktiven Reiter selbst (css/style.css). Jede Seite
 * mit ``class="tabs"`` bindet die Datei ein; test_navigation.py wacht darueber.
 */
(function () {
    if (window.VexReiter) return;

    function verzieren(leiste) {
        if (leiste.__vexReiter) return;
        leiste.__vexReiter = true;
        const ind = document.createElement('span');
        ind.className = 'tabs-ind';
        ind.setAttribute('aria-hidden', 'true');
        leiste.classList.add('tabs--gleitend');

        let erstes = true;
        const setzen = () => {
            if (!leiste.contains(ind)) leiste.prepend(ind);
            const aktiv = leiste.querySelector('.tab-btn.active');
            if (!aktiv || !aktiv.offsetWidth) { ind.style.opacity = '0'; return; }
            if (erstes) ind.style.transition = 'none';
            ind.style.opacity = '1';
            ind.style.width = aktiv.offsetWidth + 'px';
            ind.style.height = aktiv.offsetHeight + 'px';
            ind.style.transform = 'translate(' + aktiv.offsetLeft + 'px,' + aktiv.offsetTop + 'px)';
            const rollt = leiste.scrollWidth > leiste.clientWidth + 2;
            if (leiste.classList.contains('tabs--rollt') !== rollt) {
                leiste.classList.toggle('tabs--rollt', rollt);
            }
            if (rollt) {
                const ziel = aktiv.offsetLeft - (leiste.clientWidth - aktiv.offsetWidth) / 2;
                leiste.scrollTo({ left: ziel, behavior: erstes ? 'auto' : 'smooth' });
            }
            if (erstes) {
                void ind.offsetWidth;          // Lage uebernehmen, dann erst gleiten
                ind.style.transition = '';
                erstes = false;
            }
        };
        new MutationObserver(setzen).observe(leiste, {
            subtree: true, childList: true, attributes: true, attributeFilter: ['class'],
        });
        window.addEventListener('resize', setzen);
        // Die Reiter koennen unsichtbar starten (body wartet auf .ready) --
        // dann ist ihre Breite 0 und die Markierung noch nicht setzbar.
        if (document.fonts && document.fonts.ready) document.fonts.ready.then(setzen);
        window.addEventListener('load', setzen);
        setzen();
    }

    function alle() { document.querySelectorAll('.tabs').forEach(verzieren); }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', alle);
    else alle();
    window.VexReiter = { verzieren: verzieren, alle: alle };
})();
