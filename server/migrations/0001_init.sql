-- Canonical DDL applied by server/app/db.py:init_db (sqlite dialect).
-- Postgres variant notes are inline as comments.

-- submissions: one row per client POST /submit.
CREATE TABLE IF NOT EXISTS submissions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,   -- pg: BIGSERIAL
    username          TEXT    NOT NULL,
    hwid              TEXT    NOT NULL,
    fishing_catches   INTEGER NOT NULL,
    puzzles_solved    INTEGER NOT NULL,
    fishing_runtime_s REAL    NOT NULL,                    -- pg: DOUBLE PRECISION
    puzzler_runtime_s REAL    NOT NULL,                    -- pg: DOUBLE PRECISION
    app_version       TEXT    NOT NULL,
    ts                INTEGER NOT NULL,                    -- epoch seconds (pg: BIGINT)
    ip_hash           TEXT                                 -- salted sha256, never raw IP
);

CREATE INDEX IF NOT EXISTS ix_sub_hwid     ON submissions(hwid);
CREATE INDEX IF NOT EXISTS ix_sub_username ON submissions(username);
CREATE INDEX IF NOT EXISTS ix_sub_ts       ON submissions(ts);

-- bans: ban/erase by HWID or username.
CREATE TABLE IF NOT EXISTS bans (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,              -- pg: BIGSERIAL
    kind   TEXT NOT NULL CHECK (kind IN ('hwid','username')),
    value  TEXT NOT NULL,
    reason TEXT,
    ts     INTEGER NOT NULL,                               -- pg: BIGINT
    UNIQUE(kind, value)
);
