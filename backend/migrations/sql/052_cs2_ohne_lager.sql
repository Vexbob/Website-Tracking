-- CS2 — das Lager faellt weg
--
-- Die Lagerzuordnung war aus der Vorgaengerfassung uebernommen: jeder
-- Gegenstand trug, in welchem Steam-Lager er liegt. Sie beantwortet keine
-- Frage, die dieses Modul stellt -- was da ist und was es wert waere, haengt
-- nicht daran, in welchem Fach es liegt -- und sie kostete an jeder Stelle
-- etwas: eine Spalte in der Signatur, einen Filter, eine zweite Aufteilung,
-- eine eigene Snapshot-Tabelle und drei Endpunkte.
--
-- Die Signatur einer Position ist deshalb ab hier
-- (Nutzer, Gegenstand, Abnutzung, StatTrak, Playskin) -- ohne Lager.
--
-- **Was passiert, wenn zwei Zeilen dadurch gleich werden?** Sie werden
-- ZUSAMMENGEFUEHRT, nicht verworfen: die Stueckzahlen addieren sich, und
-- Preis und Preisstand kommen von der zuletzt gepflegten Zeile. Das ist
-- dieselbe Regel, nach der das Modul seit jeher Nachkaeufe zusammenfuehrt.
-- Im Bestand, der diese Migration ausgeloest hat, trifft es keine einzige
-- Zeile -- keine zwei Positionen unterschieden sich nur im Lager. Der Schritt
-- steht trotzdem hier: eine Migration, die auf fremden Daten an einem
-- eindeutigen Index scheitert, haelt die ganze App an.

-- ---------- 1. Stueckzahlen der Dubletten auf die Siegerzeile ----------
-- Sieger ist die zuletzt bepreiste Zeile; ohne Preisstand entscheidet die id.
WITH gruppe AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY user_id, item_id, COALESCE(wear, ''::text), stattrak, playskin
               ORDER BY priced_at DESC NULLS LAST, id) AS platz,
           sum(quantity) OVER (
               PARTITION BY user_id, item_id, COALESCE(wear, ''::text), stattrak, playskin
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
               PARTITION BY user_id, item_id, COALESCE(wear, ''::text), stattrak, playskin
               ORDER BY priced_at DESC NULLS LAST, id) AS platz
      FROM cs2_positions
)
DELETE FROM cs2_positions
 WHERE id IN (SELECT id FROM gruppe WHERE platz > 1);

-- ---------- 3. Die Signatur ohne Lager ----------
-- ``COALESCE(wear, ''::text)`` bleibt und bleibt aus demselben Grund wie in
-- 051: Postgres haelt zwei NULL fuer verschieden, und ohne den Ausdruck laesst
-- der Index beliebig viele gleiche Zeilen zu, sobald die Abnutzung fehlt.
-- Jedes ``ON CONFLICT`` auf diese Tabelle muss den Ausdruck weiterhin
-- WOERTLICH nennen, samt ``::text``.
DROP INDEX IF EXISTS idx_cs2_positions_signatur;

ALTER TABLE cs2_positions DROP COLUMN IF EXISTS storage_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_cs2_positions_signatur
    ON cs2_positions (user_id, item_id, COALESCE(wear, ''::text), stattrak, playskin);

-- ---------- 4. Die Lagertabellen ----------
-- Erst die Aufteilung der Snapshots, dann die Lager selbst: die eine zeigt
-- auf die andere.
DROP TABLE IF EXISTS cs2_snapshot_storages;
DROP TABLE IF EXISTS cs2_storages;
