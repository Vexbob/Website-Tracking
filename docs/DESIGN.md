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
einmal definiert, und die Regeln unten sind eindeutig statt „je nach Theme".

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
- Schatten nur ab „schwebend" (`--shadow-float`) — und dort zusätzlich zur
  Haarlinie, nicht statt ihrer.
- Kein reines Schwarz und kein reines Weiß im Interface.

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
- **Modultöne**: Ausgaben Türkis, Gesundheit Rosa, Sparziel Grün, Notizen Blau,
  Blog Bernstein, Verwaltung Violett, Musik Spotify-Grün. Sie färben Modul-Icons,
  die aktive Diagrammreihe und kleine Identitätsmarken — nie ganze Flächen.
  Das Musik-Modul ist der Fall, an dem sich zeigt, wofür ein Modulton gut ist:
  seine Daten kommen aus dem Spotify-Datenexport, und `--m-musik` sagt das
  schneller als jede Beschriftung. Aufgehellt gegenüber dem Original, damit der
  Ton auch als Text auf dunklem Grund lesbar bleibt (6,4:1). Auch hier gilt die
  Grenze: Icon-Kachel, erste Diagrammreihe, ein Punkt neben „Quelle: Spotify" —
  keine grüne Fläche.
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
keinen Text. Hinter Zahlen liegt nie ein Verlauf.

**Alle vier sind einstellbar** (v1.74.0, erweitert in v1.78.0). In den
Einstellungen wählt man je ein Preset für die primäre Aktion
(`--grad-accent`), die Fortschrittsbalken (`--grad-progress`), die Zahlen und
Diagramme (`--figure`) und die Hintergrundlichter (`--backdrop`). Ein *Thema*
setzt alle vier auf einmal.

Bei den Zahlen und Diagrammen gilt eine Besonderheit, weil dort die
Modul-Identität hängt: der Standard heißt **„Modulton"** und definiert
`--figure` bewusst gar nicht. Jedes Modul fällt dann über
`var(--figure, var(--m-sparziel))` auf seine eigene Farbe zurück — Sparziel
grün, Ausgaben türkis. Erst wer ausdrücklich ein anderes Preset wählt,
überschreibt das. Identität ist damit der Standard, nicht die Ausnahme.

- Die Presets stehen als Tokens (`--g-…`, `--bd-…`) **ausschließlich** in
  `css/style.css`. Das Frontend setzt nur ein Attribut am `<html>`
  (`data-grad-action` und Geschwister), genau wie beim Theme — dadurch bleibt
  „keine Hex-Werte in JS" heil und ein Preset ist an einer Stelle definiert.
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
| Aktiv/Gedrückt | `transform: scale(.97)`, `--dur-1` |
| Ausgewählt | Akzent trägt die Bedeutung (Fläche `--accent-strong`, Text `--accent-ink`) |
| Fokus | `--focus-ring`, sichtbar nur bei `:focus-visible` |
| Deaktiviert | `opacity:.45`, `cursor:default`, keine Transformation |
| Lädt | Skeleton (`.skel`) statt Text; nie ein „Lade …" als Fließtext |

Berührungsziele auf Mobilgeräten sind mindestens 44 px hoch.

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
- Nichts bewegt sich beim reinen Betrachten. Was sich ohne Zutun bewegt, ist
  ein Fehler.
- `prefers-reduced-motion` schaltet alles ab — das ist bereits global gelöst.

## 6. Leere Zustände

Ein Muster für die ganze App (`.empty`): Zeichen, ein Satz, optional eine
Handlung.

- Der Satz sagt, **warum** es leer ist, nicht dass es leer ist.
  „Noch keine Kategorien. Beim ersten gescannten Bon legt der Parser sie selbst
  an." statt „Keine Daten".
- Genau eine Handlung, und nur wenn sie hier sinnvoll ist.
- Gestrichelte Kante, `--surface-2`, `--text-3`. Kein Bild, keine Illustration.
- Ein **Fehler** ist kein leerer Zustand: `.empty.is-error` zeigt die Meldung
  und einen „Erneut versuchen"-Knopf.

## 6a. Dateien ablegen

Eine Ablegefläche (`.dropzone`) trägt dieselbe gestrichelte Kante wie der leere
Zustand — die Aussage ist dieselbe: hier ist noch nichts, hier könnte etwas hin.

- Drei Zustände: **bereit**, **eine Datei schwebt darüber** (`.drag`, Akzent),
  **eine Datei liegt drin** (`.has-files`). Der letzte wechselt auf eine
  durchgezogene Kante in `--ok` — gestrichelt heißt „leer", und das stimmt dann
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
- Tooltip sieht aus wie ein schwebendes Element der App: `--surface-3`,
  Haarlinie, 12 px Radius — nicht wie Chart.js-Standard.
- **Ein Datum im Tooltip trägt immer die Jahreszahl**, auch wenn die Achse aus
  Platzgründen nur `05.09.` zeigt. Die ausgeschriebene Fassung kommt aus
  `VexCharts.fullDay/fullWeek/fullMonth` (`js/charts.js`).
- **Der Tooltip verschwindet, wenn man daneben tippt.** Auf dem Handy gibt es
  kein „Maus verlässt die Fläche"; `js/charts.js` erledigt das global für alle
  Diagramme. Deshalb gehört die Datei auf jede Seite mit einem Diagramm.
- **Die Durchschnitts-/Trendlinie liegt über der Wertlinie**: `order`
  `VexCharts.ORDER.TREND` gegen `VexCharts.ORDER.VALUE`. Chart.js zeichnet die
  kleinere `order` weiter vorn — unter einer gefüllten Wertlinie wäre die
  Trendlinie bei sprunghaften Daten unsichtbar.

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
Sparziel, Notizen, Blog, Login.
