# Apple Health per iPhone-Kurzbefehl (Beta)

Zweiter, unabhängiger Weg neben der App *Health Auto Export*. Ein Kurzbefehl auf
dem iPhone schickt einmal täglich die **letzten drei Tage** an Vexbob. Drei Tage
statt einem, damit ein ausgefallener Lauf vom nächsten nachgeholt wird — derselbe
Tag kommt also mehrfach an und **überschreibt sich selbst**, statt Dubletten
anzulegen.

Die Daten landen in einer eigenen Tabelle (`health_shortcut_samples`), fließen in
**keine** Auswertung ein und sind nur im Beta-Reiter des Gesundheits-Moduls roh
sichtbar. Die bestehende Auto-Health-Export-Strecke bleibt davon unberührt.

> **Status: Versuch.** Ob und wie zuverlässig der Kurzbefehl auslöst, in welchem
> Format Kurzbefehle die Werte liefert und wie die Zeitstempel aussehen, ist
> offen. Der Endpoint ist deshalb bewusst tolerant gebaut und beantwortet jeden
> Aufruf mit einem Bericht darüber, was angekommen und was übersprungen wurde.
> Rechne damit, dass wir das Format nach den ersten Läufen nochmal anpassen.

---

## Endpoint

```
POST https://vexbob-production.up.railway.app/api/health/shortcut/import
Authorization: Bearer <dein API-Key>
```

Optional `?metric=steps` an der URL — setzt die Metrik für alle Punkte, die
selbst keine mitbringen. Damit reicht als Body eine Zeile `2026-09-05;8421`.

**Der Endpoint antwortet immer mit HTTP 200**, außer bei ungültigem Key (401)
oder zu vielen Aufrufen (429, Grenze 60/Stunde). Auch ein leerer oder unlesbarer
Body ist kein Fehler, sondern eine Antwort, die sagt, was fehlt. Grund: ein 4xx
würde den Kurzbefehl mit einem Fehler abbrechen lassen, bevor der Antworttext
sichtbar wird — und genau der ist beim Einrichten das Werkzeug.

---

## Schritt 1 — API-Key erzeugen

Vexbob → **Gesundheit → ⚙️ Einstellungen → „+ Key erzeugen"**, Bezeichnung z.B.
`Kurzbefehl`.

Der Klartext-Key wird **nur einmal** angezeigt — sofort kopieren. Es ist derselbe
Key-Typ wie für Auto Health Export; ein eigener Key mit eigener Bezeichnung ist
trotzdem sinnvoll, weil er sich dann einzeln widerrufen lässt, ohne die
bestehende Anbindung abzuschalten.

---

## Schritt 2 — Kurzbefehl bauen

Die Aktionsnamen unten sind die deutschen Bezeichnungen; je nach iOS-Version
weichen sie leicht ab, deshalb steht der englische Name daneben.

### Variante A — Textzeilen (empfohlen für den ersten Versuch)

Am wenigsten fummelig: kein verschachteltes JSON, nur Text.

1. **`Wiederholen` (Repeat) — 3 mal.** Alles Folgende bis Punkt 7 kommt *in* die
   Schleife.
2. **`Zahl berechnen` (Calculate):** `Wiederholungsindex − 1` → ergibt den Versatz
   0, 1, 2. Als Variable **Versatz** sichern.
3. **`Datum` (Date)** → *Aktuelles Datum*, danach **`Datum anpassen` (Adjust
   Date)**: *Subtrahieren*, **Versatz**, *Tage*. Als Variable **Tag** sichern.
4. **`Datum formatieren` (Format Date)** auf **Tag**: Datumsformat
   *Benutzerdefiniert*, Format `yyyy-MM-dd`. Als Variable **Datumstext** sichern.
5. **Tagesgrenzen bauen** — zweimal `Text` + `Datum`:
   - `Text`: `<Datumstext> 00:00:00` → **`Datum`**-Aktion darauf → Variable **Von**
   - `Text`: `<Datumstext> 23:59:59` → **`Datum`**-Aktion darauf → Variable **Bis**
6. **`Gesundheitsproben suchen` (Find Health Samples):**
   - Typ: **Schritte**
   - Filter: *Startdatum* — *ist im Bereich* — **Von** bis **Bis**
   - danach **`Statistik berechnen` (Calculate Statistics)**: *Summe* über *Wert*.
     Als Variable **Summe** sichern.
7. **`Text`** mit genau dem Inhalt `<Datumstext>;<Summe>` → **`Zur Variablen
   hinzufügen` (Add to Variable)**, Variable **Zeilen**.
8. *(nach der Schleife)* **`Text aus Liste verbinden` (Combine Text)** auf
   **Zeilen**, Trennzeichen *Neue Zeilen*.
9. **`Inhalte von URL abrufen` (Get Contents of URL):**
   - URL: `https://vexbob-production.up.railway.app/api/health/shortcut/import?metric=steps`
   - Methode: **POST**
   - Header: `Authorization` = `Bearer hae_…` (dein Key aus Schritt 1)
   - Anfragetext: **Datei** → der verbundene Text aus Schritt 8
