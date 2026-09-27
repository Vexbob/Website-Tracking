-- Wochenziele — eine Teilbelohnung, wenn es knapp nicht gereicht hat
--
-- Bisher zahlte ein Wochenziel alles oder nichts: 7 von 7 brachten die volle
-- Belohnung, 6 von 7 keinen Cent. Die Teilbelohnung zahlt am Ende der Periode
-- ``partial_percent`` Prozent der Belohnung aus, wenn mindestens
-- ``partial_count`` Check-ins darin stehen, das Ziel selbst aber nicht
-- erreicht wurde. Wer das Ziel schafft, bekommt die volle Belohnung und
-- keine Teilbelohnung dazu.
--
-- Gebucht wird sie als eigene ``savings_transactions``-Zeile an derselben
-- Quelle, mit ``period_key = '<periode>-teil'``. Damit beruehrt sie die
-- Hauptbelohnung nicht, die an ``period_key = '<periode>'`` haengt.
--
-- ``partial_since`` ist der Tag, ab dem die Regel gilt. Ohne ihn wuerde das
-- Einschalten jede vergangene Woche des Verlaufs nachtraeglich auszahlen, die
-- die Schwelle erreicht hatte -- eine Regel, die man heute setzt, gilt ab
-- der laufenden Periode.
--
-- 0 heisst aus -- dieselbe Lesart wie beim Streak-Bonus.

ALTER TABLE progress_goals ADD COLUMN IF NOT EXISTS partial_count   INTEGER DEFAULT 0;
ALTER TABLE progress_goals ADD COLUMN IF NOT EXISTS partial_percent NUMERIC DEFAULT 0;
ALTER TABLE progress_goals ADD COLUMN IF NOT EXISTS partial_since   DATE;
