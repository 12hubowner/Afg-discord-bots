-- keyhub schema. run once via init_db().

CREATE TABLE IF NOT EXISTS keys (
    key           TEXT PRIMARY KEY,
    discord_id    INTEGER NOT NULL,
    key_days      INTEGER,              -- NULL = lifetime key
    note          TEXT NOT NULL DEFAULT '',
    hwid          TEXT,                 -- NULL = not yet bound
    activated_at  INTEGER,              -- unix seconds, set on first bind
    auth_expire   INTEGER,              -- unix seconds, NULL = lifetime
    blacklisted   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_keys_discord ON keys(discord_id);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO settings (key, value) VALUES ('system_paused', '0');
