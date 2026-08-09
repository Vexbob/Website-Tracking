-- Paket 8:
-- Mehrere Sparziele pro User verwalten (aktiv + pausiert, jedes mit eigenem Kontostand).
--
-- 1) savings_transactions bekommt eine harte Zuordnung zu genau einem savings_goal.
-- 2) Backfill: bestehende Transactions dem jeweils aktiven Ziel des Users zuweisen.

ALTER TABLE savings_transactions
    ADD COLUMN IF NOT EXISTS savings_goal_id INTEGER
    REFERENCES savings_goals(id) ON DELETE CASCADE;

-- Backfill (nur für noch nicht zugeordnete Zeilen)
UPDATE savings_transactions st
   SET savings_goal_id = (
        SELECT id FROM savings_goals sg
        WHERE sg.user_id = st.user_id AND sg.is_active = TRUE
        ORDER BY sg.id DESC LIMIT 1)
 WHERE st.savings_goal_id IS NULL;

-- Index für die häufigste Query (Summen pro Ziel)
CREATE INDEX IF NOT EXISTS idx_savings_tx_goal
    ON savings_transactions (savings_goal_id, user_id);
