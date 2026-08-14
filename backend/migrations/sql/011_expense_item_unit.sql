-- Paket 11:
-- Speichere die vom AI-Parser erkannte Mengeneinheit (kg, g, L, ml, Stk, Pack, Btl).
-- Wird für den Preisverlauf und für €/kg-/€/L-Berechnung genutzt.
ALTER TABLE expense_items
    ADD COLUMN IF NOT EXISTS quantity_unit TEXT;
