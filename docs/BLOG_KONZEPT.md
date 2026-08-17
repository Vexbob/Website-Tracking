# 📰 Blog-Modul für Vexbob — Konzept & Roadmap

> Status: **Konzept** (v1.15.0 – noch nicht implementiert)
> Ziel: Öffentlich lesbarer Blog, der auf der **Login-Seite** angeteasert wird
> und ohne Login voll konsumierbar ist. Schreib-/Verwaltungsseite bleibt privat.

---

## 1. Idee & Motivation

Bisher ist Vexbob eine reine „Login-Only-App". Alles was hinter `/` liegt,
verlangt einen JWT-Token. Damit hat die Domain nach außen keinerlei Inhalt —
die Login-Seite ist eine leere Karte mit zwei Feldern.

Der **Blog** soll das ändern:

- **Öffentlich lesbar** — kein Login nötig, direkt indexierbar (SEO).
- **Von Admin(s) gepflegt** — im Backend hinter der bestehenden `is_admin`-Rolle.
- **Auf der Login-Seite prominent** — die letzten 3–5 Posts als Teaser-Liste,
  darüber (oder darunter) das eigentliche Login-Formular.
- **Persönlich** — Log-artige Einträge über Projekte, Gedanken, Musik, was
  gerade in der Küche ausprobiert wird. Kein „Corporate-Blog".

Blog-Inhalte sind unabhängig vom User-Datenmodell (Sparziel, Ausgaben, Notizen).
Sie leben in einer eigenen Tabelle und sind global sichtbar.

---

## 2. URL-Struktur (öffentlich)

```
/                              → Dashboard  (login-required, unverändert)
/private/login.html            → Login-Seite (jetzt mit Blog-Teasern rechts/unten)
/blog/                         → Blog-Übersicht (öffentlich)
/blog/#slug-abc                → Detailansicht via Hash-Deeplink
/blog/tag/musik                → optional: Tag-Filter (Query-Param oder Route)
/blog/rss                      → optional: RSS-Feed
```

**Wichtig:** Kein Auth-Check auf `/blog/*`. Die Static-Files liegen unter
`Website/frontend/blog/` und laden ihre Daten von einem neuen, **ungeschützten**
API-Endpoint `GET /api/public/blog/*`.

---

## 3. Datenmodell

Neue Tabelle in einer neuen Migration (`016_blog.sql`):

```sql
CREATE TABLE IF NOT EXISTS blog_posts (
    id            SERIAL PRIMARY KEY,
    slug          TEXT NOT NULL UNIQUE,          -- URL-Fragment, z.B. "mein-erster-post"
    title         TEXT NOT NULL,
    subtitle      TEXT,                          -- optional, für Teaser
    content_md    TEXT NOT NULL,                 -- Markdown-Light (wie Notizen)
    author_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    author_name   TEXT,                          -- Anzeigename (falls User gelöscht wird)
    cover_url     TEXT,                          -- optional, z.B. relativer Pfad
    tags          TEXT[],                        -- optional, Postgres-Array
    published_at  TIMESTAMPTZ,                   -- NULL = Entwurf
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    view_count    INTEGER NOT NULL DEFAULT 0     -- optional Analytics
);
CREATE INDEX IF NOT EXISTS idx_blog_posts_pub ON blog_posts(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_blog_posts_slug ON blog_posts(slug);
```

**Entscheidung „ein-Autor vs. mehr-Autor":** Da Vexbob mehrere Admins haben
kann, speichern wir `author_id` (FK) + `author_name` als Snapshot. Wenn ein
Admin-Account gelöscht wird, bleiben seine Posts sichtbar.

---

## 4. API-Endpoints

### 4.1 Öffentlich (kein Auth-Header)

| Methode | Pfad                              | Zweck                                            |
|---------|-----------------------------------|--------------------------------------------------|
| GET     | `/api/public/blog/posts`          | Liste veröffentlichter Posts (paginierbar)       |
| GET     | `/api/public/blog/posts/{slug}`   | Einzelner Post inkl. Content                     |
| GET     | `/api/public/blog/tags`           | Liste aller genutzten Tags mit Post-Count        |
| GET     | `/api/public/blog/rss`            | (optional) RSS-2.0-Feed als XML                  |

- **Rate-Limit:** großzügig, aber gesetzt (z.B. `120/min` pro IP) — verhindert Scraper-Abuse.
- Nur Posts mit `published_at IS NOT NULL AND published_at <= NOW()` werden zurückgegeben.
- Feld `view_count` wird bei GET auf Detail-Endpoint per `UPDATE ... RETURNING` erhöht — best-effort.

