-- Schach: Einstellungen fuer die Automatik (v1.84.0)
--
-- Zwei Takte, weil es zwei verschiedene Dinge sind:
--
--   * Wertungszahlen aendern sich nur, wenn gespielt wurde. Sie im
--     Minutentakt abzufragen waeren rund 1.400 Abfragen am Tag je Plattform
--     fuer eine Zahl, die sich an den meisten Tagen gar nicht bewegt --
--     deshalb ein Takt in Minuten, und zwar nur, SOLANGE DIE SEITE OFFEN IST.
--   * Partien holt der Server einmal taeglich von sich aus. Dafuer muss keine
--     Seite offen sein, und einmal am Tag reicht: aeltere Partien laufen
--     nicht weg.
--
-- ``last_auto_at`` ist der Riegel gegen Doppellaeufe: der Tagesjob prueft
-- nicht die Uhr allein, sondern ob heute schon gelaufen wurde. Ein Neustart
-- des Containers zur vollen Stunde loest sonst einen zweiten Lauf aus.
CREATE TABLE IF NOT EXISTS chess_settings (
    user_id        INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    -- Taeglicher Lauf des Servers: neue Partien holen und eine Tageszeile
    -- fuer die Wertung schreiben.
    auto_daily     BOOLEAN NOT NULL DEFAULT TRUE,
    daily_hour     SMALLINT NOT NULL DEFAULT 4 CHECK (daily_hour BETWEEN 0 AND 23),
    -- Takt der Aktualisierung bei offener Seite, in Minuten. 0 = aus.
    live_minutes   SMALLINT NOT NULL DEFAULT 15
                   CHECK (live_minutes IN (0, 5, 15, 30, 60)),
    last_auto_at   TIMESTAMPTZ,
    last_auto_note TEXT
);
