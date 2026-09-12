-- Ernaehrung: der Lebensmittel-Bestand (v1.85.0)
--
-- Die erste Haelfte des Moduls: woher ein Lebensmittel seine Naehrwerte hat.
-- Gerichte und das Tagebuch kommen in einer eigenen Migration dazu, sobald
-- sie gebaut werden -- eine Tabelle, auf die noch nichts zeigt, ist nur eine
-- Behauptung ueber die Zukunft.
--
-- Quelle ist Open Food Facts: offene Datenbank (ODbL), Abfrage ueber den
-- Strichcode, ohne Anmeldung und ohne Kosten. Was von dort kommt, bleibt als
-- Herkunft erkennbar (``source``) und aenderbar: Naehrwerte auf Packungen und
-- in der Datenbank weichen regelmaessig voneinander ab, und wer einen Wert
-- korrigiert, will ihn beim naechsten Abruf nicht wieder ueberschrieben
-- sehen (``user_edited``).
CREATE TABLE IF NOT EXISTS food_items (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- 'off' = aus Open Food Facts geholt, 'eigen' = selbst angelegt.
    source        TEXT NOT NULL DEFAULT 'eigen' CHECK (source IN ('off', 'eigen')),
    barcode       TEXT,
    name          TEXT NOT NULL,
    brand         TEXT,
    -- Alle Naehrwerte je 100 g bzw. 100 ml. NULL heisst "keine Angabe" und
    -- ist ausdruecklich nicht 0: Open Food Facts laesst gerade bei
    -- Ballaststoffen oft die Angabe weg, und eine 0 dort waere eine Zahl,
    -- die in jeder Tagessumme mitlaeuft, ohne zu stimmen.
    kcal          NUMERIC(7,2),
    protein_g     NUMERIC(7,2),
    carbs_g       NUMERIC(7,2),
    sugar_g       NUMERIC(7,2),
    fat_g         NUMERIC(7,2),
    sat_fat_g     NUMERIC(7,2),
    fiber_g       NUMERIC(7,2),
    salt_g        NUMERIC(7,2),
    -- Was eine "normale" Menge ist, in Gramm. Das Modul rechnet spaeter mit
    -- zwei Stufen (normal / uebermaessig) statt mit Gramm-Eingaben; diese
    -- Zahl ist die Bruecke von der Stufe zur Naehrwerttabelle.
    portion_g     NUMERIC(7,2),
    -- Von Hand geaendert: ein erneuter Abruf aus der Datenbank fasst die
    -- Zeile dann nicht mehr an.
    user_edited   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Ein Strichcode je Nutzer genau einmal: derselbe Artikel zweimal
    -- gescannt soll denselben Eintrag treffen, nicht einen zweiten anlegen.
    UNIQUE (user_id, barcode)
);

CREATE INDEX IF NOT EXISTS idx_food_items_user_name
    ON food_items(user_id, lower(name));
