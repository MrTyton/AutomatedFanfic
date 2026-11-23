"""SQLite data access layer for library update poller state and probe history."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from calibre_integration.models import CalibreStorySummary
from config.schemas.poller import SitePollerConfig
from history.models import DownloadStatus
from history.schema import ensure_schema_sync, setup_sync_connection

lazy from services import poller_scheduler


def _to_utc(dt: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_dt(dt: datetime) -> str:
    """Format a datetime as a UTC ISO 8601 string."""
    return _to_utc(dt).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp string into a UTC-aware datetime."""
    if not value:
        return None
    return _to_utc(datetime.fromisoformat(value))


def _parse_date(value: str | None) -> date | None:
    """Parse an ISO 8601 date (or datetime) string into a date."""
    if not value:
        return None
    return date.fromisoformat(value[:10])


def _url_scheme_variants(url: str) -> tuple[str, str, str]:
    """Return (schemeless, https://, http://) variants of a URL."""
    clean_url = url.removeprefix("https://").removeprefix("http://")
    return (clean_url, f"https://{clean_url}", f"http://{clean_url}")


def _classify_tier(
    last_update_date: date | None, cfg: SitePollerConfig, today: date
) -> str:
    """Classify a story into hot/warm/cool/dormant based on update recency."""
    if last_update_date is None:
        return "dormant"
    age_days = max(0, (today - last_update_date).days)
    if age_days <= cfg.hot_max_age_days:
        return "hot"
    if age_days <= cfg.warm_max_age_days:
        return "warm"
    if age_days <= cfg.cool_max_age_days:
        return "cool"
    return "dormant"


@dataclass(frozen=True)
class TrackedStory:
    """A story tracked by the adaptive library update poller."""

    url: str
    site: str
    calibre_id: str
    title: str | None
    last_update_date: date | None
    update_date_exact: bool
    known_chapters: int | None
    remote_status: str | None
    last_checked_at: datetime | None
    next_check_at: datetime
    consecutive_no_change: int
    consecutive_errors: int
    last_error: str | None
    active: bool
    deleted_remotely: bool


@dataclass(frozen=True)
class PollEventRecord:
    """A single recorded update probe event, optionally joined with story title."""

    id: int
    url: str
    site: str
    checked_at: datetime
    outcome: str
    remote_chapters: int | None
    remote_updated_at: date | None
    error_message: str | None
    title: str | None = None


def _row_to_tracked_story(row: sqlite3.Row) -> TrackedStory:
    next_check = _parse_dt(row["next_check_at"])
    assert next_check is not None
    return TrackedStory(
        url=row["url"],
        site=row["site"],
        calibre_id=row["calibre_id"],
        title=row["title"],
        last_update_date=_parse_date(row["last_update_date"]),
        update_date_exact=bool(row["update_date_exact"]),
        known_chapters=row["known_chapters"],
        remote_status=row["remote_status"],
        last_checked_at=_parse_dt(row["last_checked_at"]),
        next_check_at=next_check,
        consecutive_no_change=int(row["consecutive_no_change"]),
        consecutive_errors=int(row["consecutive_errors"]),
        last_error=row["last_error"],
        active=bool(row["active"]),
        deleted_remotely=bool(row["deleted_remotely"]),
    )


def _row_to_poll_event(row: sqlite3.Row) -> PollEventRecord:
    checked_at = _parse_dt(row["checked_at"])
    assert checked_at is not None
    return PollEventRecord(
        id=int(row["id"]),
        url=row["url"],
        site=row["site"],
        checked_at=checked_at,
        outcome=row["outcome"],
        remote_chapters=row["remote_chapters"],
        remote_updated_at=_parse_date(row["remote_updated_at"]),
        error_message=row["error_message"],
        title=row["title"],
    )


