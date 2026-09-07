/* charts.js — v1.59.0
 * Gemeinsames Verhalten aller Chart.js-Diagramme der App. Die Optionen selbst
 * bleiben in den Modulen (dort weiss man, was die Zahlen bedeuten) — hier
 * stehen nur die drei Dinge, die ueberall gleich sein muessen:
 *
 *   1. Tippt man neben ein Diagramm, verschwindet der angezeigte Tageswert.
 *      Auf dem Handy bleibt er sonst stehen, bis man zufaellig wieder aufs
 *      Diagramm fasst — es gibt dort kein "Maus verlaesst die Flaeche".
 *   2. Ein Datum im Tooltip traegt immer die Jahreszahl. Auf der Achse ist
 *      dafuer kein Platz, im Tooltip schon — und ohne Jahr ist ein "05.09."
 *      in einer Jahresansicht wertlos.
 *   3. Die Durchschnitts-/Trendlinie liegt ueber der Wertlinie. Chart.js
 *      zeichnet die Datensaetze nach `order` von hinten nach vorne: der
 *      NIEDRIGSTE Wert liegt oben. Deshalb ORDER.TREND < ORDER.VALUE.
 *
 * Einbindung: <script src="/js/charts.js"></script> vor dem Modul-Skript,
 * nach chart.js. Idempotent, braucht Chart.js nicht zum Zeitpunkt des Ladens.
 */
(function () {
    if (window.VexCharts) return;

    /* Reihenfolge beim Zeichnen. Wer eine Trendlinie ueber Balken oder ueber
       eine gefuellte Wertlinie legen will, nimmt diese beiden Konstanten und
       nicht wieder eigene Zahlen. */
    var ORDER = { TREND: 1, VALUE: 2 };

    function chartOf(canvas) {
        try {
            return (window.Chart && Chart.getChart) ? Chart.getChart(canvas) : null;
        } catch (e) { return null; }
    }

    function hideTooltip(chart) {
        try {
            if (!chart || !chart.tooltip) return;
            var act = chart.tooltip.getActiveElements ? chart.tooltip.getActiveElements() : [];
            if (!act || !act.length) return;
            chart.setActiveElements([]);
            chart.tooltip.setActiveElements([], { x: 0, y: 0 });
            chart.update('none');
        } catch (e) { /* Diagramm gerade zerstoert */ }
    }

    /* Alle Diagramme ausser dem, das gerade beruehrt wurde. Wir gehen ueber die
       Canvas-Elemente statt ueber eine eigene Registry: so erwischen wir auch
       Diagramme, die ein Modul ohne uns angelegt hat. */
    function hideAllExcept(canvas) {
        var list = document.querySelectorAll('canvas');
        for (var i = 0; i < list.length; i++) {
            if (list[i] === canvas) continue;
            hideTooltip(chartOf(list[i]));
        }
    }

    // Liegt der Finger gerade AUF einem Diagramm, zieht er Werte durch. Ein
    // dabei ausgeloestes Scrollen der Seite darf den Wert dann nicht wegnehmen
    // -- sonst waere das Durchziehen auf dem Handy kaputt.
    var scrubbing = false;

    function onPointerDown(e) {
        var t = e.target;
        var canvas = (t && t.closest) ? t.closest('canvas') : null;
        scrubbing = !!canvas;
        hideAllExcept(canvas);
    }
    function onPointerUp() { scrubbing = false; }

    document.addEventListener('pointerdown', onPointerDown, true);
    // Aeltere WebViews ohne Pointer Events. Doppelt aufzuraeumen schadet nicht.
    document.addEventListener('touchstart', onPointerDown, { capture: true, passive: true });
    ['pointerup', 'pointercancel', 'touchend', 'touchcancel'].forEach(function (ev) {
        document.addEventListener(ev, onPointerUp, true);
    });
    // Wegscrollen ist auch ein "ich meine das nicht mehr" -- aber nur, wenn
    // gerade niemand am Diagramm zieht.
    window.addEventListener('scroll', function () {
        if (!scrubbing) hideAllExcept(null);
    }, { passive: true });

    /* ---------------------------------------------------------------- Datum */

    function safeDate(iso) {
        if (!iso) return null;
        var d = new Date(String(iso).length === 10 ? iso + 'T00:00:00' : iso);
        return isNaN(d.getTime()) ? null : d;
    }

    /* Voller Tag mit Wochentag und Jahr: "Mo, 05.09.2026". */
    function fullDay(iso) {
        var d = safeDate(iso);
        if (!d) return String(iso || '');
        return d.toLocaleDateString('de-DE',
            { weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric' });
    }

    /* Voller Monat: "September 2026". Nimmt 'YYYY-MM' oder ein volles Datum. */
    function fullMonth(ym) {
        var s = String(ym || '');
        var d = safeDate(s.length === 7 ? s + '-01' : s);
        if (!d) return s;
        return d.toLocaleDateString('de-DE', { month: 'long', year: 'numeric' });
    }

    /* Kalenderwoche mit Jahr: "KW 36 · 2026". `week` kommt vom Backend als
       "2026-KW36" oder aehnlich, deshalb wird nur nach Ziffern gesucht. */
    function fullWeek(week) {
        var s = String(week || '');
        var m = s.match(/(\d{4})\D+(\d{1,2})/);
        if (m) return 'KW ' + m[2] + ' · ' + m[1];
        return s;
    }

    /* Macht aus einer Liste ausgeschriebener Beschriftungen einen
       tooltip.callbacks.title — die Achse behaelt ihre kurze Fassung. */
    function titleFrom(fullLabels) {
        return function (items) {
            if (!items || !items.length) return '';
            var i = items[0].dataIndex;
            var v = (i >= 0 && fullLabels) ? fullLabels[i] : null;
            return (v == null || v === '') ? (items[0].label || '') : v;
        };
    }

    /* Setzt den Titel-Callback in ein fertiges Options-Objekt, ohne die
       uebrigen Tooltip-Einstellungen des Moduls zu ueberschreiben. */
    function applyFullDates(options, fullLabels) {
        if (!options) return options;
        options.plugins = options.plugins || {};
        options.plugins.tooltip = options.plugins.tooltip || {};
        options.plugins.tooltip.callbacks = options.plugins.tooltip.callbacks || {};
        options.plugins.tooltip.callbacks.title = titleFrom(fullLabels);
        return options;
    }

    window.VexCharts = {
        ORDER: ORDER,
        fullDay: fullDay,
        fullMonth: fullMonth,
        fullWeek: fullWeek,
        titleFrom: titleFrom,
        applyFullDates: applyFullDates,
        hideAllTooltips: function () { hideAllExcept(null); },
    };
})();
