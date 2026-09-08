/* changelog.js — v1.38.0
 * Statisch generierte Versions-Historie fuer den vertikalen Zeitstrahl,
 * der beim Klick auf .version-tag angezeigt wird.
 * Neue Releases OBEN einfuegen.
 *
 * Konvention seit v1.51.1 — damit die Liste lesbar bleibt:
 *   - Ein Eintrag = eine Version, hinter der etwas Erkennbares steht.
 *   - Ein bis fuenf Stichpunkte, je ein Satz. Was nur den Code betrifft,
 *     gehoert in den Commit, nicht hierher.
 *   - Eine Korrektur am selben Thema bekommt KEINEN eigenen Eintrag: sie hebt
 *     die Patch-Nummer des bestehenden Eintrags an und kommt als Stichpunkt
 *     dazu ("Nachgezogen: ..."). So bleibt APP_VERSION immer der oberste
 *     Eintrag, und aus einem Tag mit sieben Hotfixes werden nicht sieben
 *     Zeilen im Zeitstrahl.
 */
window.VEXBOB_CHANGELOG = [
    { v: 'v1.67.2', date: '2026-09-08', title: 'Musik-Modul und ein zusammenstellbarer Export', notes: [
        'Neues Modul „Musik“: die CSV aus dem Spotify-Export wird zum durchsuchbaren Hörregister mit Verlauf, Ranglisten und einem Filter, der für Überblick und Register derselbe ist.',
        'Der Import zeigt vor dem Schreiben, welche Blöcke er erkannt hat und welchen Zeitraum jeder ersetzen würde — derselbe Upload zweimal hintereinander bleibt dadurch folgenlos.',
        'Der Verlauf fasst nur nach oben zusammen und sagt es, wenn ältere Zeilen gröber vorliegen als die gewählte Stufe.',
        'Der Gesamt-Export kennt jetzt Tag, Jahr und „Automatisch“ je Modul, und die Spalten jeder Sektion lassen sich einzeln abwählen.',
        'Dateien werden überall über dieselbe Ablegefläche entgegengenommen; der Gesundheits-Import hatte bis jetzt seine eigene.',
        'Nachgezogen: Die Startseite blieb beim Laden bis zu vier Sekunden komplett unsichtbar — man sah nur den Hintergrund, nicht einmal die Navigationsleiste.',
        'Nachgezogen: Die Musikseite blieb ganz unsichtbar — sie hat als einzige Modulseite den Body nie freigegeben.',
    ]},
    { v: 'v1.66.0', date: '2026-09-08', title: 'Bild-Upload im Blog: die eigentliche Ursache', notes: [
        'Ein nicht lesbares Bild wurde stillschweigend als Rohdatei gespeichert — der Upload meldete Erfolg, der Browser konnte daraus aber nie ein Bild zeichnen.',
        'HEIC-Fotos vom iPhone kann der Server jetzt öffnen; vorher landete jedes davon in genau diesem stillen Rückfall.',
        'Ein fehlgeschlagener Upload sagt jetzt, woran es lag, und die Meldung bleibt stehen statt nach drei Sekunden zu verschwinden.',
    ]},
    { v: 'v1.65.0', date: '2026-09-07', title: 'Sicherheits-Durchsicht', notes: [
        'Ein Backup enthielt bei zwei Gesundheits-Tabellen die Zeilen ALLER Konten statt nur der eigenen — sie haben als einzige keine Zuordnung zum Nutzer und fielen deshalb durchs Raster.',
        'Beim Wiederherstellen wurden die Spaltennamen ungeprüft aus der hochgeladenen Datei in die Datenbank-Abfrage übernommen; sie werden jetzt gegen das echte Schema gefiltert.',
        'Fehlermeldungen von Bereitschaftsprüfung und Wiederherstellung nennen nach außen keine Server-Interna mehr — der volle Text steht im Log.',
        'Die automatische API-Dokumentation ist nicht mehr öffentlich erreichbar (ENABLE_DOCS=1 schaltet sie zurück).',
    ]},
    { v: 'v1.64.0', date: '2026-09-07', title: 'Statistik und Produkte sind eine Seite', notes: [
        'Kategorien, Läden, Produkte und Wochentage stehen jetzt als vier Aufschlüsselungen derselben Summe unter einem Umschalter — Zeitraum, Gesamtsumme und Verlauf darüber bleiben beim Wechsel stehen.',
        'Die Produkt-Seite ist damit weg: sie beantwortete dieselbe Frage nach Artikel und hatte dafür einen zweiten Zeitraum-Filter, den man getrennt einstellen musste.',
        'Die Produkt-Tabelle liest jetzt eine Zusammenfassungszeile statt vier Kacheln, deren Gesamtsumme ohnehin schon oben stand.',
        '„Top-Artikel“ ist entfallen — die vollständige Produkt-Tabelle sagt dasselbe.',
    ]},
    { v: 'v1.63.0', date: '2026-09-07', title: 'Bilder im Blog funktionieren', notes: [
        'Der Bild-Upload im Blog-Editor lief seit jeher in eine Anmeldefehler-Meldung — er hat den Anmelde-Schlüssel unter einem Namen gesucht, den es nicht gibt.',
        'Hochgeladene Bilder werden jetzt auch angezeigt: ihre Adresse zeigte auf den Webserver statt auf das Backend, das die Bilder ausliefert.',
        'Rechtsklick auf ein Bild löscht es aus Beitrag und Datenbank — der Bildtitel hat das versprochen, gebaut war es nie.',
        'Schlägt ein Upload fehl, steht jetzt der Grund da statt einer HTTP-Nummer.',
    ]},
    { v: 'v1.62.0', date: '2026-09-07', title: 'Statistik neu, Produkte sortierbar, Blog schreibt sich selbst', notes: [
        'Die Ausgaben-Statistik hat jetzt eine Hauptzahl statt vier gleich lauter Kacheln, und Kategorien wie Läden stehen als Rangliste statt als Ringdiagramm mit Tabelle darunter.',
        'Der Zeitverlauf zeigt Tage ohne Einkäufe endlich als Lücke — vorher standen die Balken gleichmäßig verteilt und der Ø mittelte über Einkaufstage statt über Kalendertage.',
        'Dahinter liegt neu die Vorperiode als feine Linie: der Balken allein beantwortet nicht, ob das viel ist.',
        'Die Produkt-Tabelle lässt sich über jede Spalte sortieren.',
        'Auf der Blog-Seite steht ein Knopf für einen neuen Beitrag; Fotos und Rezeptbuch sind entfernt.',
    ]},
    { v: 'v1.61.0', date: '2026-09-07', title: 'Leiste ausblendbar, Export-Fehler behoben', notes: [
        'In der Navigationsleiste am Rechner lassen sich einzelne Module jetzt ausblenden — über das Punkte-Menü bleiben sie erreichbar.',
        'Im Export hat die Wahl einer Zusammenfassung das ganze Modul abgehakt; jetzt bleibt die Auswahl stehen.',
        'Die Aktivitäts-Zahlen unter dem aktuellen Sparziel sind raus.',
        'Workouts nennen als Kopfzahl die Anzahl statt der Gesamtzeit — die steht klein darunter.',
        'Der farbige Strich über den Kennzahlen im Ausgaben-Dashboard ist weg.',
    ]},
    { v: 'v1.60.2', date: '2026-09-07', title: 'Zeitfilter hinter einem Knopf, Export zum Zusammenstellen', notes: [
        'Der Zeitraum liegt überall hinter einem Knopf, der den aktuellen Stand benennt — 7/30/90/365 Tage, Gesamt und ein eigener Von/Bis-Zeitraum.',
        'Im Export wählst du jetzt aus, welche Module und Sektionen hinein sollen, und fasst jedes Modul einzeln wochen- oder monatsweise zusammen.',
        'Eine Vorschau zeigt vorher, wie viele Zeilen je Sektion herauskommen, wie groß die Datei wird und wie ihre ersten Zeilen aussehen.',
        'In den Einstellungen lässt sich festlegen, mit welchem Zeitraum Statistik- und Gesundheitsseiten aufmachen.',
        'Nachgezogen: Die Modul-Leiste stand auf sechs Seiten links vom Zurück-Link, der öffentliche Blog warf Ausgeloggte zum Login, die Produkte-Seite hat jetzt denselben Zeitraum-Knopf, und beim Durchziehen auf dem Handy bleibt der Tageswert beim Scrollen stehen.',
    ]},
    { v: 'v1.59.0', date: '2026-09-07', title: 'Module offen in der Leiste, hellere Akzente', notes: [
        'Am Rechner stehen die Module jetzt offen in der Navigationszeile statt hinter dem Punkte-Symbol — was nicht mehr hineinpasst, rutscht von selbst ins Menü.',
        'Neue Seite „Einstellungen“: Reihenfolge der Leiste am Rechner, Belegung der Tab-Leiste am Handy und der Gesamt-Export an einem Ort.',
        'Die Akzentfarben sind heller und wärmer; ausgewählte Flächen tragen dafür dunkle statt weißer Schrift.',
        'Beide Heatmaps sind raus — die Serien- und Aktivitätszahlen aus der Sparziel-Heatmap stehen jetzt auf dessen Dashboard.',
        'In Diagrammen trägt der Tooltip die Jahreszahl, verschwindet beim Tippen daneben, und die Ø-Linie liegt über der Wertlinie.',
    ]},
    { v: 'v1.58.1', date: '2026-09-07', title: 'Gesundheit, Sparziel, Notizen und Blog ziehen nach', notes: [
        'Die restlichen Module laufen jetzt über dieselben Farben und Ebenen wie der Rest — damit ist die Umstellung auf die neue Designsprache überall durch.',
        'Auch ihre Diagramme folgen den Regeln: Achsen und Gitter aus den Tokens, Tooltips wie schwebende Elemente der App, kein senkrechtes Gitter.',
        'Statt „Lade …“ erscheinen jetzt Skeletons, und die fünfzehn verschiedenen Leer-Zustände sehen endlich gleich aus.',
        'Der Login trägt den Verlauf der Marke, und Toasts kommen überall aus derselben Quelle.',
        'Nachgezogen: Auch Gesundheit, Sparziel, Notizen und der Blog-Admin fragen jetzt im gestalteten Fenster nach, statt das graue Systemfenster zu öffnen.',
    ]},
    { v: 'v1.57.0', date: '2026-09-07', title: 'Ausgaben-Modul fertig umgestellt', notes: [
        'Die nativen Browser-Dialoge sind weg: Löschen fragt jetzt in einem gestalteten Fenster nach, und neue Läden oder Kategorien legst du im selben Stil an statt in einem grauen Systemkasten.',
        'Bon-Formular und Bon-Ansicht folgen der Designsprache — ruhige Flächen ohne Schatten, der Akzent nur auf der Hauptaktion, das Foto kleiner, damit die Positionen darunter sichtbar bleiben.',
        'Auf dem Handy ist jede Position eine Karte statt gequetschter Rasterzellen.',
        'Produkte, Kategorien, Läden, Marken und Duplikate teilen sich jetzt dieselben Bausteine und Statusfarben.',
    ]},
    { v: 'v1.56.0', date: '2026-09-07', title: 'Startseite und Ausgaben im neuen Gewand', notes: [
        'Die Startseite zeigt jetzt Zahlen statt nur Kacheln: was dieser Monat gekostet hat, im Vergleich zum Vormonat, und wie weit das Sparziel ist.',
        'Im Ausgaben-Dashboard gibt es eine Hauptzahl statt sechs gleich lauter Kacheln — der laufende Monat groß, alles andere ordnet sich darunter.',
        'Die Diagramme folgen der Designsprache: kein senkrechtes Gitter, keine Achsenrahmen, Tooltips wie schwebende Elemente der App, Balken mit Radius und Flächen als Verlauf.',
        'Blog, Export und Verwaltung standen in drei Abschnitten mit je einer Kachel — daraus ist eine Zeile geworden.',
    ]},
    { v: 'v1.55.0', date: '2026-09-07', title: 'Designsprache: Fundament', notes: [
        'Vexbob hat jetzt eine geschriebene Designsprache — docs/DESIGN.md legt Ebenen, Textrollen, Zustände, Bewegung, leere Zustände und Diagramme fest, /design.html zeigt jeden Baustein in jedem Zustand.',
        'Nur noch dunkel: Umschalter, helle Farbwerte und Druckansicht sind raus, dadurch ist jedes Token einmal definiert statt zweimal.',
        'Neue Tokens für vier Flächenebenen, vier Textrollen mit gemessenen Kontrasten, Modultöne, Statusfarben, drei Bewegungsdauern und eine Diagrammpalette; die alten Namen bleiben als Aliasse gültig, damit keine Seite bricht.',
        'Erste Komponenten mit allen Zuständen: Knopf, Chip, Karte, Zeile, leerer Zustand, Skeleton, Statusmarke, Icon-Kachel — und die vier Toast-Varianten sehen ab sofort gleich aus.',
        'Login und Aktivierung haben endlich App-Icon, Manifest und passende Statusleistenfarbe.',
    ]},
    { v: 'v1.54.0', date: '2026-09-07', title: 'Statistik aufgeräumt, Marken aus der Leiste', notes: [
        'Die Erkenntnis-Karten der Statistik stehen jetzt ganz unten statt zwischen Kennzahlen und Diagrammen — der erste Bildschirm zeigt wieder Zahlen und Verlauf.',
        'Marken sind aus der Ausgaben-Leiste raus, weil auf Kassenbons selten eine Marke steht; die Seite bleibt unter /ausgaben/marken.html erreichbar und alle Daten bleiben.',
        'Der KI-Prompt schickt nicht mehr bis zu 800 Markennamen mit — erkannte Marken werden weiterhin gespeichert.',
    ]},
    { v: 'v1.53.0', date: '2026-09-07', title: 'Kategorien und Läden neu, Zusammenführen überall erreichbar', notes: [
        'Kategorien und Läden sind keine Wand aus Formularfeldern mehr, sondern Karten mit Nutzung — wie viele Positionen und wie viel Geld daran hängen —, dazu Suche, Sortierung und ein Sammel-Löschen für nie benutzte Einträge.',
        'Beide Seiten haben jetzt eine echte Überschrift mit einem Satz Erklärung, bearbeitet wird im Dialog statt in dauerhaft offenen Zeilen.',
        'Produkte zusammenführen geht jetzt von jedem Produkt aus: Zeile anklicken, „Mit anderem Produkt zusammenführen“ — mit Suche über alle Produkte, unabhängig von den Vorschlägen.',
        'Eine bestehende Gruppe öffnet denselben Dialog: Name ändern, einzelne Schreibweisen abwählen oder ganz auftrennen.',
        'Helle Ansicht: blasse graue Meta-Texte und weiße Schrift auf grünen und türkisen Flächen erfüllen jetzt WCAG-AA.',
    ]},
    { v: 'v1.52.2', date: '2026-09-07', title: 'Bon-Scan: Typ automatisch, Zahlungsart und Einheiten raus', notes: [
        'Die Zahlungsart ist weg — beim Scannen, beim manuellen Eintrag und in der Bon-Ansicht.',
        'Der KI-Parser entscheidet den Beleg-Typ jetzt selbst und darf einen eigenen vergeben (z.B. „Arztrechnung“), der danach überall zur Auswahl steht.',
        'Positionen haben keine Einheit mehr: die Menge ist eine reine Stückzahl und steht nur da, wenn ein Artikel mehrfach gekauft wurde — Gewicht und Packungsgröße bleiben im Bon-Text.',
        'Zusammenführen-Vorschläge bei den Produkten sind bearbeitbar: Name ändern und einzelne Schreibweisen abwählen, bevor du zusammenführst.',
        'Der Parser-Prompt wurde aufgeräumt, u.a. nutzen seine Beispiele jetzt die Kategorienamen aus der eigenen Liste.',
        'Nachgezogen: Alte Positionen, in denen noch ein Gewicht als Menge stand („500 g“), zeigen keine erfundene Stückzahl an.',
        'Nachgezogen: Auch eine bestehende Zusammenführung lässt sich bearbeiten — ein Klick auf das 🔗 in der Produktliste öffnet Name und Mitglieder.',
        'Nachgezogen: Der eingetippte Gruppenname stand vorher nur im Schlüssel; die Produktliste zeigte weiter den Namen der neuesten Variante.',
    ]},
    { v: 'v1.51.1', date: '2026-09-06', title: 'Changelog zusammengefasst und gekürzt', notes: [
        'Der Zeitstrahl hatte 86 Einträge, darunter ein Tag mit sieben Hotfix-Versionen — ein README-Aufräumen wog darin so viel wie ein neues Modul. Folgekorrekturen stehen jetzt als „Nachgezogen“-Stichpunkt in dem Eintrag, zu dem sie gehören; übrig bleiben 39 Versionen, hinter denen etwas Erkennbares steht.',
        'Die Texte der letzten Releases sind auf ein bis fünf Stichpunkte à einem Satz gekürzt, ältere Einträge bleiben im Wortlaut. Künftig hebt eine Korrektur die Patch-Nummer des bestehenden Eintrags an, statt eine eigene Zeile zu bekommen.',
    ]},
    { v: 'v1.51.0', date: '2026-09-06', title: 'Tab-Leiste frei belegbar, Schlaf-Streuung in Stunden', notes: [
        'Die Leiste unten auf dem Handy war fest auf vier Module verdrahtet. Jetzt wählst du zwei bis sechs selbst aus und bestimmst die Reihenfolge — im Modul-Switcher unter „Tab-Leiste anpassen“.',
        'Zur Auswahl stehen alle Module des Kontos, auch Gesundheit, Blog und User-Verwaltung; jedes mit eigenem Icon. Die Belegung hängt am Konto, nicht am Gerät.',
        'Schlaf: Die Streuung neben typischer Zubettgeh- und Aufstehzeit steht jetzt in Stunden statt in Minuten — „± 1,3 h“ statt „± 78 min“.',
    ]},
    { v: 'v1.50.0', date: '2026-09-06', title: 'Workouts: beide Exportvarianten werden zu einem Training zusammengeführt', notes: [
        'Auto Health Export liefert dasselbe Workout in zwei Ausprägungen mit je eigener ID: die eine bringt Puls und Minutenreihe, die andere Schwimmzüge, Kadenz und Höhenmeter. Zugeordnet wird jetzt über Typ und Startzeit statt über die ID — vorher stand jedes Training doppelt und halb leer in der Liste.',
        'Einheiten werden dabei geradegezogen: dieselbe Bahn kommt je nach Variante als 1,825 km oder als 1825 m an. Migration 033 führt bestehende Dubletten zusammen und korrigiert Distanzen, die als Meter gespeichert wurden.',
        'Neu im aufgeklappten Workout: der Pulsverlauf je Minute, die Erholung danach als eigene Linie. Dazu eine Min-Puls-Kachel.',
        'Der Roh-Payload im Import-Protokoll lädt als .txt statt .bin und lässt sich ohne Umbenennen öffnen.',
    ]},
    { v: 'v1.49.0', date: '2026-09-06', title: 'Beta-Strecke „Apple Health per iPhone-Kurzbefehl“ wieder entfernt', notes: [
        'Die zweite Importstrecke aus v1.47.0 ist vollständig zurückgebaut. Der Grund: Das Problem lag nie am Sync, sondern an Auto Health Export selbst — die App exportiert die sportartspezifischen Zusatzmetriken nicht, sobald mehrere Workout-Typen zusammen exportiert werden.',
        'Migration 032 löscht die Beta-Tabelle. Geblieben ist das größere Import-Protokoll mit 1000 statt 200 Aufrufen je Nutzer.',
    ]},
    { v: 'v1.47.0', date: '2026-09-05', title: 'Gesundheit: zweiter Importweg per iPhone-Kurzbefehl (Beta)', notes: [
        'Ein Kurzbefehl schickt Werte an einen eigenen, sehr toleranten Endpoint mit eigener Tabelle; die bestehenden Gesundheitsdaten bleiben unangetastet. Dazu ein Beta-Reiter, der die Aufrufe roh zeigt.',
        'Nachgezogen: CSV mit Kopfzeile im Import, Import-Protokoll auf 1000 Aufrufe, Roh-Payload als .txt. In v1.49.0 wurde die Strecke wieder entfernt.',
    ]},
    { v: 'v1.46.0', date: '2026-09-04', title: 'Einheitliche Zeitfilter, Schlaf in einem Diagramm', notes: [
        'Zeitraum-Filter sind überall dieselben: 7 Tage · 30 Tage · 90 Tage · 1 Jahr · Gesamt.',
        'Schlaf: Phasen und Schlaffenster stecken in EINEM Diagramm — je Nacht ein Balken auf der 24-Stunden-Achse (18:00 bis 18:00), die Phasen darin mit ihrer echten Dauer. Eine Nacht, die über die Kante läuft, wird oben in derselben Spalte weitergezeichnet.',
        'Unter dem Diagramm stehen typische Zubettgeh- und Aufstehzeit mit ihrer Streuung. Nächte ohne Zeitstempel bleiben aus dem Diagramm draußen, zählen aber in die Ø-Werte.',
        'Vitalwerte: Diagramme per Drag & Drop anordenbar, Reihenfolge am Konto (Migration 030). Beim Zeitraumwechsel bleiben sie stehen und animieren, statt hinter „Lade …“ zu verschwinden.',
        'Nachgezogen: Sparziel-Export mit Typ und Kontostand je Ziel, user_prefs im Backup.',
    ]},
    { v: 'v1.45.0', date: '2026-09-04', title: 'Jede Vitalwert-Metrik mit eigenem Diagramm, neues Schlaffenster', notes: [
        'Vitalwerte: Jede Metrik hat ihr eigenes Diagramm — kleiner, dafür alle gleichzeitig sichtbar, jeweils mit Kennzahl, Min/Max und gleitender Ø-Linie. Vorher musste man sich durch eine Kachelreihe klicken.',
        'Schlaf: Statt einer Doppel-Punktwolke ist jede Nacht ein Balken vom Zubettgehen bis zum Aufstehen auf einer Uhrzeit-Achse. Fenster und Phasen sitzen in einer Karte untereinander.',
        'Die Phasen wandern bewusst nicht in den Fenster-Balken: Apple liefert je Nacht nur ihre Summen, nicht ihre zeitliche Lage — auf einer Uhrzeit-Achse würden sie eine Reihenfolge behaupten, die in den Daten nicht steht.',
    ]},
    { v: 'v1.44.0', date: '2026-09-04', title: 'Schlaf als eigene CSV, drei neue Vitalwerte', notes: [
        'Auto Health Export legt den Schlaf als eigene CSV ab; dieses Format wird jetzt am Header erkannt. Das Nacht-Datum kommt aus der Datumsspalte statt aus dem Startzeitpunkt — sonst überschreiben Nächte, die vor Mitternacht beginnen, die Vornacht.',
        'Die geschlafene Zeit kommt aus „Gesamtschlaf“ statt aus „Schlafend“: Letzteres weist nur den Anteil ohne Phasen-Zuordnung aus und lag in der Beispielwoche bei 0,0–1,3 h statt der tatsächlichen 4,6–10,1 h.',
        'Drei neue Vitalwerte: Blutsauerstoff, Geh-/Laufstrecke und Gehgeschwindigkeit. Der Vitalwerte-Tab zeigt jetzt alle Metriken statt nur der ersten acht.',
    ]},
    { v: 'v1.43.0', date: '2026-09-04', title: 'Abgeschlossene Sparziele verschwinden wirklich, Workout-Kennzahlen', notes: [
        'Ein abgeschlossenes Sparziel wird gelöscht statt auf 0 zurückgesetzt, und das automatische „Neues Sparziel“ über 100 € ist raus. Ist kein Ziel aktiv, laufen die Belohnungen in den Puffer — das Dashboard zeigt dann ihn statt eines 0-%-Rings.',
        'Der Tab „Ideen & Ziele“ ist neu gebaut: Kennzahlen-Leiste, Puffer-Karte, Sparziel-Karten mit Fortschritt, getrennte Abschnitte für Wunschliste und Ideen. „→ Sparziel“ übernimmt Name und Preis eines Wunsches.',
        'Workouts: Kennzahlen (Gesamtzeit, Ø Dauer, Ø Kalorien) mit eigenem Zeitraum-Filter.',
        'Der Ø Puls stand bei 8 bpm — der CSV-Import hielt die HRV-Spalte (ms) für die Puls-Spalte. Unplausible Werte werden jetzt schon beim Schreiben verworfen, Migration 029 räumt die Altlasten weg.',
    ]},
    { v: 'v1.42.0', date: '2026-09-03', title: 'Preisverlauf entfernt, Produkte gruppieren jetzt über Läden hinweg', notes: [
        'Die Preisverlauf-Seite und der normierte Preisvergleich sind raus. Er hat Artikel miteinander verrechnet, deren Einheiten gar nicht vergleichbar waren: fehlte die Mengeneinheit oder stand auf dem Bon "1 Pack" statt "500 g", landete ein €/Stück-Wert im selben Ø wie die €/kg-Werte — samt erfundener Preissprünge und falschem "günstigster Laden"-Ranking.',
        'Die Produkte-Seite bleibt und zeigt jetzt echte Zahlen: tatsächlich bezahlte Summe statt hochgerechnetem Ø-Einheitspreis, und pro Produkt ALLE Läden nebeneinander statt nur den letzten.',
        'Neu: Zusammenführen-Vorschläge. "Gouda", "Gouda jung" und "Goudakäse" waren drei Zeilen, weil jeder Laden anders auf den Bon druckt. Der Server erkennt solche Schreibvarianten (Präfix bzw. enthaltene Wortmenge — nie über ein zufällig geteiltes Adjektiv) und schlägt sie zum Zusammenführen vor; ein Klick schreibt allen Positionen dieselbe Gruppe, dauerhaft auch für künftige Käufe. Abgelehnte Vorschläge kommen nicht wieder (Migration 028).',
        'Import: Mengeneinheiten gehen nicht mehr verloren. Lieferte die KI "Haferflocken 500g" nur im Namen, hat der Parser das "500g" aus dem Namen geschnitten und weggeworfen — jetzt landet es in Menge/Einheit. Synonyme wie Liter, Gramm, Stück, Packung, Rolle oder Dose werden zugeordnet statt still verworfen.',
        '"Alle neu parsen" ist von der Preisverlauf- auf die Produkte-Seite umgezogen; der Bon-Toggle heißt jetzt "aus der Produktliste ausblenden" statt "aus dem Preisvergleich".',
    ]},
    { v: 'v1.41.0', date: '2026-09-03', title: 'Log zeigt jede Wertänderung an Achievements', notes: [
        'Bisher landete eine Änderung am Meilenstein-Ziel nur dann im Aktivitäts-Log, wenn sie eine Meilenstein-Schwelle überschritten hat — der "+x"-Button und das manuelle Setzen des Werts haben darunter nichts hinterlassen. Jede Änderung wird jetzt protokolliert (neue Tabelle achievement_progress_logs, Migration 027).',
        'Neuer Log-Typ "Fortschritt" mit eigenem Filter-Chip: zeigt Vorher → Nachher und in der Betragsspalte die Änderung selbst (z.B. "+2,5 km"). Ausgezahlt wird weiterhin nur beim Meilenstein, diese Zeilen tragen keinen Betrag.',
        'Notizen sind wie bei allen anderen Log-Einträgen möglich. Zurücknehmen lässt sich die jeweils letzte Änderung eines Ziels — sie setzt den Wert wieder auf den Stand davor; hat die Änderung einen Meilenstein ausgelöst, geht das über den Meilenstein-Eintrag.',
        'Nachgezogen: Log-Notizen brechen auf dem Handy nicht mehr auf ein Zeichen pro Zeile um.',
    ]},
    { v: 'v1.40.0', date: '2026-09-02', title: 'Gesundheit: Import-Protokoll mit Payload-Download', notes: [
        'Jeder automatische Sync der Auto-Health-Export-App wird jetzt mit seinem Roh-Payload gespeichert (neue Tabelle health_import_log, Migration 025).',
        'Neue Karte "Import-Protokoll" in den Gesundheits-Einstellungen: Zeitpunkt, Format, Dateiname, Größe, Ingest-Ergebnis und Vorschau je Aufruf — plus Download der Originaldatei zum Abgleich mit den importierten Werten.',
        'Einzelne Einträge löschbar, Protokoll komplett leerbar. Aufbewahrt werden die letzten 200 Aufrufe je Nutzer, Payloads über 5 MB werden gekürzt (ENV HEALTH_IMPORT_LOG_KEEP / HEALTH_IMPORT_LOG_MAX_BYTES).',
        'Nachgezogen: Schwimm-Pace in min/100 m und korrigierte Distanz-Einheit, Gesamtschlafzeit im Schlaf-Diagramm, Nächte unter 1 h zählen nicht mehr in den Ø, Einkäufe bleiben bei Wochen-/Monats-Aggregation im Gesamt-Export, README mit einzeln beschriebenen Funktionen.',
    ]},
    { v: 'v1.39.0', date: '2026-09-01', title: 'Duplikate: eigener Tab + ausblendbare Vorschläge', notes: [
        'Neue Seite "♻️ Duplikate" im Ausgaben-Subnav statt Karte auf dem Dashboard.',
        'Jeder Vorschlag hat jetzt ein "✕" zum dauerhaften Ausblenden, ohne die Bons zu löschen oder zusammenzuführen (neue Tabelle dismissed_expense_duplicates, Migration 024).',
        'Nachgezogen: Ø-Linie der Vitalwerte als gleitender Trend, Messlücken raus aus Ø/Min/Max, doppelter Schlaf-Insight entfernt.',
    ]},
    { v: 'v1.38.0', date: '2026-09-01', title: 'Ausgaben-UX + Versions-Zeitstrahl', notes: [
        'Filter im Ausgaben-Dashboard hinter einem Popover versteckt (Suche + Presets bleiben sichtbar).',
        'Aktive Filter erscheinen als Zahl-Badge am Filter-Button.',
        '"+ Neuer Bon" oeffnet ein Modal direkt im Dashboard statt einer eigenen Seite.',
        'Klick auf die Versionszahl unten rechts oeffnet einen vertikalen Zeitstrahl mit allen Releases.',
        'Nachgezogen: Hotfix für das nicht ladende Ausgaben-Dashboard, Neuer-Bon-Tiles im Homepage-Design, versteckte File-Inputs repariert, Ausgaben-Übersicht auf 14 Tage mit Aufklappen, README aufgeräumt und überarbeitet.',
    ]},
    { v: 'v1.37.0', date: '2026-08-31', title: 'Toast/Confirm, Mobile Tab-Bar, SVG-Theme-Icon', notes: [
        'Modul-uebergreifender Toast/Confirm-Layer, Bottom-Tab-Bar auf Mobile.',
        'Nachgezogen: Zeitraum und Aggregation im Gesamt-Export, Aggregation korrigiert.',
    ]},
    { v: 'v1.36.0', date: '2026-08-29', title: 'Design-Refresh (Glass Navbar, Hero, iOS-Tabs)', notes: [
        'Nachgezogen: Schlaf-Fix und Icon-only-Modul-Switcher.',
    ]},
    { v: 'v1.35.0', date: '2026-08-29', title: 'Migration-Checksums, Dry-Run, Sentry-Hook', notes: [] },
    { v: 'v1.34.0', date: '2026-08-29', title: 'Observability + Readiness-Probe', notes: [] },
    { v: 'v1.33.0', date: '2026-08-29', title: 'Backend-Haertung (Pool-Race, Timing-Attack, JSON)', notes: [] },
    { v: 'v1.32.0', date: '2026-08-29', title: ':where()-Form-Base, .btn-Utility, weg mit !important', notes: [] },
    { v: 'v1.31.0', date: '2026-08-29', title: 'CSS-Auslagerung, Print/Touch/SEO', notes: [] },
    { v: 'v1.30.0', date: '2026-08-29', title: 'P0/P1 CSS-Fixes (A11y, FOUC, Design-Tokens)', notes: [] },
    { v: 'v1.29.0', date: '2026-08-28', title: 'CSV-Import 1:1, Rescale entfernt', notes: [
        'Nachgezogen: Schlaf-KPIs bei fehlenden Werten korrigiert, CSV-Exports mit UTF-8-BOM.',
    ]},
    { v: 'v1.28.0', date: '2026-08-28', title: 'Health-Datensaetze loeschen', notes: [
        'Nachgezogen: Startup-Crash durch slowapi behoben.',
    ]},
    { v: 'v1.27.0', date: '2026-08-28', title: 'Health-CSV im Gesamt-Export', notes: [] },
    { v: 'v1.26.0', date: '2026-08-28', title: 'Uebertrag vom Puffer aufs Sparziel', notes: [] },
    { v: 'v1.25.0', date: '2026-08-28', title: 'Health-Seite modernisiert', notes: [
        'Nachgezogen: Workouts inline statt im Modal, Empty-State für Schlaf.',
    ]},
    { v: 'v1.24.0', date: '2026-08-28', title: 'CSV-basierter Health-Import', notes: [] },
    { v: 'v1.23.0', date: '2026-08-28', title: 'Gesamt-Export (Sparziel+Ausgaben+Health)', notes: [
        'Nachgezogen: manueller JSON-Import für Gesundheitsdaten, Hotfix für den Crash-Loop im health_router.',
    ]},
    { v: 'v1.22.0', date: '2026-08-28', title: 'Health-Modul (Auto Health Export Sync)', notes: [
        'Nachgezogen: das Modal für den API-Key blockierte Klicks.',
    ]},
    { v: 'v1.21.0', date: '2026-08-25', title: 'Duplikat-Erkennung + SW-Cache-Fix', notes: [
        'Nachgezogen: Service-Worker-Auto-Update, Blog im Menü, GZip, Fixes für HTTP 500 und die unsichtbare Produkte-Seite.',
    ]},
    { v: 'v1.20.0', date: '2026-08-25', title: 'Produkt-Seite Bugfix + Server-Filter', notes: [] },
    { v: 'v1.19.0', date: '2026-08-25', title: 'Blog, Wochenziel-History, Produkt-Statistik', notes: [] },
    { v: 'v1.12.0', date: '2026-08-14', title: 'Item-Split, Preisvergleich pro Laden, ~70 Kategorien', notes: [] },
    { v: 'v1.11.0', date: '2026-08-14', title: 'Reparse-All, 3-Spalten-Items, Produkt-History-Modal', notes: [] },
    { v: 'v1.10.0', date: '2026-08-14', title: 'Suche, Presets, Undo/Swipe, Preis-Chart, main.py aufgeteilt', notes: [] },
    { v: 'v1.9.0', date: '2026-08-14', title: 'Preisverlauf-Tab, globale Subnav', notes: [] },
    { v: 'v1.8.2', date: '2026-08-14', title: 'AI liefert category_name, Gemini-Default, Dashboard-Inline-Detail', notes: [] },
    { v: 'v1.7.1', date: '2026-08-13', title: 'SW-redirect-fix (iOS), expense_type, BILLA-Parser', notes: [] },
    { v: 'v0.x', date: '2026-08-08', title: 'Projekt-Setup + erste Version', notes: [
        'Initial commit, erste AI-BON-Erkennung, mehrere Parser-Iterationen.',
    ]},
];
