-- Erlaubt Backdating: date_achieved wird beim Insert explizit gesetzt.
-- date_achieved existiert bereits, aber wir stellen sicher dass es nullable ist und einen Index bekommt.
CREATE INDEX IF NOT EXISTS idx_achievement_logs_achievement_date
    ON achievement_logs(achievement_id, date_achieved DESC);
CREATE INDEX IF NOT EXISTS idx_savings_transactions_source
    ON savings_transactions(source_type, source_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_progress_logs_goal_period
    ON progress_logs(progress_goal_id, week_key, month_key);