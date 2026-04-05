"""Async SQLite database for persistent history storage.

HistoryDB owns the connection lifecycle, schema creation, and all
read/write operations.  Reads are async (aiosqlite) for the FastAPI
web server; the synchronous write helpers are called exclusively from
the single-threaded HistoryWriter (see recorder.py).
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from history.models import (
    DownloadEvent,
    DownloadStatus,
    EmailCheckEvent,
    NotificationEvent,
    RetryEvent,
)

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
    completed_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_download_events_url ON download_events(url);
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
    urls_disabled_site  INTEGER NOT NULL DEFAULT 0
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


def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


# ---------------------------------------------------------------------------
# Synchronous helpers (used by HistoryWriter thread only)
# ---------------------------------------------------------------------------


class SyncHistoryDB:
    """Synchronous SQLite wrapper used exclusively by the HistoryWriter thread."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # -- writes --

    def insert_download(self, event: DownloadEvent) -> int:
        assert self._conn is not None
        cur = self._conn.execute(
            """INSERT INTO download_events
               (url, site, title, calibre_id, behavior, status,
                error_message, started_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.url,
                event.site,
                event.title,
                event.calibre_id,
                event.behavior,
                event.status.value,
                event.error_message,
                _dt_to_str(event.started_at),
                _dt_to_str(event.completed_at),
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def update_download(
        self,
        url: str,
        status: DownloadStatus,
        title: Optional[str] = None,
        calibre_id: Optional[str] = None,
        error_message: Optional[str] = None,
        completed_at: Optional[datetime] = None,
        site: Optional[str] = None,
    ) -> None:
        """Update the most recent in-progress download_event for *url*.

        Matches rows with status 'pending' or 'waiting' (both represent
        in-progress downloads).  If no such row exists, insert a new
        completed row so the event isn't lost.
        """
        assert self._conn is not None
        cur = self._conn.execute(
            """UPDATE download_events
               SET status = ?,
                   title = COALESCE(?, title),
                   calibre_id = COALESCE(?, calibre_id),
                   error_message = COALESCE(?, error_message),
                   completed_at = COALESCE(?, completed_at)
               WHERE id = (
                   SELECT id FROM download_events
                   WHERE url = ? AND status IN ('pending', 'waiting')
                   ORDER BY started_at DESC LIMIT 1
               )""",
            (
                status.value,
                title,
                calibre_id,
                error_message,
                _dt_to_str(completed_at),
                url,
            ),
        )
        if cur.rowcount == 0:
            # No pending row found — insert a complete record
            self._conn.execute(
                """INSERT INTO download_events
                   (url, site, title, calibre_id, status,
                    error_message, started_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    url,
                    site or "",
                    title,
                    calibre_id,
                    status.value,
                    error_message,
                    _dt_to_str(completed_at or datetime.now()),
                    _dt_to_str(completed_at),
                ),
            )
        self._conn.commit()

    def insert_retry(self, event: RetryEvent) -> int:
        assert self._conn is not None
        # Resolve download_event_id from url if not provided
        download_event_id = event.download_event_id
        if download_event_id is None:
            row = self._conn.execute(
                """SELECT id FROM download_events
                   WHERE url = ? ORDER BY started_at DESC LIMIT 1""",
                (event.url,),
            ).fetchone()
            if row:
                download_event_id = row[0]

        cur = self._conn.execute(
            """INSERT INTO retry_events
               (download_event_id, url, site, attempt_number, action,
                delay_minutes, error_message, scheduled_at, fired_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                download_event_id,
                event.url,
                event.site,
                event.attempt_number,
                event.action.value,
                event.delay_minutes,
                event.error_message,
                _dt_to_str(event.scheduled_at),
                _dt_to_str(event.fired_at),
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def update_retry_fired(
        self, url: str, attempt_number: int, fired_at: datetime
    ) -> None:
        assert self._conn is not None
        self._conn.execute(
            """UPDATE retry_events
               SET fired_at = ?
               WHERE url = ? AND attempt_number = ? AND fired_at IS NULL""",
            (_dt_to_str(fired_at), url, attempt_number),
        )
        self._conn.commit()

    def insert_email_check(self, event: EmailCheckEvent) -> int:
        assert self._conn is not None
        cur = self._conn.execute(
            """INSERT INTO email_events
               (checked_at, urls_found, urls_new, urls_duplicate, urls_disabled_site)
               VALUES (?, ?, ?, ?, ?)""",
            (
                _dt_to_str(event.checked_at),
                event.urls_found,
                event.urls_new,
                event.urls_duplicate,
                event.urls_disabled_site,
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def insert_notification(self, event: NotificationEvent) -> int:
        assert self._conn is not None
        download_event_id = event.download_event_id
        if download_event_id is None and event.site:
            # Best-effort: link to most recent download for this site
            row = self._conn.execute(
                """SELECT id FROM download_events
                   WHERE site = ? ORDER BY started_at DESC LIMIT 1""",
                (event.site,),
            ).fetchone()
            if row:
                download_event_id = row[0]

        cur = self._conn.execute(
            """INSERT INTO notification_events
               (download_event_id, title, body, site, sent_at, provider)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                download_event_id,
                event.title,
                event.body,
                event.site,
                _dt_to_str(event.sent_at),
                event.provider,
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Async helpers (used by FastAPI web server for reads)
# ---------------------------------------------------------------------------


class AsyncHistoryDB:
    """Async SQLite wrapper for read queries from the web API."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    async def _get_conn(self) -> aiosqlite.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(self._db_path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        return conn

    async def ensure_schema(self) -> None:
        conn = await self._get_conn()
        try:
            await conn.executescript(_SCHEMA)
            await conn.commit()
        finally:
            await conn.close()

    async def get_downloads(
        self,
        limit: int = 50,
        offset: int = 0,
        site: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[dict]:
        conn = await self._get_conn()
        try:
            conditions = []
            params: list = []
            if site:
                conditions.append("site = ?")
                params.append(site)
            if status:
                conditions.append("status = ?")
                params.append(status)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            query = f"""SELECT * FROM download_events {where}
                        ORDER BY started_at DESC LIMIT ? OFFSET ?"""
            params.extend([limit, offset])

            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            await conn.close()

    async def get_download_count(
        self,
        site: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        conn = await self._get_conn()
        try:
            conditions = []
            params: list = []
            if site:
                conditions.append("site = ?")
                params.append(site)
            if status:
                conditions.append("status = ?")
                params.append(status)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            cursor = await conn.execute(
                f"SELECT COUNT(*) FROM download_events {where}", params
            )
            row = await cursor.fetchone()
            return row[0] if row else 0
        finally:
            await conn.close()

    async def get_retries_for_url(self, url: str) -> list[dict]:
        conn = await self._get_conn()
        try:
            cursor = await conn.execute(
                """SELECT * FROM retry_events
                   WHERE url = ? ORDER BY scheduled_at ASC""",
                (url,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            await conn.close()

    async def get_email_checks(self, limit: int = 50, offset: int = 0) -> list[dict]:
        conn = await self._get_conn()
        try:
            cursor = await conn.execute(
                """SELECT * FROM email_events
                   ORDER BY checked_at DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            await conn.close()

    async def get_notifications(self, limit: int = 50, offset: int = 0) -> list[dict]:
        conn = await self._get_conn()
        try:
            cursor = await conn.execute(
                """SELECT * FROM notification_events
                   ORDER BY sent_at DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            await conn.close()

    async def get_recent_events(self, limit: int = 10) -> list[dict]:
        """Get the most recent events across all tables for dashboard feed."""
        conn = await self._get_conn()
        try:
            events = []

            cursor = await conn.execute(
                """SELECT 'download' as event_type, id, url, site, title,
                          calibre_id, status, error_message,
                          started_at as timestamp, completed_at
                   FROM download_events
                   ORDER BY started_at DESC LIMIT ?""",
                (limit,),
            )
            events.extend([dict(r) for r in await cursor.fetchall()])

            cursor = await conn.execute(
                """SELECT 'retry' as event_type, id, url, site,
                          attempt_number, action, scheduled_at as timestamp
                   FROM retry_events
                   ORDER BY scheduled_at DESC LIMIT ?""",
                (limit,),
            )
            events.extend([dict(r) for r in await cursor.fetchall()])

            cursor = await conn.execute(
                """SELECT 'notification' as event_type, id, title, body,
                          site, provider, sent_at as timestamp
                   FROM notification_events
                   ORDER BY sent_at DESC LIMIT ?""",
                (limit,),
            )
            events.extend([dict(r) for r in await cursor.fetchall()])

            cursor = await conn.execute(
                """SELECT 'email_check' as event_type, id,
                          urls_found, urls_new, checked_at as timestamp
                   FROM email_events
                   ORDER BY checked_at DESC LIMIT ?""",
                (limit,),
            )
            events.extend([dict(r) for r in await cursor.fetchall()])

            # Sort all by timestamp descending and return top N
            events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
            return events[:limit]
        finally:
            await conn.close()

    async def get_recent_downloads(self, limit: int = 20) -> list[dict]:
        """Get the most recent download events for the dashboard."""
        conn = await self._get_conn()
        try:
            cursor = await conn.execute(
                """SELECT id, url, site, title, calibre_id, status,
                          error_message, started_at, completed_at
                   FROM download_events
                   ORDER BY started_at DESC LIMIT ?""",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    async def get_recent_activity(self, limit: int = 20) -> list[dict]:
        """Get the most recent non-download events for the dashboard feed."""
        conn = await self._get_conn()
        try:
            events: list[dict] = []

            cursor = await conn.execute(
                """SELECT 'retry' as event_type, id, url, site,
                          attempt_number, action, scheduled_at as timestamp
                   FROM retry_events
                   ORDER BY scheduled_at DESC LIMIT ?""",
                (limit,),
            )
            events.extend([dict(r) for r in await cursor.fetchall()])

            cursor = await conn.execute(
                """SELECT 'notification' as event_type, id, title, body,
                          site, provider, sent_at as timestamp
                   FROM notification_events
                   ORDER BY sent_at DESC LIMIT ?""",
                (limit,),
            )
            events.extend([dict(r) for r in await cursor.fetchall()])

            cursor = await conn.execute(
                """SELECT 'email_check' as event_type, id,
                          urls_found, urls_new, checked_at as timestamp
                   FROM email_events
                   ORDER BY checked_at DESC LIMIT ?""",
                (limit,),
            )
            events.extend([dict(r) for r in await cursor.fetchall()])

            events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
            return events[:limit]
        finally:
            await conn.close()
