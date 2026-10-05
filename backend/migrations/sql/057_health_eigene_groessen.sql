-- Gesundheit: eigene Messgroessen und Werte von Hand (v2.37.0)
--
-- Bisher kam jede Zahl im Gesundheitsmodul vom iPhone (Auto Health Export).
-- Was es dort nicht gibt -- „Rueckenschmerzen 1-10“, „Glaeser Wasser“ --,
-- liess sich nirgends festhalten, und was es gibt, aber an einem Tag nicht
-- gemessen wurde (Gewicht auf einer Waage ohne App), auch nicht.
--
-- 1) ``health_eigene_groessen``: Name, Einheit und ob ueber den Tag summiert
--    wird (Glaeser Wasser) oder ein Messwert gilt (Schmerz, Gewicht).
-- 2) ``health_eigene_werte``: die Werte dazu, mit echtem Fremdschluessel --
--    ein Verweis als Text in ``health_metric_samples.metric_type`` ueberlebte
--    ein Zurueckspielen mit neuen IDs nicht.
--
-- Werte fuer VORHANDENE Groessen (Gewicht, Ruhepuls, Blutdruck, Blutzucker)
-- brauchen keine neue Tabelle: sie stehen in den bestehenden mit
-- ``source = 'manual'`` und erscheinen dadurch in denselben Diagrammen.

CREATE TABLE IF NOT EXISTS health_eigene_groessen (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    einheit     TEXT,
    kumulativ   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_health_eigene_groessen_user ON health_eigene_groessen(user_id);

CREATE TABLE IF NOT EXISTS health_eigene_werte (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    groesse_id  INTEGER NOT NULL REFERENCES health_eigene_groessen(id) ON DELETE CASCADE,
    recorded_at TIMESTAMPTZ NOT NULL,
    sample_date DATE NOT NULL,
    wert        NUMERIC NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_health_eigene_werte_groesse
    ON health_eigene_werte(user_id, groesse_id, sample_date);
