-- Paket 6 + Invites: completed_goals um Trophäen-Felder erweitern,
-- Invite-Token für Passwort-Selbstvergabe.

-- Invite-Tokens
CREATE TABLE IF NOT EXISTS invite_tokens (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_invite_tokens_user ON invite_tokens(user_id);

-- User muss password_hash NULL erlauben, damit "Invited, not yet activated" möglich ist
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;

-- Trophäen-Felder für abgeschlossene Sparziele
ALTER TABLE completed_goals ADD COLUMN IF NOT EXISTS icon TEXT DEFAULT '🏆';
ALTER TABLE completed_goals ADD COLUMN IF NOT EXISTS color TEXT DEFAULT 'gold';
ALTER TABLE completed_goals ADD COLUMN IF NOT EXISTS duration_days INTEGER;

-- Index für Trophäen-Wand
CREATE INDEX IF NOT EXISTS idx_completed_goals_user_date
    ON completed_goals(user_id, completed_at DESC);