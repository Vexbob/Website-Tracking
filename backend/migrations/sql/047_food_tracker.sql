-- Der Tracker zaehlt Mengen, keine Stufen mehr (v1.98.0)
--
-- Migration 046 hat das Tagebuch herausgeloest; hier bekommt die andere
-- Haelfte ihre eigene Form. Bis jetzt liess ``food_log`` beides zu: eine
-- Zeile mit Gramm ODER eine mit "normal"/"uebermaessig". Das war die Klammer,
-- die beide Betriebsarten zusammenhielt -- und sie ist jetzt hinderlich:
--
--   * Eine Stufe gehoert ins Tagebuch. Steht sie auch hier, gibt es wieder
--     zwei Orte fuer dieselbe Auskunft, und der Fehler, den 046 behoben hat,
--     haette einen zweiten Weg zurueck.
--   * Ein eigenes Gericht wird ab hier in PORTIONEN eingetragen (0,5 / 1 /
--     1,5) statt in Stufen. ``food_dishes`` kennt die Naehrwerte EINER
--     Portion; damit ist die Rechnung exakt statt geschaetzt, und der
--     Kalorienring zeigt eine Zahl statt einer Spanne.
--
-- Damit faellt die halbe Rechnung des Moduls weg: eintrag_spanne(),
-- exakte_spanne() und tages_summe() werden nicht mehr gebraucht. Die
-- Ehrlichkeit der Spanne wandert dorthin, wo sie hingehoert -- ins Tagebuch,
-- das gar keine Zahlen behauptet.
--
-- ``food_log`` ist seit 046 leer, deshalb geht das ohne Zwischenschritt:
-- NOT NULL laesst sich auf einer leeren Tabelle bedenkenlos setzen.

-- Zuerst die Bedingungen, dann die Spalten: eine Bedingung, die auf eine
-- geloeschte Spalte zeigt, waere ein Fehler mitten in der Migration.
ALTER TABLE food_log DROP CONSTRAINT IF EXISTS food_log_genau_eines;
ALTER TABLE food_log DROP CONSTRAINT IF EXISTS food_log_menge_vorhanden;

ALTER TABLE food_log DROP COLUMN IF EXISTS level;
ALTER TABLE food_log DROP COLUMN IF EXISTS label;

-- Eine Tracker-Zeile OHNE Menge gibt es nicht mehr. Was dann? Ein
-- Tagebucheintrag -- und der liegt woanders.
ALTER TABLE food_log ALTER COLUMN grams  SET NOT NULL;
ALTER TABLE food_log ALTER COLUMN amount SET NOT NULL;
ALTER TABLE food_log ALTER COLUMN unit   SET NOT NULL;

-- Genau eine Herkunft: ein Gericht oder ein Lebensmittel. Den frueheren
-- dritten Fall (freier Name) gibt es hier nicht mehr; er ist der Normalfall
-- des Tagebuchs.
ALTER TABLE food_log ADD CONSTRAINT food_log_genau_eines CHECK (
    (dish_id IS NOT NULL)::int + (item_id IS NOT NULL)::int = 1
);

-- Die Ortszeit der Eingabe, wie im Tagebuch: der Server laeuft in UTC und
-- duerfte aus seiner eigenen Uhr keine Mahlzeit ableiten.
ALTER TABLE food_log ADD COLUMN IF NOT EXISTS logged_time TIME;
ALTER TABLE food_log ADD COLUMN IF NOT EXISTS meal_auto BOOLEAN NOT NULL DEFAULT FALSE;

-- Der Modus ist keine Einstellung mehr, sondern die Wahl des Moduls. Die
-- fuenf Zielspalten bleiben und gehoeren ab jetzt eindeutig dem Tracker.
ALTER TABLE food_settings DROP COLUMN IF EXISTS mode;
