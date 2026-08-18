-- General-Pool + Achievement/Progress-Goal Zuordnung (v1.18.2)
-- Ergänzt ein "Allgemein"-Konto pro User: dahin gehen Meilenstein-Belohnungen,
-- wenn kein aktives Sparziel existiert ODER wenn das aktive Sparziel bereits
-- am/über dem Zielbetrag ist. So werden Meilensteine IMMER verbucht.

ALTER TABLE savings_goals
    ADD COLUMN IF NOT EXISTS is_general BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE achievements
    ADD COLUMN IF NOT EXISTS reward_goal_id INTEGER
        REFERENCES savings_goals(id) ON DELETE SET NULL;

ALTER TABLE progress_goals
    ADD COLUMN IF NOT EXISTS reward_goal_id INTEGER
        REFERENCES savings_goals(id) ON DELETE SET NULL;

-- Fuer jeden bestehenden User ein General-Konto anlegen (idempotent).
INSERT INTO savings_goals (user_id, name, target_amount, is_active, is_general)
SELECT u.id, 'Allgemein', 0, FALSE, TRUE
FROM users u
WHERE NOT EXISTS (
    SELECT 1 FROM savings_goals sg
    WHERE sg.user_id = u.id AND sg.is_general = TRUE
);

-- Uniqueness: nur EIN General-Konto pro User
CREATE UNIQUE INDEX IF NOT EXISTS uniq_savings_goals_general_per_user
    ON savings_goals (user_id) WHERE is_general = TRUE;
