# Vexbob

Persönliche Web-App — Sparziele, Ausgaben, Notizen, Gesundheit, Ernährung, Musik, Schach, CS2 und ein öffentlicher Blog. Selbst gehostet, PWA, mehrere Konten mit Admin-Bereich.

## Module

| Modul | Worum es geht |
| --- | --- |
| **Sparziel** | Sparziele mit eigenem Kontostand, Achievements (auch aus anderen Modulen gespeist), Wochen-/Monatsziele mit Streak-Bonus und Teilbelohnung, Puffer-Konto, Log, Trophäen |
| **Ausgaben** | Kassenbons per OCR (Google Vision, optional Gemini-Parser), Positionen, Läden, Kategorien, Statistik, Dubletten, Import aus dem Bank-CSV |
| **Notizen** | Master-Detail-Editor mit Auto-Save, Checkboxen, Farben, Pin und Archiv |
| **Gesundheit** | Ziel für die iPhone-App *Auto Health Export*: Vitalwerte, Schlaf, Workouts |
| **Essenstagebuch** (`/essen/`) | Nur notieren, was es gab — Name und Stufe, keine Mengen |
| **Nährwerte** (`/naehrwerte/`) | Mengen, kcal und Makros, Tagesziele, Gerichte, Strichcode, eigener Open-Food-Facts-Katalog |
| **Musik** | Hörregister aus dem Spotify-Datenexport |
| **Schach** | Partien und Wertung von Lichess/Chess.com |
| **CS2** | Bestand an Spielgegenständen, sein Zeitwert und der Preisverlauf je Gegenstand |
| **Blog** | Öffentlich unter `/blog/`, geschrieben im Admin-Bereich |

Dazu: Gesamt-Export aller Module (CSV oder ZIP, mit Zeitraum und Verdichtung), JSON-Backup, anpassbare Tab-Leiste, Versions-Zeitstrahl.

## Technik

- **Backend:** Python 3.11, FastAPI, asyncpg, PostgreSQL. Versionen sind in `backend/requirements.txt` gepinnt — getestet wird gegen genau diese.
- **Frontend:** reines HTML/CSS/JS ohne Build-Schritt, Chart.js, Service Worker. Nur dunkles Design.
- **Migrationen:** `backend/migrations/sql/`, nummeriert, beim Start angewendet, per Checksumme gegen nachträgliches Ändern geschützt.

## Lokal starten

```bash
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql://user:pass@localhost:5432/vexbob"   # Postgres mit SSL
export SECRET_KEY="langer-zufaelliger-string"
export CORS_ORIGINS="http://localhost:5500"
export ADMIN_BOOTSTRAP_USERNAME=admin ADMIN_BOOTSTRAP_PASSWORD=...  # nur beim ersten Start
uvicorn main:app --reload --port 8000

cd ../frontend && python3 -m http.server 5500
```

Die Backend-Adresse steht **zweimal** im Frontend: `frontend/js/config.js` und `frontend/js/api.js` (`API_BASE`). Für lokales Arbeiten beide auf `http://localhost:8000` stellen.

Optional: `GEMINI_API_KEY` (KI-Parser), `OCR_PROVIDER=google` + `GOOGLE_APPLICATION_CREDENTIALS_JSON` (Bon-OCR), `SENTRY_DSN`.

Tests: `cd backend && pytest -q` (braucht zusätzlich `httpx`).

## Ausliefern

**Ein Push auf `main` ist ein Deploy:** Railway baut und startet danach automatisch neu. Was gepusht wird, ist kurz darauf live — deshalb vorher die Tests gegen die gepinnten Versionen laufen lassen. Neue Migrationen laufen beim Start sofort auf der echten Datenbank.

## Lebensmittel-Katalog (optional)

`backend/data/off-katalog-dach.csv.gz` ist ein Auszug aus Open Food Facts (ODbL, siehe `backend/data/HERKUNFT.md`). Eingespielt wird er als Admin unter *Nährwerte → Lebensmittel → Katalog einspielen* oder per `python backend/scripts/off_katalog.py <datei> --einspielen`. Ohne Katalog fragt die Suche live bei Open Food Facts.

## Wo was steht

- `docs/DESIGN.md` und `frontend/design.html` — Designsprache und Bausteine, verbindlich.
- `frontend/js/changelog.js` — Versionsverlauf; `frontend/js/version.js` — aktuelle Version.
- `tools/vorschau/` — rendert Seiten mit gefälschtem Backend als PNG.
