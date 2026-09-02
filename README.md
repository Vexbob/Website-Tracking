# Vexbob

**Persönliche Web-App mit Sparziel-Tracker, Ausgaben, Notizen, Gesundheit & Blog — selfhosted, PWA-fähig, Multi-User mit Admin-Bereich.**

---

## ✨ Module

### 💰 Sparziel-Tracker
Führt Buch über echtes Gespartes statt über gute Vorsätze: jedes Ziel hat einen eigenen Kontostand, und jede Bewegung darauf bleibt als Transaktion nachvollziehbar.

- **Mehrere parallele Sparziele** — jedes Ziel mit eigenem Zielbetrag, Kontostand und Verlauf. Genau eines ist aktiv und nimmt neue Einzahlungen auf, die übrigen laufen unangetastet weiter — so lassen sich mehrere Anschaffungen nebeneinander planen, ohne die Beträge im Kopf trennen zu müssen.
- **Achievements** — selbst definierte Meilensteine, die an eine Kennzahl gekoppelt sind (Startwert, Schrittweite, Richtung steigend oder fallend). Jeder erreichte Schritt schüttet eine Belohnung aufs Sparziel aus und macht damit Fortschritt in einem anderen Lebensbereich finanziell sichtbar.
- **Wochen- & Monatsziele** — wiederkehrende Vorhaben mit Check-in pro Periode, Streak-Bonus für ununterbrochene Serien und Historie. Ein versehentlicher Check-in lässt sich per Check-out zurücknehmen.
- **Ideen & mögliche Ziele** — zwei Vorstufen-Listen für Anschaffungen, die noch kein aktives Sparziel verdienen. Hält die Zielliste sauber, ohne dass Einfälle verloren gehen.
- **„Allgemein"-Konto als Puffer** — läuft ein Sparziel voll oder ist gerade keines aktiv, landen Belohnungen automatisch hier statt verloren zu gehen. Von dort lassen sie sich gezielt auf ein Ziel übertragen.
- **Aktivitäts-Log & 365-Tage-Heatmap** — jede Einzahlung, jeder Check-in und jeder Meilenstein mit Datum und optionaler Notiz; die Heatmap zeigt auf einen Blick, wie durchgehend das letzte Jahr bespielt war.
- **Trophäenwand** — abgeschlossene Sparziele wandern als Trophäe in eine eigene Ansicht, damit erreichte Ziele nicht einfach aus der Liste verschwinden.
- **Export & Backup** — Transaktionen als CSV, dazu ein vollständiges JSON-Backup mit Restore. Tägliche Snapshots laufen automatisch mit und sind pro Nutzer isoliert.

### 📝 Notizen
Schnelle Notiz-Ablage im Apple-Notes-Stil (Master-Detail): links die Liste, rechts der Editor, ohne Speichern-Knopf.

- **WYSIWYG-Editor** — `contenteditable` mit HTML als Speicherformat, dazu Markdown-Shortcuts beim Tippen. Formatieren, ohne die Hände von der Tastatur zu nehmen.
- **Task-Checkboxen** — abhakbare Punkte direkt im Fließtext, damit eine Notiz auch als kleine To-do-Liste taugt.
- **Farblabels, Pin & Archiv** — Farben zum groben Sortieren, Pin für Dauerbrenner ganz oben, Archiv für Erledigtes, das man nicht löschen will.
- **Auto-Save & Live-Suche** — Änderungen werden im Hintergrund gespeichert, die Suche filtert die Liste während des Tippens über alle Notizen.

### 💶 Ausgaben-Tracker
Erfasst Einkäufe bis auf die einzelne Position und beantwortet damit die Frage, wofür das Geld tatsächlich draufgeht.

