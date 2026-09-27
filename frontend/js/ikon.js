/* ikon.js — v2.4.0
 *
 * Die kleinen Zeichen an Bedienelementen: Lupe, Papierkorb, Kamera, Stift.
 *
 * Warum es diese Datei gibt: bis v2.3.0 standen an genau diesen Stellen
 * Emoji — „🗑️“ als Löschknopf, „🔎“ im Suchfeld, „📷 Scannen“. Das verstößt
 * gegen die Regel aus docs/DESIGN.md („Keine Emoji als Funktionsicons“), und
 * zwar nicht aus Prinzipienreiterei: ein Emoji ist auf jedem Gerät eine
 * andere Zeichnung, in einer Farbe, die niemand gewählt hat, in einer Größe,
 * die sich nicht zur Schrift daneben verhält — und wo die Schriftart es nicht
 * kennt, steht ein leerer Kasten. Genau das war auf den Vorschaubildern zu
 * sehen.
 *
 * Ein SVG erbt dagegen `currentColor` und die Zustände des Knopfes, in dem es
 * steckt. Damit gilt hier dieselbe Regel wie überall sonst: die Farbe kommt
 * aus den Tokens, nicht aus dem Zeichen.
 *
 * Die Form ist dieselbe wie bei den Modul-Icons in `nav-switcher.js`
 * (24er-Raster, nur Linien, 1.7 Strichstärke) — es sollen nicht zwei
 * Zeichenstile nebeneinander stehen.
 */
(function () {
    if (window.VexIkon) return;

    const PFADE = {
        lupe:   '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
        muell:  '<path d="M4 7h16"/><path d="M10 4h4a1 1 0 0 1 1 1v2H9V5a1 1 0 0 1 1-1Z"/>'
              + '<path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/><path d="M10 11v6M14 11v6"/>',
        kamera: '<path d="M3 8.5A1.5 1.5 0 0 1 4.5 7h2.2l1.2-2h8.2l1.2 2h2.2A1.5 1.5 0 0 1 21 8.5v9A1.5 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5Z"/>'
              + '<circle cx="12" cy="13" r="3.4"/>',
        stift:  '<path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3Z"/><path d="M14.5 6.5l3 3"/>',
        ziel:   '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.6"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2"/>',
        // v2.19.0 (Sparziel): die Zeichen, die dort als Emoji auf Knoepfen
        // standen -- ✎, ⋮, 🔄, 🏆, 🔥 -- plus das, was die neuen Kacheln brauchen.
        plus:   '<path d="M12 5v14M5 12h14"/>',
        haken:  '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
        mehr:   '<circle cx="5.5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="18.5" cy="12" r="1.2"/>',
        zurueck: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
        flamme: '<path d="M12 21a6.5 6.5 0 0 0 6.5-6.5c0-3.4-2.3-5.6-3.6-8.5-.5 1.9-1.5 3.1-2.6 3.6C12.4 6.8 11 4.4 8.7 3c.3 2.6-.8 4.4-2 6.2A8 8 0 0 0 5.5 14.5 6.5 6.5 0 0 0 12 21Z"/>'
              + '<path d="M12 21a2.8 2.8 0 0 1-2.8-2.8c0-1.6 1.4-2.6 2.8-4.2 1.4 1.6 2.8 2.6 2.8 4.2A2.8 2.8 0 0 1 12 21Z"/>',
        pokal:  '<path d="M8 4h8v5.5a4 4 0 0 1-8 0Z"/><path d="M8 6H5.5v1a3.5 3.5 0 0 0 3 3.4M16 6h2.5v1a3.5 3.5 0 0 1-3 3.4"/>'
              + '<path d="M12 13.5V17M8.5 20.5h7M9.5 17h5v3.5h-5Z"/>',
        tauschen: '<path d="M4 8.5h14.5L15 5"/><path d="M20 15.5H5.5L9 19"/>',
        kalender: '<rect x="4" y="5.5" width="16" height="14.5" rx="2.5"/><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>',
        uhr:    '<circle cx="12" cy="12" r="8"/><path d="M12 7.5V12l3 2"/>',
        griff:  '<circle cx="9" cy="6.5" r="1"/><circle cx="15" cy="6.5" r="1"/><circle cx="9" cy="12" r="1"/>'
              + '<circle cx="15" cy="12" r="1"/><circle cx="9" cy="17.5" r="1"/><circle cx="15" cy="17.5" r="1"/>',
        muenze: '<circle cx="12" cy="12" r="8"/><path d="M15 9.2a3.5 3.5 0 1 0 0 5.6M7.6 11h5.2M7.6 13.1h5.2"/>',
        einkauf: '<path d="M3.5 4.5h2.2l2.1 10.2a1.5 1.5 0 0 0 1.5 1.2h7.9a1.5 1.5 0 0 0 1.4-1.1l1.6-6.3H6.6"/>'
              + '<circle cx="10" cy="19.5" r="1.1"/><circle cx="17" cy="19.5" r="1.1"/>',
        idee:   '<path d="M9 17.5h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.1 1 1.9v.2h5v-.2c0-.8.4-1.4 1-1.9A6 6 0 0 0 12 3Z"/>',
        pfeil:  '<path d="M9.5 6l6 6-6 6"/>',
        filter: '<path d="M4 6h16M7 12h10M10 18h4"/>',
        herunter: '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5"/><path d="M5 19.5h14"/>',
    };

    /* Das Zeichen als SVG-Text. `groesse` ist die Kantenlänge in Pixeln; 18
       passt neben 15-px-Schrift, 16 in einen kleinen Knopf.

       `aria-hidden` ist Absicht und keine Nachlässigkeit: jeder Knopf, der
       eines dieser Zeichen trägt, hat sein `aria-label` — ohne das wäre er
       auch mit Beschriftung im Bild für ein Vorleseprogramm stumm. Ein
       zweiter Name am Icon darin läse den Knopf doppelt vor. */
    function svg(name, groesse) {
        const pfad = PFADE[name];
        if (!pfad) return '';
        const g = groesse || 18;
        return '<svg viewBox="0 0 24 24" width="' + g + '" height="' + g + '"'
            + ' fill="none" stroke="currentColor" stroke-width="1.7"'
            + ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            + pfad + '</svg>';
    }

    /* Aus reinem HTML benutzbar: `<span data-ikon="muell"></span>` fuellt
       sich selbst. Ohne das musste jede Seite fuer jedes Zeichen eine Zeile
       JavaScript schreiben -- und genau deshalb standen in den aelteren
       Modulen weiter Emoji. Die Groesse kommt aus `data-ikon-gross`. */
    function einsetzen(wurzel) {
        (wurzel || document).querySelectorAll('[data-ikon]').forEach(el => {
            if (el.firstElementChild) return;          // schon gefuellt
            const g = parseInt(el.dataset.ikonGross, 10) || 18;
            el.innerHTML = svg(el.dataset.ikon, g);
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => einsetzen());
    } else {
        einsetzen();
    }

    window.VexIkon = { svg: svg, einsetzen: einsetzen, namen: Object.keys(PFADE) };
})();
