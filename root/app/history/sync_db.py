"""Synchronous SQLite database wrapper used by the HistoryWriter worker thread."""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import ff_logging
from history.models import (
    DownloadEvent,
    DownloadStatus,
    EmailCheckEvent,
    NotificationEvent,
    RetryEvent,
)
from history.schema import (
    _dt_to_str,
    ensure_schema_sync,
    setup_sync_connection,
)


class SyncHistoryDB:
    """Synchronous SQLite wrapper used exclusively by the HistoryWriter thread."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Return the active SQLite connection, connecting if not already connected."""
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        return self._conn

    def connect(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        setup_sync_connection(self._conn)
        ensure_schema_sync(self._conn)
        self.prune_email_events(max_records=5000)

    def prune_email_events(self, max_records: int = 5000) -> int:
        """Keep only the most recent max_records email checks in rotating storage."""
        if not self._conn:
            return 0
        try:
            cur = self._conn.execute(
                """DELETE FROM email_events
                   WHERE id NOT IN (
                       SELECT id FROM email_events
                       ORDER BY id DESC LIMIT ?
                   )""",
                (max_records,),
            )
            self._conn.commit()
            return cur.rowcount
        except Exception as e:
            ff_logging.log_failure(f"SyncHistoryDB: error pruning email_events: {e}")
            return 0

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # -- writes --

    def insert_download(self, event: DownloadEvent, *, commit: bool = True) -> int:
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
        if commit:
            self._conn.commit()
        return cur.lastrowid or 0

    def update_download(
        self,
        url: str,
        status: DownloadStatus | str,
        title: str | None = None,
        calibre_id: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
        site: str | None = None,
        *,
        commit: bool = True,
    ) -> None:
        """Update the most recent non-successful download_event for *url*."""
        assert self._conn is not None
        if isinstance(status, str):
            status = DownloadStatus(status)
        now_str = _dt_to_str(datetime.now(timezone.utc))
        is_in_progress = status in (
            DownloadStatus.PENDING,
            DownloadStatus.PROCESSING,
            DownloadStatus.WAITING,
        )
        clean_url = url.removeprefix("https://").removeprefix("http://")
        url_candidates = (clean_url, f"https://{clean_url}", f"http://{clean_url}")
        cur = self._conn.execute(
            """UPDATE download_events
               SET status = ?,
                   title = COALESCE(?, title),
                   calibre_id = COALESCE(?, calibre_id),
                   error_message = CASE WHEN ? = 'success' THEN NULL
                                        ELSE COALESCE(?, error_message) END,
                   completed_at = CASE WHEN ? THEN NULL
                                       ELSE COALESCE(?, completed_at) END,
                   updated_at = ?
               WHERE id = (
                   SELECT id FROM download_events
                   WHERE (url = ? OR url = ? OR url = ?)
                     AND status IN ('pending', 'processing', 'waiting', 'failed', 'abandoned')
                   ORDER BY started_at DESC, id DESC LIMIT 1
               )""",
            (
                status.value,
                title,
                calibre_id,
                status.value,
                error_message,
                1 if is_in_progress else 0,
                _dt_to_str(completed_at),
                now_str,
                url_candidates[0],
                url_candidates[1],
                url_candidates[2],
            ),
        )
        if cur.rowcount == 0:
            self._conn.execute(
                """INSERT INTO download_events
                   (url, site, title, calibre_id, status,
                    error_message, started_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    url,
                    site or "unknown",
                    title,
                    calibre_id,
                    status.value,
                    error_message,
                    now_str,
                    _dt_to_str(completed_at),
                ),
            )
        if commit:
            self._conn.commit()

    def insert_retry(self, event: RetryEvent, *, commit: bool = True) -> int:
        assert self._conn is not None
        dl_id = event.download_event_id
        if dl_id is None:
            clean_url = event.url.removeprefix("https://").removeprefix("http://")
            url_candidates = (clean_url, f"https://{clean_url}", f"http://{clean_url}")
            cur = self._conn.execute(
                """SELECT id FROM download_events
                   WHERE url = ? OR url = ? OR url = ?
                   ORDER BY started_at DESC, id DESC LIMIT 1""",
                url_candidates,
            )
            row = cur.fetchone()
            if row:
                dl_id = row[0]

        cur = self._conn.execute(
            """INSERT INTO retry_events
               (download_event_id, url, site, attempt_number, action,
                delay_minutes, error_message, scheduled_at, fired_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                dl_id,
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
        if commit:
            self._conn.commit()
        return cur.lastrowid or 0

    def update_retry_fired(
        self,
        url: str,
        attempt_number: int,
        fired_at: datetime | None = None,
        *,
        commit: bool = True,
    ) -> None:
        assert self._conn is not None
        clean_url = url.removeprefix("https://").removeprefix("http://")
        url_candidates = (clean_url, f"https://{clean_url}", f"http://{clean_url}")
        self._conn.execute(
            """UPDATE retry_events
               SET fired_at = ?
               WHERE id = (
                   SELECT id FROM retry_events
                   WHERE (url = ? OR url = ? OR url = ?)
                     AND attempt_number = ?
                   ORDER BY scheduled_at DESC, id DESC LIMIT 1
               )""",
            (
                _dt_to_str(fired_at or datetime.now(timezone.utc)),
                url_candidates[0],
                url_candidates[1],
                url_candidates[2],
                attempt_number,
            ),
        )
        if commit:
            self._conn.commit()

    def insert_email_check(self, event: EmailCheckEvent, *, commit: bool = True) -> int:
        assert self._conn is not None
        cur = self._conn.execute(
            """INSERT INTO email_events
               (checked_at, urls_found, urls_new, urls_duplicate, urls_disabled_site, trigger)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                _dt_to_str(event.checked_at),
                event.urls_found,
                event.urls_new,
                event.urls_duplicate,
                event.urls_disabled_site,
                event.trigger,
            ),
        )
        if commit:
            self._conn.commit()
        return cur.lastrowid or 0

    def insert_notification(
        self, event: NotificationEvent, *, commit: bool = True
    ) -> int:
        assert self._conn is not None
        dl_id = event.download_event_id
        if dl_id is None and event.site:
            cur = self._conn.execute(
                """SELECT id FROM download_events
                   WHERE site = ?
                   ORDER BY started_at DESC, id DESC LIMIT 1""",
                (event.site,),
            )
            row = cur.fetchone()
            if row:
                dl_id = row[0]

        cur = self._conn.execute(
            """INSERT INTO notification_events
               (download_event_id, title, body, site, sent_at, provider)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                dl_id,
                event.title,
                event.body,
                event.site,
                _dt_to_str(event.sent_at),
                event.provider,
            ),
        )
        if commit:
            self._conn.commit()
        return cur.lastrowid or 0

    def get_uncompleted_downloads(self) -> list[dict]:
        """Get latest uncompleted download rows synchronously."""
        assert self._conn is not None
        cur = self._conn.execute("""WITH ranked_downloads AS (
                   SELECT id, url, site, title, calibre_id, behavior, status, error_message, started_at,
                          ROW_NUMBER() OVER (
                              PARTITION BY REPLACE(REPLACE(url, 'https://', ''), 'http://', '')
                              ORDER BY COALESCE(completed_at, started_at) DESC, id DESC
                          ) as rn
                   FROM download_events
               )
               SELECT id, url, site, title, calibre_id, behavior, status, error_message
               FROM ranked_downloads
               WHERE rn = 1 AND status IN ('pending', 'processing', 'waiting')
               ORDER BY started_at ASC, id ASC""")
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
