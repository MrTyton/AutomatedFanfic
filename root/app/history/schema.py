"""Database schema, DDL definitions, connection pragmas, and migrations for history storage."""

from datetime import datetime
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS download_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT    NOT NULL,
    site            TEXT    NOT NULL,
    title           TEXT,
    calibre_id      TEXT,
    behavior        TEXT,
    status          TEXT    NOT NULL DEFAULT 'pending',
    error_message   TEXT,
    started_at      TEXT    NOT NULL,
    completed_at    TEXT,
    updated_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_download_events_url ON download_events(url);
CREATE INDEX IF NOT EXISTS idx_download_events_url_started_at ON download_events(url, started_at);
CREATE INDEX IF NOT EXISTS idx_download_events_site ON download_events(site);
CREATE INDEX IF NOT EXISTS idx_download_events_status ON download_events(status);
CREATE INDEX IF NOT EXISTS idx_download_events_started_at ON download_events(started_at);

CREATE TABLE IF NOT EXISTS retry_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    download_event_id   INTEGER,
    url                 TEXT    NOT NULL,
    site                TEXT    NOT NULL,
    attempt_number      INTEGER NOT NULL,
    action              TEXT    NOT NULL,
    delay_minutes       REAL    NOT NULL DEFAULT 0,
    error_message       TEXT,
    scheduled_at        TEXT    NOT NULL,
    fired_at            TEXT,
    FOREIGN KEY (download_event_id) REFERENCES download_events(id)
);

CREATE INDEX IF NOT EXISTS idx_retry_events_url ON retry_events(url);
CREATE INDEX IF NOT EXISTS idx_retry_events_download_id ON retry_events(download_event_id);

CREATE TABLE IF NOT EXISTS email_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at          TEXT    NOT NULL,
    urls_found          INTEGER NOT NULL DEFAULT 0,
    urls_new            INTEGER NOT NULL DEFAULT 0,
    urls_duplicate      INTEGER NOT NULL DEFAULT 0,
    urls_disabled_site  INTEGER NOT NULL DEFAULT 0,
    trigger             TEXT    NOT NULL DEFAULT 'poll'
);

CREATE TABLE IF NOT EXISTS notification_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    download_event_id   INTEGER,
    title               TEXT    NOT NULL,
    body                TEXT    NOT NULL,
    site                TEXT,
    sent_at             TEXT    NOT NULL,
    provider            TEXT,
    FOREIGN KEY (download_event_id) REFERENCES download_events(id)
);

CREATE INDEX IF NOT EXISTS idx_notification_events_sent_at ON notification_events(sent_at);
"""


def _dt_to_str(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def setup_sync_connection(conn: sqlite3.Connection) -> None:
    """Configure connection pragmas for synchronous SQLite connections."""
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-65536")  # 64 MB page cache


async def setup_async_connection(conn: aiosqlite.Connection) -> None:
    """Configure connection pragmas for asynchronous SQLite connections."""
    await conn.execute("PRAGMA busy_timeout=5000")
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA cache_size=-65536")  # 64 MB page cache


def ensure_schema_sync(conn: sqlite3.Connection) -> None:
    """Execute DDL schema and apply necessary column migrations synchronously."""
    conn.executescript(_SCHEMA)
    try:
        conn.execute("ALTER TABLE download_events ADD COLUMN updated_at TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            "ALTER TABLE email_events ADD COLUMN trigger TEXT NOT NULL DEFAULT 'poll'"
        )
    except sqlite3.OperationalError:
        pass
    conn.commit()


async def ensure_schema_async(conn: aiosqlite.Connection) -> None:
    """Execute DDL schema and apply necessary column migrations asynchronously."""
    await conn.executescript(_SCHEMA)
    try:
        await conn.execute("ALTER TABLE download_events ADD COLUMN updated_at TEXT")
    except Exception:
        pass
    try:
        await conn.execute(
            "ALTER TABLE email_events ADD COLUMN trigger TEXT NOT NULL DEFAULT 'poll'"
        )
    except Exception:
        pass
    await conn.commit()
