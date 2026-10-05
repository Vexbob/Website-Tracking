-- Sparziel: jede Aenderung in den Verlauf, Ideen als fertige Vorlage, Links
--
-- 1) ``sparziel_aenderungen`` haelt fest, was am Sparziel-Modul selbst
--    veraendert wurde: Wochenziel angelegt, Belohnung von 5 auf 8 EUR
--    geaendert, Achievement geloescht, Sparziel pausiert. Bisher stand im
--    Verlauf nur, was GELD bewegt hat (Check-ins, Meilensteine, Uebertraege)
--    -- dass ein Wochenziel gestern noch 3 und heute 5 Check-ins verlangt,
--    stand nirgends. Die Zeile traegt den Namen des Objekts zum Zeitpunkt der
--    Aenderung, weil das Objekt selbst spaeter umbenannt oder geloescht sein
--    kann; ``objekt_id`` ist nur ein Hinweis, kein Fremdschluessel.
--
-- 2) ``future_ideas.config`` ist die vollstaendige Vorlage eines Wochenziels
--    oder Achievements (dieselben Felder wie beim Anlegen, als JSON-Text --
--    wie ``achievements.auto_params``). Eine Idee laesst sich damit fertig
--    ausarbeiten und spaeter mit einem Tipp aktivieren. Ideen ohne Vorlage
--    bleiben, was sie waren: ein Titel.
--
-- 3) ``link`` an Sparziel und Wunsch: wo es das Ding zu kaufen gibt.

CREATE TABLE IF NOT EXISTS sparziel_aenderungen (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    aktion      TEXT NOT NULL,
    objekt      TEXT NOT NULL,
    objekt_id   INTEGER,
    titel       TEXT NOT NULL,
    details     TEXT
);
CREATE INDEX IF NOT EXISTS idx_sparziel_aenderungen_user
    ON sparziel_aenderungen(user_id, created_at DESC);

ALTER TABLE future_ideas    ADD COLUMN IF NOT EXISTS config TEXT;
ALTER TABLE savings_goals   ADD COLUMN IF NOT EXISTS link   TEXT;
ALTER TABLE potential_goals ADD COLUMN IF NOT EXISTS link   TEXT;
