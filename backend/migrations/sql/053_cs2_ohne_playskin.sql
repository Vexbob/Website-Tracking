-- CS2 — „selbst gespielt“ faellt weg
--
-- Das Merkmal kam aus der Vorgaengerfassung: Skins und Agenten, die im
-- eigenen Inventar benutzt und nicht zum Verkauf gedacht sind. Es zaehlte im
-- Gesamtwert mit und wurde daneben getrennt ausgewiesen.
--
-- Seit die Kopfzeile die Itemanzahl nennt statt des gespielten Anteils
-- (v2.14.0), beantwortet es keine Frage mehr, die dieses Modul stellt: der
-- Bestand ist derselbe, ob ein Skin getragen wird oder liegt. Geblieben war
-- eine Plakette an der Zeile, eine Spalte in der Signatur, eine an der
-- Kategorie und zwei an jedem Snapshot.
--
-- Die Signatur einer Position ist ab hier
-- (Nutzer, Gegenstand, Abnutzung, StatTrak) -- ohne Playskin.
--
-- **Was passiert, wenn zwei Zeilen dadurch gleich werden?** Dasselbe wie in
-- 052: sie werden ZUSAMMENGEFUEHRT. Stueckzahlen addieren sich, Preis und
-- Preisstand kommen von der zuletzt gepflegten Zeile. Im Bestand, der diese
-- Migration ausgeloest hat, trifft es keine einzige Zeile -- von 21
-- gespielten Positionen hat keine ein ungespieltes Gegenstueck. Der Schritt
-- steht trotzdem hier: eine Migration, die auf fremden Daten an einem
-- eindeutigen Index scheitert, haelt die ganze App an.
--
-- Die beiden Snapshot-Spalten gehen mit. Sie tragen echte Zahlen fuer die
-- zehn uebernommenen Staende, aber keine Ansicht zeigt sie, und nach diesem
-- Schritt koennte auch kein neuer Stand sie fuellen -- eine Spalte, die
-- dauerhaft null meldet, sieht aus wie eine Messung. Verloren ist dabei
-- nichts: die Rohzahlen stehen unveraendert in ``Prototyp_V2/data/history.json``.

-- ---------- 1. Stueckzahlen der Dubletten auf die Siegerzeile ----------
WITH gruppe AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY user_id, item_id, COALESCE(wear, ''::text), stattrak
               ORDER BY priced_at DESC NULLS LAST, id) AS platz,
           sum(quantity) OVER (
               PARTITION BY user_id, item_id, COALESCE(wear, ''::text), stattrak
           ) AS menge_gesamt
      FROM cs2_positions
)
UPDATE cs2_positions p
   SET quantity = g.menge_gesamt
  FROM gruppe g
 WHERE p.id = g.id AND g.platz = 1 AND g.menge_gesamt IS NOT NULL;

-- ---------- 2. Die unterlegenen Zeilen weg ----------
WITH gruppe AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY user_id, item_id, COALESCE(wear, ''::text), stattrak
               ORDER BY priced_at DESC NULLS LAST, id) AS platz
      FROM cs2_positions
)
DELETE FROM cs2_positions
 WHERE id IN (SELECT id FROM gruppe WHERE platz > 1);

-- ---------- 3. Die Signatur ohne Playskin ----------
-- ``COALESCE(wear, ''::text)`` bleibt und bleibt aus demselben Grund wie in
-- 051: Postgres haelt zwei NULL fuer verschieden. Jedes ``ON CONFLICT`` auf
-- diese Tabelle muss den Ausdruck weiterhin WOERTLICH nennen, samt ``::text``.
DROP INDEX IF EXISTS idx_cs2_positions_signatur;

ALTER TABLE cs2_positions  DROP COLUMN IF EXISTS playskin;
ALTER TABLE cs2_categories DROP COLUMN IF EXISTS supports_playskin;

CREATE UNIQUE INDEX IF NOT EXISTS idx_cs2_positions_signatur
    ON cs2_positions (user_id, item_id, COALESCE(wear, ''::text), stattrak);

-- ---------- 4. Die beiden Spalten am Snapshot ----------
ALTER TABLE cs2_snapshots DROP COLUMN IF EXISTS playskin_gross;
ALTER TABLE cs2_snapshots DROP COLUMN IF EXISTS playskin_net;
