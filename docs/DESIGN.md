# Vexbob — Designsprache

> **Vexbob ist ein Werkzeug zum Nachschlagen, kein Schaufenster.**
> Die Oberfläche tritt zurück, die Zahlen treten vor. Der Grund ist dunkel und
> neutral, gestuft in wenigen klar unterscheidbaren Ebenen. Flächen tragen keine
> Farbe, außer die Farbe bedeutet etwas: jedes Modul hat seinen Ton, jede
> Kategorie und jeder Laden trägt den eigenen, und der Akzent gehört allein dem,
> was gerade aktiv ist oder Aufmerksamkeit verlangt. Leuchten und Verläufe gibt
> es genau dort, wo kein Text liegt. Bewegung erklärt eine Veränderung und ist
> danach sofort vorbei.

Dieses Dokument ist die Quelle für alle Gestaltungsentscheidungen. Wer eine neue
Seite oder Komponente baut, schlägt hier nach, statt sich etwas auszudenken.
Die Werte selbst stehen als Tokens in `frontend/css/style.css`; hier steht,
**wann** welcher gilt.

Seit v1.55.0 gibt es **nur noch das dunkle Theme**. Der Umschalter, die hellen
Farbwerte und die Druckansicht sind entfernt — dadurch wird jedes Token genau
einmal definiert, und die Regeln unten sind eindeutig statt „je nach Theme“.

---

## 1. Ebenen

Im Dunkeln trennen Schatten nichts. Ebenen entstehen durch **Helligkeit plus
Haarlinie**, nie durch Schatten allein.

| Ebene | Token | Wofür |
|---|---|---|
| Grund | `--bg` `#0a0c10` | Seitenhintergrund, sonst nichts |
| Fläche | `--surface-1` `#12151c` | Karten, Listenkacheln, Tabellenkörper |
| Erhoben | `--surface-2` `#171b23` | Eingabefelder, Chips, Zeilen *in* einer Karte |
| Schwebend | `--surface-3` `#1e232d` | Menüs, Modals, Toasts, Popover |

Dazu: `--line` (7 % Weiß) als Standardkante, `--line-strong` (14 %) für
Hover-Zustände und Trennlinien, die tragen müssen.

**Regeln**

- Eine Fläche liegt nie auf einer Fläche derselben Stufe. Wer verschachtelt,
  geht eine Stufe hoch.
- Schatten nur ab „schwebend“ (`--shadow-float`) — und dort zusätzlich zur
  Haarlinie, nicht statt ihrer.
- Kein reines Schwarz und kein reines Weiß im Interface.

**Lichteinfall** (v2.18.0). Eine ruhende Karte ist nicht einfarbig: Sie trägt
`--flaeche`, einen Hauch Weiß (3 %) von oben, der zur Mitte ausklingt, und
`--kante-licht`, eine 1-px-Lichtkante an der Oberseite. Das ist Helligkeit,
keine Farbe, und ändert den Kontrast von Text darauf um weniger als ein
Prozent. Alle Kartenklassen (`.v-card`, `.card`, `.tile`, `.kpi-hero`,
`.stat-card`, `.stat-kpi`) teilen sich diese eine Fläche. Karten runden mit
`--radius-lg` (18 px), innere Flächen mit `--radius` (12 px), Blätter und
große Kacheln mit `--radius-xl` (22 px).

## 2. Textrollen

Vier Rollen, mehr braucht es nicht. Gemessene Kontraste gelten gegen
`--surface-1`.

| Rolle | Token | Kontrast | Wofür |
|---|---|---|---|
| Titel | `--text-1` | 16,9:1 | Überschriften, Beträge, alles Ablesbare |
| Fließtext | `--text-2` | 10,0:1 | Beschreibungen, Erklärsätze |
| Sekundär | `--text-3` | 5,9:1 | Meta-Zeilen, Datum, Einheiten, Achsen |
| Schwach | `--text-4` | 3,8:1 | **nur** Dekoratives: Trennzeichen, Platzhalter, Version |

**Regeln**

- `--text-4` trägt nie Information, die man lesen muss. Wer versucht ist, damit
  einen Satz zu schreiben, nimmt `--text-3`.
- Zahlen, die untereinander stehen (Beträge, Messwerte, Zeiten), bekommen
  `font-variant-numeric: tabular-nums`. Immer.
- Schriftgrößen aus der Skala: 12 / 13 / 15 / 17 / 22 / 28 px. Überschriften
  mit `letter-spacing: -0.02em`, Fließtext ohne.