class PollerStore:
    """Thread- and process-safe synchronous SQLite store for poller state."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._schema_ready = False

    def _ensure_initialized(self) -> None:
        if self._schema_ready:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            setup_sync_connection(conn)
            ensure_schema_sync(conn)
        finally:
            conn.close()
        self._schema_ready = True

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self._ensure_initialized()
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            setup_sync_connection(conn)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def sync_site_stories(
        self,
        site: str,
        stories: list[CalibreStorySummary],
        initial_next_check_fn: Callable[[CalibreStorySummary], datetime],
    ) -> dict[str, int]:
        """Upsert Calibre stories for a site and deactivate stories no longer present.

        Preserves existing probe state (`known_chapters`, `next_check_at`,
        `consecutive_no_change`, `consecutive_errors`) and never re-activates
        stories marked `deleted_remotely = 1` or `remote_status = 'Completed'`.
        """
        added = 0
        updated = 0
        incoming_urls: set[str] = set()

        with self._connect() as conn:
            for story in stories:
                incoming_urls.add(story.url)
                existing = conn.execute(
                    """SELECT last_update_date, update_date_exact, deleted_remotely, remote_status
                       FROM poll_tracked_stories
                       WHERE url = ?""",
                    (story.url,),
                ).fetchone()

                incoming_date = (
                    story.last_update_date.isoformat()
                    if story.last_update_date is not None
                    else None
                )
                incoming_exact = 1 if story.update_date_exact else 0

                if existing is None:
                    next_check_str = _format_dt(initial_next_check_fn(story))
                    conn.execute(
                        """INSERT INTO poll_tracked_stories (
                               url, site, calibre_id, title,
                               last_update_date, update_date_exact,
                               next_check_at, active, deleted_remotely
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)""",
                        (
                            story.url,
                            site,
                            story.calibre_id,
                            story.title,
                            incoming_date,
                            incoming_exact,
                            next_check_str,
                        ),
                    )
                    added += 1
                else:
                    existing_date: str | None = existing["last_update_date"]
                    existing_exact: int = int(existing["update_date_exact"])
                    deleted_remotely: int = int(existing["deleted_remotely"])
                    existing_remote_status: str = (
                        (existing["remote_status"] or "").strip().lower()
                    )

                    new_date = existing_date
                    new_exact = existing_exact
                    if incoming_date is not None:
                        if existing_date is None:
                            new_date = incoming_date
                            new_exact = incoming_exact
                        elif incoming_exact == 1:
                            if existing_exact == 0 or incoming_date > existing_date:
                                new_date = incoming_date
                            new_exact = 1
                        elif existing_exact == 0:
                            new_date = incoming_date

                    new_active = (
                        0
                        if (
                            deleted_remotely == 1
                            or existing_remote_status == "completed"
                        )
                        else 1
                    )
                    conn.execute(
                        """UPDATE poll_tracked_stories
                           SET site = ?,
                               calibre_id = ?,
                               title = ?,
                               last_update_date = ?,
                               update_date_exact = ?,
                               active = ?
                           WHERE url = ?""",
                        (
                            site,
                            story.calibre_id,
                            story.title,
                            new_date,
                            new_exact,
                            new_active,
                            story.url,
                        ),
                    )
                    updated += 1

            active_rows = conn.execute(
                """SELECT url FROM poll_tracked_stories
                   WHERE site = ? AND active = 1""",
                (site,),
            ).fetchall()
            to_deactivate = [
                row["url"] for row in active_rows if row["url"] not in incoming_urls
            ]
            for url in to_deactivate:
                conn.execute(
                    "UPDATE poll_tracked_stories SET active = 0 WHERE url = ?",
                    (url,),
                )

        return {
            "added": added,
            "updated": updated,
            "deactivated": len(to_deactivate),
        }

    def get_tracked_story(self, url: str) -> TrackedStory | None:
        """Fetch a single tracked story by URL, or None if not tracked."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM poll_tracked_stories WHERE url = ?",
                (url,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_tracked_story(row)

    def get_due_stories(self, site: str, now: datetime) -> list[TrackedStory]:
        """Return active stories for a site whose next_check_at <= now."""
        now_str = _format_dt(now)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM poll_tracked_stories
                   WHERE site = ? AND active = 1 AND next_check_at <= ?
                   ORDER BY next_check_at ASC""",
                (site, now_str),
            ).fetchall()
        return [_row_to_tracked_story(row) for row in rows]

    def get_checks_in_window(self, site: str, since: datetime) -> int:
        """Count poll events for a site since the given UTC timestamp."""
        since_str = _format_dt(since)
        with self._connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) AS cnt FROM poll_events
                   WHERE site = ? AND checked_at >= ?""",
                (site, since_str),
            ).fetchone()
        return int(row["cnt"]) if row is not None else 0

    def get_last_site_check(self, site: str) -> datetime | None:
        """Return the most recent poll_events.checked_at for a site, or None."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT MAX(checked_at) AS last_checked FROM poll_events
                   WHERE site = ?""",
                (site,),
            ).fetchone()
        if row is None or row["last_checked"] is None:
            return None
        return _parse_dt(row["last_checked"])

    def record_probe_outcome(
        self,
        url: str,
        site: str,
        outcome: str,
        checked_at: datetime,
        next_check_at: datetime | None,
        remote_chapters: int | None,
        remote_updated_at: date | None,
        remote_status: str | None,
        error_message: str | None,
        advance_baseline: bool,
        mark_deleted: bool = False,
        mark_completed: bool = False,
    ) -> None:
        """Record a probe event and update the corresponding tracked story state."""
        checked_at_str = _format_dt(checked_at)
        next_check_str = (
            _format_dt(next_check_at) if next_check_at is not None else None
        )
        remote_updated_str = (
            remote_updated_at.isoformat() if remote_updated_at is not None else None
        )

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO poll_events (
                       url, site, checked_at, outcome,
                       remote_chapters, remote_updated_at, error_message
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    url,
                    site,
                    checked_at_str,
                    outcome,
                    remote_chapters,
                    remote_updated_str,
                    error_message,
                ),
            )

            if mark_deleted:
                conn.execute(
                    """UPDATE poll_tracked_stories
                       SET last_checked_at = ?,
                           active = 0,
                           deleted_remotely = 1,
                           last_error = ?,
                           next_check_at = COALESCE(?, next_check_at)
                       WHERE url = ?""",
                    (checked_at_str, error_message, next_check_str, url),
                )
            elif outcome == "error":
                conn.execute(
                    """UPDATE poll_tracked_stories
                       SET last_checked_at = ?,
                           consecutive_errors = consecutive_errors + 1,
                           last_error = ?,
                           next_check_at = COALESCE(?, next_check_at)
                       WHERE url = ?""",
                    (checked_at_str, error_message, next_check_str, url),
                )
            elif advance_baseline:
                conn.execute(
                    """UPDATE poll_tracked_stories
                       SET last_checked_at = ?,
                           known_chapters = COALESCE(?, known_chapters),
                           remote_status = CASE
                               WHEN ? = 1 THEN 'Completed'
                               ELSE COALESCE(?, remote_status)
                           END,
                           active = CASE
                               WHEN ? = 1 THEN 0
                               ELSE active
                           END,
                           last_update_date = CASE
                               WHEN ? IS NOT NULL THEN ?
                               ELSE last_update_date
                           END,
                           update_date_exact = CASE
                               WHEN ? IS NOT NULL THEN 1
                               ELSE update_date_exact
                           END,
                           next_check_at = COALESCE(?, next_check_at),
                           consecutive_errors = 0,
                           last_error = NULL,
                           consecutive_no_change = CASE
                               WHEN ? = 'unchanged' THEN consecutive_no_change + 1
                               ELSE 0
                           END
                       WHERE url = ?""",
                    (
                        checked_at_str,
                        remote_chapters,
                        1 if mark_completed else 0,
                        remote_status,
                        1 if mark_completed else 0,
                        remote_updated_str,
                        remote_updated_str,
                        remote_updated_str,
                        next_check_str,
                        outcome,
                        url,
                    ),
                )
            else:
                conn.execute(
                    """UPDATE poll_tracked_stories
                       SET last_checked_at = ?,
                           next_check_at = COALESCE(?, next_check_at),
                           consecutive_errors = 0,
                           last_error = NULL
                       WHERE url = ?""",
                    (checked_at_str, next_check_str, url),
                )

    def mark_story_downloaded(
        self,
        url: str,
        downloaded_at: datetime,
        new_next_check_at: datetime,
        known_chapters: int | None = None,
        mark_completed: bool = False,
    ) -> None:
        """Advance tracked baseline and next_check_at after a successful download."""
        downloaded_date_str = _to_utc(downloaded_at).date().isoformat()
        next_check_str = _format_dt(new_next_check_at)
        url_candidates = _url_scheme_variants(url)

        with self._connect() as conn:
            if mark_completed:
                conn.execute(
                    """UPDATE poll_tracked_stories
                       SET last_update_date = ?,
                           update_date_exact = 1,
                           next_check_at = ?,
                           consecutive_no_change = 0,
                           consecutive_errors = 0,
                           last_error = NULL,
                           known_chapters = ?,
                           remote_status = 'Completed',
                           active = 0
                       WHERE (url = ? OR url = ? OR url = ?)""",
                    (
                        downloaded_date_str,
                        next_check_str,
                        known_chapters,
                        url_candidates[0],
                        url_candidates[1],
                        url_candidates[2],
                    ),
                )
            else:
                conn.execute(
                    """UPDATE poll_tracked_stories
                       SET last_update_date = ?,
                           update_date_exact = 1,
                           next_check_at = ?,
                           consecutive_no_change = 0,
                           consecutive_errors = 0,
                           last_error = NULL,
                           known_chapters = ?
                       WHERE (url = ? OR url = ? OR url = ?)""",
                    (
                        downloaded_date_str,
                        next_check_str,
                        known_chapters,
                        url_candidates[0],
                        url_candidates[1],
                        url_candidates[2],
                    ),
                )

    def _query_recent_download_timestamps(
        self, conn: sqlite3.Connection, url: str, since: datetime
    ) -> list[datetime]:
        """Query completed_at timestamps of successful download_events on an open connection."""
        since_str = _format_dt(since)
        url_candidates = _url_scheme_variants(url)
        rows = conn.execute(
            """SELECT completed_at FROM download_events
               WHERE (url = ? OR url = ? OR url = ?)
                 AND status = ?
                 AND completed_at IS NOT NULL
                 AND completed_at >= ?
               ORDER BY completed_at ASC""",
            (
                url_candidates[0],
                url_candidates[1],
                url_candidates[2],
                DownloadStatus.SUCCESS.value,
                since_str,
            ),
        ).fetchall()

        timestamps: list[datetime] = []
        for row in rows:
            parsed = _parse_dt(row["completed_at"])
            if parsed is not None:
                timestamps.append(parsed)
        return timestamps

    def get_recent_download_timestamps(
        self, url: str, since: datetime
    ) -> list[datetime]:
        """Return completed_at timestamps of successful download_events since `since`."""
        with self._connect() as conn:
            return self._query_recent_download_timestamps(conn, url, since)

    def get_history_sites(self) -> list[str]:
        """Return distinct non-empty site names from download_events ordered by download count DESC."""
        with self._connect() as conn:
            rows = conn.execute("""SELECT site, COUNT(*) AS cnt
                   FROM download_events
                   WHERE site IS NOT NULL AND TRIM(site) != ''
                   GROUP BY site
                   ORDER BY cnt DESC, site ASC""").fetchall()
        return [str(row["site"]) for row in rows]

    def get_site_status(
        self,
        site: str,
        cfg: SitePollerConfig,
        now: datetime,
        up_next_limit: int = 10,
        recent_limit: int = 15,
    ) -> dict[str, object]:
        """Build a status summary for a site including budget, tiers, queue, and events."""
        now_utc = _to_utc(now)
        since_24h_str = _format_dt(now_utc - timedelta(hours=24))
        since_180d = now_utc - timedelta(days=180)
        today = now_utc.date()

        with self._connect() as conn:
            checks_row = conn.execute(
                """SELECT COUNT(*) AS cnt FROM poll_events
                   WHERE site = ? AND checked_at >= ?""",
                (site, since_24h_str),
            ).fetchone()
            checks_last_24h = int(checks_row["cnt"]) if checks_row is not None else 0

            active_rows = conn.execute(
                """SELECT * FROM poll_tracked_stories
                   WHERE site = ? AND active = 1
                   ORDER BY next_check_at ASC""",
                (site,),
            ).fetchall()

            recent_rows = conn.execute(
                """SELECT e.id, e.url, e.site, e.checked_at, e.outcome,
                          e.remote_chapters, e.remote_updated_at, e.error_message,
                          s.title
                   FROM poll_events e
                   LEFT JOIN poll_tracked_stories s ON e.url = s.url
                   WHERE e.site = ?
                   ORDER BY e.checked_at DESC, e.id DESC
                   LIMIT ?""",
                (site, recent_limit),
            ).fetchall()

            active_stories = [_row_to_tracked_story(row) for row in active_rows]
            up_next_cadence: dict[str, float | None] = {}
            up_next_schedule_label: dict[str, str | None] = {}
            for story in active_stories[:up_next_limit]:
                recent_ts = self._query_recent_download_timestamps(
                    conn, story.url, since_180d
                )
                estimate = poller_scheduler.estimate_update_cadence(recent_ts)
                if estimate is not None and estimate.is_regular:
                    up_next_cadence[story.url] = round(estimate.median_gap_days, 1)
                    up_next_schedule_label[story.url] = estimate.label
                else:
                    up_next_cadence[story.url] = None
                    up_next_schedule_label[story.url] = None

        tier_counts: dict[str, int] = {
            "hot": 0,
            "warm": 0,
            "cool": 0,
            "dormant": 0,
        }
        for story in active_stories:
            tier = _classify_tier(story.last_update_date, cfg, today)
            tier_counts[tier] += 1

        up_next: list[dict[str, object]] = [
            {
                "url": story.url,
                "title": story.title,
                "calibre_id": story.calibre_id,
                "next_check_at": _format_dt(story.next_check_at),
                "last_checked_at": (
                    _format_dt(story.last_checked_at)
                    if story.last_checked_at is not None
                    else None
                ),
                "last_update_date": (
                    story.last_update_date.isoformat()
                    if story.last_update_date is not None
                    else None
                ),
                "known_chapters": story.known_chapters,
                "consecutive_no_change": story.consecutive_no_change,
                "consecutive_errors": story.consecutive_errors,
                "tier": _classify_tier(story.last_update_date, cfg, today),
                "cadence_days": up_next_cadence.get(story.url),
                "schedule_label": up_next_schedule_label.get(story.url),
            }
            for story in active_stories[:up_next_limit]
        ]

        recent_events: list[dict[str, object]] = []
        for row in recent_rows:
            event = _row_to_poll_event(row)
            recent_events.append(
                {
                    "id": event.id,
                    "url": event.url,
                    "site": event.site,
                    "title": event.title,
                    "checked_at": _format_dt(event.checked_at),
                    "outcome": event.outcome,
                    "remote_chapters": event.remote_chapters,
                    "remote_updated_at": (
                        event.remote_updated_at.isoformat()
                        if event.remote_updated_at is not None
                        else None
                    ),
                    "error_message": event.error_message,
                }
            )

        return {
            "checks_last_24h": checks_last_24h,
            "tier_counts": tier_counts,
            "tracked_count": len(active_stories),
            "up_next": up_next,
            "recent_events": recent_events,
        }
