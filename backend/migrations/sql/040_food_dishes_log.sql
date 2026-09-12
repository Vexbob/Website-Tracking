-- Ernaehrung: Gerichte und Tagebuch (v1.87.0)
--
-- Der Kern der Idee: erfasst wird eine STUFE, keine Gramm.
--
--     "Wraps, uebermaessig"   statt   "412 g Wraps"
--
-- Gramm stehen deshalb nur an einer einzigen Stelle -- im Rezept eines
-- Gerichts, das man einmal anlegt. Beim Eintragen wird nur noch gesagt, ob
-- es eine normale Portion war oder deutlich mehr. Das ist keine Bequemlich-
-- keit, sondern Ehrlichkeit: geschaetzte Gramm sind auch nur eine Grobstufe,
-- nur mit einer Nachkommastelle, die Genauigkeit vortaeuscht.
--
-- Aus der Stufe wird beim Anzeigen eine SPANNE (siehe services/food_calc.py),
-- nie eine einzelne Zahl. Eine Tagessumme "2.147 kcal" aus zwei Grobstufen
-- waere erfunden; "1.900 bis 2.400" ist das, was man wirklich weiss.

-- ---------- Ein Gericht ----------
CREATE TABLE IF NOT EXISTS food_dishes (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    note       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_food_dishes_user
    ON food_dishes(user_id, lower(name));

-- ---------- Die Zutaten eines Gerichts ----------
-- ``grams`` ist die Menge in EINER normalen Portion. Hier stehen Gramm, weil
-- ein Rezept einmal geschrieben und hundertmal benutzt wird -- der Aufwand
-- faellt genau einmal an.
CREATE TABLE IF NOT EXISTS food_dish_items (
    id       SERIAL PRIMARY KEY,
    dish_id  INTEGER NOT NULL REFERENCES food_dishes(id) ON DELETE CASCADE,
    item_id  INTEGER NOT NULL REFERENCES food_items(id) ON DELETE CASCADE,
    grams    NUMERIC(7,2) NOT NULL CHECK (grams > 0),
    position SMALLINT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_food_dish_items_dish
    ON food_dish_items(dish_id, position);

-- ---------- Das Tagebuch ----------
-- Eine Zeile ist: an diesem Tag, dieses Gericht (oder dieses einzelne
-- Lebensmittel), in dieser Stufe. Mehr nicht.
CREATE TABLE IF NOT EXISTS food_log (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day        DATE NOT NULL DEFAULT CURRENT_DATE,
    dish_id    INTEGER REFERENCES food_dishes(id) ON DELETE CASCADE,
    item_id    INTEGER REFERENCES food_items(id) ON DELETE CASCADE,
    -- 'normal' oder 'viel'. Zwei Stufen, mehr gibt die Erinnerung nicht her.
    level      TEXT NOT NULL DEFAULT 'normal' CHECK (level IN ('normal', 'viel')),
    -- Fruehstueck, Mittag, Abend, Zwischendurch -- frei, aber vorgeschlagen.
    meal       TEXT,
    note       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Entweder Gericht oder Lebensmittel, nie beides und nie keines.
    CONSTRAINT food_log_genau_eines CHECK (
        (dish_id IS NOT NULL AND item_id IS NULL) OR
        (dish_id IS NULL AND item_id IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_food_log_user_tag
    ON food_log(user_id, day DESC);
