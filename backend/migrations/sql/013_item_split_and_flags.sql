-- Paket 13:
-- Trennt die kombinierte ``description`` in strukturierte Felder auf und ergänzt
-- zwei UX-relevante Flags:
--   * base_name         = Sprechender Basisname ohne Menge, z.B. "Vollmilch"
--   * original_text     = Ursprünglicher Text vom Kassenbon (z.B. "C1. ESL-Vollm. 1L")
--   * price_comparable  = TRUE wenn der Artikel für Preisverlauf relevant ist
--                         (Standard: TRUE für Verbrauchsgüter, FALSE für Einmalkäufe
--                         wie Töpfe, Vorratsdosen, Elektronik, Kleidung, etc.)
--   * user_edited       = TRUE wenn der User Beschreibung/Kategorie manuell
--                         angepasst hat. Verhindert dass Reparse den Wert überschreibt.
-- ``description`` bleibt als Legacy-Feld erhalten (für Bestandsdaten).

ALTER TABLE expense_items
    ADD COLUMN IF NOT EXISTS base_name TEXT;
ALTER TABLE expense_items
    ADD COLUMN IF NOT EXISTS original_text TEXT;
ALTER TABLE expense_items
    ADD COLUMN IF NOT EXISTS price_comparable BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE expense_items
    ADD COLUMN IF NOT EXISTS user_edited BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_expense_items_base_name
    ON expense_items(user_id, LOWER(base_name));
CREATE INDEX IF NOT EXISTS idx_expense_items_comparable
    ON expense_items(user_id, price_comparable) WHERE price_comparable = TRUE;

-- Bestandsdaten migrieren: base_name aus description ableiten (alles vor "(")
-- und original_text aus dem Klammer-Teil. Best-effort, nur wenn base_name noch NULL.
UPDATE expense_items
SET base_name = TRIM(REGEXP_REPLACE(
        SPLIT_PART(description, '(', 1),
        '\s*\d+(?:[.,]\d+)?\s*(kg|g|l|ml|stk|pack|btl|blatt|x\d+)\s*$',
        '',
        'i'
    )),
    original_text = NULLIF(
        TRIM(BOTH ' )' FROM SUBSTRING(description FROM POSITION('(' IN description) + 1)),
        ''
    )
WHERE base_name IS NULL AND description IS NOT NULL AND description != '';
