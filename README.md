# Vexbob

**Persönliche Web-App mit Sparziel-Tracker, Notizen, Ausgaben & mehr — Selfhosted, PWA-fähig, mit Multi-User & Admin-Bereich.**

> Vexbob ist ein modulares, privat gehostetes Toolkit für den Alltag: Sparziele mit Gamification tracken, Notizen ablegen, Ausgaben erfassen — alles unter einem Login, mit Dark-Mode und mobiler PWA-Installation.

---

## ✨ Features

### 💰 Sparziel-Tracker
- **Mehrere parallele Sparziele** – jedes mit eigenem Kontostand, jederzeit zwischen ihnen wechseln
- **Achievements** – Meilensteine mit Belohnungen (steigend oder fallend, mit optionalem Zielwert)
- **Wochen-/Monatsziele** – regelmäßige Check-ins mit **Streak-Boni**
- **Aktivitäts-Log** mit Wochenübersicht, Filter, Suche, Notizen pro Eintrag
- **GitHub-Style Heatmap** über 365 Tage
- **Trophäen-Wand** für abgeschlossene Ziele
- **CSV-Export** mit Metadaten-Vorspann (Sparziele, Achievements, Wochen-/Monatsziele, Wunsch-Anschaffungen, Zukunftsideen, Trophäen) + Protokoll (v1.15.0)
- Fallende Achievements: Meilenstein zählt erst bei **strikt unter** der Schwelle (v1.15.1)
- **v1.18.0 Repair-Job**: beim Backend-Startup werden verpasste Meilenstein-Auszahlungen automatisch nachgetragen (Log + Savings-Transaktion mit Note „Nachtrag v1.18: Meilenstein-Reparatur"), `credited_milestones` neu synchronisiert.
- **Wochenziel-Historie erweitert** (v1.18.0): pro Wochenziel wird der Verlauf der letzten 12–52 Perioden mit Status-Chips (✓/◐/✕/⏳), Check-in-Anzahl und Auszahlungs-Marker gezeigt; nachträglicher Check-in in vergangene Wochen per +1-Button möglich — erreichbar über „⋮ Bearbeiten" → „Vergangene Perioden" am jeweiligen Wochenziel (die separate, funktionslose Wochen-Navigation über der Liste wurde in v1.23.0 entfernt).
- **🪙 Allgemein-Konto / Puffer** (v1.18.2): jeder User hat automatisch ein „Allgemein"-Konto, das keine Zielgrenze hat. Meilenstein- und Streak-Belohnungen werden intelligent geroutet — wenn das aktive Sparziel nicht mehr genug Platz für die Belohnung hat (bzw. abgeschlossen ist), wandert die Auszahlung automatisch ins Allgemein-Konto **und wird trotzdem verbucht**. Fixt das Problem, dass Meilensteine „verpuffen", wenn der Rest-Betrag des Sparziels kleiner ist als die Belohnung. Achievements & Wochenziele bekommen optional ein **Reward-Goal-Dropdown** („Belohnung geht an: …") um manuell ein festes Zielkonto zu wählen.
- **JSON-Backup & Restore**, automatische tägliche Snapshots

### 📝 Notizen (komplett überarbeitet in v1.18.0 → WYSIWYG)
Notiz-Ablage im **Apple-Notes-Stil** (Master-Detail): Sidebar-Liste + inline formatierender Editor, einzelne Notizen per Link aufrufbar (`#note-42`).
- **WYSIWYG-Editor** (v1.18.0): `contenteditable`, was du tippst wird sofort formatiert — **kein Umschalten** zwischen Editor und Vorschau mehr.
- **Speicherformat: HTML** (`format='html'`) — strukturiertes DOM statt Textarea-Text.
- **Task-Checkboxen als eigene Blöcke**: `<div class="nz-task" data-done="…">` mit klickbarer Custom-Box (kein `<input>`) — löst die Cursor-/Fokus-Probleme früherer Versionen komplett.
- **Enter in Task**: neue Task-Zeile; **Enter in leerer Task**: raus zu normalem Absatz (Apple-Notes-Verhalten).
- **Markdown-Shortcuts beim Tippen**: `# ` → H1, `## ` → H2, `### ` → H3, `- ` → Bullet, `1. ` → nummeriert, `> ` → Zitat, `- [ ] ` → Task, `- [x] ` → abgehakte Task.
- **Toolbar** sticky oben: H1-H3, **B** / *I* / U / S / `code`, Listen, Aufgabe, Zitat, Link, HR.
- **Keyboard-Shortcuts**: Cmd/Ctrl+B/I/U/K, +Shift+7/8/9 (Aufgabe/Ul/Ol), +N (neue Notiz).
- **Auto-Migration** alter Markdown-Notizen (v1.17) → HTML beim ersten Öffnen, wird beim nächsten Save als `format='html'` zurückgeschrieben.
- **Farblabels** (8 Farben), **Pin** (eigene Sektion oben), **Archiv** mit Tab-Toggle.
- **Auto-Save** mit Debounce (700 ms), Status-Indikator (Speichern… → Gespeichert ✓).
- **Sortieren** (Geändert / Erstellt / Titel) + **Live-Suche** filtern die Sidebar.
- Leere Neue Notizen werden beim Verlassen automatisch gelöscht, **Undo** beim Löschen/Archivieren.
- responsiv (mobil einspaltig mit Back-Button), Dark-Mode, PWA.

### 📰 Blog (neu in v1.18.0, Bilder seit v1.18.1)
Öffentlich lesbares Blog-Modul — die einzige nach außen sichtbare Fläche der App.
- **Öffentliche API** (`/api/public/blog/*`, kein Auth, Rate-Limit `120/min`).
- **URL-Struktur**: `/blog/` (Übersicht) und `/blog/#<slug>` (Detail).
- **Login-Seite** zeigt die 5 neuesten Beiträge rechts als Teaser.
- **Admin-Editor** (`/blog/admin/`, nur `is_admin`) mit **gleicher WYSIWYG-Logik** wie Notizen, Auto-Save, Publish/Unpublish, Slug editierbar (auto aus Titel), Cover-URL, Tag-Chips.
- **Bild-Einbindung** (v1.18.1): Bilder via Toolbar-Button „🖼️ Bild", **Drag & Drop** direkt in den Editor oder **Paste** aus der Zwischenablage. Bilder werden komprimiert (`process_image`, max 1600px, JPEG 82%) und in der DB (`blog_media`-Tabelle, bytea) gespeichert. Öffentlicher Lese-Endpoint `/api/public/blog/media/{id}` mit 24h-Cache. Klick auf Bild im Editor → Alt-Text bearbeiten.
- **Tag-Filter** in der Übersicht, **Lesezeit-Schätzung** (200 Wörter/min), **View-Counter**.
- **XSS-Schutz** via Whitelist-Sanitizer im Frontend (erlaubt `img[src,alt,title]`, `a[href,target,rel]` etc., filtert alle Inline-Styles und unsichere URLs).

### 🧭 Globaler Modul-Switcher (v1.18.1)
Jede Modul-Seite hat oben in der Navbar ein **Dropdown „⊞ Module"**, das direkten Wechsel zwischen Sparziel, Ausgaben, Notizen, Blog und Admin erlaubt — **ohne** den Umweg über das Dashboard. Aktives Modul wird hervorgehoben. Login- und Admin-Status werden berücksichtigt (öffentliche Seiten wie Blog sind immer sichtbar, geschützte nur eingeloggt, Admin-Bereiche nur für Admins).

### 💶 Ausgaben-Tracker (neu in v1.7.0, KI-Parser seit v1.8.0, Marken seit v1.16.0)
- **Kassenbon-OCR** via Google Cloud Vision (deutscher Receipt-Parser: Markt/Datum/Betrag/MwSt./Positionen)
- **Editierbare OCR-Ergebnisse** – nach der Erkennung Werte in einem Formular anpassen bevor gespeichert wird
- **Bildspeicher** mit Thumbnails, Bild-Preview auf der Bon-Detailseite, jederzeit löschbar
- **Läden + Kategorien** verwalten (Farbe/Icon), Ausgaben pro Laden / pro Kategorie auswerten
- **Marken-System** (v1.16.0) – ~800 vordefinierte Eigen- und Herstellermarken, automatisch beim ersten Start pro User geseedet; AI-Parser erhält Markenkontext und weist Artikel automatisch zu; eigener Marken-Tab mit Filter (Alle / Eigenmarken / Hersteller)
- **Inline-Anlage von Läden & Kategorien** (v1.16.0) direkt beim Bon-Eingeben — kein Tab-Wechsel nötig
- **Auto-Kategorisierung** mit mitlernenden Regeln (Keyword → Kategorie, Bestätigungs-Counter)
- **Verbesserter KI-Parser** (v1.16.0) – Default-Modell auf `gemini-flash-latest` hochgesetzt; Prompt behält jetzt beschreibende Adjektive (z.B. "Mais geröstet gesalzen" statt nur "Mais")
- **Statistik-Redesign** (v1.18.0) – komplett neue Statistikseite mit **globalem Zeitraumfilter** (7T/30T/90T/12M/Alle/Custom), **KPI-Kacheln** mit Vorperiode-Vergleich (Gesamt · Ø/Tag · größter Bon · teuerster Wochentag), **Zeitverlauf-Chart** mit umschaltbarer Granularität (Tag/Woche/Monat) + rollierender Trendlinie, **Donut nach Kategorie + Balken nach Laden** je mit Detail-Tabelle inkl. Vorperiode-Delta-Pills, **Wochentag-Verteilung**, **Top-Artikel-Tabelle**, **365-Tage-Heatmap** und automatisch generierte **Insight-Cards** („Du gibst freitags 40% mehr aus", „Kategorie Lebensmittel stieg um +23% ggü. Vorperiode"…). Neuer Backend-Endpoint `/api/expenses/stats/insights?from=&to=` mit `by_weekday`, `top_items`, `top_stores`, `top_categories` und Prev-Period-Diff.
- **Schnelleingabe-Modus** – nur Betrag + Laden + Datum ohne Positionen
- **Manuelle Eingabe** mit beliebig vielen Positionen und Split-Kategorien pro Bon
- **Wiederkehrende Ausgaben** – automatische Vorschlagsliste anhand von Buchungshistorie
- **Duplikat-Warnung** vor dem Speichern (gleicher Tag + Laden + ähnlicher Betrag)
- **Client-Bildkompression** (Canvas API, max. 1600 px, ~85 % JPEG-Qualität)
- **PWA-Kamera-Direktaufnahme** via `capture="environment"` auf Smartphones
- **Statistik**: Monatstrend, Doughnut nach Kategorie/Laden, 365-Tage-Heatmap, Preisverlauf-Suche
- **Preisverlauf-Redesign** (v1.16.0) – Kachel-Grid mit SVG-Sparkline pro Produkt statt Liste, filtert Einmalkäufe automatisch (nur Produkte mit ≥2 Käufen oder Marken-Bezug), Listen-Ansicht optional umschaltbar
- **Preisvergleich zweigeteilt** (v1.16.0) – im Detail-Modal zwei Tabs: „📊 Preisverlauf pro Laden" (mit Rabatt/Preissteigerung) und „🏪 Läden-Vergleich" (Tabellensicht wer billiger ist)
- **Export** als CSV (Semikolon-getrennt, deutsche Zahlenformatierung) und JSON (inkl. Items)

### 🏋️ Gesundheit (neu in v1.22.0)
Sync-Ziel für die iPhone-App **Auto Health Export** (REST-API-Automation).
- **API-Key-Auth** getrennt vom JWT-Login (`hae_<user_id>_<random>`), da die
  App keinen Login-Flow durchführen kann. Keys werden pro User erzeugt,
  einmalig im Klartext angezeigt und jederzeit widerrufbar
  (`/api/health/api-keys`).
- **Sync-Endpoint** `POST /api/health/import` nimmt den Original-JSON-Payload
  der App entgegen (`services/health_ingest.py`) und ordnet ihn regelbasiert
  typ-spezifischen Tabellen zu: einfache Zeitserien (aktive Energie,
  Herzfrequenz, Ø-HF beim Gehen, Gewicht, HRV, Ruhepuls, kardiorespiratorische
  Erholung, Schritte, Schwimmdistanz, VO2max), Blutdruck-Paare, Blutzucker,
  Schlaf (mit Phasen Core/Deep/REM/Wach) und Workouts **ohne Routendaten**
  (Kopf-Tabelle + flexible Zusatzmetriken je Sportart).
- **Idempotent**: wiederholte/überlappende Syncs erzeugen keine Duplikate
  (`ON CONFLICT DO UPDATE` auf User+Zeitstempel+Quelle).
- **Optionaler AI-Fallback** (`services/ai_health_parser.py`, Gemini) für
  unbekannte Metric-Namen — analog zum Kassenbon-Parser; schlägt er fehl,
  wird der einzelne Datenpunkt übersprungen statt den ganzen Sync zu verwerfen.
- **Frontend** (`/health/`) mit Tabs Dashboard, Vitalwerte (Charts pro
  Metrik + Blutdruck/Blutzucker), Schlaf (gestapeltes Phasen-Chart),
  Workouts (Liste + Detail) und Einstellungen (API-Key-Verwaltung).
- **Manueller Import** (v1.23.1/v1.24.0): unter „Einstellungen" → zwei
  Wege für einen einmaligen Nachimport vergangener Zeiträume ohne dafür
  eine Automation einzurichten:
  - **CSV (empfohlen, v1.24.0)**: `POST /api/health/import-csv` — Multi-File-
    Upload, verarbeitet die kompakte Tages-Gesundheitsmetriken-CSV und die
    Workouts-Übersichts-CSV (Header-basierte Spaltenerkennung, robust gegen
    leichte Formatabweichungen). Die vielen Pro-Workout-Einzelmetrik-CSVs
    werden bewusst ignoriert. Deutlich kleinere Dateien als JSON.
  - **JSON (Alternative)**: `POST /api/health/import-file` — eine Datei,
    nutzt denselben Ingest wie der automatisierte Sync, aber detaillierter
    (z.B. minutengenaue Herzfrequenz) und dafür deutlich größer.

### ⬇️ Gesamt-Export (neu in v1.23.0)
Dashboard-Kachel „Alles exportieren" (`GET /api/export/all`) liefert **eine
einzige CSV** mit allen Modulen gleichzeitig: Sparziele, Achievements,
Wochen-/Monatsziele, Wunsch-Anschaffungen, Zukunftsideen, Trophäen,
Sparziel-Protokoll, Ausgaben (Bons + Positionen) und Gesundheit
(Vitalwerte, Blutdruck, Blutzucker, Schlaf, Workouts). Jede Sektion beginnt
mit einer erklärenden Kommentarzeile `# SEKTION: ...` und ihrem eigenen
Spalten-Header — die Spaltenanzahl unterscheidet sich bewusst zwischen den
Sektionen (unterschiedliche Datentypen). Baut auf denselben Zeilen-Helfern
wie die einzelnen Modul-Exports auf (`helpers.py`, `services/full_export.py`).

### 👤 User- & Admin-System
- Login mit JWT
- Admin-Bereich mit **Invite-Tokens** (User-Erstellung ohne Passwort-Vergabe durch Admin)
- Passwort-Reset & User-Löschung
- Rate-Limiting auf allen kritischen Endpoints

### 🌓 UX
- Dark-Mode
- Responsive & mobil optimiert
- **PWA** – als App installierbar, Service-Worker für Offline-Shell
- Drag-&-Drop Sortierung
- Haptic Feedback auf mobilen Geräten
- Undo-Toasts für versehentliche Aktionen

---

## 🧱 Tech-Stack

| Schicht | Technologie |
| --- | --- |
| **Backend** | Python 3.11 · FastAPI · asyncpg · SlowAPI (Rate-Limiting) · passlib (bcrypt) |
| **Datenbank** | PostgreSQL (mit Migrationssystem in `backend/migrations/sql/`) |
| **Frontend** | Vanilla JS · Chart.js · Sortable.js · PWA (Service Worker + Manifest) |
| **Deployment** | Docker (Dockerfile im `backend/`), CORS konfigurierbar über ENV |

Keine Frontend-Frameworks, keine Build-Pipeline — reine HTML/CSS/JS-Files, direkt ausliefern.

---

## 🚀 Quickstart

### Voraussetzungen
- Python **3.11+**
- PostgreSQL **13+** (z.B. lokal, in Docker oder als Managed-DB)
- Ein Webserver, der `frontend/` als Static-Files ausliefert (nginx, Caddy, `python -m http.server`, …)

### 1. Klonen & Backend einrichten
```bash
git clone <repo-url> vexbob
cd vexbob/Website/backend

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Umgebungsvariablen (`.env` oder Shell)
```bash
export DATABASE_URL="postgresql://user:pass@localhost:5432/vexbob"
export JWT_SECRET="wähle-einen-langen-zufälligen-string"
export CORS_ORIGINS="http://localhost:5500,http://127.0.0.1:5500"

# Optional: Google Cloud Vision OCR für Kassenbons (Ausgaben-Modul)
export OCR_PROVIDER="google"
export GOOGLE_APPLICATION_CREDENTIALS_JSON='{"type":"service_account", ...}'
# Alternative: Pfad zur Datei
# export GOOGLE_APPLICATION_CREDENTIALS="/pfad/zur/gcp-vision.json"
```

### 3. Backend starten
```bash
uvicorn main:app --reload --port 8000
```
Beim ersten Start werden Schema & Migrationen automatisch angewendet.

**Admin-Account anlegen** (kein Auto-Seed mehr — Doku-Diskrepanz seit v1.33.0 behoben):
Entweder per SQL direkt in der DB einen User mit `is_admin=TRUE` und einem bcrypt-Passwort-Hash anlegen, ODER die Bootstrap-Variante nutzen. Wenn die ENV-Vars `ADMIN_BOOTSTRAP_USERNAME` und `ADMIN_BOOTSTRAP_PASSWORD` gesetzt sind **und** die `users`-Tabelle noch komplett leer ist, legt das Backend beim Startup automatisch einen Admin an — bei einer bereits bestückten DB passiert nichts (kein Overwrite-Risiko).

```bash
export ADMIN_BOOTSTRAP_USERNAME="admin"
export ADMIN_BOOTSTRAP_PASSWORD="ein-gutes-passwort-mit-mindestens-10-zeichen"
uvicorn main:app --port 8000
# Nach dem ersten Start die beiden ENVs wieder entfernen.
```

### 4. Frontend ausliefern
```bash
cd ../frontend
python3 -m http.server 5500
```
Anschließend `http://localhost:5500` öffnen und einloggen.

### 5. Konfiguration im Frontend
`frontend/js/config.js` zeigt standardmäßig auf `http://localhost:8000`. Für Produktivbetrieb dort die Backend-URL anpassen.

---

## 🐳 Docker

```bash
cd Website/backend
docker build -t vexbob-backend .
docker run -d --name vexbob \
    -e DATABASE_URL="postgresql://..." \
    -e SECRET_KEY="..." \
    -e CORS_ORIGINS="https://deine-domain.tld" \
    -e JWT_EXPIRE_HOURS="24" \
    -p 8000:8000 vexbob-backend
```

Das Frontend kann parallel z.B. hinter nginx/Caddy als Static-Site ausgeliefert werden.

---

## 🧬 Migrationen (v1.35.0)

- SQL-Dateien in `backend/migrations/sql/`, aufsteigend nummeriert.
- Jede angewendete Migration bekommt einen **SHA256-Checksum** in `schema_migrations.checksum` gespeichert.
- Wird eine bereits deployte Migration nachträglich editiert, **wirft das Backend beim nächsten Startup einen harten `RuntimeError`** – statt still ein inkonsistentes Schema zu tolerieren. Korrekte Vorgehensweise: neue Migration `NNN_fix_xyz.sql` schreiben, alte unverändert lassen.
- Alt-Einträge ohne Checksum werden beim ersten Post-Upgrade-Start opportunistisch mit dem aktuellen Wert nachgezogen – bestehende Deploys bleiben lauffähig.
- `MIGRATIONS_DRY_RUN=1` als ENV setzt den Runner in Read-only-Modus (loggt nur, was angewendet würde). Nützlich für Deploy-Preview.

---

## 📡 Optional: Sentry (v1.35.0)

Setz `SENTRY_DSN` als ENV **und** installier `sentry-sdk[fastapi]>=1.40.0` (Zeile in `requirements.txt` auskommentieren) – dann werden nicht abgefangene Exceptions automatisch nach Sentry gemeldet, mit `X-Request-ID` als Tag. Ohne DSN wird `sentry_sdk` gar nicht erst importiert.

Weitere ENVs:
- `SENTRY_TRACES_SAMPLE_RATE` (Default `0.0`) – 0.0…1.0 für Performance-Tracing.
- `SENTRY_ENVIRONMENT` (Default `production`).
- `SENTRY_RELEASE` – z.B. `v1.35.0`, damit Fehler pro Release gruppiert werden.

---

## 🩺 Monitoring & Debugging (v1.34.0)

- **`GET /api/health`** – Liveness-Probe, kein DB-Zugriff. Für Railway/Uptime-Robot: reagiert der Worker überhaupt noch?
- **`GET /api/readiness`** – Readiness-Probe, macht einen `SELECT 1` gegen die DB und liefert die Anzahl angewendeter Migrationen. Antwortet mit HTTP 503, wenn die DB nicht erreichbar ist – ideal als Deploy-Health-Check.
- **`X-Request-ID`-Header** – jede Response spiegelt eine 12-stellige Request-ID. Alle Log-Zeilen enthalten diese ID in eckigen Klammern, sodass sich ein fehlgeschlagener Request in Railway-Logs Ende-zu-Ende durchgreppen lässt. Der Client darf einen eigenen Wert mitschicken (`X-Request-ID: eigene-id`) – nützlich, wenn du auf Frontend-Seite Sentry/Datadog anbindest.

---

## 🔐 Sicherheit

- Passwörter werden mit **bcrypt** gehasht
- JWT-Auth mit konfigurierbarem Secret
- Rate-Limiting auf Login (`5/min`) und Schreib-Endpoints
- Admin-Endpoints separat abgesichert (`require_admin`)
- User können nur ihre eigenen Daten lesen/schreiben (Ownership-Checks in allen Endpoints)
- Snapshots werden per User isoliert; globale Auto-Backups nur für Admins

---

## 📁 Projekt-Struktur

```
Website/
├── backend/
│   ├── main.py                  # FastAPI-App & Sparziel-Endpoints (seit v1.15.1 verschlankt)
│   ├── schemas.py               # Pydantic-Models (ausgelagert v1.15.1)
│   ├── helpers.py               # Utility-Funktionen (ausgelagert v1.15.1)
│   ├── deps.py                  # Rate-Limiter, geteilte Utilities
│   ├── auth.py                  # JWT + bcrypt
│   ├── database.py              # asyncpg-Pool, Init, Migrationen
│   ├── routers/                 # Ausgelagerte Endpoint-Gruppen (expenses, notes)
│   ├── services/                # OCR, AI-Parser, Backup, Ausgaben-Logik
│   ├── migrations/sql/          # nummerierte SQL-Migrationen
│   └── tests/
├── docs/
│   └── BLOG_KONZEPT.md          # Konzept fuer das kommende Blog-Modul
└── frontend/
    ├── index.html               # Dashboard-Landing
    ├── sparziel/                # Sparziel-Tracker
    │   ├── index.html           # nur noch Markup (v1.15.1)
    │   ├── sparziel.css         # ausgelagerte Styles (v1.15.1)
    │   └── sparziel.js          # ausgelagerte Logik (v1.15.1)
    ├── ausgaben/                # Ausgaben-Tracker (bereits modular)
    ├── notizen/                 # Notizen
    ├── health/                  # Gesundheit (Auto Health Export Sync)
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


