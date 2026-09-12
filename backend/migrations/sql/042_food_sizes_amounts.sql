-- Ernaehrung: beliebig viele eigene Groessen, echte Mengen bei Zutaten (v1.90.0)
--
-- Zwei Korrekturen an einer Annahme, die sich im Gebrauch nicht gehalten hat.
--
-- 1. EINE Portionsgroesse reicht nicht.
--    Bisher hatte ein Lebensmittel genau eine benannte Groesse
--    (``portion_label`` + ``portion_g``) und dazu eine Packung. Im Alltag hat
--    dasselbe Lebensmittel aber mehrere: ein Brot hat eine Scheibe, eine
--    halbe und einen Laib; Joghurt hat einen Becher und einen Loeffel. Wer
--    davon nur eines hinterlegen kann, rechnet den Rest jedes Mal im Kopf.
--    Ab hier stehen die Groessen in einer eigenen Tabelle -- so viele, wie
--    jemand braucht, frei benannt, in eigener Reihenfolge.
--
--    ``food_items.portion_g``/``portion_label`` bleiben als ABGELEITETE
--    Spalten bestehen und tragen die erste Groesse der Liste. Sie sind die
--    Standardgroesse (was vorgeschlagen wird, wenn niemand etwas waehlt) und
--    halten die Uebernahme aus Open Food Facts einfach, die genau eine
--    Portionsangabe kennt. Geschrieben werden sie ausschliesslich aus der
--    Liste -- zwei Quellen fuer dieselbe Zahl waeren eine zu viel.
--
-- 2. "normal / uebermaessig" gehoert den GERICHTEN.
--    Die Stufe ist eine ehrliche Schaetzung fuer etwas Zusammengesetztes:
--    wie viel von *meinen* Wraps habe ich gegessen. Bei einem einzelnen
--    Lebensmittel ist sie dagegen unnoetig ungenau -- was auf der Packung
--    oder der Schneidebrettkante liegt, weiss man genauer: 100 g, zwei
--    Scheiben, eine Packung. Deshalb traegt eine Tagebuchzeile ab jetzt
--    entweder eine Stufe (Gericht) oder eine Menge (Lebensmittel).
--
--    Alte Zeilen werden NICHT umgerechnet. Aus "Apfel, uebermaessig" eine
--    Grammzahl zu erfinden, waere genau die falsche Genauigkeit, gegen die
--    dieses Modul gebaut ist: sie behalten ihre Stufe und werden weiter als
--    Spanne gerechnet. Der Check laesst darum beides zu.

-- ---------- Eigene Groessen je Lebensmittel ----------
CREATE TABLE IF NOT EXISTS food_item_sizes (
    id       SERIAL PRIMARY KEY,
    item_id  INTEGER NOT NULL REFERENCES food_items(id) ON DELETE CASCADE,
    -- Frei: Scheibe, Becher, Riegel, Glas, halbe Packung, Handvoll …
    label    TEXT NOT NULL,
    -- Wie schwer diese eine Einheit ist -- in der Basis des Lebensmittels
    -- (g oder ml), damit die Naehrwerte je 100 direkt passen.
    grams    NUMERIC(9,2) NOT NULL CHECK (grams > 0),
    position SMALLINT NOT NULL DEFAULT 0
);

-- Eine Bezeichnung je Lebensmittel nur einmal: zwei Zeilen "Scheibe" mit
-- verschiedenen Gewichten waeren im Auswahlfeld nicht zu unterscheiden.
CREATE UNIQUE INDEX IF NOT EXISTS idx_food_item_sizes_label
    ON food_item_sizes(item_id, lower(label));
CREATE INDEX IF NOT EXISTS idx_food_item_sizes_item
    ON food_item_sizes(item_id, position);

-- Was bisher an der Zeile stand, wird zur ersten Groesse.
INSERT INTO food_item_sizes (item_id, label, grams, position)
SELECT id, COALESCE(NULLIF(btrim(portion_label), ''), 'Portion'), portion_g, 0
  FROM food_items
 WHERE portion_g IS NOT NULL AND portion_g > 0
ON CONFLICT DO NOTHING;

INSERT INTO food_item_sizes (item_id, label, grams, position)
SELECT id, 'Packung', package_g, 1
  FROM food_items
 WHERE package_g IS NOT NULL AND package_g > 0
ON CONFLICT DO NOTHING;

-- ---------- Zutaten: Einheit ist ab jetzt die Bezeichnung ----------
-- Vorher standen dort die festen Schluessel 'portion'/'packung'. Mit
-- beliebig vielen Groessen gibt es keinen festen Schluessel mehr -- die
-- Bezeichnung selbst ist der Schluessel. 'g' und 'ml' bleiben reserviert.
UPDATE food_dish_items z
   SET unit = COALESCE(NULLIF(btrim(i.portion_label), ''), 'Portion')
  FROM food_items i
 WHERE i.id = z.item_id AND z.unit = 'portion';

UPDATE food_dish_items SET unit = 'Packung' WHERE unit = 'packung';

-- ---------- Tagebuch: Stufe ODER Menge ----------
ALTER TABLE food_log
    -- Wie es eingegeben wurde ("2" + "Scheibe"), damit die Zeile spaeter
    -- noch so dasteht, wie sie getippt wurde.
    ADD COLUMN IF NOT EXISTS amount NUMERIC(9,2),
    ADD COLUMN IF NOT EXISTS unit   TEXT,
    -- Die Rechengroesse, einmal beim Speichern umgerechnet: eine spaeter
    -- korrigierte Scheibengroesse aendert keinen vergangenen Tag mehr.
    ADD COLUMN IF NOT EXISTS grams  NUMERIC(9,2);

ALTER TABLE food_log ALTER COLUMN level DROP NOT NULL;
ALTER TABLE food_log ALTER COLUMN level DROP DEFAULT;

ALTER TABLE food_log DROP CONSTRAINT IF EXISTS food_log_menge_vorhanden;
ALTER TABLE food_log ADD CONSTRAINT food_log_menge_vorhanden CHECK (
    -- Ein Gericht wird in Stufen gegessen.
    (dish_id IS NOT NULL AND level IS NOT NULL) OR
    -- Ein Lebensmittel in Mengen -- oder, wenn es von frueher stammt, in
    -- der Stufe, mit der es damals eingetragen wurde.
    (item_id IS NOT NULL AND (grams IS NOT NULL OR level IS NOT NULL)));
