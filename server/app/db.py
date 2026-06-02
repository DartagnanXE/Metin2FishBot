# -*- coding: utf-8 -*-
"""DB layer over a DEDICATED sqlite file (its own volume; NOT shared with kilab).

sqlite (WAL mode) is plenty for a tiny honor-system leaderboard in a single
small container. The postgres swap path is documented inline. ALL queries are
parameterised (no string concatenation) -> no SQL injection.

Tables:
  submissions(id, username, hwid, fishing_catches, puzzles_solved,
              fishing_runtime_s, puzzler_runtime_s, app_version, ts, ip_hash)
  bans(id, kind 'hwid'|'username', value, reason, ts)

The leaderboard aggregates MAX(counter) per identity (a client only ever grows
its cumulative counters, so MAX is the latest truth and resists a single bad
submission lowering a score). Banned identities are excluded.
"""

import os
import sqlite3
import time
import threading

DEFAULT_DB_PATH = os.environ.get('DB_PATH', '/data/telemetry.db')

# One connection guarded by a lock (uvicorn workers in one process; for multiple
# workers switch to a connection-per-request or postgres -- see DEPLOY.md).
_LOCK = threading.Lock()
_CONN = None


def _connect(path):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def init_db(path=DEFAULT_DB_PATH):
    """Create tables/indexes if missing and cache the connection. Idempotent."""
    global _CONN
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    _CONN = _connect(path)
    _CONN.executescript(
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            hwid TEXT NOT NULL,
            fishing_catches INTEGER NOT NULL,
            puzzles_solved INTEGER NOT NULL,
            fishing_runtime_s REAL NOT NULL,
            puzzler_runtime_s REAL NOT NULL,
            app_version TEXT NOT NULL,
            ts INTEGER NOT NULL,
            ip_hash TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_sub_hwid ON submissions(hwid);
        CREATE INDEX IF NOT EXISTS ix_sub_username ON submissions(username);
        CREATE INDEX IF NOT EXISTS ix_sub_ts ON submissions(ts);

        CREATE TABLE IF NOT EXISTS bans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL CHECK (kind IN ('hwid','username')),
            value TEXT NOT NULL,
            reason TEXT,
            ts INTEGER NOT NULL,
            UNIQUE(kind, value)
        );
        """
    )
    _CONN.commit()
    return _CONN


def _conn():
    if _CONN is None:
        init_db()
    return _CONN


def last_for_identity(hwid):
    """Return the most recent submission row for an HWID (or None).

    Used by the anti-abuse check to reject implausible downward/huge jumps.
    """
    with _LOCK:
        cur = _conn().execute(
            'SELECT * FROM submissions WHERE hwid = ? '
            'ORDER BY ts DESC, id DESC LIMIT 1',
            (hwid,))
        return cur.fetchone()


def insert_submission(row):
    """Insert one submission (dict). Parameterised. Returns the new row id."""
    with _LOCK:
        cur = _conn().execute(
            """INSERT INTO submissions
               (username, hwid, fishing_catches, puzzles_solved,
                fishing_runtime_s, puzzler_runtime_s, app_version, ts, ip_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (row['username'], row['hwid'], row['fishing_catches'],
             row['puzzles_solved'], row['fishing_runtime_s'],
             row['puzzler_runtime_s'], row['app_version'], row['ts'],
             row.get('ip_hash')))
        _conn().commit()
        return cur.lastrowid


def leaderboard(period='all', limit=100):
    """Aggregated board (MAX counters per username), excluding banned identities.

    ``period`` 'daily' restricts to submissions from the last 24h; 'all' uses
    everything. Returns a list of dicts ordered by fishing_catches desc.
    """
    since = 0
    if period == 'daily':
        since = int(time.time()) - 86_400
    with _LOCK:
        cur = _conn().execute(
            """
            SELECT username,
                   MAX(fishing_catches)  AS fishing_catches,
                   MAX(puzzles_solved)   AS puzzles_solved,
                   MAX(fishing_runtime_s) AS fishing_runtime_s,
                   MAX(puzzler_runtime_s) AS puzzler_runtime_s
            FROM submissions
            WHERE ts >= ?
              AND username NOT IN (SELECT value FROM bans WHERE kind='username')
              AND hwid     NOT IN (SELECT value FROM bans WHERE kind='hwid')
            GROUP BY username
            ORDER BY fishing_catches DESC, puzzles_solved DESC
            LIMIT ?
            """,
            (since, limit))
        rows = [dict(r) for r in cur.fetchall()]
    for i, r in enumerate(rows, start=1):
        r['rank'] = i
    return rows


def is_banned(kind, value):
    """True iff (kind, value) is banned. Parameterised."""
    with _LOCK:
        cur = _conn().execute(
            'SELECT 1 FROM bans WHERE kind = ? AND value = ? LIMIT 1',
            (kind, value))
        return cur.fetchone() is not None


def add_ban(kind, value, reason=None):
    """Insert/replace a ban. Returns True. Parameterised."""
    with _LOCK:
        _conn().execute(
            """INSERT INTO bans (kind, value, reason, ts) VALUES (?, ?, ?, ?)
               ON CONFLICT(kind, value) DO UPDATE SET reason=excluded.reason,
                                                      ts=excluded.ts""",
            (kind, value, reason, int(time.time())))
        _conn().commit()
    return True


def remove_ban(kind, value):
    """Delete a ban. Returns the number of rows removed."""
    with _LOCK:
        cur = _conn().execute(
            'DELETE FROM bans WHERE kind = ? AND value = ?', (kind, value))
        _conn().commit()
        return cur.rowcount


def delete_entries(kind, value):
    """GDPR erasure: delete all submissions for an HWID or username.

    Returns the number of rows removed. Parameterised.
    """
    column = 'hwid' if kind == 'hwid' else 'username'
    with _LOCK:
        cur = _conn().execute(
            'DELETE FROM submissions WHERE {} = ?'.format(column), (value,))
        _conn().commit()
        return cur.rowcount


def list_bans():
    """Return all bans as a list of dicts."""
    with _LOCK:
        cur = _conn().execute(
            'SELECT kind, value, reason, ts FROM bans ORDER BY ts DESC')
        return [dict(r) for r in cur.fetchall()]
