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
 *      NIEDRIGSTE Wert liegt oben. Deshalb ORDER.TREND < ORDER.VALUE, und
 *      Vergleichslinien liegen mit ORDER.CONTEXT dazwischen.
 *   4. (v2.24.0) Balken sind oben rund und unten gerade -- in einem Stapel
 *      nur das oberste sichtbare Stueck. Siehe ``balken()``.
 *
 * Einbindung: <script src="/js/charts.js"></script> vor dem Modul-Skript,
 * nach chart.js. Idempotent, braucht Chart.js nicht zum Zeitpunkt des Ladens.
 */
(function () {
    if (window.VexCharts) return;

    /* Reihenfolge beim Zeichnen, von vorn nach hinten. Wer eine Trendlinie
       ueber Balken oder ueber eine gefuellte Wertlinie legen will, nimmt diese
       Konstanten und nicht wieder eigene Zahlen.
         TREND   die Anmerkung, immer obenauf
         CONTEXT Vergleichswerte (Vorperiode, Zielmarke) darunter
         VALUE   die Daten selbst, ganz hinten */
    var ORDER = { TREND: 1, CONTEXT: 2, VALUE: 3 };

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

    /* Die Ecken eines Balkens. Bis v2.23.0 stand ueberall
       ``borderRadius: 6, borderSkipped: false``: rund an allen vier Ecken.
       Am Boden sah der Balken dadurch aus, als schwebe er ueber der Achse,
       und in einem Stapel bekam jedes Stueck seine eigenen Rundungen -- an
       der Fuge zweier Stuecke stiessen Rund und Eckig aufeinander.

       Jetzt: ``borderSkipped: 'start'`` laesst die Seite an der Grundlinie
       gerade (auch bei negativen Werten, dort ist es die obere), und in
       einem Stapel rundet nur das oberste Stueck mit Wert, das gerade
       sichtbar ist. Schwebende Balken (von-bis, etwa Schlafphasen) brauchen
       das nicht und behalten ihre eigenen Ecken.

       Verwendung im Datensatz: ``Object.assign({ ... }, VexCharts.balken(6))``. */
    function balken(radius) {
        var r = radius == null ? 6 : radius;
        return {
            borderSkipped: 'start',
            borderRadius: function (ctx) {
                if (!ctx || ctx.type !== 'data') return r;
                var chart = ctx.chart;
                var skalen = (chart && chart.options && chart.options.scales) || {};
                var gestapelt = (skalen.x && skalen.x.stacked) || (skalen.y && skalen.y.stacked);
                if (!gestapelt) return r;
                var reihen = chart.data.datasets;
                var stapel = reihen[ctx.datasetIndex].stack;
                var wert = function (j) { return Number(reihen[j].data[ctx.dataIndex]) || 0; };
                var eigener = wert(ctx.datasetIndex);
                if (!eigener) return 0;
                // Liegt ueber diesem Stueck noch eines mit Wert in dieselbe
                // Richtung, ist dieses nicht das oberste.
                for (var j = ctx.datasetIndex + 1; j < reihen.length; j++) {
                    if (reihen[j].stack !== stapel) continue;
                    if ((reihen[j].type || chart.config.type) !== 'bar') continue;
                    if (!chart.isDatasetVisible(j)) continue;
                    if (wert(j) * eigener > 0) return 0;
                }
                return r;
            },
        };
    }

    /* Jahreswechsel als senkrechter Strich (v2.46.0). Die Achse nennt nur
       Tag und Monat ("05.01."), und ueber ein Jahr gesehen steht dort zweimal
       derselbe Tag -- welcher Teil der Kurve in welches Jahr faellt, sah man
       nur im Tooltip. Der Strich steht zwischen dem letzten Punkt des alten
       und dem ersten des neuen Jahres, die Jahreszahl klein oben daneben.

       ``tage`` liefert die ISO-Daten der Punkte, in derselben Reihenfolge wie
       die Beschriftungen: ``plugins: [VexCharts.jahresStriche(c => c.$vexIso)]``.
       Farbe aus dem Token --chart-axis, keine eigene. */
    function jahresStriche(tage) {
        return {
            id: 'vexJahre',
            // Vor den Kurven: der Strich liegt hinter den Daten, nicht darauf.
            beforeDatasetsDraw: function (chart) {
                var liste = (typeof tage === 'function' ? tage(chart) : tage) || [];
                var x = chart.scales && chart.scales.x, flaeche = chart.chartArea;
                if (liste.length < 2 || !x || !flaeche) return;
                var css = getComputedStyle(document.documentElement);
                var schrift = css.getPropertyValue('--chart-axis').trim();
                var ctx = chart.ctx;
                ctx.save();
                ctx.font = '600 10px ' + (Chart.defaults.font.family || 'sans-serif');
                ctx.textBaseline = 'top';
                for (var i = 1; i < liste.length; i++) {
                    var a = safeDate(liste[i - 1]), b = safeDate(liste[i]);
                    if (!a || !b || a.getFullYear() === b.getFullYear()) continue;
                    var px = (x.getPixelForValue(i - 1) + x.getPixelForValue(i)) / 2;
                    if (px < flaeche.left || px > flaeche.right) continue;
                    ctx.strokeStyle = schrift;
                    ctx.globalAlpha = 0.6;
                    ctx.lineWidth = 1;
                    ctx.setLineDash([4, 3]);
                    ctx.beginPath();
                    ctx.moveTo(Math.round(px) + 0.5, flaeche.top);
                    ctx.lineTo(Math.round(px) + 0.5, flaeche.bottom);
                    ctx.stroke();
                    ctx.globalAlpha = 1;
                    // Die Zahl rechts vom Strich, ausser ganz am rechten Rand.
                    var text = String(b.getFullYear());
                    var breite = ctx.measureText(text).width;
                    var rechts = px + 4 + breite <= flaeche.right;
                    ctx.fillStyle = schrift;
                    ctx.textAlign = rechts ? 'left' : 'right';
                    ctx.fillText(text, rechts ? px + 4 : px - 4, flaeche.top + 2);
                }
                ctx.restore();
            },
        };
    }

    /* Chart.js kommt mit ``defer`` vom CDN und kann NACH den Daten ankommen.
       Wer zeichnet, wartet hierauf (v2.25.0): in der Statistik fiel das erst
       auf, als ein zweiter Abruf wegfiel, der das Zeichnen bis dahin zufaellig
       lange genug verzoegert hatte -- „Chart is not defined“. Laedt die
       Bibliothek gar nicht, wird abgelehnt statt ewig gewartet. */
    function bereit() {
        if (window.Chart) return Promise.resolve();
        return new Promise(function (ja, nein) {
            var pruefen = function () {
                if (window.Chart) ja(); else nein(new Error('Chart.js nicht geladen'));
            };
            if (document.readyState === 'complete') pruefen();
            else window.addEventListener('load', pruefen, { once: true });
        });
    }

    window.VexCharts = {
        ORDER: ORDER,
        balken: balken,
        jahresStriche: jahresStriche,
        bereit: bereit,
        fullDay: fullDay,
        fullMonth: fullMonth,
        fullWeek: fullWeek,
        titleFrom: titleFrom,
        applyFullDates: applyFullDates,
        hideAllTooltips: function () { hideAllExcept(null); },
    };
})();
