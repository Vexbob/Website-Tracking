-- Multi-User Migration: user_id an alle Nutzdaten-Tabellen, is_admin für Main-Account.
-- Idempotent, verträgt Re-Runs.

-- 1) Admin-Flag
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;

-- 2) user_id auf allen Nutzdaten-Tabellen (nullable — wird gleich befüllt)
ALTER TABLE savings_goals         ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE achievements          ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE achievement_logs      ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE progress_goals        ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE progress_logs         ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE health_metrics        ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE savings_transactions  ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE potential_goals       ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE future_ideas          ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE completed_goals       ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;
-- backup_snapshots bekommt user_id, aber NULL = globaler/admin Snapshot
ALTER TABLE backup_snapshots      ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;

-- 3) Etienne zum Admin machen (falls existent)
UPDATE users SET is_admin = TRUE WHERE username = 'Etienne';

-- 4) Backfill: alle Bestandsdaten Etienne zuordnen
DO $$
DECLARE main_id INTEGER;
BEGIN
    SELECT id INTO main_id FROM users WHERE username = 'Etienne' LIMIT 1;
    IF main_id IS NOT NULL THEN
        UPDATE savings_goals        SET user_id = main_id WHERE user_id IS NULL;
        UPDATE achievements         SET user_id = main_id WHERE user_id IS NULL;
        UPDATE achievement_logs     SET user_id = main_id WHERE user_id IS NULL;
        UPDATE progress_goals       SET user_id = main_id WHERE user_id IS NULL;
        UPDATE progress_logs        SET user_id = main_id WHERE user_id IS NULL;
        UPDATE health_metrics       SET user_id = main_id WHERE user_id IS NULL;
        UPDATE savings_transactions SET user_id = main_id WHERE user_id IS NULL;
        UPDATE potential_goals      SET user_id = main_id WHERE user_id IS NULL;
        UPDATE future_ideas         SET user_id = main_id WHERE user_id IS NULL;
        UPDATE completed_goals      SET user_id = main_id WHERE user_id IS NULL;
    END IF;
END $$;

-- 5) Indizes für Performance
CREATE INDEX IF NOT EXISTS idx_savings_goals_user        ON savings_goals(user_id);
CREATE INDEX IF NOT EXISTS idx_achievements_user         ON achievements(user_id);
CREATE INDEX IF NOT EXISTS idx_achievement_logs_user     ON achievement_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_progress_goals_user       ON progress_goals(user_id);
CREATE INDEX IF NOT EXISTS idx_progress_logs_user        ON progress_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_health_metrics_user       ON health_metrics(user_id);
CREATE INDEX IF NOT EXISTS idx_savings_transactions_user ON savings_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_potential_goals_user      ON potential_goals(user_id);
CREATE INDEX IF NOT EXISTS idx_future_ideas_user         ON future_ideas(user_id);
CREATE INDEX IF NOT EXISTS idx_completed_goals_user      ON completed_goals(user_id);
CREATE INDEX IF NOT EXISTS idx_backup_snapshots_user     ON backup_snapshots(user_id);