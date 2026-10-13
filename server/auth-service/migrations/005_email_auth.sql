BEGIN;
SET LOCAL ROLE documate_auth;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(254);
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_version INTEGER NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique ON users (email);
CREATE TABLE IF NOT EXISTS email_challenges (
    id VARCHAR(32) PRIMARY KEY,
    email VARCHAR(254) NOT NULL,
    purpose VARCHAR(16) NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    auth_version INTEGER NOT NULL DEFAULT 0,
    code_hash VARCHAR(64) NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    delivered BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_email_challenges_email ON email_challenges(email);
CREATE INDEX IF NOT EXISTS ix_email_challenges_expires_at ON email_challenges(expires_at);
CREATE TABLE IF NOT EXISTS auth_rate_buckets (
    key VARCHAR(64) PRIMARY KEY,
    count INTEGER NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_auth_rate_buckets_expires_at ON auth_rate_buckets(expires_at);
COMMIT;
