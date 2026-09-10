-- Abgelehnte Laden-Zusammenfuehrungen (v1.81.0)
--
-- Der CSV-Import legt Laeden aus den Zahlungsempfaengern des Kontoauszugs an
-- und fasst dabei schon zusammen, was er erkennen kann ("AMAZON.DE" ->
-- vorhandener Laden "Amazon"). Was er NICHT aufloesen kann, sind Dubletten,
-- die vorher schon im Bestand lagen oder erst durch den Import daneben
-- entstanden sind: "Lidl" neben "Lidl PLUS", "Rewe" neben "REWE Markt".
--
-- Deshalb dasselbe Muster wie bei Bon-Duplikaten (024) und Produkt-Varianten
-- (028): der Server schlaegt Kandidaten vor, der Nutzer entscheidet. Lehnt er
-- einen Vorschlag ab, weil es eben doch zwei verschiedene Laeden sind, darf
-- er nicht bei jedem Seitenaufruf erneut auftauchen. Eine Vorschlagsgruppe
-- hat keine stabile ID (sie wird bei jeder Anfrage frisch geclustert),
-- deshalb dient die sortierte, mit "|" verbundene Liste der Laden-IDs als
-- Fingerabdruck.

CREATE TABLE IF NOT EXISTS dismissed_store_merges (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    store_ids  TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, store_ids)
);

CREATE INDEX IF NOT EXISTS idx_dismissed_store_merges_user
    ON dismissed_store_merges(user_id);
