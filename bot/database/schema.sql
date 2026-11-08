PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS groups (
    group_id          INTEGER PRIMARY KEY,
    title             TEXT,
    tracking_enabled  INTEGER NOT NULL DEFAULT 0,
    rules1            TEXT,
    rules2            TEXT,
    rules3            TEXT,
    active_session_id INTEGER,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id              INTEGER NOT NULL,
    status                TEXT NOT NULL DEFAULT 'collecting',
    -- collecting -> collecting_closed -> engaging -> closed
    link_reminder_msg_id  INTEGER,
    scam_reminder_msg_id  INTEGER,
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at             TEXT,
    FOREIGN KEY (group_id) REFERENCES groups (group_id)
);

CREATE TABLE IF NOT EXISTS members (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL,
    group_id        INTEGER NOT NULL,
    telegram_id     INTEGER NOT NULL,
    username        TEXT,
    x_username      TEXT,
    x_link          TEXT,
    tweet_id        TEXT,
    link_message_id INTEGER,
    status          TEXT NOT NULL DEFAULT 'pending',
    -- pending -> safe / resend / fraud / deleted / edited
    submitted_at    TEXT,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (session_id, telegram_id),
    FOREIGN KEY (session_id) REFERENCES sessions (id)
);

-- Permanent ownership of an X account, currently held by whichever
-- Telegram account most recently used it "cleanly" (see telegram_sanctions
-- below for how a new account can inherit ownership).
CREATE TABLE IF NOT EXISTS x_ownership (
    x_username     TEXT PRIMARY KEY,
    telegram_id    INTEGER NOT NULL,
    username       TEXT,
    first_seen_at  TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Tracks the most recent time a Telegram account was sanctioned
-- (muted/banned/suspended by an admin, or auto-muted for X-ownership fraud).
-- Used to decide whether a different Telegram account may legitimately take
-- over an X account previously used by someone who was never punished for
-- it (e.g. lost access to their old Telegram account) vs. someone who WAS
-- sanctioned after their last use of it (a genuine alt-account attempt).
CREATE TABLE IF NOT EXISTS telegram_sanctions (
    telegram_id         INTEGER PRIMARY KEY,
    last_sanctioned_at  TEXT NOT NULL,
    reason              TEXT
);

-- Every message the bot needs to be able to purge later (/clean)
CREATE TABLE IF NOT EXISTS message_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL,
    group_id    INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    telegram_id INTEGER,
    kind        TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fraud_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id            INTEGER,
    session_id          INTEGER,
    x_username          TEXT,
    owner_telegram_id   INTEGER,
    offender_telegram_id INTEGER,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Lightweight cache so /unmute @username can resolve a username -> id
CREATE TABLE IF NOT EXISTS user_cache (
    group_id    INTEGER NOT NULL,
    username    TEXT NOT NULL,
    telegram_id INTEGER NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (group_id, username)
);

CREATE INDEX IF NOT EXISTS idx_members_session_status ON members (session_id, status);
CREATE INDEX IF NOT EXISTS idx_message_log_session ON message_log (session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_group_status ON sessions (group_id, status);
