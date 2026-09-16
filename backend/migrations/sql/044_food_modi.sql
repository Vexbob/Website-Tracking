-- Ernaehrung: zwei Modi, freie Eintraege, Mahlzeiten, eigene Ziele (v1.94.0)
--
-- Das Modul hatte bisher genau eine Betriebsart, und die war ein Kompromiss:
-- locker genug, dass man Gramm nicht zaehlen muss, aber trotzdem nur
-- benutzbar, wenn das Gegessene vorher als Gericht oder Lebensmittel im
-- Bestand stand. Wer abends beim Italiener sass, konnte gar nichts
-- eintragen -- und wer es genau wissen wollte, bekam nur Spannen.
--
-- Ab hier sind es zwei Betriebsarten auf EINEM Tagebuch:
--
--   locker        Man schreibt hin, WAS es gab und OB es normal oder
--                 uebermaessig viel war. Mehr fragt die Seite nicht.
--   ausfuehrlich  Mengen, Naehrwerte, eigene Tagesziele, Verlauf.
--
-- Entscheidend ist, dass beide in dieselbe Tabelle schreiben. Ein Modus, der
-- eigene Zeilen anlegt, waere eine zweite Wahrheit ueber denselben Tag: der
-- Wechsel wuerde Eintraege verschwinden lassen, und niemand koennte einen
-- locker notierten Tag spaeter genauer machen. Ein lockerer Eintrag ist
-- deshalb einfach ein Eintrag mit weniger Angaben -- und die Anzeige sagt,
-- welche fehlen.

-- ---------- Freie Eintraege ----------
-- Der dritte Fall neben Gericht und Lebensmittel: ein Name, sonst nichts.
-- "Pizza beim Italiener" hat keine Naehrwerte und soll auch keine bekommen --
-- erfundene Zahlen waeren schlechter als eine ehrliche Luecke. Gezaehlt wird
-- er trotzdem: er steht im Tag, er traegt eine Stufe, und die Anzeige weist
-- aus, dass die Tagessumme ihn nicht enthaelt.
ALTER TABLE food_log ADD COLUMN IF NOT EXISTS label TEXT;

-- Genau eine Herkunft je Zeile: Gericht, Lebensmittel oder freier Name.
ALTER TABLE food_log DROP CONSTRAINT IF EXISTS food_log_genau_eines;
ALTER TABLE food_log ADD CONSTRAINT food_log_genau_eines CHECK (
    (dish_id IS NOT NULL)::int
  + (item_id IS NOT NULL)::int
  + (label IS NOT NULL AND btrim(label) <> '')::int = 1);

-- Was die Zeile rechenbar macht: eine Stufe oder eine Menge. Ein freier
-- Eintrag hat nie eine Menge -- er traegt immer eine Stufe.
ALTER TABLE food_log DROP CONSTRAINT IF EXISTS food_log_menge_vorhanden;
ALTER TABLE food_log ADD CONSTRAINT food_log_menge_vorhanden CHECK (
    (dish_id IS NOT NULL AND level IS NOT NULL) OR
    (item_id IS NOT NULL AND (grams IS NOT NULL OR level IS NOT NULL)) OR
    (label  IS NOT NULL AND level IS NOT NULL));

-- Der Tag wird nach Mahlzeiten gelesen, nicht nach Uhrzeit: "Mittag" ist die
-- Auskunft, die man geben kann, "12:47" ist eine, die man erfinden muesste.
-- Bewusst ohne CHECK: geprueft wird im Server gegen eine Liste, die dort auch
-- ihre Beschriftung hat. Eine zweite Liste in der Datenbank waere eine, die
-- man beim Ergaenzen vergisst.
CREATE INDEX IF NOT EXISTS idx_food_log_user_tag_mahlzeit
    ON food_log(user_id, day DESC, meal);

-- Fuer die Vorschlagsliste ("was du oft eintraegst") und den Verlauf.
CREATE INDEX IF NOT EXISTS idx_food_log_user_label
    ON food_log(user_id, lower(label)) WHERE label IS NOT NULL;

-- ---------- Modus und eigene Tagesziele ----------
-- Der Modus steht hier und nicht bei den Oberflaechen-Einstellungen, weil er
-- keine Ansicht umschaltet, sondern die FRAGE: im lockeren Modus wird eine
-- Stufe erfasst, im ausfuehrlichen eine Menge. Damit gehoert er zu den Daten
-- des Moduls und neben die Ziele, die er ein- und ausschaltet.
--
-- Die Ziele sind ausdruecklich freiwillig. Bleibt eines leer, gilt weiter der
-- allgemeine Richtwert aus services/food_calc.py -- und die Antwort sagt,
-- welcher von beiden gerade den Massstab stellt. Ein Balken, der gegen ein
-- Ziel laeuft, das man nie gesetzt hat, waere eine Bewertung, um die niemand
-- gebeten hat.
CREATE TABLE IF NOT EXISTS food_settings (
    user_id        INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    mode           TEXT NOT NULL DEFAULT 'locker'
                   CHECK (mode IN ('locker', 'ausfuehrlich')),
    kcal_target    NUMERIC(7,1) CHECK (kcal_target IS NULL OR kcal_target > 0),
    protein_target NUMERIC(7,1) CHECK (protein_target IS NULL OR protein_target > 0),
    fiber_target   NUMERIC(7,1) CHECK (fiber_target IS NULL OR fiber_target > 0),
    carbs_target   NUMERIC(7,1) CHECK (carbs_target IS NULL OR carbs_target > 0),
    fat_target     NUMERIC(7,1) CHECK (fat_target IS NULL OR fat_target > 0),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
