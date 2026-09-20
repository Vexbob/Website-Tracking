# -*- coding: utf-8 -*-
"""Vorschau-Server: die echten Seiten, ein erfundenes Backend.

Warum ueberhaupt: auf diesem Rechner laeuft kein Postgres und keine echte
Anmeldung, aber Edge liegt installiert da und kann als Chromium
Bildschirmfotos schreiben. Damit laesst sich zum ersten Mal ANSEHEN, was
gebaut wurde, statt es nur zu parsen.

Aufbau:

* Dateien kommen unveraendert aus ``frontend/`` -- dieselbe CSS, dasselbe
  JavaScript, dieselben Pfade wie im Betrieb. Nachgebaut wird nichts; eine
  Nachbildung wuerde genau die Fehler verstecken, die man sucht.
* In jede HTML-Antwort wird EIN Skript eingehaengt, ganz vorn im ``<head>``.
  Es legt einen Token in den localStorage (sonst schickt ``isLoggedIn()``
  einen zur Anmeldung) und ersetzt ``fetch`` durch einen Verteiler auf feste
  Antworten aus ``daten.py``.
* Die Antworten haben die Form, die die Router wirklich liefern. Wo sie
  abweicht, sieht man es sofort -- die Seite bleibt dann leer oder faellt um,
  und das ist ein echter Befund, kein Fehler der Vorschau.

Aufruf: ``python server.py [port]`` -- laeuft, bis man ihn beendet.
"""
import json
import pathlib
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HIER = pathlib.Path(__file__).resolve().parent
WURZEL = HIER.parent.parent / "frontend"

sys.path.insert(0, str(HIER))
import daten  # noqa: E402


def stub_js() -> str:
    """Das eingehaengte Skript. Es muss VOR config.js laufen."""
    return """
<script>
(function () {
    try {
        localStorage.setItem('token', 'vorschau');
        localStorage.setItem('me', JSON.stringify(%s));
    } catch (e) {}

    const ANTWORTEN = %s;

    // Jeder Aufruf geht an API_BASE + Pfad; der Wirt ist egal, gesucht wird
    // nur der Pfad. Unbekanntes gibt 404 zurueck -- so faellt beim Ansehen
    // auf, welche Antwort in den Daten noch fehlt, statt dass die Seite
    // stumm haengt.
    const echtesFetch = window.fetch.bind(window);
    window.fetch = function (eingabe, optionen) {
        const roh = (typeof eingabe === 'string') ? eingabe : (eingabe && eingabe.url) || '';
        let pfad = roh;
        try { pfad = new URL(roh, location.origin).pathname
                   + new URL(roh, location.origin).search; } catch (e) {}
        if (pfad.indexOf('/api/') !== 0) return echtesFetch(eingabe, optionen);

        const ohneFrage = pfad.split('?')[0];
        let treffer = ANTWORTEN[pfad] || ANTWORTEN[ohneFrage];
        if (treffer === undefined) {
            // Pfade mit Nummern drin (…/log/12) auf ihre Vorlage abbilden.
            for (const schluessel of Object.keys(ANTWORTEN)) {
                if (schluessel.indexOf('*') < 0) continue;
                const muster = new RegExp('^' + schluessel.split('*').map(
                    s => s.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')).join('[^/]+') + '$');
                if (muster.test(ohneFrage)) { treffer = ANTWORTEN[schluessel]; break; }
            }
        }
        if (treffer === undefined) {
            console.warn('[Vorschau] keine Antwort hinterlegt fuer', pfad);
            return Promise.resolve(new Response(
                JSON.stringify({ detail: 'In der Vorschau nicht hinterlegt: ' + pfad }),
                { status: 404, headers: { 'Content-Type': 'application/json' } }));
        }
        return Promise.resolve(new Response(JSON.stringify(treffer),
            { status: 200, headers: { 'Content-Type': 'application/json' } }));
    };

    /* ---- Der Griff: etwas anfassen, bevor das Bild faellt ----
       Ohne das endet die Vorschau vor jedem Dialog, und genau dort steckt
       die Arbeit. Ein Griff steht in der Adresse der Seite:

           /naehrwerte/?griff=klick:#nwAdd;tippe:#nwDlgSuche=Hafer
       Dazu ``warte:<ms>`` fuer Dialoge, die ihre Daten erst holen.

       Zwei Griffe genuegen fuer alles bisher Gesuchte: ``klick`` auf eine
       Kennung und ``tippe`` in ein Feld.

       Gearbeitet wird SYNCHRON, ein Schritt nach dem anderen im selben
       Durchlauf. Der erste Anlauf hat die Schritte ueber
       requestAnimationFrame verkettet und blieb nach dem ersten Klick
       stehen: unter --virtual-time-budget laeuft die Bilderfolge nicht
       weiter, wenn nichts mehr zu zeichnen ist. Es braucht sie auch nicht --
       ein Dialog wird synchron in den DOM gehaengt, er ist unmittelbar nach
       dem Klick da. Wer auf etwas wartet, das erst eine Antwort bringt,
       schiesst zweimal: einmal davor, einmal danach. */

    async function griffeAbarbeiten(schritte) {
        for (const schritt of schritte) {
            const teil = schritt.split(':');
            const art = teil.shift().trim();
            const rumpf = teil.join(':');

            if (art === 'warte') {
                // Ein Dialog, der seine Daten erst holt, ist nach dem Klick
                // noch nicht im DOM -- der naechste Griff ginge ins Leere und
                // das Bild zeigte die Seite ohne ihn, als waere der Knopf
                // kaputt. setTimeout geht dabei trotz --virtual-time-budget:
                // die Uhr wird vorgespult, die Rueckrufe kommen also sehr
                // wohl, nur nicht nach echten Millisekunden.
                const ms = parseInt(rumpf, 10) || 400;
                await new Promise(fertig => setTimeout(fertig, ms));
                continue;
            }
            if (art === 'klick') {
                const el = document.querySelector(rumpf.trim());
                if (!el) { console.warn('[Vorschau] Griff findet nicht:', rumpf); return; }
                el.click();
                continue;
            }
            if (art === 'tippe') {
                const schnitt = rumpf.indexOf('=');
                const el = document.querySelector(rumpf.slice(0, schnitt).trim());
                if (!el) { console.warn('[Vorschau] Griff findet nicht:', rumpf); return; }
                const text = rumpf.slice(schnitt + 1);
                // Zeichen fuer Zeichen mit ``input``-Ereignis: eine Eingabe,
                // die in einem Rutsch dasteht, loest die Taktgeber der Seite
                // anders aus als ein Finger -- und gesucht wird genau deren
                // Zusammenspiel.
                for (let i = 1; i <= text.length; i++) {
                    el.value = text.slice(0, i);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                }
                continue;
            }
            console.warn('[Vorschau] unbekannter Griff:', art);
            return;
        }
    }

    const griff = new URLSearchParams(location.search).get('griff');
    if (griff) {
        // Uebergaenge abschalten. Ein Dialog blendet sich in 180 ms ein; die
        // virtuelle Zeit des Kopflosen trifft das Bild mitten hinein, und
        // was dann dasteht, ist halb durchsichtig -- man haelt es fuer einen
        // Fehler in der Farbe. Gesucht ist der Zustand NACH der Bewegung.
        document.addEventListener('DOMContentLoaded', () => {
            const s = document.createElement('style');
            s.textContent = '*,*::before,*::after{transition-duration:0s !important;'
                + 'animation-duration:0s !important;animation-delay:0s !important}';
            document.head.appendChild(s);
        });
        // Gewartet wird auf den FERTIGEN Zustand, nicht auf ``load``: die
        // Module holen beim Start ihre Daten, und ``eintragDialog`` steigt
        // ohne den geladenen Tag wortlos wieder aus -- der Klick ginge ins
        // Leere und das Bild zeigte die Seite ohne Dialog, als waere der
        // Knopf kaputt. Genau das ist hier einmal passiert.
        //
        // setTimeout ist dabei entgegen dem ersten Verdacht brauchbar:
        // --virtual-time-budget spult die Uhr vor, die Rueckrufe kommen also
        // sehr wohl -- nur eben nicht nach echten Sekunden. Was NICHT geht,
        // ist eine Kette aus requestAnimationFrame: sobald nichts mehr zu
        // zeichnen ist, laeuft die Bilderfolge nicht weiter, und die Kette
        // bleibt nach dem ersten Klick liegen.
        window.addEventListener('load', () =>
            setTimeout(() => griffeAbarbeiten(griff.split(';').filter(Boolean)), 600));
    }
})();
</script>
""" % (json.dumps(daten.ICH), json.dumps(daten.ANTWORTEN, ensure_ascii=False))