- Dazu **eine** Stufe darüber, `--fs-display` (36 px), für die eine große Zahl,
  um die es auf einer Seite geht: die Kalorien des Tages, der Kontostand. Sie
  steht höchstens einmal je Seite und trägt immer eine Zahl, nie ein Wort.
  Große Zahlen laufen enger (`-0.03em`); die Ziffern stehen sonst zu weit
  auseinander.
- Darüber steht nur noch die **Heldenzahl** (v2.19.0, `.v-held`,
  `--fs-held`, 52 px, am Handy mit der Breite gedeckelt): die eine Zahl, um
  die sich ein ganzes Modul dreht, auf der Bühne (Abschnitt 3). Ganze Euro
  groß, Cent und Zeichen klein daneben (`.v-held-rest`); gelesen wird die
  vordere Zahl, die hintere ist Genauigkeit.
- Systemschrift, keine Webfonts. Auf Apple-Geräten ist das SF Pro, und genau so
  soll es aussehen.

## 3. Farbe

Farbe ist Information, nicht Dekoration.

- **Akzent** `--accent` `#ff5c7a` — gehört dem Aktiven: ausgewählter Tab, Fokus,
  primäre Aktion, der Punkt am aktuellen Modul. Nichts anderes.
  Als Text/Icon auf dunkel erlaubt (6,1:1) ab 15 px halbfett.
  Als **Fläche** `--accent-strong` `#ff4d72` oder der Verlauf `--grad-accent`.
  Beide tragen **dunkle** Schrift `--accent-ink` (6,1:1) — nie weiße. Damit
  gilt in der ganzen App dieselbe Regel wie bei den Statusfarben: helle
  Farbe, dunkle Schrift.
- **Ein Knopf ohne eigene Klasse ist neutral** (`--surface-2`, `--line-strong`).
  Bis v2.17.0 war er weiß und damit der lauteste Knopf jeder Seite, lauter als
  die Primäraktion daneben. Lauter als die Primäraktion ist nichts.
- **Modultöne**: Ausgaben Türkis, Gesundheit Rosa, Sparziel Grün, Notizen Blau,
  Blog Bernstein, Verwaltung Violett, Musik Spotify-Grün, Schach Holzbrett-Orange,
  Ernährung Blattgrün. Sie färben Modul-Icons,
  die aktive Diagrammreihe und kleine Identitätsmarken — nie ganze Flächen.
  Das Musik-Modul ist der Fall, an dem sich zeigt, wofür ein Modulton gut ist:
  seine Daten kommen aus dem Spotify-Datenexport, und `--m-musik` sagt das
  schneller als jede Beschriftung. Aufgehellt gegenüber dem Original, damit der
  Ton auch als Text auf dunklem Grund lesbar bleibt (6,4:1). Auch hier gilt die
  Grenze: Icon-Kachel, erste Diagrammreihe, ein Punkt neben „Quelle: Spotify“ —
  keine grüne Fläche.
- **Die Bühne** (v2.19.0, `.v-buehne`) ist die eine Ausnahme davon: Der Kopf
  eines Moduls darf seinen Ton als Licht tragen, ein weicher Schein von oben
  (20 %, läuft vor der Mitte aus) und eine getönte Kante. Das ist keine
  Fläche in Modulfarbe, und sie steht höchstens einmal je Seite, dort, wo die
  Heldenzahl steht. Der Grund: Ein Modul soll man am ersten Blick erkennen,
  nicht erst an der Überschrift. Der Text auf der Bühne bleibt über 14:1.
  „Einmal je Seite“ heißt einmal je **Ansicht**: Ein Reiter, der eine eigene
  Frage beantwortet, darf seine eigene Bühne haben (v2.27.0, Gesundheit:
  „Überblick“ mit den Schritten von gestern, „Workouts“ mit der
  Trainingszeit im Zeitraum). Sichtbar ist immer nur eine.
- **Statusfarben** `--ok` `--warn` `--danger` `--info` sind helle Töne für
  **Text und Marken auf dunklem Grund**. Sie tragen **niemals weiße Schrift**
  (weiß auf `--ok` wäre 1,7:1). Wo eine Statusfläche nötig ist: getönter
  Hintergrund (`--ok-soft`) mit der Statusfarbe als Text.
- **Entitätsfarben** (Kategorie, Laden, Marke) sind Nutzerdaten. Sie erscheinen
  als 3-px-Streifen, Punkt oder 16-%-Tönung hinter einem Icon — nie als
  Vollfläche hinter Text, weil der Nutzer sie frei wählt und wir ihren Kontrast
  nicht garantieren können.

