# Vexbob

**Persönliche Web-App mit Sparziel-Tracker, Notizen, Rezeptbuch, Fotoalbum & mehr — Selfhosted, PWA-fähig, mit Multi-User & Admin-Bereich.**

> Vexbob ist ein modulares, privat gehostetes Toolkit für den Alltag: Sparziele mit Gamification tracken, Notizen ablegen, Rezepte sammeln, Fotos organisieren — alles unter einem Login, mit Dark-Mode und mobiler PWA-Installation.

---

## ✨ Features

### 💰 Sparziel-Tracker
- **Mehrere parallele Sparziele** – jedes mit eigenem Kontostand, jederzeit zwischen ihnen wechseln
- **Achievements** – Meilensteine mit Belohnungen (steigend oder fallend, mit optionalem Zielwert)
- **Wochen-/Monatsziele** – regelmäßige Check-ins mit **Streak-Boni**
- **Aktivitäts-Log** mit Wochenübersicht, Filter, Suche, Notizen pro Eintrag
- **GitHub-Style Heatmap** über 365 Tage
- **Trophäen-Wand** für abgeschlossene Ziele
- **CSV-Export**, **JSON-Backup & Restore**, automatische tägliche Snapshots

### 📝 Notizen
Schnelle Notiz-Ablage mit Kategorien.

### 🍳 Rezeptbuch
Persönliche Rezepte mit Zutaten, Schritten und Kategorien.

### 📸 Fotos
Privates Fotoalbum mit Upload und Galerie-Ansicht.

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
```

### 3. Backend starten
```bash
uvicorn main:app --reload --port 8000
```
Beim ersten Start werden Schema & Migrationen automatisch angewendet und ein Admin-User angelegt (Anmeldedaten stehen im Log).

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
    -e JWT_SECRET="..." \
    -e CORS_ORIGINS="https://deine-domain.tld" \
    -p 8000:8000 vexbob-backend
```

Das Frontend kann parallel z.B. hinter nginx/Caddy als Static-Site ausgeliefert werden.

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
│   ├── main.py                  # FastAPI-App & alle Endpoints
│   ├── auth.py                  # JWT + bcrypt
│   ├── database.py              # asyncpg-Pool, Init, Migrationen
│   ├── services/
│   │   └── backup.py            # Snapshots, Restore, Prune
│   ├── migrations/sql/          # nummerierte SQL-Migrationen
│   └── tests/
└── frontend/
    ├── index.html               # Dashboard-Landing
    ├── sparziel/                # Sparziel-Tracker (Hauptfeature)
    ├── notizen/                 # Notizen
    ├── rezeptbuch/              # Rezepte
    ├── photos/                  # Fotoalbum
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