### 4.2 Admin (JWT + `is_admin`)

| Methode | Pfad                              | Zweck                                            |
|---------|-----------------------------------|--------------------------------------------------|
| GET     | `/api/admin/blog/posts`           | Alle Posts inkl. Entwürfe                        |
| POST    | `/api/admin/blog/posts`           | Post anlegen                                     |
| PUT     | `/api/admin/blog/posts/{id}`      | Bearbeiten (Auto-Save-Pattern wie Notizen)       |
| POST    | `/api/admin/blog/posts/{id}/publish` | `published_at = NOW()`                        |
| POST    | `/api/admin/blog/posts/{id}/unpublish` | `published_at = NULL`                       |
| DELETE  | `/api/admin/blog/posts/{id}`      | Löschen                                          |

**Router-Datei:** `Website/backend/routers/blog_router.py`, im gleichen Stil
wie `notes_router.py` / `expenses_router.py`. Wird in `main.py` per
`app.include_router(blog_router)` eingebunden.

---

## 5. Frontend-Struktur

### 5.1 Neue Dateien

```
Website/frontend/blog/
├── index.html          → Übersicht + Detail-View (Master-Detail wie Notizen)
├── blog.js             → Rendering, Deeplink-Handling, Markdown-Rendering
└── admin.html          → Editor für Admins (Draft + Live-Preview)
    admin.js
```

### 5.2 Login-Seite umbauen

`Website/frontend/private/login.html` bekommt ein neues Zwei-Spalten-Layout:

```
┌─────────────────────────┬────────────────────────────────┐
│                         │  📰 Neueste Beiträge           │
│      [Login-Card]       │                                │
│  Benutzername [___]     │  • Titel 1  · vor 2 Tagen      │
│  Passwort     [___]     │  • Titel 2  · vor 1 Woche      │
│  [ Einloggen ]          │  • Titel 3  · vor 3 Wochen     │
│                         │                                │
│                         │  → Alle Beiträge lesen         │
└─────────────────────────┴────────────────────────────────┘
```

- Mobile: Login oben, Teaser darunter (Single-Column).
- Teaser lädt via `fetch('/api/public/blog/posts?limit=5')` **ohne Auth-Header**.
- Wenn Backend nicht antwortet: Teaser-Sektion leise ausblenden — Login bleibt nutzbar.
- Klick auf Titel → `/blog/#slug-xyz`.

### 5.3 Blog-Übersicht (`/blog/`)

- Header mit „← Zurück zur Anmeldung" (führt auf `/private/login.html`)
- Optional Nav-Bar: **[Alle] [Tag1] [Tag2] …**
- Kartengrid oder Listen-Layout, jede Karte:
  - Titel, Untertitel, Datum, Autor, Tag-Chips, „Weiter lesen →"
  - Cover-Bild (falls gesetzt) klein rechts oder oben
- Bei Klick: SPA-artig — Hash setzen, Detail-Bereich einblenden.

### 5.4 Detail-Ansicht

- Titel groß, darunter Metadaten (Datum, Autor, Lesezeit-Schätzung).
- Content aus `content_md` per **wiederverwendetem** Markdown-Renderer aus
  Notizen (dort schon vorhanden) — genau derselbe Stil (Überschriften,
  Listen, Code-Blöcke, Links, aber **ohne** interaktive Checkboxen).
- Optional: „Auf X teilen"-Buttons (Twitter, Mail).
- „← Zurück zur Übersicht"-Link.

### 5.5 Admin-Editor (`/blog/admin.html`)

- Nur mit Admin-Login erreichbar (redirect zu Login sonst).
- Split-Screen: links Markdown-Editor, rechts Live-Preview.
- Felder: Titel, Slug (auto aus Titel, überschreibbar), Untertitel,
  Cover-URL, Tags (Comma-Chips), Content (Textarea, monospace).
- Statuszeile: „Entwurf" / „Veröffentlicht am X" + Button
  `[Veröffentlichen] / [Zurückziehen]`.
- Auto-Save wie im Notizen-Modul (Debounce ~800 ms).

---

## 6. Feature-Set — Was der Blog kann

**MVP (Session 3+ Umsetzung):**
- Markdown-Posts mit Titel, Untertitel, Content, Autor, Datum
- Öffentliche Übersicht + Detail-Deeplink
- Admin-Editor mit Auto-Save
- Draft/Publish-Workflow
- Login-Seite mit Blog-Teasern