RAHMEN = """<!doctype html><meta charset="utf-8">
<title>Rahmen</title>
<style>
  html,body{margin:0;background:#05070a}
  iframe{border:0;display:block;background:#0a0c10}
</style>
<iframe src="%s" style="width:%dpx;height:%dpx"></iframe>
"""


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WURZEL), **kw)

    def log_message(self, *a):
        pass                                   # still bleiben

    def do_GET(self):
        # Ein Rahmen fester Breite. Edge laesst sich mit --window-size nicht
        # unter die Mindestbreite eines Windows-Fensters druecken: das Bild
        # wird dann beschnitten, waehrend die Seite breiter gerechnet
        # bleibt -- und man haelt Zuschnitt fuer Ueberlauf. Im iframe gilt
        # die gewuenschte Breite wirklich, samt Media Queries.
        if self.path.startswith("/rahmen"):
            from urllib.parse import urlparse, parse_qs
            frage = parse_qs(urlparse(self.path).query)
            ziel_url = frage.get("url", ["/"])[0]
            # Ein "#" IM Griff (``klick:#nwAdd``) ist Teil eines Selektors,
            # kein Anker. Bliebe es stehen, schnitte der Browser die halbe
            # Adresse als Fragment ab und die Seite saehe nur noch
            # ``griff=klick:``. Der Anker der Seite selbst (``/…/#ziele``)
            # steht vor dem Fragezeichen und bleibt deshalb unberuehrt.
            if "?" in ziel_url:
                kopf, _, schwanz = ziel_url.partition("?")
                ziel_url = kopf + "?" + schwanz.replace("#", "%23")
            breite = int(frage.get("w", ["390"])[0])
            hoehe = int(frage.get("h", ["1200"])[0])
            roh = (RAHMEN % (ziel_url, breite, hoehe)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(roh)))
            self.end_headers()
            self.wfile.write(roh)
            return

        pfad = self.path.split("?")[0]
        ziel = WURZEL / pfad.lstrip("/")
        if pfad.endswith("/"):
            ziel = ziel / "index.html"
        if ziel.suffix == ".html" and ziel.exists():
            text = ziel.read_text(encoding="utf-8")
            # Ganz vorn in den Kopf: vor config.js und vor api.js.
            marke = "<head>"
            stelle = text.find(marke)
            if stelle >= 0:
                text = (text[:stelle + len(marke)] + stub_js()
                        + text[stelle + len(marke):])
            roh = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(roh)))
            self.end_headers()
            self.wfile.write(roh)
            return
        return super().do_GET()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    print("Vorschau auf http://127.0.0.1:%d/ aus %s" % (port, WURZEL))
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
