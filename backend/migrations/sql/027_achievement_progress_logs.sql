-- Fortschritts-Journal fuer Meilenstein-Ziele (v1.41.0)
--
-- Bisher hinterliess eine Wertaenderung an einem Meilenstein-Ziel nur dann
-- eine Spur, wenn dabei eine Meilenstein-Schwelle ueberschritten wurde: der
-- "+x"-Button und das manuelle Setzen des Werts haben ``current_value``
-- ueberschrieben und sonst nichts. Im Log klaffte dadurch eine Luecke -- man
-- sah 10 km und 20 km, aber nicht, wann die 14 km dazwischen dazukamen.
--
-- Diese Tabelle protokolliert jede Aenderung von ``current_value`` mit Vorher-
-- /Nachher-Wert. Sie traegt bewusst KEINEN Geldbetrag: ausgezahlt wird
-- weiterhin ausschliesslich beim Meilenstein (achievement_logs), diese Zeilen
-- sind reine Historie.

CREATE TABLE IF NOT EXISTS achievement_progress_logs (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    achievement_id INTEGER NOT NULL REFERENCES achievements(id) ON DELETE CASCADE,
    old_value      NUMERIC NOT NULL,
    new_value      NUMERIC NOT NULL,
    delta          NUMERIC NOT NULL,
    -- TRUE, wenn dieselbe Aenderung zusaetzlich mindestens einen Meilenstein
    -- ausgeloest hat. Das Frontend kann die Zeile dann als "davon Meilenstein"
    -- markieren, statt sie wie eine reine Zwischenmeldung zu zeigen.
    hit_milestone  BOOLEAN NOT NULL DEFAULT FALSE,
    note           TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ach_progress_user_date
    ON achievement_progress_logs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ach_progress_achievement
    ON achievement_progress_logs(achievement_id);