**Ausbaustufe 1:**
- **Tags** mit Filter-Route
- **Cover-Bilder** (Upload-Endpoint analog Fotos oder Bon-Bilder)
- **Lesezeit-Schätzung** (Wörter/200)
- **Suchleiste** in der Übersicht (Client-side über bereits geladene Posts)

**Ausbaustufe 2 (optional):**
- **RSS-Feed** (`/api/public/blog/rss`)
- **Anonyme Reaktionen** (❤️/🔥 pro Post, per IP-Fingerprint gegen Doppelklicks)
- **Kommentare** — bewusst weggelassen (Moderations-Aufwand + Spam-Risiko).
  Falls doch gewünscht: nur eingeloggte User dürfen kommentieren.
- **Verwandte Posts** unten (nach Tags)
- **Dark-Mode-optimierte Code-Blöcke** (Highlight.js einbinden)
- **Sitemap.xml** für SEO

---


## 7. Öffentlicher Zugriff — technische Details

### 7.1 CORS

Falls Frontend und Backend auf verschiedenen Domains laufen: `CORS_ORIGINS`
muss auch die Public-Domain enthalten. Beim MVP kein Problem, da alles
über nginx auf einer Domain läuft.

### 7.2 Service-Worker & Offline

Der bestehende Service-Worker (`sw.js`) sollte `/blog/*` **nicht** cachen,
damit Änderungen sofort sichtbar sind. Alternativ: stale-while-revalidate
für die Übersicht, network-first für Details.

### 7.3 SEO

- `<title>`, `<meta name="description">` pro Post via kleiner Server-Side-
  Injection oder Client-Side (weniger SEO-Wert, aber ok für persönliches Blog).
- OpenGraph-Tags (`og:title`, `og:image`) für Sharing.
- Für ernsthaftes SEO: Static-Site-Generation überlegen (Post beim
  Publish als statisches HTML in `/frontend/blog/posts/` rausschreiben).
  → **Nicht MVP.**

### 7.4 Sicherheit

- **Kein XSS**: Markdown-Renderer ist der von Notizen — der escaped bereits
  HTML. Für Bilder in Posts: nur relative URLs / eigene Domain erlauben.
- **Rate-Limit** auf Public-Endpoints gegen Scraping.
- Admin-Endpoints wie bisher via `require_admin`.

---

## 8. Migrations- & Deploy-Reihenfolge

1. SQL-Migration `016_blog.sql` schreiben & lokal testen
2. `blog_router.py` — Public + Admin-Endpoints
3. `Website/frontend/blog/index.html` + `blog.js` (Übersicht + Detail)
4. `Website/frontend/blog/admin.html` + `admin.js` (Editor)
5. `login.html` umbauen: Zwei-Spalten mit Blog-Teasern
6. `index.html` (Dashboard) — Kachel „Blog verwalten" für Admins
7. README-Update + Version bump

---

## 9. Offene Fragen (vor Umsetzung entscheiden)

- **Mehrsprachigkeit?** — Aktuell nein (nur DE).
- **Bilder in Posts** — eigener Upload oder externe URLs? Vorschlag: eigener
  Upload analog Fotos-Modul, Speicherung in `blog_media` Bucket.
- **Nur Admin darf schreiben, oder auch normale User?** — Vorschlag: **nur Admin**.
- **Posts sichtbar für eingeloggte User anders?** — Vorschlag: **nein**, gleich.
- **Analytics / Views** — Zähler mitloggen? Vorschlag: `view_count` reicht,
  kein externes Tool.
- **Volltextsuche** — bei überschaubarer Post-Zahl (<200) Client-side ok.
  Bei mehr: Postgres `to_tsvector` einbauen.

---

## 10. Aufwandsschätzung (grob)

| Komponente                          | Aufwand   |
|-------------------------------------|-----------|
| Migration + Router (Backend)        | ~2 h      |
| Blog-Übersicht + Detail (Frontend)  | ~2–3 h    |
| Admin-Editor mit Auto-Save          | ~2 h      |
| Login-Seite mit Teasern             | ~1 h      |
| README + Deploy + Tests             | ~1 h      |
| **Gesamt MVP**                      | **~8–9 h**|

Ausbaustufe 1 (Tags, Cover-Upload, Suche): + ~3–4 h
Ausbaustufe 2 (RSS, Reaktionen, verwandte Posts): + ~4–5 h

---

*Nächster Schritt: bei nächster Session „Session 3+" das MVP umsetzen.*