10. **`Wörterbuch-Wert abrufen` (Get Dictionary Value)**: Schlüssel `summary` →
    **`Mitteilung anzeigen` (Show Notification)**.

Der Body sieht dann so aus:

```
2026-09-05;8421
2026-09-04;9033
2026-09-03;7120
```

### Variante B — JSON

Gleiche Schleife, aber statt Schritt 7:

7. **`Wörterbuch` (Dictionary)** mit drei Feldern:
   `metric` = `steps`, `date` = **Datumstext**, `value` = **Summe**
   → **`Zur Variablen hinzufügen`**, Variable **Punkte**.

und statt Schritt 8/9:

8. **`Inhalte von URL abrufen`**, Methode POST, Anfragetext **JSON**, ein Feld
   `metrics` vom Typ *Array* mit dem Wert **Punkte**. `?metric=steps` an der URL
   ist dann überflüssig.

Body:

```json
{"metrics": [
  {"metric": "steps", "date": "2026-09-05", "value": 8421},
  {"metric": "steps", "date": "2026-09-04", "value": 9033},
  {"metric": "steps", "date": "2026-09-03", "value": 7120}
]}
```

---

## Schritt 3 — Täglich auslösen

Kurzbefehle → **Automation** → **+** → *Tageszeit* → z.B. **23:50** → *Sofort
ausführen*, **„Vor dem Ausführen fragen" ausschalten**.

23:50 statt Mitternacht, damit der heutige Tag noch als heutiger Tag gezählt wird.
Ein verpasster Lauf ist unkritisch: der nächste schickt denselben Tag nochmal mit.

---

## Die Antwort lesen

```json
{
  "ok": true,
  "summary": "3 Punkte · 2 neu · 1 überschrieben · 0 übersprungen",
  "received": {"format": "json", "content_type": "application/json",
               "bytes": 184, "points_found": 3, "default_metric": null},
  "imported": 3,
  "skipped_count": 0,
  "accepted": [
    {"metric": "steps", "date": "2026-09-05", "value": 8421,
     "unit": "count", "action": "inserted"}
  ],
  "skipped": [],
  "warnings": [],
  "log_id": 812,
  "request_id": "a1b2c3d4e5f6"
}
```

| Feld | Bedeutung |
| --- | --- |
| `summary` | Fertiger Einzeiler für „Mitteilung anzeigen". |
| `received.format` | Wie der Body gelesen wurde: `json`, `json-array`, `json-single`, `json-hae`, `text`, `empty`, `unreadable`. Steht hier `unreadable`, hat der Kurzbefehl etwas geschickt, das der Parser nicht deuten konnte — der Rohpayload liegt trotzdem im Protokoll. |
| `received.points_found` | Wie viele Punkte im Body erkannt wurden, **bevor** geprüft wurde, ob sie brauchbar sind. |
| `accepted[].action` | `inserted` = neuer Tag, `updated` = derselbe Tag nochmal geliefert und überschrieben. Beim täglichen Drei-Tage-Fenster ist genau ein `inserted` und zwei `updated` der Normalfall. |
| `skipped[]` | Je Eintrag ein `reason` (siehe unten) plus der Rohpunkt, an dem es lag. |
| `warnings[]` | Stellen, an denen der Parser geraten hat — z.B. eine Zahl als Tausendertrennzeichen gelesen oder eine unbekannte Metrik gespeichert. |
| `log_id` | Eintrag im Import-Protokoll; darüber lässt sich der Rohpayload herunterladen. |
| `request_id` | Taucht in jeder zugehörigen Server-Logzeile auf. |

### Gründe für `skipped`

| `reason` | Heißt |
| --- | --- |
| `no_metric` | Kein Metrikname im Punkt und kein `?metric=` an der URL. |
| `bad_metric_key` | Name ergibt nach der Normalisierung keinen brauchbaren Schlüssel. |
| `no_date` | Kein Datumsfeld gefunden. |
| `bad_date` | Datum in keinem bekannten Format (`detail` nennt den Rohwert). |
| `no_value` | Kein Wertfeld gefunden. |
| `bad_value` | Wert ist keine Zahl (`detail` nennt den Rohwert). |
| `bad_line` | Textzeile hatte nur ein Feld. |
| `bad_json` / `no_points_in_json` | Body war JSON-artig, aber nicht lesbar bzw. ohne erkennbare Punkte. |
| `not_an_object` | Listeneintrag war kein Objekt. |
| `db_error` | Schreiben in die Datenbank fehlgeschlagen — die übrigen Punkte sind trotzdem drin. |

---

## Was der Endpoint alles frisst

Falls Kurzbefehle etwas anderes liefert als geplant, ist die Chance gut, dass es
trotzdem durchgeht.

**Envelope:** `{"metrics": [...]}`, `{"points": [...]}`, `{"data": [...]}`,
`{"samples": [...]}`, ein blankes Array `[...]`, ein einzelnes Objekt — und die
Struktur von Auto Health Export
(`{"data":{"metrics":[{"name":…,"units":…,"data":[…]}]}}`). Letztere ist
absichtlich mit drin, damit die Strecke später kompatibel umgeschaltet werden
kann, ohne den Parser anzufassen.

