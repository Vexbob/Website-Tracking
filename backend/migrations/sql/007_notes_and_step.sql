-- Paket 7:
-- 1) Notizen an Log-Einträgen (Meilensteine, Check-ins, Sparbeiträge/Streak-Bonus/Initial)
-- 2) Getrennte "Schrittweite pro Klick" (step_amount) und "Meilenstein-Schwelle" (threshold_increment)
--    Beispiel Abnehmen: Button = +1 kg, Meilenstein alle 5 kg.

-- 1) Notiz-Spalten (idempotent)
ALTER TABLE achievement_logs      ADD COLUMN IF NOT EXISTS note TEXT;
ALTER TABLE progress_logs         ADD COLUMN IF NOT EXISTS note TEXT;
ALTER TABLE savings_transactions  ADD COLUMN IF NOT EXISTS note TEXT;

-- 2) step_amount an Achievements
ALTER TABLE achievements          ADD COLUMN IF NOT EXISTS step_amount NUMERIC;

-- Backfill: Bestehende Achievements verhalten sich weiter wie bisher,
-- indem step_amount = threshold_increment gesetzt wird.
UPDATE achievements
   SET step_amount = threshold_increment
 WHERE step_amount IS NULL;