**Verläufe und Leuchten** gibt es genau an vier Stellen: Modul-Icon-Kacheln,
die primäre Aktion, Fortschrittsbalken und Diagrammfüllungen. Alle vier tragen
keinen Text. Hinter Zahlen liegt nie ein Verlauf — außer dem Schein der Bühne,
der so schwach ist, dass er den Kontrast der Heldenzahl nicht messbar
ändert. Das Leuchten bleibt klein
(`--gl-…`: 6 px Versatz, 20 px Weite, 22 %): Es hebt einen Knopf ab, statt
einen Hof um ihn zu legen.

**Alle vier sind einstellbar** (v1.74.0, erweitert in v1.78.0). In den
Einstellungen wählt man je ein Preset für die primäre Aktion
(`--grad-accent`), die Fortschrittsbalken (`--grad-progress`), die Zahlen und
Diagramme (`--figure`) und die Hintergrundlichter (`--backdrop`). Ein *Thema*
setzt alle vier auf einmal.

Bei den Zahlen und Diagrammen gilt eine Besonderheit, weil dort die
Modul-Identität hängt: der Standard heißt **„Modulton“** und definiert
`--figure` bewusst gar nicht. Jedes Modul fällt dann über
`var(--figure, var(--m-sparziel))` auf seine eigene Farbe zurück — Sparziel
grün, Ausgaben türkis. Erst wer ausdrücklich ein anderes Preset wählt,
überschreibt das. Identität ist damit der Standard, nicht die Ausnahme.

- Die Presets stehen als Tokens (`--g-…`, `--bd-…`) **ausschließlich** in
  `css/style.css`. Das Frontend setzt nur ein Attribut am `<html>`
  (`data-grad-action` und Geschwister), genau wie beim Theme — dadurch bleibt
  „keine Hex-Werte in JS“ heil und ein Preset ist an einer Stelle definiert.
- Die Auswahl ist eine **geschlossene Liste**, kein Farbwähler. Jedes Preset
  ist hell genug, um `--accent-ink` zu tragen; bei frei gewählten Farben ließe
  sich der Kontrast der Beschriftung nicht mehr zusichern, und genau das ist
  die Regel, die über allem steht.
- Ein neuer Fortschrittsbalken nimmt `--grad-progress`, nicht `--grad-accent`.
  Sonst folgt er der Einstellung für die Aktionen und wandert bei der nächsten
  Umstellung mit der falschen Gruppe.

## 4. Zustände

Jede interaktive Fläche kennt sieben Zustände. Fehlt einer, ist die Komponente
nicht fertig.

| Zustand | Was passiert |
|---|---|
| Ruhe | Basisfläche, `--line` |
| Hover | eine Ebene heller **oder** `--line-strong`, nie beides |
| Aktiv/Gedrückt | `transform: scale(.97)`, `--dur-1`; breite Zeilen und Kacheln `.99` |
| Ausgewählt | Akzent als Schrift auf getöntem Grund (`--accent-soft`, Text `--accent`); Reiter: die gleitende Markierung |
| Fokus | `--focus-ring`, sichtbar nur bei `:focus-visible` |
| Deaktiviert | `opacity:.45`, `cursor:default`, keine Transformation |
| Lädt | Skeleton (`.skel`) statt Text; nie ein „Lade …“ als Fließtext |

Berührungsziele auf Mobilgeräten sind mindestens 44 px hoch.

Als **Vollfläche** trägt der Akzent nur noch die primäre Aktion. Ein
ausgewählter Chip in voller Akzentfläche war lauter als der Knopf, um den es
auf der Seite geht. Seit v2.18.0 ist „ausgewählt“ dieselbe Tönung wie im
Zeitraumfilter und beim aktiven Modul in der Leiste; Stellen in den Modulen,
die noch die Vollfläche tragen, ziehen mit ihrem Modul nach.

**Der achte Zustand: die Seite selbst.** Modulseiten starten unsichtbar
(`body{visibility:hidden}` in `css/statistics.css`), damit vor einer
Weiterleitung zum Login nicht kurz die fertige Oberfläche aufblitzt. Sie geben
sich mit `body.classList.add('ready')` frei — **direkt nach dem synchronen
Login-Check**, nie erst nach einer Serverantwort. Hängt die Freigabe an einem
`await`, ist eine langsame oder fehlende Antwort nicht mehr von einer kaputten
Seite zu unterscheiden: man sieht nur den Seitenhintergrund.

