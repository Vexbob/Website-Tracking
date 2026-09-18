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

    window.VexIkon = { svg: svg, namen: Object.keys(PFADE) };
})();