- **Kassenbon-Scan (OCR)** — Foto des Bons an Google Cloud Vision, das Ergebnis ist vor dem Speichern vollständig editierbar. Erspart das Abtippen, ohne blind zu übernehmen, was die Erkennung liefert.
- **Optionaler KI-Parser** — Gemini zerlegt den OCR-Text in saubere Positionen inkl. Markenzuordnung (~800 vordefinierte Marken und Eigenmarken werden pro Nutzer angelegt). Fehlt der API-Key oder scheitert der Aufruf, greift transparent der Regex-Parser.
- **Schnelleingabe** — Bon ohne Positionen, nur Laden, Datum und Summe. Für den Fall, dass der Beleg nicht mehr da ist oder sich der Aufwand nicht lohnt.
- **Läden & Kategorien mit Auto-Regeln** — Regeln ordnen wiederkehrende Artikel automatisch einer Kategorie zu, damit die Auswertung nicht an unsortierten Positionen scheitert.
- **Marken & Produkte** — eigene Seiten für Markenpflege und die Produktliste, Grundlage für Marken- und Produktvergleiche.
- **Preisverlauf** — je Produkt die Preisentwicklung über die Zeit und über Läden hinweg; zeigt, ob ein „Angebot" wirklich eines ist.
- **Statistikseite** — Zeitraumfilter, KPI-Kacheln, Trend-Chart, Auswertung nach Kategorie und Laden, Läden-Vergleich.
- **Duplikat-Erkennung** — eigener Tab mit Vorschlägen für doppelt erfasste Bons; jeder Vorschlag lässt sich zusammenführen oder dauerhaft ausblenden, ohne Bons zu löschen.
- **Wiederkehrende Ausgaben** — Bons als wiederkehrend markieren, damit Fixkosten in der Auswertung als solche erkennbar bleiben.
- **Export** — Ausgaben als CSV oder JSON, wahlweise gefiltert.

### 🏋️ Gesundheit
Sync-Ziel für die iPhone-App **Auto Health Export** — die App schiebt die Apple-Health-Daten hierher, die Auswertung passiert in Vexbob.

- **Eigener API-Key pro Nutzer** — getrennt vom Login, jederzeit widerrufbar. Der Klartext ist nur bei der Erzeugung sichtbar, gespeichert wird ein Hash; ein abhandengekommener Sync-Key gibt damit keinen Zugang zum Account.
- **Idempotenter Import** (`POST /api/health/import`) — nimmt JSON, CSV und Multipart in allen Varianten entgegen, die die App je nach Version schickt. Wiederholte Syncs desselben Zeitraums aktualisieren bestehende Werte, statt Dubletten anzulegen.
- **Import-Protokoll** — jeder Sync wird mit seinem Roh-Payload gespeichert und ist herunterladbar. Damit lässt sich bei einem auffälligen Wert unterscheiden, ob die App ihn schon so geliefert oder Vexbob ihn falsch verarbeitet hat.
- **Optionaler AI-Fallback** — unbekannte Metriknamen aus neuen App-Versionen werden per Gemini einem bekannten Typ zugeordnet, statt still im Import verloren zu gehen.
- **Manueller Nachimport** — CSV-Mehrfachauswahl oder JSON-Datei per Drag & Drop, für einen einmaligen Backfill vergangener Monate ohne eingerichtete Automation.
- **Dashboard** — Kacheln für heute und die letzten 7 Tage, Aktivitätsverlauf (Schritte oder Kalorien), letzte Nacht, Blutdruck und Herz-Übersicht.
- **Vitalwerte-Verlauf** — Zeitreihe je Metrik mit gleitender Ø-Linie. Messlücken (Werte unter 20 % des Medians, etwa durch den angebrochenen heutigen Tag oder eine nicht getragene Uhr) fließen nicht in Ø, Min und Max ein und werden unter dem Diagramm ausgewiesen.
- **Schlaf** — Balkendiagramm mit der geschlafenen Gesamtzeit je Nacht und den Phasen als Binnenzeichnung, dazu ein Diagramm für Zubettgeh- und Aufstehzeiten. Nächte unter einer Stunde Schlaf gelten als Messlücke und bleiben aus Kacheln und Diagrammen draußen.
- **Workouts** — Historie mit Typ-Filter und Detailansicht inkl. sportartspezifischer Zusatzmetriken.
- **CSV-Export & gezieltes Löschen** — alle Gesundheitsdaten als eine CSV; gelöscht wird wahlweise nach Kategorie und Zeitraum, damit ein fehlerhafter Import korrigierbar bleibt, ohne alles wegzuwerfen.

### 📰 Blog
Das einzige nach außen sichtbare Modul: `/blog/` ist ohne Anmeldung lesbar, geschrieben wird im Admin-Bereich.

