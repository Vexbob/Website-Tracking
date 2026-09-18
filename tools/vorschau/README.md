# Vorschau — die Seiten ansehen, ohne Server und ohne Datenbank

```
python tools/vorschau/schuss.py                 # alles, Handy und Rechner
python tools/vorschau/schuss.py /essen/         # nur eine Seite
python tools/vorschau/schuss.py /essen/ 390     # nur eine Breite
```

Die Bilder landen in `tools/vorschau/bilder/` (nicht versioniert).

## Wozu

Auf dem Entwicklungsrechner läuft kein Postgres und keine Anmeldung. Bis
v2.3.0 hieß das: Layout, Ringe und der Ablauf am Handy waren **ungeprüft** —
es gab nur „es parst", „die Tests sind grün", „jede Kennung existiert". Das
prüft die Form, nicht die Tauglichkeit.

Es geht aber doch: auf einem Windows-Rechner liegt Edge, und Edge ist
Chromium. `--headless=new --screenshot` schreibt ein PNG. Damit lässt sich
ansehen, was gebaut wurde.

Gefunden hat der erste Durchgang sofort zwei echte Fehler: „KOHLENHYDRATE"
brach über seinen 78-px-Ring hinaus, und ein eingeschaltetes Modul galt auf
einem frischen Gerät als ruhend.

## Wie es zusammenhängt

* **`server.py`** liefert `frontend/` unverändert aus — dieselbe CSS, dasselbe
  JavaScript, dieselben Pfade wie im Betrieb. Nachgebaut wird nichts; eine
  Nachbildung würde genau die Fehler verstecken, die man sucht.
  In jede HTML-Antwort hängt er ganz vorn im `<head>` ein Skript, das einen
  Token in den `localStorage` legt (sonst schickt `isLoggedIn()` einen zur
  Anmeldung) und `fetch` durch einen Verteiler auf feste Antworten ersetzt.
* **`daten.py`** hält diese Antworten. Was sich rechnen lässt, wird aus dem
  **echten** Backend-Code gerechnet (`food_calc`, `food_mahlzeit`):
  Mahlzeitenliste, Stundengrenzen, Tagessummen, Richtwerte. Abgetippte
  Beispielantworten wären die zweite Wahrheit über die Schnittstelle und
  würden genau dort abweichen, wo es darauf ankommt. Von Hand steht dort nur,
  was ohne Datenbank nicht zu holen ist.
  Fehlt eine Antwort, bleibt die Seite an der Stelle leer und die Konsole sagt
  welche — das ist ein Befund, kein Fehler der Vorschau.
* **`schuss.py`** startet den Server, wenn er nicht läuft, und schießt.

## Zwei Fallstricke, beide haben einmal in die Irre geführt

1. **`--window-size` trägt schmale Breiten nicht.** Windows erzwingt eine
   Mindest-Fensterbreite; darunter wird das **Bild** beschnitten, während die
   Seite weiter breit gerechnet wird. Das sieht exakt aus wie ein waagerechter
   Überlauf — abgeschnittene Knöpfe, eine Karte, die über den Rand läuft — ist
   aber keiner. Erkennungszeichen: auch die untere Leiste ist abgeschnitten,
   und die ist `position: fixed` und kann gar nicht überlaufen.
   Deshalb läuft die Seite immer in einem `<iframe>` fester Breite
   (`/rahmen?url=…&w=390`) und das Fenster ist großzügig. Im Rahmen gilt die
   Breite wirklich, samt Media Queries.
2. **`--virtual-time-budget` friert `setTimeout` ein.** Ein Messfühler, der
   nach zwei Sekunden etwas in die Seite schreibt, läuft nie. Wer messen will,
   misst am Bild.

Dazu eine Kleinigkeit: ein `#` im Seitenpfad muss als `%23` in die
Rahmen-Adresse, sonst behält der **Browser** alles dahinter als eigenen Anker
und der Server sieht es nie — `/naehrwerte/#ziele` öffnete dann stumm den
ersten Reiter.

## Grenzen

Statische Bilder. Bewegung, Tippen, Tastatur am Handy und alles hinter einem
Klick (Dialoge, Kamera, Dateiauswahl) sind damit **nicht** geprüft. Wer einen
Dialog ansehen will, muss ihn beim Laden öffnen lassen — dafür gibt es hier
noch nichts.
