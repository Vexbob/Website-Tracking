-- Overcast: Podcast-Folgen aus dem OPML-Export (v2.42.0)
--
-- Overcast gibt keinen Verlauf heraus, sondern einen Stand: je Folge, ob sie
-- fertig gehoert ist, wie weit eine angefangene ist und wann sich das zuletzt
-- geaendert hat. Aeltere Folgen fallen irgendwann aus dem Export. Deshalb
-- ERGAENZT ein Import (je Folge eine Zeile ueber ``overcast_id``) und loescht
-- nie, was in einer neueren Datei fehlt.
--
-- ``podcast_folgen`` ist die Quelle. Die Zeilen im Hoerregister
-- (``music_entries`` mit block = 'Overcast') werden nach jedem Import daraus
-- neu gebaut -- so rechnen Ueberblick, Ranglisten und Verlauf ohne zweiten
-- Weg mit. ``laenge_s`` kommt aus dem RSS-Feed der Sendung
-- (``itunes:duration``), weil der Export sie nicht nennt.

CREATE TABLE IF NOT EXISTS podcast_imports (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dateiname      TEXT,
    hochgeladen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    folgen         INTEGER NOT NULL DEFAULT 0,
    neu            INTEGER NOT NULL DEFAULT 0,
    aktualisiert   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_podcast_imports_user ON podcast_imports(user_id, hochgeladen_at DESC);

CREATE TABLE IF NOT EXISTS podcast_folgen (
    id              BIGSERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    import_id       INTEGER REFERENCES podcast_imports(id) ON DELETE SET NULL,
    overcast_id     TEXT NOT NULL,
    podcast         TEXT NOT NULL DEFAULT '',
    feed_url        TEXT NOT NULL DEFAULT '',
    titel           TEXT NOT NULL DEFAULT '',
    veroeffentlicht TIMESTAMPTZ,
    zuletzt         TIMESTAMPTZ,
    gehoert         BOOLEAN NOT NULL DEFAULT FALSE,
    fortschritt_s   INTEGER,
    laenge_s        INTEGER,
    geloescht       BOOLEAN NOT NULL DEFAULT FALSE,
    audio_url       TEXT NOT NULL DEFAULT '',
    UNIQUE (user_id, overcast_id)
);
CREATE INDEX IF NOT EXISTS idx_podcast_folgen_user ON podcast_folgen(user_id, zuletzt);