- **Öffentliche Leseansicht** — Artikelliste, Tag-Filter, Lesezeit-Schätzung und View-Counter.
- **Admin-Editor** — dieselbe WYSIWYG-Logik wie bei den Notizen, Bilder per Drag & Drop oder Paste, Sichtbarkeit je Artikel steuerbar.
- **XSS-Schutz** — der gespeicherte HTML-Inhalt läuft vor der Ausgabe durch einen Whitelist-Sanitizer, weil die Seite öffentlich erreichbar ist.

### ⬇️ Gesamt-Export
Eine Dashboard-Kachel exportiert alle Module gemeinsam als eine CSV (`GET /api/export/all`), abschnittsweise gegliedert mit erklärenden Kommentarzeilen — gedacht als Archiv und als Futter für externe Auswertungen.

- **Zeitraumfilter** — Presets (30 Tage, 3 bzw. 12 Monate, laufendes Jahr) oder freie Von-Bis-Auswahl.
- **Wochen-/Monats-Aggregation** — fasst Ausgaben und Vitalwerte zu Perioden zusammen. Ausgaben behalten dabei eine Zeile je Einkauf (Datum, Laden, Typ, Anzahl Positionen, Summe, Kategorien-Split); nur die Einzelpositionen entfallen, damit ein Jahresexport lesbar bleibt.
- **gzip** — die Antwort wird komprimiert, wenn der Browser es anbietet; bei einem Jahresexport spart das rund 85 % Übertragung.

### 👤 User- & Admin-System
- **JWT-Login** mit bcrypt-gehashten Passwörtern.
- **Invite-Tokens** — der Admin legt Nutzer an, ohne ein Passwort zu vergeben; der Eingeladene setzt es selbst über den Aktivierungslink. Token sind neu erzeugbar, falls einer verfällt.
- **Passwort-Reset** durch den Admin, für den Fall, dass der Aktivierungsweg nicht mehr funktioniert.
- **Rate-Limiting & Ownership-Checks** — Login und alle Schreib-Endpoints sind gedrosselt, jede Abfrage ist an den eingeloggten Nutzer gebunden; Daten anderer Nutzer sind auch bei geratenen IDs nicht erreichbar.

### 🧭 UX
- **Globaler Modul-Switcher** in der Navbar für den Sprung zwischen den Modulen.
- **Dark-Mode** mit Umschalter, den auch die Diagramme mitmachen.
- **PWA** — installierbar, Service Worker mit Update-Hinweis, sobald eine neue Version ausgeliefert wurde.
- **Drag-&-Drop-Sortierung** für Ziele, Achievements und Listen.
- **Undo-Toasts** — Löschvorgänge lassen sich für ein paar Sekunden zurücknehmen, statt sie vorher wegzuklicken.
- **Versions-Zeitstrahl** — Klick auf die Versionsnummer öffnet den Changelog der letzten Releases.

---

## 🧱 Tech-Stack

| Schicht | Technologie |
| --- | --- |
| **Backend** | Python 3.11 · FastAPI · asyncpg · SlowAPI (Rate-Limiting) · passlib (bcrypt) |
| **Datenbank** | PostgreSQL, Migrationssystem mit Checksum-Schutz in `backend/migrations/sql/` |
| **Frontend** | Vanilla JS · Chart.js · Sortable.js · PWA (Service Worker + Manifest) |
| **Deployment** | Docker (`backend/Dockerfile`), CORS über ENV konfigurierbar |

Keine Frontend-Frameworks, keine Build-Pipeline — reine HTML/CSS/JS-Files, direkt ausliefern.

---

## 🚀 Quickstart

### Voraussetzungen
- Python **3.11+**
- PostgreSQL **13+**
- Ein Webserver, der `frontend/` als Static-Files ausliefert (nginx, Caddy, `python -m http.server`, …)

### 1. Backend einrichten
```bash
git clone <repo-url> vexbob
cd vexbob/backend

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Umgebungsvariablen
```bash
export DATABASE_URL="postgresql://user:pass@localhost:5432/vexbob"
export SECRET_KEY="wähle-einen-langen-zufälligen-string"
export CORS_ORIGINS="http://localhost:5500,http://127.0.0.1:5500"

