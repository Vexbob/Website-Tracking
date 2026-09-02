# Vexbob

**Persönliche Web-App mit Sparziel-Tracker, Ausgaben, Notizen, Gesundheit & Blog — selfhosted, PWA-fähig, Multi-User mit Admin-Bereich.**

---

## ✨ Module

### 💰 Sparziel-Tracker
Mehrere parallele Sparziele mit eigenem Kontostand. Achievements (Meilensteine mit Belohnungen), Wochen-/Monatsziele mit Streak-Boni, Aktivitäts-Log, 365-Tage-Heatmap, Trophäen-Wand. Ein automatisches „Allgemein"-Konto fängt Belohnungen auf, wenn im Sparziel kein Platz mehr ist. CSV-Export, JSON-Backup mit täglichen Snapshots.

### 📝 Notizen
Notiz-Ablage im Apple-Notes-Stil (Master-Detail) mit WYSIWYG-Editor (`contenteditable`, HTML-Speicherformat), Markdown-Shortcuts beim Tippen, Task-Checkboxen, Farblabels, Pin, Archiv, Auto-Save und Live-Suche.

### 💶 Ausgaben-Tracker
Kassenbon-OCR (Google Cloud Vision) mit editierbaren Ergebnissen vor dem Speichern, optionaler KI-Parser (Gemini) für bessere Artikelerkennung inkl. Markenzuordnung (~800 vordefinierte Marken). Läden & Kategorien mit Auto-Kategorisierung, Schnelleingabe, wiederkehrende Ausgaben, Duplikat-Warnung. Statistikseite mit Zeitraumfilter, KPI-Kacheln, Trend-Chart, Kategorie-/Laden-Auswertung, Preisverlauf pro Produkt, Läden-Vergleich. Export als CSV/JSON.

### 🏋️ Gesundheit
Sync-Ziel für die iPhone-App **Auto Health Export**: eigener API-Key pro User (getrennt vom Login), idempotenter Import (`POST /api/health/import`) für Vitalwerte, Blutdruck/-zucker, Schlaf und Workouts. Optionaler AI-Fallback für unbekannte Metriknamen. Manueller Nachimport per CSV oder JSON möglich. Jeder Sync landet mit seinem Roh-Payload im **Import-Protokoll** (`GET /api/health/imports`) und ist von dort herunterladbar — damit lässt sich prüfen, ob ein auffälliger Wert schon so geliefert oder erst beim Import falsch verarbeitet wurde. Frontend mit Dashboard, Vitalwert-Charts, Schlafphasen und Workout-Historie.

### 📰 Blog
Öffentlich lesbares Blog-Modul (`/blog/`, keine Anmeldung nötig) — die einzige nach außen sichtbare Fläche der App. Admin-Editor mit derselben WYSIWYG-Logik wie Notizen, Bild-Einbindung per Drag & Drop/Paste, Tag-Filter, Lesezeit-Schätzung, View-Counter, XSS-Schutz per Whitelist-Sanitizer.

### ⬇️ Gesamt-Export
Eine Dashboard-Kachel exportiert alle Module gleichzeitig als eine CSV-Datei (`GET /api/export/all`), abschnittsweise gegliedert.

### 👤 User- & Admin-System
JWT-Login, Admin-Bereich mit Invite-Tokens (Nutzer anlegen ohne Passwortvergabe), Passwort-Reset, Rate-Limiting auf allen kritischen Endpoints.

### 🧭 UX
Globaler Modul-Switcher in der Navbar, Dark-Mode, responsive & PWA-installierbar, Drag-&-Drop-Sortierung, Undo-Toasts.

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
