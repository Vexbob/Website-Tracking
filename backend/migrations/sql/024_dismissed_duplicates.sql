-- Duplikat-Vorschlaege dauerhaft ausblenden (v1.39.0)
-- Eine Duplikat-Gruppe hat keine stabile ID (wird bei jedem Request frisch
-- geclustert) -- als Fingerabdruck dient die sortierte, kommagetrennte Liste
-- der beteiligten expense-IDs.

CREATE TABLE IF NOT EXISTS dismissed_expense_duplicates (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expense_ids  TEXT NOT NULL,
    dismissed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, expense_ids)
);
CREATE INDEX IF NOT EXISTS idx_dismissed_dup_user ON dismissed_expense_duplicates(user_id);