## 5. Bewegung

Drei Dauern, eine Kurve: `--dur-1` 120 ms (Zustandswechsel), `--dur-2` 200 ms
(Ein-/Ausblenden, Aufklappen), `--dur-3` 280 ms (Overlays, Seitenwechsel),
Kurve `--ease` `cubic-bezier(.2,.7,.2,1)`.

**Regeln**

- Bewegung erklärt eine Veränderung: etwas kommt dorthin, wo es herkam.
- Kein Federn, kein Nachschwingen, keine Dauerbewegung außer Skeleton-Puls.
- **Auftritt** (v2.18.0): Karten erscheinen beim Laden und beim Reiterwechsel
  einmal von unten (8 px, `--dur-3`), gestaffelt um 40 ms, ab der fünften
  gleichzeitig. Die Animation füllt nur `backwards`: Danach gehört die
  Transformation wieder dem Element, sonst hielte sie Hover und Druck fest.
- Der Skeleton-Schimmer läuft über die ganze Fläche des Platzhalters, nicht
  als Streifen darüber.
- Nichts bewegt sich beim reinen Betrachten. Was sich ohne Zutun bewegt, ist
  ein Fehler.
- `prefers-reduced-motion` schaltet alles ab — das ist bereits global gelöst.

## 6. Leere Zustände

Ein Muster für die ganze App (`.empty`): Zeichen, ein Satz, optional eine
Handlung.

- Der Satz sagt, **warum** es leer ist, nicht dass es leer ist.
  „Noch keine Kategorien. Beim ersten gescannten Bon legt der Parser sie selbst
  an." statt „Keine Daten“.
- Genau eine Handlung, und nur wenn sie hier sinnvoll ist.
- Gestrichelte Kante, `--surface-2`, `--text-3`. Kein Bild, keine Illustration.
- Ein **Fehler** ist kein leerer Zustand: `.empty.is-error` zeigt die Meldung
  und einen „Erneut versuchen“-Knopf.

## 6a. Dateien ablegen

Eine Ablegefläche (`.dropzone`) trägt dieselbe gestrichelte Kante wie der leere
Zustand — die Aussage ist dieselbe: hier ist noch nichts, hier könnte etwas hin.

- Drei Zustände: **bereit**, **eine Datei schwebt darüber** (`.drag`, Akzent),
  **eine Datei liegt drin** (`.has-files`). Der letzte wechselt auf eine
  durchgezogene Kante in `--ok` — gestrichelt heißt „leer“, und das stimmt dann
  nicht mehr.
- Sie ist immer auch mit der Tastatur bedienbar (`tabindex`, Enter/Leertaste)
  und hat ein verstecktes `<input type="file">` dahinter, nie nur Drag & Drop.
- Ein Import, der etwas ersetzt, zeigt **vor** dem Schreiben, was er ersetzen
  würde. Das Musik-Modul lädt dafür dieselbe Datei erst als Vorschau hoch
  (`dry_run`) — eine zweite Rechnung wäre irgendwann eine andere.

## 6b. Filter

Ein Filter zeigt im Ruhezustand seinen **Stand**, nicht seine Möglichkeiten: der
Knopf heißt „30 Tage“, nicht „Zeitraum ▾“. Die Auswahl liegt in einem
schwebenden Feld darunter (`.filter-toggle-btn` + `.filter-popover`), nicht
dauerhaft auf der Seite — sie wird selten benutzt und kostet sonst auf dem
Handy zwei Zeilen.

- Der **Zeitraum** hat genau eine Fassung: `VexRange.mount` aus
  `js/range-filter.js`. Presets als Liste mit Haken (die Auswahl ist
  einwertig), darunter der eigene Von/Bis-Zeitraum.
- Ein Preset gilt **sofort** und schließt das Feld. Ein eigener Zeitraum wird
  bestätigt — zwei Datumsfelder sind zwei Eingaben, und nach der ersten wäre
  jede Ladung falsch.
- Ist etwas anderes als der Standard gewählt, trägt der Knopf den Akzent
  (`.has-active`). Ein Filter, den man nicht sieht, ist eine Falle.

## 6c Listen von Datensätzen

Drei Formen, und die Wahl hängt allein daran, **wie gelesen wird**:

