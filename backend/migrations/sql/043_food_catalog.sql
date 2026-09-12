-- Ernaehrung: ein eigener Katalog aus dem Open-Food-Facts-Abzug (v1.90.0)
--
-- Bisher lief jede Textsuche live gegen search.openfoodfacts.org -- einen
-- ehrenamtlich betriebenen Dienst, der unter Last mit 503 antwortet. Genau
-- das ist im Gebrauch passiert. Ein Nachschlagewerk, das beim Tippen
-- ausfaellt, ist keins.
--
-- Open Food Facts veroeffentlicht denselben Bestand taeglich als Datei.
-- ``backend/scripts/off_katalog.py`` schneidet daraus das heraus, was hier
-- im Regal steht und Naehrwerte hat -- aus gut vier Millionen Produkten
-- werden ein paar hunderttausend. Die liegen ab jetzt hier: die Suche ist
-- damit eine Datenbankabfrage statt einer Reise durchs Netz.
--
-- Diese Tabelle ist ausdruecklich NICHT der Bestand. Sie gehoert keinem
-- Nutzer, wird komplett ersetzt, wenn ein neuer Abzug kommt, und niemand
-- bearbeitet sie. Was jemand uebernimmt, wandert nach ``food_items`` und
-- gehoert von da an ihm -- samt seiner Korrekturen. Deshalb hat sie auch
-- keine user_id und keine Fremdschluessel: sie ist ein Nachschlagewerk.
CREATE TABLE IF NOT EXISTS food_catalog (
    -- Der Strichcode ist der Schluessel: er ist es, mit dem gesucht wird,
    -- und er ist im Abzug eindeutig.
    code       TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    brand      TEXT,
    -- Beziehen sich die Angaben auf 100 g oder 100 ml.
    base_unit  TEXT NOT NULL DEFAULT 'g' CHECK (base_unit IN ('g', 'ml')),
    -- Alle Naehrwerte je 100. NULL heisst auch hier "keine Angabe" und wird
    -- beim Uebernehmen als Luecke sichtbar, nicht als 0 verrechnet.
    kcal       NUMERIC(7,2),
    protein_g  NUMERIC(7,2),
    carbs_g    NUMERIC(7,2),
    sugar_g    NUMERIC(7,2),
    fat_g      NUMERIC(7,2),
    sat_fat_g  NUMERIC(7,2),
    fiber_g    NUMERIC(7,2),
    salt_g     NUMERIC(7,2),
    -- Die Portionsangabe der Packung, soweit vorhanden.
    portion_g  NUMERIC(9,2),
    -- Wann Open Food Facts diese Zeile zuletzt geaendert hat (Unixzeit).
    -- Ein Katalog altert; an dieser Zahl sieht man, wie sehr.
    updated_at BIGINT
);

-- Die Suche geht ueber Name UND Marke ("milka" soll die Tafel finden).
-- Deshalb liegt der Index auf genau dem Ausdruck, gegen den auch gesucht
-- wird -- ein Index nur auf ``name`` wuerde bei jeder Abfrage uebergangen.
--
-- pg_trgm ist eine Contrib-Erweiterung. Sie liegt in den ueblichen
-- Postgres-Images bei, laesst sich aber nur mit den noetigen Rechten
-- anlegen. Faellt das aus, laeuft die Suche ohne den Index weiter: bei ein
-- paar hunderttausend Zeilen dauert sie dann Bruchteile einer Sekunde statt
-- Millisekunden. Das ist der Grund fuer den Block drumherum -- ein
-- fehlgeschlagenes CREATE EXTENSION wuerde sonst den ganzen Start
-- abbrechen, und das Backend stuende wegen eines Index still.
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pg_trgm nicht verfuegbar (%): Katalogsuche laeuft ohne Trigramm-Index',
                 SQLERRM;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
        CREATE INDEX IF NOT EXISTS idx_food_catalog_suche
            ON food_catalog USING gin (
                (name || ' ' || COALESCE(brand, '')) gin_trgm_ops);
    END IF;
END $$;

-- Fuer die haeufigste Sortierung: kurze, allgemeine Namen zuerst.
CREATE INDEX IF NOT EXISTS idx_food_catalog_name
    ON food_catalog(lower(name));
