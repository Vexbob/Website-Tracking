-- Paket 17: Marken (Brands) fuer Ausgaben-Modul (v1.16.0)
-- Zweck: Explizit erfasste Marken (z.B. "Milka", "Ja! Natuerlich", "Clever") die
-- vom AI-Parser erkannt und optional an ``expense_items`` verknuepft werden.
-- Dadurch lassen sich (a) Preisvergleiche fair machen (Eigenmarke vs. Markenartikel)
-- und (b) Statistiken pro Marke bauen.
--
-- Marken sind pro-User (idempotent per Case-insensitive Uniq-Index).
-- ``is_private_label`` markiert Eigenmarken (Milbona = Lidl, Clever = Billa,
-- K-Classic = Kaufland, ...). ``store_id`` verknuepft eine Eigenmarke mit
-- ihrem "Heimatladen" (NULL bei markenneutralen und Hersteller-Marken).
-- ``seed_source`` erlaubt es dem Seeder, System-Marken von User-Marken zu
-- unterscheiden (z.B. um beim Update neue System-Marken nachzuziehen ohne
-- User-Aenderungen zu ueberschreiben).

CREATE TABLE IF NOT EXISTS brands (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    is_private_label    BOOLEAN NOT NULL DEFAULT FALSE,
    store_id            INTEGER REFERENCES stores(id) ON DELETE SET NULL,
    parent_company      TEXT,        -- z.B. "Nestle", "Unilever"
    aliases             TEXT[],      -- alternative Schreibweisen fuer Matching
    seed_source         TEXT,        -- "system" fuer geseedete, NULL fuer User-Anlage
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_brands_user ON brands(user_id);
CREATE INDEX IF NOT EXISTS idx_brands_store ON brands(store_id) WHERE store_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uniq_brands_user_name
    ON brands(user_id, LOWER(name));

-- Verknuepfung Item -> Brand. NULL = keine Marke erkannt.
ALTER TABLE expense_items
    ADD COLUMN IF NOT EXISTS brand_id INTEGER REFERENCES brands(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_expense_items_brand
    ON expense_items(user_id, brand_id) WHERE brand_id IS NOT NULL;
