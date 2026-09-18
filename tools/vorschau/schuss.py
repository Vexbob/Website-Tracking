# -*- coding: utf-8 -*-
"""Bildschirmfotos der echten Seiten machen -- ohne Server, ohne Datenbank.

    python tools/vorschau/schuss.py                 # alles, Handy und Rechner
    python tools/vorschau/schuss.py /essen/         # nur eine Seite
    python tools/vorschau/schuss.py /essen/ 390     # nur eine Breite

Die Bilder landen unter ``tools/vorschau/bilder/``.

Warum das ueberhaupt geht: auf einem Windows-Rechner liegt Edge, und Edge ist
Chromium -- ``--headless=new --screenshot`` schreibt ein PNG. Damit laesst sich
ansehen, was gebaut wurde, statt es nur zu parsen.

Zwei Dinge, die man dabei wissen muss, weil beide einmal in die Irre gefuehrt
haben:

1. **``--window-size`` traegt schmale Breiten nicht.** Windows erzwingt eine
   Mindest-Fensterbreite; darunter wird das BILD beschnitten, waehrend die
   Seite weiter breit gerechnet wird. Das sieht exakt aus wie ein
   waagerechter Ueberlauf, ist aber keiner -- der erste Befund dieser Sitzung
   war genau dieser Trugschluss. Deshalb laeuft die Seite hier immer in einem
   ``<iframe>`` fester Breite (``/rahmen?url=…&w=390``), und das Fenster ist
   grosszuegig. Im Rahmen gilt die Breite wirklich, samt Media Queries.
2. **``--virtual-time-budget`` friert ``setTimeout`` ein.** Ein Messfuehler,
   der nach zwei Sekunden etwas in die Seite schreibt, laeuft nie. Wer messen
   will, misst am Bild.
"""
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HIER = pathlib.Path(__file__).resolve().parent
BILDER = HIER / "bilder"
PORT = 8787

# Die Seiten, die es zu sehen lohnt. Wer eine dazunimmt, braucht meist auch
# eine Antwort dafuer in daten.py -- fehlt sie, bleibt die Seite leer, und
# genau das soll sie dann auch.
SEITEN = ["/", "/essen/", "/naehrwerte/", "/naehrwerte/#ziele",
          "/naehrwerte/#gerichte", "/naehrwerte/#vorrat", "/schach/",
          "/einstellungen/"]

# Handy und Rechner. 390 ist ein iPhone, 1280 ein uebliches Fenster.
BREITEN = {390: 1400, 1280: 1200}

EDGE_ORTE = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def browser() -> str:
    for ort in EDGE_ORTE:
        if os.path.exists(ort):
            return ort
    raise SystemExit("Kein Chromium gefunden (Edge oder Chrome).")


def server_starten():
    """Den Vorschau-Server hochfahren, falls er nicht schon laeuft."""
    def laeuft():
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/" % PORT, timeout=1)
            return True
        except (urllib.error.URLError, OSError):
            return False

    if laeuft():
        return None
    prozess = subprocess.Popen(
        [sys.executable, str(HIER / "server.py"), str(PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        time.sleep(0.3)
        if laeuft():
            return prozess
    prozess.terminate()
    raise SystemExit("Der Vorschau-Server kam nicht hoch.")


# Git Bash wandelt Argumente, die wie Unix-Pfade aussehen, in
# Windows-Pfade um: aus "/essen/" wird "C:/Program Files/Git/essen/". Das
# hier macht es rueckgaengig, damit derselbe Aufruf in beiden Shells geht.
_MSYS = re.compile(r"^[A-Za-z]:[\/].*?[\/]Git[\/]", re.I)


def seite_saeubern(roh: str) -> str:
    seite = _MSYS.sub("/", roh.replace("\\", "/"))
    if not seite.startswith("/"):
        seite = "/" + seite
    return seite


def name_fuer(seite: str, breite: int) -> str:
    teil = seite.strip("/").replace("/", "-").replace("#", "-") or "start"
    return "%s-%d.png" % (teil, breite)


def schiessen(exe: str, seite: str, breite: int, hoehe: int) -> pathlib.Path:
    ziel = BILDER / name_fuer(seite, breite)
    url = ("http://127.0.0.1:%d/rahmen?url=%s&w=%d&h=%d"
           % (PORT, urllib.parse.quote(seite, safe="/"), breite, hoehe))
    subprocess.run(
        [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--virtual-time-budget=9000",
         # Fenster deutlich groesser als der Rahmen: siehe Fallstrick 1.
         "--window-size=%d,%d" % (breite + 320, hoehe + 60),
         "--screenshot=%s" % ziel, url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return ziel


def main():
    seiten = ([seite_saeubern(sys.argv[1])] if len(sys.argv) > 1
              else SEITEN)
    breiten = ({int(sys.argv[2]): BREITEN.get(int(sys.argv[2]), 1400)}
               if len(sys.argv) > 2 else BREITEN)

    BILDER.mkdir(exist_ok=True)
    exe = browser()
    prozess = server_starten()
    try:
        for seite in seiten:
            for breite, hoehe in breiten.items():
                ziel = schiessen(exe, seite, breite, hoehe)
                zustand = ("%d KB" % (ziel.stat().st_size // 1024)
                           if ziel.exists() else "FEHLGESCHLAGEN")
                print("%-34s %-6s %s" % (seite, breite, zustand))
    finally:
        if prozess:
            prozess.terminate()
    print("\nBilder in %s" % BILDER)


if __name__ == "__main__":
    main()
