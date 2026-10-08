-- Essenstagebuch: Lebensmittel aus der eigenen Liste nehmen (v2.42.0)
--
-- Das Tagebuch fuehrt keine Lebensmittel-Tabelle: „Meine Lebensmittel“ ist,
-- was je eingetragen wurde, zusammengefasst je Schreibweise klein
-- geschrieben (wie die Schnellwahl). Wer einen Vertipper oder etwas
-- Einmaliges loswerden will, nimmt es hier heraus -- die Tage, an denen es
-- steht, bleiben, wie sie waren. Wird derselbe Name wieder eingetragen, ist
-- er zurueck (der Eintrag loescht die Zeile hier).

CREATE TABLE IF NOT EXISTS food_diary_ausgeblendet (
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    schluessel      TEXT NOT NULL,
    ausgeblendet_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, schluessel)
);
