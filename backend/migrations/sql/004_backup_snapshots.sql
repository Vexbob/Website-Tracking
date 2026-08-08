CREATE TABLE IF NOT EXISTS backup_snapshots (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    trigger_type TEXT NOT NULL,  -- 'auto_daily' | 'auto_weekly' | 'manual'
    payload JSONB NOT NULL,
    size_bytes INTEGER
);
CREATE INDEX IF NOT EXISTS idx_backup_snapshots_date ON backup_snapshots(created_at DESC);