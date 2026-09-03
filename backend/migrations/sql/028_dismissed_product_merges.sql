-- Abgelehnte Produkt-Zusammenfuehrungen (v1.42.0)
--
-- Die Produkt-Seite schlaegt vor, Schreibvarianten desselben Artikels
-- zusammenzufuehren ("Gouda", "Gouda jung", "Goudakaese"). Lehnt der User einen
-- Vorschlag ab, weil es eben doch zwei verschiedene Produkte sind, darf er
-- nicht bei jedem Seitenaufruf erneut auftauchen. Eine Vorschlagsgruppe hat
-- keine stabile ID (sie wird bei jedem Request frisch geclustert), deshalb
-- dient die sortierte, mit "|" verbundene Liste ihrer Gruppenschluessel als
-- Fingerabdruck -- analog zu ``dismissed_expense_duplicates`` (Migration 024).

CREATE TABLE IF NOT EXISTS dismissed_product_merges (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_keys TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, product_keys)
);

CREATE INDEX IF NOT EXISTS idx_dismissed_product_merges_user
    ON dismissed_product_merges(user_id);