| Form | Wofür |
|---|---|
| `.v-row`-Stapel | wenige, ungleiche Zeilen in einer Karte |
| `.rec-list` | viele gleichartige Datensätze (Partien, Buchungen, Läufe) |
| `.stat-table` | ein Zahlenraster, bei dem Spalte gegen Spalte gelesen wird |

Eine `.rec-list`-Zeile trägt eine Marke, eine Titelzeile, eine Meta-Zeile und
einen Wert am Rand. Sie ist die Antwort auf die quer scrollende Tabelle: ein
Partienprotokoll hat acht Angaben je Zeile, und davon lag auf dem Handy die
Hälfte hinter dem rechten Rand. Wer waagerecht scrollen muss, um das Ergebnis
zu sehen, liest die Liste nicht.

- Die Zeile liegt eine Ebene über der Karte (`--surface-2`), getrennt wird
  durch 1-px-Lücken auf `--line` — dieselbe Rasterkante wie beim
  Wertungsvergleich, kein Schatten.
- Sie darf ein `<a>` oder `<button>` sein, wenn dahinter etwas aufgeht; dann
  trägt sie rechts den Winkel und die vollen sieben Zustände. Die globale
  Button-Base wird dafür in `style.css` zurückgenommen — eine Ergänzung der
  Komponente, keine zweite Variante.
- Die Marke trägt Status- oder Entitätsfarbe als 18-%-Tönung, nie als
  Vollfläche.
- Trennzeichen in der Meta-Zeile sind `--text-4`; die Angaben daneben nicht.

## 6d. Was selten passiert, steht nicht dauerhaft da

Eine Seite gehört dem, weswegen man sie aufruft. Alles, was man **selten** tut
— ein Rezept anlegen, ein Lebensmittel von Hand pflegen, einen Katalog
einspielen —, liegt hinter einem Knopf im Dialog (`.modal-overlay` /
`.modal-box`), nicht als dauerhaft offene Maske darüber.

**Den Dialog baut `js/modal.js` (`VexModal.open`), nicht das Modul.** Bis
v2.1.0 lag `openModal` viermal kopiert in ausgaben, essen, nährwerte und
schach, und keine der vier Fassungen sperrte das Scrollen dahinter — auf dem
Handy scrollte am Ende der Liste die Seite weiter, und beim Schließen stand
man woanders. Was die geteilte Fassung leistet und jede eigene wieder verlieren
würde:

- **Hintergrund gesperrt**, solange ein Dialog offen ist (`overflow: hidden`
  am Body, gezählt — ein Dialog kann einen zweiten öffnen), dazu
  `overscroll-behavior: contain` am `.modal-body` gegen den Kettenlauf.
- **`role="dialog"`, `aria-modal="true"`** und der Titel als `aria-label`.
- **Der Fokus bleibt drin**: Tab läuft im Kasten im Kreis und nach dem
  Schließen zurück auf den Knopf, von dem aus geöffnet wurde. Das erste Feld
  bekommt den Fokus **nicht** von selbst — auf dem Handy risse das die
  Tastatur hoch und verdeckte die halbe Liste. Wer ein Feld vorn haben will,
  setzt den Fokus selbst und nur am Rechner.
- **Escape-Horcher sauber abgeräumt**, auf jedem Schließweg.

Ein Modul behält seine Funktion `openModal` und leitet in einer Zeile dorthin
— so bleiben die Aufrufstellen unberührt. Optionen: `breit`/`wide`, `voll`,
`beimSchliessen`/`onClose`.

**Die Handlungen stehen im Dialogfuß** (v2.19.0, `.modal-fuss`): Er bleibt
unten, wenn der Inhalt scrollt, die Hauptsache steht rechts, Löschen links
außen — so weit weg von „Speichern“, wie der Kasten es zulässt. Enter im
Formular löst die Hauptsache aus. Zahlenfelder tragen keine Pfeile: Firefox
malte sie an jedes Feld, am Handy trifft sie niemand, und am Rechner
verdeckten sie die letzte Ziffer.

**Am Handy ist der Dialog ein Blatt** (v2.18.0): Unter 720 px kommt jeder
Dialog, der nicht `voll` ist, von unten, oben gerundet, mit Griff. Am Kopf
nach unten ziehen schließt ihn; im Körper wird gescrollt, nicht gezogen, sonst
wanderte das Blatt beim Scrollen der Liste mit. Am Rechner bleibt es der
Kasten in der Mitte, der Grund dahinter wird weich.

