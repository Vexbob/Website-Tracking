-- Paket 14: Eigenständige Notizen (Schnell-Ablage mit Tags, Farben, Pin, Archiv).
-- Idempotent. Jede Notiz gehört genau einem User.

CREATE TABLE IF NOT EXISTS notes (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT '',
    color       TEXT NOT NULL DEFAULT 'default',   -- default|red|orange|yellow|green|blue|purple|pink
    pinned      BOOLEAN NOT NULL DEFAULT FALSE,
    archived    BOOLEAN NOT NULL DEFAULT FALSE,
    tags        TEXT[]   NOT NULL DEFAULT '{}',
    sort_order  INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id);
CREATE INDEX IF NOT EXISTS idx_notes_user_updated ON notes(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_user_pinned ON notes(user_id, pinned);
CREATE INDEX IF NOT EXISTS idx_notes_user_archived ON notes(user_id, archived);
CREATE INDEX IF NOT EXISTS idx_notes_tags ON notes USING GIN (tags);

-- updated_at automatisch bei jeder Änderung aktualisieren.
CREATE OR REPLACE FUNCTION notes_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_notes_touch ON notes;
CREATE TRIGGER trg_notes_touch
    BEFORE UPDATE ON notes
    FOR EACH ROW
    EXECUTE FUNCTION notes_touch_updated_at();
