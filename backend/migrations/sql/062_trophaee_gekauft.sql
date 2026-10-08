-- Sparziel: Trophaeen mit Haken „gekauft“ (v2.43.0)
--
-- Eine Trophaee entsteht, wenn ein Sparziel voll ist -- gekauft ist das Ding
-- damit noch nicht. ``gekauft_am`` haelt fest, ob und wann es angeschafft
-- wurde; leer heisst: noch offen. Ein Datum statt eines Wahrheitswerts, weil
-- „wann“ beim Zurueckschauen mehr sagt als „ob“.

ALTER TABLE completed_goals ADD COLUMN IF NOT EXISTS gekauft_am DATE;