# Optional: Kassenbon-OCR (Ausgaben-Modul)
export OCR_PROVIDER="google"
export GOOGLE_APPLICATION_CREDENTIALS_JSON='{"type":"service_account", ...}'

# Optional: KI-Parser für Ausgaben & Gesundheit (Google AI Studio)
export GEMINI_API_KEY="..."
```

### 3. Backend starten
```bash
uvicorn main:app --reload --port 8000
```
Schema & Migrationen werden beim ersten Start automatisch angewendet.

**Admin-Account anlegen:** entweder direkt per SQL einen User mit `is_admin=TRUE` anlegen, oder einmalig `ADMIN_BOOTSTRAP_USERNAME` + `ADMIN_BOOTSTRAP_PASSWORD` setzen — ist die `users`-Tabelle noch leer, legt das Backend beim Startup automatisch einen Admin an (danach die beiden ENVs wieder entfernen).

### 4. Frontend ausliefern
```bash
cd ../frontend
python3 -m http.server 5500
```
Anschließend `http://localhost:5500` öffnen. `frontend/js/config.js` zeigt standardmäßig auf `http://localhost:8000` — für Produktivbetrieb dort die Backend-URL anpassen.

---

## 🐳 Docker

```bash
cd backend
docker build -t vexbob-backend .
docker run -d --name vexbob \
    -e DATABASE_URL="postgresql://..." \
    -e SECRET_KEY="..." \
    -e CORS_ORIGINS="https://deine-domain.tld" \
    -p 8000:8000 vexbob-backend
```

Das Frontend kann parallel z.B. hinter nginx/Caddy als Static-Site ausgeliefert werden.

---

## 🩺 Betrieb

- **Migrationen**: SQL-Dateien in `backend/migrations/sql/`, aufsteigend nummeriert, jede mit SHA256-Checksum abgesichert — nachträgliches Editieren einer deployten Migration wirft beim Start einen harten Fehler. `MIGRATIONS_DRY_RUN=1` für einen Read-only-Preview.
- **Health-Checks**: `GET /api/health` (Liveness), `GET /api/readiness` (prüft DB-Verbindung, für Deploy-Checks).
- **Request-Tracing**: jede Response trägt einen `X-Request-ID`-Header, der sich durch alle Log-Zeilen zieht.
- **Sentry (optional)**: `SENTRY_DSN` setzen und `sentry-sdk[fastapi]` installieren, dann werden unbehandelte Exceptions automatisch gemeldet.

---

## 🔐 Sicherheit

- Passwörter mit **bcrypt** gehasht, JWT-Auth mit konfigurierbarem Secret
- Rate-Limiting auf Login und Schreib-Endpoints
- Admin-Endpoints separat abgesichert, Ownership-Checks auf allen User-Daten
- Snapshots/Backups sind pro User isoliert

---

## 📁 Projekt-Struktur

```
├── backend/
│   ├── main.py                  # FastAPI-App & Sparziel-Endpoints
│   ├── schemas.py               # Pydantic-Models
│   ├── helpers.py                # Utility-Funktionen
│   ├── deps.py                  # Rate-Limiter, geteilte Utilities
│   ├── auth.py                  # JWT + bcrypt
│   ├── database.py              # asyncpg-Pool, Init, Migrationen
│   ├── routers/                 # Ausgelagerte Endpoint-Gruppen (blog, brands, expenses, export, health, notes)
│   ├── services/                # OCR, KI-Parser, Backup, Ausgaben-/Health-Logik
│   ├── migrations/sql/          # Nummerierte SQL-Migrationen
│   └── tests/
├── docs/
│   └── BLOG_KONZEPT.md
└── frontend/
    ├── index.html               # Dashboard-Landing
    ├── sparziel/                # Sparziel-Tracker
    ├── ausgaben/                # Ausgaben-Tracker
    ├── notizen/                 # Notizen
    ├── health/                  # Gesundheit
    ├── blog/                    # Blog
    ├── admin/                   # Admin-Panel
    ├── private/                 # Login-Seite
    ├── css/style.css            # Themes (light/dark)
    ├── js/                      # config, api, version
    ├── manifest.webmanifest     # PWA-Manifest
    └── sw.js                    # Service Worker
```

---

## 📝 Lizenz

Persönliches Projekt — bei Interesse an einer Verwendung bitte im Repo Kontakt aufnehmen.
