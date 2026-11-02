"""Async SQLite database wrapper for FastAPI web server read operations."""

from contextlib import asynccontextmanager
from pathlib import Path

lazy import aiosqlite

from history.schema import (
    ensure_schema_async,
    setup_async_connection,
)
from history.stats_queries import (
    query_recent_activity,
    query_recent_events,
    query_site_statistics,
    query_stats,
)


class AsyncHistoryDB:
    """Async SQLite wrapper for read queries from the web API."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def _get_conn(self) -> aiosqlite.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = aiosqlite.connect(self._db_path)
        setattr(conn, "daemon", True)
        await conn
        conn.row_factory = aiosqlite.Row
        await setup_async_connection(conn)
        return conn

    async def connect(self) -> None:
        """Open a persistent read connection for the lifetime of the web server."""
        if self._conn is None:
            self._conn = await self._get_conn()

    @asynccontextmanager
    async def _connection(self):
        """Yield the persistent connection if open, otherwise a one-shot connection."""
        if self._conn is not None:
            yield self._conn
        else:
            conn = await self._get_conn()
            try:
                yield conn
            finally:
                await conn.close()

    async def ensure_schema(self) -> None:
        async with self._connection() as conn:
            await ensure_schema_async(conn)
            try:
                await self.prune_email_events(max_records=5000)
            except Exception:
                pass

    async def prune_email_events(self, max_records: int = 5000) -> int:
        """Keep only the most recent max_records email checks in rotating storage."""
        async with self._connection() as conn:
            cur = await conn.execute(
                """DELETE FROM email_events
                   WHERE id NOT IN (
                       SELECT id FROM email_events
                       ORDER BY id DESC LIMIT ?
                   )""",
                (max_records,),
            )
            await conn.commit()
            return cur.rowcount

    async def close(self) -> None:
        """Close the persistent connection if open."""
        if self._conn is not None:
            conn = self._conn
            self._conn = None
            await conn.close()

    async def get_downloads(
        self,
        limit: int = 50,
        offset: int = 0,
        site: str | None = None,
        status: str | None = None,
        search: str | None = None,
    ) -> list[dict]:
        async with self._connection() as conn:
            conditions = []
            params: list = []
            if site:
                conditions.append("LOWER(site) = LOWER(?)")
                params.append(site)
            if status:
                conditions.append("status = ?")
                params.append(status)
            if search:
                conditions.append("(site LIKE ? OR url LIKE ? OR title LIKE ?)")
                pattern = f"%{search}%"
                params.extend([pattern, pattern, pattern])

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            query = f"""SELECT * FROM download_events {where}
                        ORDER BY started_at DESC LIMIT ? OFFSET ?"""
            params.extend([limit, offset])

            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_download_count(
        self,
        site: str | None = None,
        status: str | None = None,
        search: str | None = None,
    ) -> int:
        async with self._connection() as conn:
            conditions = []
            params: list = []
            if site:
                conditions.append("LOWER(site) = LOWER(?)")
                params.append(site)
            if status:
                conditions.append("status = ?")
                params.append(status)
            if search:
                conditions.append("(site LIKE ? OR url LIKE ? OR title LIKE ?)")
                pattern = f"%{search}%"
                params.extend([pattern, pattern, pattern])

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            cursor = await conn.execute(
                f"SELECT COUNT(*) FROM download_events {where}", params
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_retries_for_url(
        self, url: str, download_event_id: int | None = None
    ) -> list[dict]:
        async with self._connection() as conn:
            if download_event_id is not None:
                cursor = await conn.execute(
                    """SELECT * FROM retry_events
                       WHERE download_event_id = ? ORDER BY scheduled_at ASC""",
                    (download_event_id,),
                )
            else:
                cursor = await conn.execute(
                    """SELECT * FROM retry_events
                       WHERE url = ? ORDER BY scheduled_at ASC""",
                    (url,),
                )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_retries(
        self,
        limit: int = 50,
        offset: int = 0,
        site: str | None = None,
        search: str | None = None,
    ) -> list[dict]:
        async with self._connection() as conn:
            conditions: list[str] = []
            params: list[object] = []

            if site:
                conditions.append("LOWER(r.site) = LOWER(?)")
                params.append(site)
            if search:
                pattern = f"%{search.lower()}%"
                conditions.append(
                    "(LOWER(r.url) LIKE ? OR LOWER(COALESCE(d.title, ld.title, '')) LIKE ? OR LOWER(COALESCE(r.error_message, '')) LIKE ?)"
                )
                params.extend([pattern, pattern, pattern])

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            query = f"""WITH latest_downloads AS (
                       SELECT d1.url, d1.title
                       FROM download_events d1
                       JOIN (
                           SELECT url, MAX(started_at) AS max_started_at
                           FROM download_events
                           GROUP BY url
                       ) latest
                       ON latest.url = d1.url AND latest.max_started_at = d1.started_at
                   )
                   SELECT r.*,
                          COALESCE(
                              d.title,
                              ld.title
                          ) AS title
                   FROM retry_events r
                   LEFT JOIN download_events d ON d.id = r.download_event_id
                   LEFT JOIN latest_downloads ld ON ld.url = r.url
                   {where_clause}
                   ORDER BY r.scheduled_at DESC LIMIT ? OFFSET ?"""

            params.extend([limit, offset])
            cursor = await conn.execute(query, tuple(params))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_retry_count(
        self, site: str | None = None, search: str | None = None
    ) -> int:
        async with self._connection() as conn:
            conditions: list[str] = []
            params: list[object] = []

            if site:
                conditions.append("LOWER(r.site) = LOWER(?)")
                params.append(site)
            if search:
                pattern = f"%{search.lower()}%"
                conditions.append(
                    "(LOWER(r.url) LIKE ? OR LOWER(COALESCE(d.title, ld.title, '')) LIKE ? OR LOWER(COALESCE(r.error_message, '')) LIKE ?)"
                )
                params.extend([pattern, pattern, pattern])

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            query = f"""WITH latest_downloads AS (
                       SELECT d1.url, d1.title
                       FROM download_events d1
                       JOIN (
                           SELECT url, MAX(started_at) AS max_started_at
                           FROM download_events
                           GROUP BY url
                       ) latest
                       ON latest.url = d1.url AND latest.max_started_at = d1.started_at
                   )
                   SELECT COUNT(*)
                   FROM retry_events r
                   LEFT JOIN download_events d ON d.id = r.download_event_id
                   LEFT JOIN latest_downloads ld ON ld.url = r.url
                   {where_clause}"""

            cursor = await conn.execute(query, tuple(params))
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_email_checks(self, limit: int = 50, offset: int = 0) -> list[dict]:
        async with self._connection() as conn:
            cursor = await conn.execute(
                """SELECT id, checked_at, urls_found, urls_new,
                          urls_duplicate, urls_disabled_site, trigger
                   FROM email_events
                   ORDER BY checked_at DESC, id DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_email_checks_count(self) -> int:
        async with self._connection() as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM email_events")
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def get_notifications(
        self,
        limit: int = 50,
        offset: int = 0,
        site: str | None = None,
        search: str | None = None,
    ) -> list[dict]:
        async with self._connection() as conn:
            conditions: list[str] = []
            params: list[object] = []

            if site:
                conditions.append("LOWER(site) = LOWER(?)")
                params.append(site)
            if search:
                pattern = f"%{search.lower()}%"
                conditions.append(
                    "(LOWER(title) LIKE ? OR LOWER(body) LIKE ? OR LOWER(COALESCE(site, '')) LIKE ? OR LOWER(COALESCE(provider, '')) LIKE ?)"
                )
                params.extend([pattern, pattern, pattern, pattern])

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            query = f"""SELECT * FROM notification_events
                       {where}
                       ORDER BY sent_at DESC LIMIT ? OFFSET ?"""
            params.extend([limit, offset])
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_notifications_count(
        self, site: str | None = None, search: str | None = None
    ) -> int:
        async with self._connection() as conn:
            conditions: list[str] = []
            params: list[object] = []

            if site:
                conditions.append("LOWER(site) = LOWER(?)")
                params.append(site)
            if search:
                pattern = f"%{search.lower()}%"
                conditions.append(
                    "(LOWER(title) LIKE ? OR LOWER(body) LIKE ? OR LOWER(COALESCE(site, '')) LIKE ? OR LOWER(COALESCE(provider, '')) LIKE ?)"
                )
                params.extend([pattern, pattern, pattern, pattern])

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            cursor = await conn.execute(
                f"SELECT COUNT(*) FROM notification_events {where}", tuple(params)
            )
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def get_distinct_sites(self) -> list[str]:
        async with self._connection() as conn:
            cursor = await conn.execute("""SELECT DISTINCT site FROM (
                        SELECT site FROM download_events WHERE site IS NOT NULL AND site != ''
                        UNION
                        SELECT site FROM retry_events WHERE site IS NOT NULL AND site != ''
                        UNION
                        SELECT site FROM notification_events WHERE site IS NOT NULL AND site != ''
                    ) ORDER BY site ASC""")
            rows = await cursor.fetchall()
            return [str(r[0]) for r in rows if r[0]]

    async def get_site_statistics(self) -> dict[str, dict[str, int]]:
        async with self._connection() as conn:
            return await query_site_statistics(conn)

    async def get_recent_events(self, limit: int = 10) -> list[dict]:
        async with self._connection() as conn:
            return await query_recent_events(conn, limit)

    async def get_recent_downloads(self, limit: int = 20) -> list[dict]:
        async with self._connection() as conn:
            cursor = await conn.execute(
                """WITH ranked_downloads AS (
                       SELECT id, url, site, title, calibre_id, status,
                              error_message, started_at, completed_at,
                              COALESCE(completed_at, started_at) as timestamp,
                              ROW_NUMBER() OVER (
                                  PARTITION BY REPLACE(REPLACE(url, 'https://', ''), 'http://', '')
                                  ORDER BY COALESCE(completed_at, started_at) DESC, id DESC
                              ) as rn
                       FROM download_events
                   )
                   SELECT id, url, site, title, calibre_id, status,
                          error_message, started_at, completed_at, timestamp
                   FROM ranked_downloads
                   WHERE rn = 1
                   ORDER BY timestamp DESC, id DESC LIMIT ?""",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_uncompleted_downloads(self) -> list[dict]:
        async with self._connection() as conn:
            cursor = await conn.execute("""WITH ranked_downloads AS (
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
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_waiting_urls(self) -> list[dict]:
        async with self._connection() as conn:
            cursor = await conn.execute("""WITH ranked_downloads AS (
                       SELECT id, url, site, title, calibre_id, status, updated_at, error_message,
                              ROW_NUMBER() OVER (
                                  PARTITION BY REPLACE(REPLACE(url, 'https://', ''), 'http://', '')
                                  ORDER BY COALESCE(completed_at, started_at) DESC, id DESC
                              ) as rn
                       FROM download_events
                   ),
                   latest_retries AS (
                       SELECT download_event_id, url, attempt_number, action, delay_minutes, scheduled_at,
                              ROW_NUMBER() OVER (
                                  PARTITION BY REPLACE(REPLACE(url, 'https://', ''), 'http://', '')
                                  ORDER BY id DESC
                              ) as rn_re
                       FROM retry_events
                   )
                   SELECT d.url, d.site, d.title, d.calibre_id, d.updated_at, d.error_message,
                          r.attempt_number, r.action, r.delay_minutes, r.scheduled_at
                   FROM ranked_downloads d
                   LEFT JOIN latest_retries r ON (r.download_event_id = d.id OR REPLACE(REPLACE(r.url, 'https://', ''), 'http://', '') = REPLACE(REPLACE(d.url, 'https://', ''), 'http://', '')) AND r.rn_re = 1
                   WHERE d.rn = 1 AND d.status = 'waiting'""")
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_latest_download(self, url: str) -> dict | None:
        clean_url = url.removeprefix("https://").removeprefix("http://")
        url_candidates = (
            clean_url,
            f"https://{clean_url}",
            f"http://{clean_url}",
        )
        async with self._connection() as conn:
            cursor = await conn.execute(
                """SELECT id, url, site, title, calibre_id, status, behavior,
                          error_message, started_at, completed_at, updated_at
                   FROM download_events
                   WHERE url = ? OR url = ? OR url = ?
                   ORDER BY COALESCE(completed_at, started_at) DESC, id DESC
                   LIMIT 1""",
                url_candidates,
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_story_history(self, url: str) -> dict | None:
        download = await self.get_latest_download(url)
        if not download:
            return None

        clean_url = url.removeprefix("https://").removeprefix("http://")
        url_candidates = (
            clean_url,
            f"https://{clean_url}",
            f"http://{clean_url}",
        )
        dl_id = download.get("id")
        async with self._connection() as conn:
            if dl_id is not None:
                cursor = await conn.execute(
                    """SELECT * FROM retry_events
                       WHERE download_event_id = ?
                       ORDER BY scheduled_at ASC""",
                    (dl_id,),
                )
            else:
                cursor = await conn.execute(
                    """SELECT * FROM retry_events
                       WHERE url = ? OR url = ? OR url = ?
                       ORDER BY scheduled_at ASC""",
                    url_candidates,
                )
            retries = [dict(r) for r in await cursor.fetchall()]

            cursor = await conn.execute(
                """SELECT * FROM notification_events
                   WHERE download_event_id = ?
                   ORDER BY sent_at DESC""",
                (dl_id,),
            )
            notifications = [dict(n) for n in await cursor.fetchall()]

        return {
            "download": download,
            "retries": retries,
            "notifications": notifications,
        }

    async def get_recent_activity(self, limit: int = 20) -> list[dict]:
        async with self._connection() as conn:
            return await query_recent_activity(conn, limit)

    async def get_stats(self, period_hours: int = 24) -> dict:
        async with self._connection() as conn:
            return await query_stats(conn, period_hours)
