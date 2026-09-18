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