Das Muster stammt aus der Ernährungsseite (v1.95.0): dort standen Eingabefeld,
Mahlzeiten-Chips, Vorschlagsliste, Tagesbild und Eintragsliste als fünf Klötze
untereinander — und das, weswegen man die Seite öffnet (was habe ich heute
gegessen), begann unter dem Bildschirmrand.

- **Der Gegenstand der Seite steht oben**, die Werkzeuge dazu daneben oder
  darin. Ein Eingabefeld über dem Inhalt kostet jeden Aufruf eine
  Bildschirmhöhe, auch die neunzig Prozent, in denen man nur nachsieht.
- **Der Ort sagt den Zusammenhang.** Ein Plus am Kopf der Mahlzeit trägt die
  Mahlzeit schon in sich; eine Chipreihe, die dieselbe Frage noch einmal
  stellt, ist damit überflüssig. Was aus dem Ort folgt, wird nicht gefragt.
- **Eine Zeile, eine Hauptsache.** In einer Vorschlagsliste ist die ganze Zeile
  der Knopf für den häufigen Fall; der seltene steht klein daneben. Zwei gleich
  große Knöpfe je Zeile sind bei acht Vorschlägen sechzehn gleichberechtigte
  Ziele, und keins davon sticht heraus.
- **Erklärabsätze sind ein Warnzeichen.** Wo drei Sätze erklären, wie ein
  Bedienelement gemeint ist, stimmt meist das Bedienelement nicht. Bleibt ein
  Satz nötig, steht er direkt daneben — nicht als Karte am Seitenende.

## 6e. Seitenkopf, Reiter und Abschnitt

**Am Handy gibt es keinen Seitenkopf.** Der Modulname steht in der Leiste; ein
zweites Mal als Überschrift darunter kostete siebzig Pixel der ersten Ansicht.
`.page-head` ist unter 720 px ausgeblendet, für alle Seiten an einer Stelle.
Was im Seitenkopf an Handlung steht, braucht deshalb am Handy einen zweiten
Ort. Am Rechner bleibt der Kopf, aber ohne Erklärabsatz (6d).

**Reiter stehen in einer Zeile** (`.tabs`), auch am Handy. Unter den aktiven
gleitet eine Markierung (`js/reiter.js`); das Modul setzt wie bisher nur die
Klasse `active`. Passt die Zeile nicht in die Breite, rollt sie, der Rand
blendet weich aus, und der aktive Reiter steht in der Mitte. Jede Seite mit
`.tabs` bindet `js/reiter.js` ein; der Test in `test_navigation.py` wacht
darüber. Ein Reiter darf ein **Link** sein (`a.tab-btn`), wenn jeder Bereich
eine eigene Seite ist: Die Ausgaben haben seit v2.21.0 drei Bereiche
(Übersicht, Statistik, Verwalten) über neun Seiten, und die Pflegeseiten unter
„Verwalten“ tragen zusätzlich einen Weg zurück.

**Ein Abschnitt** (`.v-abschnitt`, v2.19.0) ist eine Überschrift über einer
Gruppe von Karten, mit der Handlung am Rand („Neu“). Er ist kein Kasten: die
Karten darunter sind die Flächen, und eine Karte um Karten wäre eine Fläche
auf einer Fläche derselben Stufe (Abschnitt 1).

## 6f. Schalter

**An oder aus ist ein Schalter** (v2.30.0, `.v-schalter`, Muster in
`design.html`), kein Knopf, der seinen Zustand als Wort trägt. Die
Einstellungen hatten dreizehn rote Knöpfe „Benutze ich“ — gleich laut,
und ob das Wort den Zustand meinte oder das, was beim Tippen passiert,
sah man ihm nicht an. Bedient wird die ganze Zeile
(`button.v-schalt-zeile` mit `role="switch"` und `aria-checked`), der
Schalter ist nur das Bild des Zustands. Ein Schalter speichert sofort;
steht er neben Feldern, die auf einen Speichern-Knopf warten (Export-
Voreinstellung), wartet er mit — zwei Verhaltensweisen in einer Karte
kann man nicht auseinanderhalten.

## 6g. Navigationsleiste

**Am Rechner steht links die Marke, nicht der Seitenname** (v2.34.0, gebaut
von `js/nav-switcher.js`). Der Name stand dreimal da — links, als aktiver
Reiter und als Überschrift der Seite — und war je Seite verschieden breit:
die Reiter fingen auf jeder Seite an einer anderen Stelle an. Die Marke ist
immer gleich breit und führt zum Dashboard; am Handy bleibt der Seitenname,
weil es dort oben keine Reiter gibt.

