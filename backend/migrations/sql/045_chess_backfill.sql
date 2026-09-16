-- 045: Der Stand der Historie steht am Konto.
--
-- ``games_through`` sagt bisher nur, bis wohin geholt wurde -- nicht, ob
-- davor noch etwas fehlt. Ein Zeiger, der nur vorwaerts wandert, sieht nach
-- dem ersten Stueck genauso aus wie nach dem letzten: die Seite schrieb
-- deshalb "Neue Partien holen", waehrend in Wahrheit noch Jahre offen waren.
-- ``backfill_done`` wird gesetzt, sobald ein Lauf ein nicht volles Stueck
-- bekommt -- das ist das Ende der Historie.
ALTER TABLE chess_accounts
    ADD COLUMN IF NOT EXISTS backfill_done BOOLEAN NOT NULL DEFAULT FALSE;

-- Wer schon Partien hat, hat sie stueckweise geholt; ob das Ende erreicht
-- war, weiss hier niemand. FALSE ist die ehrliche Annahme: die Seite bietet
-- dann das Weiterholen an, und ein Lauf, der nichts findet, setzt das Flag
-- beim naechsten Mal selbst.
