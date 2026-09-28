-- CS2 — der Preisverlauf je Gegenstand
--
-- Bis hierher kannte das Modul von jedem Gegenstand genau EINEN Preis: den
-- zuletzt bestaetigten, an der Position. Wer ihn aenderte, ueberschrieb den
-- alten. Die Staende (``cs2_snapshots``) halten den Gesamtwert fest, aber
-- nicht, was eine einzelne Kiste im Maerz kostete.
--
-- Diese Tabelle haelt jede Preisbestaetigung als eigene Zeile. Sie waechst
-- auf zwei Wegen:
--
-- 1. **Jede Bestaetigung ab jetzt.** Wer einen Preis in der Tabelle eintraegt
--    oder bestaetigt, schreibt hier eine Zeile mit -- auch wenn der Preis
--    derselbe bleibt. „Am 28. September stimmte der Preis noch“ ist eine
--    Beobachtung, und ohne sie saehe ein Verlauf aus, als sei zwischen zwei
--    Aenderungen nichts nachgesehen worden.
-- 2. **Die Vorgaengerfassung.** Rund 800 Beobachtungen vom Maerz bis
--    September, gelesen aus den alten Exporten und Berichten
--    (``uebernahme/altpreise.py``), kommen ueber die Uebertragungsdatei herein.
--
-- **Der Schluessel ist die Signatur, nicht die Position.** Eine Position wird
-- geloescht, wenn der Gegenstand verkauft ist -- sein Verlauf bleibt Teil der
-- Geschichte dieses Bestands. Deshalb zeigt eine Zeile auf den Gegenstand
-- samt Abnutzung und StatTrak, genau wie die Signatur einer Position, und
-- nicht auf ``cs2_positions.id``. Rund 40 der uebernommenen Gegenstaende
-- gibt es heute nicht mehr im Bestand.
--
-- Eine Zeile je (Signatur, Zeitpunkt). Dieselbe Beobachtung zweimal
-- einzuspielen -- ein zweiter Import derselben Datei -- aendert nichts.
--
-- ``quantity`` ist Beiwerk: die Stueckzahl zum Zeitpunkt der Beobachtung,
-- soweit bekannt. Die Staende tragen die Stueckzahlen je Tag verlaesslicher.

CREATE TABLE IF NOT EXISTS cs2_price_history (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- CASCADE und nicht RESTRICT: sonst liesse sich ein Nutzer nicht mehr
    -- loeschen, weil seine Gegenstaende an ihrem Verlauf haengen. Dass ein
    -- Gegenstand nicht aus Versehen samt Verlauf verschwindet, haelt der
    -- Router fest (``item_loeschen``), nicht der Fremdschluessel.
    item_id     INTEGER NOT NULL REFERENCES cs2_items(id) ON DELETE CASCADE,
    wear        TEXT CHECK (wear IS NULL OR wear IN ('FN', 'MW', 'FT', 'WW', 'BS')),
    stattrak    BOOLEAN NOT NULL DEFAULT FALSE,
    price_eur   NUMERIC(12, 2) NOT NULL CHECK (price_eur >= 0),
    quantity    INTEGER CHECK (quantity IS NULL OR quantity >= 0),
    priced_at   TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Derselbe Ausdruck wie an der Signatur der Positionen, aus demselben Grund:
-- Postgres haelt zwei NULL fuer verschieden, und ohne ``COALESCE`` liesse
-- der Index beliebig viele gleiche Zeilen zu, sobald die Abnutzung fehlt.
-- Jedes ``ON CONFLICT`` auf diese Tabelle nennt den Ausdruck woertlich.
CREATE UNIQUE INDEX IF NOT EXISTS idx_cs2_price_history_punkt
    ON cs2_price_history (user_id, item_id, COALESCE(wear, ''::text), stattrak, priced_at);

CREATE INDEX IF NOT EXISTS idx_cs2_price_history_abruf
    ON cs2_price_history (user_id, item_id, priced_at);

-- Der heutige Preis jeder Position ist ihre erste Beobachtung. Ohne diesen
-- Schritt faenge der Verlauf erst mit der naechsten Bestaetigung an, und ein
-- Import der alten Beobachtungen haette keinen Endpunkt von heute.
INSERT INTO cs2_price_history (user_id, item_id, wear, stattrak, price_eur, quantity, priced_at)
SELECT user_id, item_id, wear, stattrak, price_eur, quantity, priced_at
  FROM cs2_positions
 WHERE price_eur IS NOT NULL AND priced_at IS NOT NULL
ON CONFLICT (user_id, item_id, COALESCE(wear, ''::text), stattrak, priced_at) DO NOTHING;
