CREATE TABLE IF NOT EXISTS completed_goals (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    target_amount NUMERIC NOT NULL,
    final_amount NUMERIC NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ DEFAULT NOW(),
    photo_url TEXT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_completed_goals_date ON completed_goals(completed_at DESC);