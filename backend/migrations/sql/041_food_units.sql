-- Ernaehrung: Einheiten und eigene Angaben (v1.88.0)
--
-- Bisher kannte das Modul nur Gramm je 100 g und eine Portionsgroesse. Im
-- Alltag sagt aber niemand "80 Gramm Wrap" -- man sagt ein Stueck, eine
-- Portion, eine Packung. Genau diese Woerter bekommen deshalb eine Groesse:
--
--     base_unit       'g' oder 'ml' -- worauf sich die Naehrwerte beziehen.
--                     Bei Getraenken ist die 100er-Angabe je 100 ml, und
--                     "100 g Saft" waere schlicht falsch abgelesen.
--     portion_label   Wie die Einheit heisst: Stueck, Scheibe, Portion, Glas.
--                     Frei, weil ein Wrap ein Stueck hat und ein Joghurt
--                     einen Becher.
--     portion_g       Wie schwer diese eine Einheit ist.
--     package_g       Was in der ganzen Packung ist -- fuer "ich hab die
--                     Packung gegessen", das ehrlichste Mass ueberhaupt.
--
-- An den Zutaten eines Gerichts steht ab jetzt zusaetzlich, WIE es
-- eingegeben wurde (amount + unit). ``grams`` bleibt die Rechengroesse und
-- wird daraus abgeleitet: die Umrechnung einmal beim Speichern statt bei
-- jeder Anzeige, und die Eingabe bleibt beim Bearbeiten so stehen, wie sie
-- getippt wurde -- "2 Stueck" bleibt "2 Stueck" und wird nicht zu "90 g".
ALTER TABLE food_items
    ADD COLUMN IF NOT EXISTS base_unit     TEXT NOT NULL DEFAULT 'g'
        CHECK (base_unit IN ('g', 'ml')),
    ADD COLUMN IF NOT EXISTS portion_label TEXT,
    ADD COLUMN IF NOT EXISTS package_g     NUMERIC(8,2);

ALTER TABLE food_dish_items
    ADD COLUMN IF NOT EXISTS amount NUMERIC(8,2),
    ADD COLUMN IF NOT EXISTS unit   TEXT;

-- Bestehende Zutaten wurden in Gramm eingegeben -- das bleibt so stehen.
UPDATE food_dish_items
   SET amount = grams, unit = 'g'
 WHERE amount IS NULL;
