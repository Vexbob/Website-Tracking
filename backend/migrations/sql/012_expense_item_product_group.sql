-- Paket 12:
-- Optionaler expliziter Produkt-Gruppenschlüssel. Wenn NULL, wird der
-- Basisname aus ``description`` als Gruppenschlüssel abgeleitet (Standard).
-- Wenn gesetzt, überschreibt dieser Wert die automatische Gruppierung —
-- dadurch kann der User falsch zusammengeführte Artikel manuell auftrennen
-- (Item aus einer Produkt-Gruppe herauslösen, z.B. wenn "Kaffeesahne" fälsch-
-- lich in die "Vollmilch"-Gruppe rutscht).
ALTER TABLE expense_items
    ADD COLUMN IF NOT EXISTS product_group TEXT;

CREATE INDEX IF NOT EXISTS idx_expense_items_pgroup
    ON expense_items(user_id, product_group);
