# -*- coding: utf-8 -*-
"""Bildschirmfotos der echten Seiten machen -- ohne Server, ohne Datenbank.

    python tools/vorschau/schuss.py                   # alles, Handy und Rechner
    python tools/vorschau/schuss.py /essen/           # nur eine Seite
    python tools/vorschau/schuss.py /essen/ 390       # nur eine Breite
    python tools/vorschau/schuss.py /essen/ 390 844   # ... und eine Hoehe

Einen Dialog ansehen: er steht hinter einem Klick, also wird geklickt. Der
Griff steht in der Adresse der Seite und kennt ``klick`` und ``tippe``:

    python tools/vorschau/schuss.py "/essen/?griff=klick:#esAdd" 390 844
    python tools/vorschau/schuss.py "/essen/?griff=klick:#esAdd;tippe:#esDlgSuche=Pi" 390 844

Getippt wird Zeichen fuer Zeichen mit ``input``-Ereignis -- eine Eingabe, die
in einem Rutsch dasteht, loest die Taktgeber der Seite anders aus als ein
Finger, und genau deren Zusammenspiel ist das, was man sehen will.

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
SEITEN = ["/", "/essen/", "/naehrwerte/", "/naehrwerte/#gerichte",
          "/naehrwerte/#vorrat", "/schach/", "/sparziel/", "/einstellungen/",
          "/design.html",
          # Seit v2.11.4 auch die sechs Module, die bis dahin keine
          # Vorschau-Daten hatten -- ihre Darstellung war unbelegt, waehrend
          # die anderen bei jeder Aenderung im Bild geprueft wurden.
          "/ausgaben/", "/ausgaben/statistik.html", "/ausgaben/kategorien.html",
          "/health/", "/musik/", "/notizen/", "/blog/", "/admin/",
          # Seit v2.11.9: der Blog-Editor (er stand acht Versionen lang leer
          # da, ohne dass es jemandem auffiel) und das Hoerregister, das nur
          # hinter einem Reiter zu sehen ist.
          "/blog/admin/",
          "/musik/?griff=warte:900;klick:#mTabRegister;warte:700",
          # Die beiden Dialoge, in denen die eigentliche Arbeit steckt.
          # Ohne Griff endet die Vorschau davor.
          "/essen/?griff=klick:#esAdd;tippe:#esDlgSuche=Pi",
          "/naehrwerte/?griff=klick:#nwAdd;tippe:#nwDlgSuche=Milch",
          "/naehrwerte/?griff=klick:[data-zu-zielen]"]

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
    # Ein Griff (``?griff=klick:#nwAdd``) steht mit in der Adresse und damit
    # auch im Dateinamen -- sonst ueberschreiben sich die Bilder derselben
    # Seite in verschiedenen Zustaenden gegenseitig. Alles, was kein
    # Dateiname sein darf, wird zu einem Strich.
    teil = re.sub(r"[^A-Za-z0-9]+", "-", seite).strip("-") or "start"
    return "%s-%d.png" % (teil[:80], breite)


def schiessen(exe: str, seite: str, breite: int, hoehe: int) -> pathlib.Path:
    ziel = BILDER / name_fuer(seite, breite)
    # "#" und "&" muessen kodiert bleiben: das eine behielte sonst der
    # BROWSER als eigenen Anker und der Server saehe alles dahinter nie
    # (README), das andere risse die Rahmen-Adresse auseinander. Die Zeichen
    # eines Griffs (?=:;,) duerfen dagegen stehen bleiben -- das haelt den
    # Aufruf lesbar.
    url = ("http://127.0.0.1:%d/rahmen?url=%s&w=%d&h=%d"
           % (PORT, urllib.parse.quote(seite, safe="/?=:;,"), breite, hoehe))
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
    # Dritte Zahl: die Hoehe. Fuer eine lange Seite ist ein hohes Fenster
    # richtig (man will alles auf einem Bild), fuer einen Dialog dagegen
    # falsch -- der liegt mittig im SICHTFELD, und bei 1400 px Sichtfeld
    # beantwortet das Bild eine Frage, die auf keinem Telefon gestellt wird.
    # 844 ist ein iPhone 14.
    breiten = ({int(sys.argv[2]): (int(sys.argv[3]) if len(sys.argv) > 3
                                   else BREITEN.get(int(sys.argv[2]), 1400))}
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
