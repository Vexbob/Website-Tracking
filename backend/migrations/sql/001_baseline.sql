-- Baseline: bildet den Status quo ab. Idempotent auf frischen UND bestehenden DBs.

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS savings_goals (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    target_amount NUMERIC NOT NULL,
    current_amount NUMERIC DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS achievements (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    reward_amount NUMERIC NOT NULL,
    unit TEXT NOT NULL,
    current_value NUMERIC DEFAULT 0,
    start_value NUMERIC DEFAULT 0,
    threshold_increment NUMERIC NOT NULL,
    target_value NUMERIC,
    direction TEXT DEFAULT 'increase',
    credited_milestones INTEGER DEFAULT 0,
    is_completed BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS achievement_logs (
    id SERIAL PRIMARY KEY,
    achievement_id INTEGER REFERENCES achievements(id) ON DELETE CASCADE,
    achieved_value NUMERIC,
    reward_amount NUMERIC,
    date_achieved TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS progress_goals (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    reward_amount NUMERIC NOT NULL,
    rhythm_type TEXT DEFAULT 'weekly',
    target_count INTEGER NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS progress_logs (
    id SERIAL PRIMARY KEY,
    progress_goal_id INTEGER REFERENCES progress_goals(id) ON DELETE CASCADE,
    log_date DATE NOT NULL,
    week_key TEXT NOT NULL,
    month_key TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS health_metrics (
    id SERIAL PRIMARY KEY,
    metric_type TEXT NOT NULL,
    value NUMERIC,
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS savings_transactions (
    id SERIAL PRIMARY KEY,
    amount NUMERIC NOT NULL,
    source_type TEXT NOT NULL,
    source_id INTEGER,
    description TEXT,
    period_key TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS potential_goals (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    estimated_price NUMERIC,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS future_ideas (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Zusätzliche Spalten, die durch spätere Erweiterungen entstanden sind (idempotent)
ALTER TABLE progress_logs         ADD COLUMN IF NOT EXISTS month_key TEXT;
ALTER TABLE savings_transactions  ADD COLUMN IF NOT EXISTS period_key TEXT;
ALTER TABLE progress_goals        ADD COLUMN IF NOT EXISTS streak_bonus_amount NUMERIC DEFAULT 0;
ALTER TABLE progress_goals        ADD COLUMN IF NOT EXISTS streak_bonus_threshold INTEGER DEFAULT 0;
ALTER TABLE achievements          ADD COLUMN IF NOT EXISTS sort_order INTEGER;
ALTER TABLE progress_goals        ADD COLUMN IF NOT EXISTS sort_order INTEGER;

-- Backfill für alte Daten (idempotent)
UPDATE progress_logs
   SET month_key = TO_CHAR(log_date, 'YYYY-MM')
 WHERE month_key IS NULL;

UPDATE savings_transactions
   SET period_key = TO_CHAR(created_at, 'IYYY') || '-W' || LPAD(TO_CHAR(created_at, 'IW'), 2, '0')
 WHERE source_type = 'progress' AND period_key IS NULL;