-- Meilenstein-Kacheln aus anderen Modulen speisen (v2.9.0)
--
-- Eine Kachel im Sparziel kann ihren Stand aus einem anderen Tracker holen --
-- das Gewicht aus Health, die Wertung aus dem Schachmodul -- statt ihn von
-- Hand zu bekommen. Zwei Saetze halten das ungefaehrlich, und sie sind der
-- Grund, warum hier NUR zwei Spalten stehen und keine Zustandstabelle:
--
-- 1. Eine Quelle liest, sie schreibt nie. ``current_value`` bleibt der
--    bestaetigte Stand; die Automatik legt nur eine Zahl daneben. Erst die
--    Bestaetigung traegt sie ein, und zwar durch dieselbe Stelle, die auch
--    der Knopf "Setzen" benutzt. Es gibt also weiterhin genau EINEN Weg zu
--    einer Gutschrift.
-- 2. Deshalb braucht es auch keine zweite Schutzregel gegen Doppelzahlung:
--    ``credited_milestones`` zaehlt weiter nur vorwaerts. Wer von 143 auf 146
--    zunimmt und wieder unter 145 faellt, hat den Meilenstein nicht ein
--    zweites Mal -- das galt vorher und gilt fuer die Automatik genauso.
--
-- ``auto_params`` ist TEXT mit JSON darin, nicht JSONB: asyncpg liefert JSONB
-- ohne registrierten Codec ohnehin als String zurueck, und so bleibt das
-- Serialisieren an einer Stelle (Router) statt halb in der Datenbank. Dieselbe
-- Begruendung steht in 030 ueber ``user_prefs.value``.

ALTER TABLE achievements ADD COLUMN IF NOT EXISTS auto_source TEXT;
ALTER TABLE achievements ADD COLUMN IF NOT EXISTS auto_params TEXT NOT NULL DEFAULT '{}';
