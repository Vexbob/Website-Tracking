# Vorschau — die Seiten ansehen, ohne Server und ohne Datenbank

```
python tools/vorschau/schuss.py                  # alles, Handy und Rechner
python tools/vorschau/schuss.py /essen/          # nur eine Seite
python tools/vorschau/schuss.py /essen/ 390      # nur eine Breite
python tools/vorschau/schuss.py /essen/ 390 844  # ... und eine Höhe
```

## Etwas anfassen: der Griff

Bis v2.3.0 endete die Vorschau vor jedem Dialog — und dort steckt die Arbeit.
Ein **Griff** steht in der Adresse der Seite und kennt zwei Handgriffe,
``klick`` und ``tippe``:

```
python tools/vorschau/schuss.py "/essen/?griff=klick:#esAdd" 390 844
python tools/vorschau/schuss.py "/essen/?griff=klick:#esAdd;tippe:#esDlgSuche=Pi" 390 844
```

Dazu kommen ``warte:<ms>`` für Dialoge, die ihre Daten erst holen, und
``zeige:<kennung>`` für eine Karte weit unten — sie bleibt stehen, ihre
Geschwister werden ausgeblendet:

```
python tools/vorschau/schuss.py "/einstellungen/?griff=zeige:%23expCfg" 390
```

Eine große dritte Zahl hilft dafür **nicht**: Windows deckelt die
Fensterhöhe, und das Bild sieht danach genauso aus wie davor. Rollen hilft
ebenfalls nicht — die Karten laden nacheinander, die Seite wächst also nach
dem Rollen weiter, und die Scroll-Verankerung schiebt das Ziel wieder aus dem
Bild. Zweimal gerollt kam zweimal ein anderer Ausschnitt heraus, und ein Bild,
das bei jedem Lauf woanders steht, belegt nichts.

Getippt wird Zeichen für Zeichen mit ``input``-Ereignis: eine Eingabe, die in
einem Rutsch dasteht, löst die Taktgeber der Seite anders aus als ein Finger,
und genau deren Zusammenspiel will man sehen. Während ein Griff läuft, sind
alle Übergänge abgeschaltet — sonst trifft das Bild den Dialog mitten im
Einblenden, und was halb durchsichtig dasteht, hält man für einen Fehler in
der Farbe.

Die **Höhe** ist bei Dialogen wichtig: ein Dialog liegt mittig im Sichtfeld,
und bei 1400 px Sichtfeld beantwortet das Bild eine Frage, die auf keinem
Telefon gestellt wird. 844 ist ein iPhone 14.

Die Bilder landen in `tools/vorschau/bilder/` (nicht versioniert).

## Wozu

Auf dem Entwicklungsrechner läuft kein Postgres und keine Anmeldung. Bis
v2.3.0 hieß das: Layout, Ringe und der Ablauf am Handy waren **ungeprüft** —
es gab nur „es parst“, „die Tests sind grün“, „jede Kennung existiert“. Das
prüft die Form, nicht die Tauglichkeit.

Es geht aber doch: auf einem Windows-Rechner liegt Edge, und Edge ist
Chromium. `--headless=new --screenshot` schreibt ein PNG. Damit lässt sich
ansehen, was gebaut wurde.

Gefunden hat der erste Durchgang sofort zwei echte Fehler: „KOHLENHYDRATE“
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
2. **Eine Kette aus `requestAnimationFrame` bleibt stehen.** Sobald nichts
   mehr zu zeichnen ist, läuft die Bilderfolge unter `--virtual-time-budget`
   nicht weiter — der erste Griff verkettete seine Schritte so und kam nach
   dem ersten Klick nie wieder dran. `setTimeout` ist entgegen dem ersten
   Verdacht brauchbar: die virtuelle Uhr wird vorgespult, die Rückrufe kommen
   also sehr wohl, nur nicht nach echten Sekunden. Ein Messfühler, der nach
   zwei Sekunden etwas in die Seite schreibt, läuft trotzdem ins Leere, wenn
   das Budget vorher abgelaufen ist — wer messen will, misst am Bild.

Dazu eine Kleinigkeit: ein `#` im Seitenpfad muss als `%23` in die
Rahmen-Adresse, sonst behält der **Browser** alles dahinter als eigenen Anker
und der Server sieht es nie — `/naehrwerte/#ziele` öffnete dann stumm den
ersten Reiter.

## Grenzen

Statische Bilder. Dialoge und Eingaben gehen seit v2.4.0 über den Griff;
**nicht** geprüft bleiben Bewegung, die Tastatur am Handy (sie verkleinert das
Sichtfeld, das tut hier nichts), die Kamera und die Dateiauswahl.

Und eines, das immer wieder in die Irre führt: `@media (hover: none) and
(pointer: coarse)` trifft im kopflosen Browser auf einem Rechner **nie** zu.
Wer Berührungsziele nur daran hängt, kann sie hier nicht ansehen — in den
beiden Ernährungsmodulen steht deshalb `@media (max-width: 720px), (hover:
none) and (pointer: coarse)`.