Die Module stehen in einer **Kapsel**, derselben Sprache wie `.tabs`: das
aktive liegt erhaben darin (`--surface-3`, Haarlinie, Lichtkante) und färbt
sein Zeichen im Modulton (`--nav-ton`, aus `tone` in `MODULES`). Der Akzent
als Fläche war in der Milchglas-Leiste zu laut. Das Konto ist ein Kreis mit
dem Anfangsbuchstaben; der Name steht oben in seinem Menü. Das Punkte-Menü
zeigt dieselben gezeichneten Zeichen wie Leiste und Tab-Leiste, keine Emoji.

## 7. Diagramme

Reduziert, ruhig, dieselbe Farbwelt.

- Reihenfolge der Reihenfarben: `--chart-1` … `--chart-6`. Die erste Reihe
  trägt den Modulton, nicht den Akzent — der Akzent markiert Auswahl, nicht
  Daten.
- **Ein Ringdiagramm trägt höchstens fünf, sechs Posten.** Darüber wird es zur
  Farbrateübung und braucht eine Legende, die es doppelt so groß macht — dann
  ist eine **Rangliste** (`.rank-list`) richtig: Name, Anteil als Balken,
  Betrag. Sie ersetzt Ring *und* Tabelle darunter, nicht nur den Ring.
- **Eine Zeitreihe wird lückenlos gezeichnet.** Endpunkte liefern meist nur
  Perioden mit Daten; ungefüllt stehen die Balken gleichmäßig verteilt, die
  Lücken sind unsichtbar, und ein gleitender Durchschnitt mittelt über
  Einträge statt über Tage. Auffüllen ist Aufgabe der Seite.
- Kein Gitter außer waagerechten Linien in `--chart-grid` (8 % Weiß).
  Keine senkrechten Linien, keine Rahmen, keine Achsentitel.
- Achsenbeschriftung `--text-3`, 11 px, tabellarische Ziffern.
- Flächen unter Linien: Verlauf von 18 % auf 0 % derselben Farbe.
- Balken bekommen `borderRadius: 6`, keine Trennlinien zwischen Segmenten.
- Legende nur, wenn mehr als zwei Reihen und keine direkte Beschriftung möglich
  ist. Sonst beschriften wir am Punkt.
- **Zeigen statt umschalten.** Ein Umschalter vor einem Diagramm, der nur
  bestimmt, welcher Ausschnitt derselben Daten gerade sichtbar ist, wird zu
  mehreren kleinen Diagrammen nebeneinander — je Disziplin, je Kennzahl, je
  Konto. Beim Klicken vergisst man, was vorher dastand; ein Vergleich, der
  nebeneinander liegt, ist keiner, den man sich merken muss. Ein kleines
  Diagramm braucht dafür keine eigene Legende: die Zahl über der Kurve trägt
  die Farbe ihrer Linie. Nicht gemeint ist der **Zeitraum** — der gilt für die
  ganze Seite und filtert nicht, er verschiebt.
- Tooltip sieht aus wie ein schwebendes Element der App: `--surface-3`,
  Haarlinie, 12 px Radius — nicht wie Chart.js-Standard.
- **Ein Datum im Tooltip trägt immer die Jahreszahl**, auch wenn die Achse aus
  Platzgründen nur `05.09.` zeigt. Die ausgeschriebene Fassung kommt aus
  `VexCharts.fullDay/fullWeek/fullMonth` (`js/charts.js`).
- **Der Tooltip verschwindet, wenn man daneben tippt.** Auf dem Handy gibt es
  kein „Maus verlässt die Fläche“; `js/charts.js` erledigt das global für alle
  Diagramme. Deshalb gehört die Datei auf jede Seite mit einem Diagramm.
- **Die Durchschnitts-/Trendlinie liegt über der Wertlinie**: `order`
  `VexCharts.ORDER.TREND` gegen `VexCharts.ORDER.VALUE`. Chart.js zeichnet die
  kleinere `order` weiter vorn — unter einer gefüllten Wertlinie wäre die
  Trendlinie bei sprunghaften Daten unsichtbar.

## 7a. Ringe

Ein Ring beantwortet **eine** Frage: wie viel von einem Ziel. Mehr als eine
Zahl trägt er nicht, und für Anteile an einem Ganzen (Kategorien, Posten)
bleibt die Rangliste zuständig — das ist der Unterschied zum Ringdiagramm,
das in Abschnitt 7 bei fünf, sechs Posten endet.