**Feldnamen je Punkt** (der erste gefundene gewinnt, Groß-/Kleinschreibung egal):

| Zweck | akzeptiert |
| --- | --- |
| Metrik | `metric`, `metric_key`, `name`, `key`, `type`, `metrik` |
| Datum | `date`, `day`, `datum`, `timestamp`, `time`, `start`, `recorded_at`, `start_date`, `sample_date` |
| Wert | `value`, `qty`, `quantity`, `amount`, `sum`, `wert`, `count` |
| Einheit | `unit`, `units`, `einheit` |

**Textzeilen:** Trenner `;`, `,` oder Tab. Zeilen mit `#` am Anfang und Leerzeilen
werden übersprungen.

```
2026-09-05;steps;8421;count     # Datum;Metrik;Wert;Einheit
2026-09-05;steps;8421           # Datum;Metrik;Wert
2026-09-05;8421                 # Datum;Wert  (braucht ?metric=steps)
```

**Datumsformate:** `2026-09-05`, `2026/09/05`, `05.09.2026`,
`2026-09-05T12:30:00+02:00`, `2026-09-05 12:30:00 +0200`, `2026-09-05T10:30:00Z`,
`2026-09-05 12:30:00`, `05.09.2026, 12:30`, Epoch-Sekunden und -Millisekunden.

**Zahlen:** `8421`, `"8421"`, `"8.421"` (deutsche Tausendertrennung),
`"8 421"` (auch mit geschütztem Leerzeichen), `"70,5"`, `"8421 Schritte"`.
Wenn der Parser dabei rät, steht das in `warnings` — schau da beim Einrichten
einmal hin.

> **Tipp:** Am wenigsten kann schiefgehen mit einem blanken `yyyy-MM-dd` als Datum
> und einer rohen Zahl als Wert. Ein blankes Datum wird wörtlich genommen und
> nicht durch eine Zeitzone gedreht; ein voller Zeitstempel dagegen wird in
> `HEALTH_SHORTCUT_TZ` (Standard `Europe/Berlin`) umgerechnet, um den Tag zu
> bestimmen.

---

## Fehlersuche

1. **Antwort im Kurzbefehl anschauen** — `summary`, `skipped`, `warnings` sagen in
   der Regel schon alles.
2. **Rohpayload herunterladen** — Vexbob → Gesundheit → 🧪 Beta → *Letzte Aufrufe*.
   Dort liegt Byte für Byte, was das iPhone geschickt hat. Damit lässt sich
   unterscheiden, ob der Kurzbefehl Unsinn geliefert oder der Parser ihn falsch
   gelesen hat.
3. **Server-Logs** — die `request_id` aus der Antwort steht in jeder zugehörigen
   Logzeile.
4. **Testdaten wegräumen** — im Beta-Reiter, sobald sich das Format geändert hat.

**Häufige Stolpersteine**

- *401* — Key falsch kopiert oder widerrufen. Das Header-Feld muss
  `Authorization` heißen und der Wert mit `Bearer ` (mit Leerzeichen) beginnen.
- *429* — mehr als 60 Aufrufe pro Stunde. Beim Testen kurz warten.
- `format: "empty"` — Kurzbefehle hat einen leeren Body geschickt; meist ist im
  Schritt „Anfragetext" die falsche Variable gewählt.
- *Alles `skipped` mit `no_metric`* — zweispaltiger Text ohne `?metric=steps`.

---

## Später mehr Metriken

Zwei Wege, beide ohne Datenbank-Änderung:

- **Sofort, ohne Codeänderung:** Der Kurzbefehl schickt einfach einen neuen
  Metriknamen mit. Er wird gespeichert und im Beta-Reiter angezeigt; in
  `warnings` steht, dass der Name unbekannt ist, und im Reiter erscheint er als
  `known: false`.
- **Sauber benannt:** ein Eintrag in `SHORTCUT_METRICS` in
  `backend/services/health_shortcut.py` — Label, Aliase, Default-Einheit und ob
  es ein Tageswert (`day`) oder eine Einzelmessung (`point`) ist. Einzelmessungen
  mit mehreren Werten pro Tag laufen in dieselbe Tabelle, ohne dass am
  Unique-Index etwas geändert werden muss.

---

## Betriebsnotizen

- **Rate-Limit** 60 Aufrufe/Stunde (`LIMIT_SHORTCUT_IMPORT` in `backend/deps.py`).
- **Zeitzone** über `HEALTH_SHORTCUT_TZ`, Standard `Europe/Berlin`. Betrifft nur
  Punkte mit vollem Zeitstempel.
- **Import-Protokoll geteilt:** Die Aufrufe liegen in derselben Tabelle wie die
  von Auto Health Export (`kind` = `shortcut-<format>`). Die Aufbewahrungsgrenze
  von `HEALTH_IMPORT_LOG_KEEP` (Standard 200) Einträgen gilt damit für **beide
  Strecken zusammen** — bei ausgiebigem Testen können ältere HAE-Einträge
  herausfallen.
- **Obergrenze** 2000 Punkte pro Aufruf; darüber wird abgeschnitten und in
  `warnings` vermerkt.
