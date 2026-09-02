-- Import-Protokoll fuer den automatisierten Health-Sync (v1.40.0)
--
-- Motivation: Wenn die Auto-Health-Export-App einen Tag mit offensichtlich
-- falschen Werten liefert (z.B. 750 statt 4700 Schritte), war bisher nicht
-- nachvollziehbar, ob die App zu wenig geschickt oder der Ingest falsch
-- geparst hat -- der Roh-Payload landete nur als 160-Zeichen-Preview im Log.
-- Diese Tabelle haelt den kompletten Body jedes Sync-Aufrufs vor, damit er
-- im Frontend heruntergeladen und mit den importierten Werten verglichen
-- werden kann.
--
-- Aufbewahrung: pro User werden nur die letzten N Eintraege behalten
-- (ENV ``HEALTH_IMPORT_LOG_KEEP``, Default 200), jeder Payload wird bei
-- ``HEALTH_IMPORT_LOG_MAX_BYTES`` (Default 5 MB) abgeschnitten -- dann steht
-- ``truncated=TRUE``. Damit bleibt die Tabelle beschraenkt, auch wenn die App
-- mehrmals stuendlich synct.

CREATE TABLE IF NOT EXISTS health_import_log (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Wie der Payload reinkam: multipart / multipart-manual / multipart-raw /
    -- json / csv / csv-fallback / empty
    kind          TEXT NOT NULL,
    filename      TEXT,
    content_type  TEXT,
    user_agent    TEXT,
    size_bytes    INTEGER NOT NULL DEFAULT 0,
    truncated     BOOLEAN NOT NULL DEFAULT FALSE,
    payload       BYTEA,
    -- Ingest-Ergebnis dieses Teils (metrics_imported, workouts_imported, ...)
    stats         JSONB
);
CREATE INDEX IF NOT EXISTS idx_health_import_log_user
    ON health_import_log(user_id, created_at DESC);
