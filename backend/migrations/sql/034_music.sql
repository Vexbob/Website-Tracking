-- Musik-Modul (v1.67.0) — das Hoerregister aus dem Spotify-Datenexport
--
-- Die Daten kommen NICHT von einer Schnittstelle, sondern als CSV aus dem
-- Programm "Spotify-Export" (eigenes Werkzeug, liegt neben diesem Repo). Es
-- fasst die Rohwiedergaben bereits zu Bloecken zusammen:
--
--     Block                                    Periode    Interpret  Titel   Wiedergaben
--     Anfang bis heute · woechentlich · nach Titel   2026-KW01  Marsimoto  ...     5
--
-- Deshalb speichert dieses Modul KEINE Einzelwiedergaben, sondern genau die
-- zusammengefassten Zeilen. Zehn Jahre Hoerhistorie als Einzelereignisse
-- waeren einige hunderttausend Zeilen, von denen niemand je eine einzelne
-- nachschlaegt; die Zusammenfassung ist die Aufloesung, in der man diese
-- Daten tatsaechlich liest.
--
-- Die Aufloesung steht deshalb IN der Zeile (``grain``): aeltere Jahre duerfen
-- jaehrlich oder monatlich vorliegen, die letzten Monate woechentlich. Beim
-- Anzeigen wird nur noch nach oben zusammengefasst (Woche -> Monat -> Jahr),
-- nie nach unten aufgeteilt.

-- ---------- Ein Upload ----------
-- Jeder Upload wird protokolliert, damit spaeter nachvollziehbar ist, woher
-- eine Zeile stammt, und damit ein versehentlicher Import als Ganzes wieder
-- verschwinden kann.
CREATE TABLE IF NOT EXISTS music_imports (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename       TEXT,
    size_bytes     INTEGER NOT NULL DEFAULT 0,
    uploaded_at    TIMESTAMPTZ DEFAULT NOW(),
    rows_read      INTEGER NOT NULL DEFAULT 0,   -- Datenzeilen in der Datei
    rows_written   INTEGER NOT NULL DEFAULT 0,   -- davon uebernommen
    rows_skipped   INTEGER NOT NULL DEFAULT 0,   -- ohne Periode/ohne Titel
    rows_replaced  INTEGER NOT NULL DEFAULT 0,   -- vorher geloescht (Zeitraum-Ersatz)
    -- Was in der Datei stand: je Block Bezeichnung, Raster, Zeitraum, Zeilen.
    -- Als JSONB, weil die Zahl der Bloecke frei ist und niemand danach filtert.
    blocks         JSONB NOT NULL DEFAULT '[]'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_music_imports_user
    ON music_imports(user_id, uploaded_at DESC);

-- ---------- Das Register ----------
-- Eine Zeile = eine Gruppe (Titel / Interpret / Album / …) in einer Periode.
CREATE TABLE IF NOT EXISTS music_entries (
    id              BIGSERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- Beim Loeschen eines Protokoll-Eintrags bleiben die Daten stehen; das
    -- Protokoll ist Herkunftsnachweis, nicht Besitzer.
    import_id       INTEGER REFERENCES music_imports(id) ON DELETE SET NULL,

    block           TEXT NOT NULL DEFAULT '',   -- Beschriftung aus der CSV
    grain           TEXT NOT NULL,              -- tag | woche | monat | jahr
    period_key      TEXT NOT NULL,              -- 2026-KW01 | 2026-09 | 2026 | 2026-09-08
    -- Der erste und letzte Tag der Periode. Alles Zeitliche rechnet damit,
    -- nicht mit dem Schluessel: ein Datum laesst sich vergleichen, ein
    -- "2026-KW01" nicht.
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,

    group_by        TEXT NOT NULL DEFAULT 'titel',  -- wonach die CSV gruppiert hat
    kind            TEXT NOT NULL DEFAULT '',       -- Musik | Podcast | Hoerbuch (leer: sagt die CSV nicht)
    artist          TEXT NOT NULL DEFAULT '',
    title           TEXT NOT NULL DEFAULT '',
    album           TEXT NOT NULL DEFAULT '',

    plays           INTEGER NOT NULL DEFAULT 0,
    ms_played       BIGINT,      -- aus "Minuten"/"Stunden", falls exportiert
    skipped         INTEGER,
    distinct_titles INTEGER,
    first_play      TIMESTAMPTZ,
    last_play       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),

    -- Identitaet einer Zeile. Als Hash statt als mehrspaltiger UNIQUE-Index,
    -- weil Titel + Interpret + Album zusammen laenger werden koennen als ein
    -- btree-Eintrag tragen darf (~2700 Byte) — ein einziger sehr langer
    -- Podcast-Titel wuerde den Import sonst mit einem Indexfehler abbrechen.
    entry_hash      TEXT GENERATED ALWAYS AS (
        md5(grain || '|' || period_key || '|' || group_by || '|' ||
            kind || '|' || artist || '|' || title || '|' || album)
    ) STORED,
    UNIQUE (user_id, entry_hash)
);

-- Zeitfilter und Zusammenfassung laufen immer ueber period_start.
CREATE INDEX IF NOT EXISTS idx_music_entries_user_period
    ON music_entries(user_id, period_start);
-- Ranglisten je Interpret bzw. Titel.
CREATE INDEX IF NOT EXISTS idx_music_entries_user_artist
    ON music_entries(user_id, artist);
-- "Was kam mit diesem Upload?" und das Zuruecknehmen eines Imports.
CREATE INDEX IF NOT EXISTS idx_music_entries_import
    ON music_entries(import_id);
