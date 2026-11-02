"""Analytics, aggregations, and statistics queries for the web dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite


async def query_site_statistics(
    conn: aiosqlite.Connection,
) -> dict[str, dict[str, int]]:
    """Return download counts (total, failed) grouped by site."""
    stats: dict[str, dict[str, int]] = {}
    try:
        cursor = await conn.execute("""SELECT site,
                      COUNT(*) as total,
                      SUM(CASE WHEN status IN ('failed', 'abandoned') THEN 1 ELSE 0 END) as failed
               FROM download_events
               WHERE site IS NOT NULL AND site != ''
               GROUP BY site""")
        rows = await cursor.fetchall()
        for row in rows:
            stats[str(row[0]).lower()] = {
                "total": int(row[1] or 0),
                "failed": int(row[2] or 0),
            }
    except Exception:
        pass
    return stats


async def query_recent_events(
    conn: aiosqlite.Connection, limit: int = 10
) -> list[dict]:
    """Get the most recent events across all tables for dashboard feed."""
    events: list[dict] = []

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

    events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return events[:limit]


async def query_recent_activity(
    conn: aiosqlite.Connection, limit: int = 20
) -> list[dict]:
    """Get the most recent non-download events for the dashboard feed."""
    events: list[dict] = []

    cursor = await conn.execute(
        """SELECT 'retry' as event_type, id, url, site,
                  attempt_number, action, delay_minutes,
                  error_message, scheduled_at as timestamp
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

    events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return events[:limit]


async def query_stats(conn: aiosqlite.Connection, period_hours: int = 24) -> dict:
    """Get comprehensive statistics for the stats dashboard page."""
    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=period_hours)
        ).isoformat()

        cursor = await conn.execute(
            """SELECT
                   COUNT(*),
                   COALESCE(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN status IN ('failed', 'abandoned') THEN 1 ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN started_at >= ? THEN 1 ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN status = 'success' AND started_at >= ? THEN 1 ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN status IN ('failed', 'abandoned') AND started_at >= ? THEN 1 ELSE 0 END), 0)
               FROM download_events""",
            (cutoff, cutoff, cutoff),
        )
        dl_row = await cursor.fetchone()
        if dl_row:
            (
                total_downloads,
                total_success,
                total_failed,
                period_downloads,
                period_success,
                period_failed,
            ) = (int(v or 0) for v in dl_row)
        else:
            total_downloads = total_success = total_failed = 0
            period_downloads = period_success = period_failed = 0

        cursor = await conn.execute(
            """SELECT
                   COUNT(DISTINCT CASE WHEN scheduled_at >= ? THEN download_event_id ELSE NULL END),
                   COALESCE(SUM(CASE WHEN scheduled_at >= ? THEN 1 ELSE 0 END), 0)
               FROM retry_events""",
            (cutoff, cutoff),
        )
        retry_row = await cursor.fetchone()
        downloads_with_retries = int(retry_row[0] or 0) if retry_row else 0
        total_retries = int(retry_row[1] or 0) if retry_row else 0

        cursor = await conn.execute(
            """SELECT AVG(cnt) FROM (
                   SELECT COUNT(*) as cnt
                   FROM retry_events r
                   WHERE r.scheduled_at >= ?
                   GROUP BY r.download_event_id
               )""",
            (cutoff,),
        )
        row = await cursor.fetchone()
        avg_retries_to_success = (
            round(row[0], 2)
            if row and row[0] is not None
            else (
                round(total_retries / downloads_with_retries, 2)
                if downloads_with_retries > 0
                else 0.0
            )
        )

        cursor = await conn.execute(
            """SELECT site,
                      COUNT(*) as total,
                      SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                      SUM(CASE WHEN status IN ('failed', 'abandoned') THEN 1 ELSE 0 END) as failed
               FROM download_events
               WHERE started_at >= ?
               GROUP BY site
               ORDER BY total DESC
               LIMIT 20""",
            (cutoff,),
        )
        downloads_by_site = [dict(r) for r in await cursor.fetchall()]

        time_group = (
            "strftime('%Y-%m-%d %H:00', started_at)"
            if period_hours <= 24
            else "DATE(started_at)"
        )
        cursor = await conn.execute(
            f"""SELECT {time_group} as date,
                      COUNT(*) as total,
                      SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                      SUM(CASE WHEN status IN ('failed', 'abandoned') THEN 1 ELSE 0 END) as failed
               FROM download_events
               WHERE started_at >= ?
               GROUP BY {time_group}
               ORDER BY date""",
            (cutoff,),
        )
        downloads_over_time = [dict(r) for r in await cursor.fetchall()]

        cursor = await conn.execute(
            """SELECT CAST(strftime('%H', started_at) AS INTEGER) as hour,
                      COUNT(*) as count
               FROM download_events
               GROUP BY hour
               ORDER BY hour"""
        )
        hourly_distribution = [dict(r) for r in await cursor.fetchall()]

        cursor = await conn.execute(
            """SELECT CAST(strftime('%w', started_at) AS INTEGER) as day_of_week,
                      COUNT(*) as count
               FROM download_events
               GROUP BY day_of_week
               ORDER BY day_of_week"""
        )
        weekly_distribution = [dict(r) for r in await cursor.fetchall()]

        cursor = await conn.execute(
            """SELECT CAST(strftime('%d', started_at) AS INTEGER) as day_of_month,
                      COUNT(*) as count
               FROM download_events
               GROUP BY day_of_month
               ORDER BY day_of_month"""
        )
        monthly_distribution = [dict(r) for r in await cursor.fetchall()]

        cursor = await conn.execute(
            """SELECT attempt_number, COUNT(*) as count
               FROM retry_events
               WHERE scheduled_at >= ?
               GROUP BY attempt_number
               ORDER BY attempt_number""",
            (cutoff,),
        )
        retry_distribution = [dict(r) for r in await cursor.fetchall()]

        cursor = await conn.execute(
            """SELECT status, COUNT(*) as count
               FROM download_events
               WHERE started_at >= ?
               GROUP BY status
               ORDER BY count DESC""",
            (cutoff,),
        )
        status_breakdown = [dict(r) for r in await cursor.fetchall()]

        return {
            "total_downloads": total_downloads,
            "total_success": total_success,
            "total_failed": total_failed,
            "period_downloads": period_downloads,
            "period_success": period_success,
            "period_failed": period_failed,
            "downloads_with_retries": downloads_with_retries,
            "total_retries": total_retries,
            "avg_retries_to_success": avg_retries_to_success,
            "downloads_by_site": downloads_by_site,
            "downloads_over_time": downloads_over_time,
            "hourly_distribution": hourly_distribution,
            "weekly_distribution": weekly_distribution,
            "monthly_distribution": monthly_distribution,
            "retry_distribution": retry_distribution,
            "status_breakdown": status_breakdown,
        }
    except Exception:
        return {
            "total_downloads": 0,
            "total_success": 0,
            "total_failed": 0,
            "period_downloads": 0,
            "period_success": 0,
            "period_failed": 0,
            "downloads_with_retries": 0,
            "total_retries": 0,
            "avg_retries_to_success": 0.0,
            "downloads_by_site": [],
            "downloads_over_time": [],
            "hourly_distribution": [],
            "weekly_distribution": [],
            "monthly_distribution": [],
            "retry_distribution": [],
            "status_breakdown": [],
        }
