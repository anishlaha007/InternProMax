"""SQLite storage: schema, connections and the key/value store."""

from __future__ import annotations

import copy
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    list_source   TEXT,
    company       TEXT NOT NULL,
    title         TEXT NOT NULL,
    category      TEXT,
    terms         TEXT NOT NULL DEFAULT '[]',
    locations     TEXT NOT NULL DEFAULT '[]',
    url           TEXT,
    url_key       TEXT,
    ats           TEXT,
    ats_key       TEXT,
    company_url   TEXT,
    sponsorship   TEXT,
    degrees       TEXT NOT NULL DEFAULT '[]',
    active        INTEGER NOT NULL DEFAULT 1,
    visible       INTEGER NOT NULL DEFAULT 1,
    date_posted   INTEGER,
    date_updated  INTEGER,
    first_seen    INTEGER NOT NULL,
    last_seen     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_url_key ON jobs(url_key);
CREATE INDEX IF NOT EXISTS idx_jobs_ats_key ON jobs(ats_key);
CREATE INDEX IF NOT EXISTS idx_jobs_active ON jobs(active, visible);

CREATE TABLE IF NOT EXISTS job_state (
    job_id     TEXT PRIMARY KEY,
    hidden     INTEGER NOT NULL DEFAULT 0,
    opened_at  INTEGER,
    notes      TEXT
);

CREATE TABLE IF NOT EXISTS job_details (
    job_id           TEXT PRIMARY KEY,
    description      TEXT,
    fetch_method     TEXT,
    fetched_at       INTEGER,
    analysis         TEXT,
    analysis_method  TEXT,
    analyzed_at      INTEGER,
    status           TEXT NOT NULL DEFAULT 'none',
    error            TEXT
);

CREATE TABLE IF NOT EXISTS resumes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT,
    data        TEXT,
    changes     TEXT,
    warnings    TEXT,
    method      TEXT,
    status      TEXT NOT NULL DEFAULT 'ready',
    error       TEXT,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resumes_job ON resumes(job_id, id);

CREATE TABLE IF NOT EXISTS applications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT UNIQUE,
    company     TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    url         TEXT,
    location    TEXT,
    status      TEXT NOT NULL,
    applied_at  INTEGER,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    source      TEXT,
    ats         TEXT,
    notes       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id  INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    ts              INTEGER NOT NULL,
    type            TEXT NOT NULL,
    from_status     TEXT,
    to_status       TEXT,
    detail          TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_app ON events(application_id, ts);

CREATE TABLE IF NOT EXISTS email_suggestions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    message_key      TEXT UNIQUE,
    sender           TEXT,
    subject          TEXT,
    snippet          TEXT,
    received_at      INTEGER,
    application_id   INTEGER REFERENCES applications(id) ON DELETE SET NULL,
    suggested_status TEXT,
    confidence       REAL,
    reasons          TEXT,
    state            TEXT NOT NULL DEFAULT 'pending',
    created_at       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""

_lock = threading.Lock()
_initialized: set[str] = set()
_db_path: Path | None = None


def db_path() -> Path:
    return _db_path or (config.ensure_data_dir() / "internpromax.db")


def set_db_path(path: Path | str) -> None:
    """Point the app at a different database (used by tests)."""
    global _db_path
    _db_path = Path(path)


def _init(conn: sqlite3.Connection, key: str) -> None:
    with _lock:
        if key in _initialized:
            return
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        conn.commit()
        _initialized.add(key)


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    _init(conn, str(path))
    return conn


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now() -> int:
    return int(time.time())


# ---------------------------------------------------------------- key/value

def kv_get(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    if row is None:
        return copy.deepcopy(default)
    return json.loads(row["value"])


def kv_set(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def get_settings(conn: sqlite3.Connection) -> dict:
    return deep_merge(config.DEFAULT_SETTINGS, kv_get(conn, "settings", {}))


def save_settings(conn: sqlite3.Connection, patch: dict) -> dict:
    current = kv_get(conn, "settings", {})
    merged = deep_merge(current, patch)
    kv_set(conn, "settings", merged)
    return deep_merge(config.DEFAULT_SETTINGS, merged)


def row_to_dict(row: sqlite3.Row | None, json_fields: tuple[str, ...] = ()) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for f in json_fields:
        if f in d and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except json.JSONDecodeError:
                pass
    return d
