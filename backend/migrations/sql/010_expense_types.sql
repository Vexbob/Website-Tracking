-- Paket 10:
-- 1) Ausgaben-Typ: nicht nur Kassenbons, sondern auch Online-Bestellungen,
--    Restaurant-Besuche, Abos, Sonstiges. Bestehende Zeilen bekommen 'receipt'.
-- 2) original_price + is_reduced für Positions-Level Preisverfolgung
--    (Reduziert-Erkennung, prozentualer Rabatt).

ALTER TABLE expenses
    ADD COLUMN IF NOT EXISTS expense_type TEXT NOT NULL DEFAULT 'receipt';

-- Alt-Daten explizit auf 'receipt' setzen, falls Default noch nicht galt
UPDATE expenses SET expense_type = 'receipt' WHERE expense_type IS NULL;

-- Positions-Level: Originalpreis + Reduziert-Flag
ALTER TABLE expense_items
    ADD COLUMN IF NOT EXISTS original_price NUMERIC;
ALTER TABLE expense_items
    ADD COLUMN IF NOT EXISTS is_reduced BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_expenses_user_type ON expenses(user_id, expense_type);
