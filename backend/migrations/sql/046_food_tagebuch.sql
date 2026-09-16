-- Das Essenstagebuch bekommt eine eigene Tabelle (v1.97.0)
--
-- Migration 044 hat beide Betriebsarten bewusst in dieselbe Tabelle gelegt:
-- "Ein Modus, der eigene Zeilen anlegt, waere eine zweite Wahrheit ueber
-- denselben Tag." Das war falsch gedacht, und der Nutzer hat den Beweis
-- geliefert: wer im Tracker "100 g Haferflocken" eintrug, fand denselben
-- Eintrag anschliessend im Tagebuch stehen -- dort, wo es nur "normal" und
-- "uebermaessig" geben sollte.
--
-- Es sind nicht zwei Wahrheiten ueber denselben Tag, sondern zwei FRAGEN an
-- denselben Tag:
--
--   Tagebuch  Was gab es, und war es normal oder uebermaessig viel?
--             Keine Menge, keine Naehrwerte, kein Bestand. Null Einrichtung.
--   Tracker   Wie viel wovon, und was steckt drin?
--
-- Die Trennung steht deshalb ab hier in der SPALTENLISTE, nicht in einer
-- Pruefung: ``food_diary`` hat kein ``grams``, kein ``amount``, kein
-- ``unit``, kein ``item_id`` und kein ``dish_id``. Ein Mengen-Eintrag kann
-- dort nicht landen, weil es nichts gibt, wohin er koennte. Das ist staerker
-- als jede Bedingung, die spaeter jemand lockert -- und es war genau die
-- Bedingung, die im Backend nie existiert hat: ``POST /api/food/log`` hat den
-- eingestellten Modus kein einziges Mal gelesen.
--
-- Was hier NICHT passiert: ``food_log`` wird nicht umgebaut. Es wird nur
-- geleert (der Nutzer wollte, dass beide Seiten leer anfangen). Die
-- Verschaerfung des Schemas gehoert zur Etappe, in der auch die Oberflaeche
-- des Trackers neu entsteht -- bis dahin laeuft die alte Seite unveraendert
-- weiter, nur ruhend. Gerichte und Lebensmittel bleiben in jedem Fall.

CREATE TABLE IF NOT EXISTS food_diary (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day        DATE NOT NULL DEFAULT CURRENT_DATE,
    -- Der Name, so wie er getippt wurde. Kein Fremdschluessel: das Tagebuch
    -- kennt keinen Bestand, und "Pizza beim Italiener" steht in keinem.
    label      TEXT NOT NULL CHECK (btrim(label) <> '' AND length(label) <= 120),
    -- Die einzige Angabe zur Menge, die es hier gibt -- und sie ist Pflicht.
    -- Eine Zeile ohne Stufe waere im Tagebuch eine halbe Auskunft.
    level      TEXT NOT NULL CHECK (level IN ('normal', 'viel')),
    -- fruehstueck | mittag | abend | snack | NULL (= ohne Zuordnung).
    -- Bewusst ohne CHECK, wie in 044 begruendet: die Liste steht in
    -- services/food_mahlzeit.py, und zwei Listen waeren eine, die man beim
    -- Ergaenzen vergisst.
    meal       TEXT,
    note       TEXT,
    -- Die ORTSZEIT der Eingabe, vom Browser geschickt. Der Server laeuft in
    -- UTC: seine eigene Uhr zu befragen hiesse, einen Snack um 22:30 als
    -- 20:30 zu lesen und unter "Abend" einzusortieren.
    logged_time TIME,
    -- Ob die Mahlzeit geraten oder gewaehlt wurde. Eine Vermutung, die man
    -- nicht als solche erkennt, ist eine Behauptung.
    meal_auto  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_food_diary_tag
    ON food_diary(user_id, day DESC, meal);
-- Fuer die Vorschlagsliste: sie gruppiert ueber die kleingeschriebene
-- Schreibweise, damit "Muesli" und "muesli" eine Zeile sind.
CREATE INDEX IF NOT EXISTS idx_food_diary_label
    ON food_diary(user_id, lower(label));

-- Beide Seiten fangen leer an (ausdruecklicher Wunsch). Gerichte,
-- Lebensmittel, eigene Groessen und Tagesziele bleiben unangetastet --
-- geloescht werden nur die Tageszeilen.
DELETE FROM food_log;