Eine Komponente, zwei Formen (`.v-ring` in `css/style.css`, Muster in
`design.html`):

- **Halbkreis** (`.v-ring--halb`) für die eine grosse Zahl. Er liest sich wie
  ein Tank: es gibt ein Maximum, und der freie Rest ist die eigentliche
  Auskunft.
- **Vollkreis** für die kleinen daneben. Er liest sich als Anteil und
  vergleicht sich gut mit seinen Nachbarn. Jeder trägt seine Beschriftung
  darunter — so braucht keine Reihe eine Legende.
- Gesteuert wird ausschliesslich über CSS-Variablen (`--ring-val`,
  `--ring-over`, `--ring-tone`). Kein Hex in JS, keine Inline-Farbe.
- **Über dem Ziel** reitet ein zweiter Bogen in `--warn` von vorn über den
  vollen Ring, gedeckelt bei 200 %. Gelb und nicht rot: „mehr“ ist keine
  Bewertung. Wo mehr ein Erfolg ist, dreht `.v-ring--gut` ihn auf `--ok`.
- **Wo es kein Ziel gibt, ist der eigene Schnitt das Ziel** (v2.20.0,
  Gesundheit): Schritte, Energie und Schlaf laufen gegen den Durchschnitt
  der dreißig Tage davor, ohne Messlücken gerechnet. Eine fremde Zahl wie
  „10.000 Schritte“ wäre ein Ziel, das niemand gesetzt hat; der eigene
  Schnitt ist eine Zahl aus den Daten, und die Beschriftung nennt ihn
  („37 % von Ø 8.489“).
- **Wo es kein Ziel gibt und keins geben soll, gibt es keinen Ring**
  (v2.21.0, Ausgaben): Ausgaben haben kein Ziel, also steht die Heldenzahl
  dort ohne Ring. Verglichen wird mit dem Vormonat **bis zum selben Tag** --
  der ganze Vormonat gegen den angebrochenen hieß am 5. jeden Monat „−80 %“.
- **`.is-unvollstaendig`** macht die Spur gestrichelt. Ein Wert, zu dem
  Angaben fehlen, darf nicht aussehen wie einer, zu dem alle da sind.
- **Die runden Kappen werden abgezogen.** Der Bogen wird eine Strichbreite
  kürzer gezeichnet, als der Anteil lang ist — die beiden Kappen legen sie
  wieder drauf. Ohne den Abzug war jeder Ring gut vier Prozentpunkte zu voll
  und ab etwa 95 % von „geschafft“ nicht mehr zu unterscheiden. Ein Ring, der
  zu früh zugeht, nimmt der Zahl daneben das letzte Stück Weg.

## 8. Was wir nicht tun

- Kein Milchglas auf allem. Es bleibt der Navigationsleiste, Menüs und Overlays
  vorbehalten, wo Inhalt darunter durchscheint.
- Keine Emoji als Funktionsicons in neuen Komponenten. Emoji sind Nutzerdaten
  (Kategorie-Icons) oder Schmuck in Überschriften, nicht Bedienelemente.
- Keine zweite Variante einer bestehenden Komponente. Wer eine braucht,
  erweitert die vorhandene und trägt sie hier ein.
- Keine Farbe ohne Bedeutung.

---

## Migration

Die alten Token-Namen (`--surface`, `--border`, `--text-muted`, `--green-dark`
…) bleiben als Aliasse gültig und zeigen auf die neuen Werte. Sie verschwinden
Modul für Modul, während die Seiten auf die Komponenten umgestellt werden —
nicht in einem großen Schnitt, damit jede Etappe lauffähig bleibt.

Reihenfolge: **Fundament** (v1.55.0) → Startseite und Ausgaben → Gesundheit,
Sparziel, Notizen, Blog, Login. **Auffrischung** (v2.18.0): Lichteinfall,
Reiter, Blatt, Auftritt wirken auf allen Seiten; die Module ziehen danach
einzeln nach. **Neugestaltung** ab v2.19.0: Sparziel, Gesundheit und Ausgaben
bekommen je ein neues Grundkonzept mit Bühne und Heldenzahl; das Sparziel ist
das Muster, an dem die anderen sich ausrichten. **Die Startseite bleibt, wie
sie ist:** Kacheln je Modul und darüber zwei Zahlen. Eine Fassung mit einer
Karte und einer aktuellen Zahl je Modul wurde gebaut und vor dem Push
verworfen, weil dem Nutzer die bisherige besser gefiel.
