"""Unit tests for SQLite poller tables and PollerStore DAO."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from calibre_integration.models import CalibreStorySummary
from config.schemas.poller import SitePollerConfig
from history.models import DownloadEvent, DownloadStatus
from history.poller_store import PollEventRecord, PollerStore, TrackedStory
from history.sync_db import SyncHistoryDB


def _story(
    url: str,
    calibre_id: str = "1",
    title: str = "Test Story",
    last_update_date: date | None = date(2026, 11, 10),
    update_date_exact: bool = True,
) -> CalibreStorySummary:
    return CalibreStorySummary(
        calibre_id=calibre_id,
        title=title,
        url=url,
        tags=["In-Progress"],
        last_modified=datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc),
        last_update_date=last_update_date,
        update_date_exact=update_date_exact,
    )


def test_sync_upserts_and_deactivates_missing_stories(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    store = PollerStore(db_path)

    base_next = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    stories_v1 = [
        _story("https://archiveofourown.org/works/1", calibre_id="10", title="Story 1"),
        _story("https://archiveofourown.org/works/2", calibre_id="20", title="Story 2"),
        _story("https://archiveofourown.org/works/3", calibre_id="30", title="Story 3"),
    ]

    counts1 = store.sync_site_stories("ao3", stories_v1, lambda _s: base_next)
    assert counts1 == {"added": 3, "updated": 0, "deactivated": 0}

    # Record probe state on story 1 and mark story 2 as deleted remotely
    checked_at = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)
    custom_next = datetime(2026, 11, 25, 18, 0, tzinfo=timezone.utc)
    store.record_probe_outcome(
        url="https://archiveofourown.org/works/1",
        site="ao3",
        outcome="unchanged",
        checked_at=checked_at,
        next_check_at=custom_next,
        remote_chapters=12,
        remote_updated_at=date(2026, 11, 15),
        remote_status="In-Progress",
        error_message=None,
        advance_baseline=True,
    )
    store.record_probe_outcome(
        url="https://archiveofourown.org/works/2",
        site="ao3",
        outcome="deleted",
        checked_at=checked_at,
        next_check_at=None,
        remote_chapters=None,
        remote_updated_at=None,
        remote_status=None,
        error_message="404 Not Found",
        advance_baseline=False,
        mark_deleted=True,
    )

    # Second sync: story 1 updated title, story 2 still in Calibre (must stay inactive!),
    # story 3 missing (must be deactivated), story 4 added.
    stories_v2 = [
        _story(
            "https://archiveofourown.org/works/1",
            calibre_id="10",
            title="Story 1 Renamed",
            last_update_date=date(2026, 11, 1),
            update_date_exact=False,
        ),
        _story("https://archiveofourown.org/works/2", calibre_id="20", title="Story 2"),
        _story("https://archiveofourown.org/works/4", calibre_id="40", title="Story 4"),
    ]
    later_next = datetime(2026, 11, 30, 0, 0, tzinfo=timezone.utc)
    counts2 = store.sync_site_stories("ao3", stories_v2, lambda _s: later_next)
    assert counts2 == {"added": 1, "updated": 2, "deactivated": 1}

    # Verify story 1 preserved probe state & exact date while updating title
    s1 = store.get_tracked_story("https://archiveofourown.org/works/1")
    assert isinstance(s1, TrackedStory)
    assert s1.title == "Story 1 Renamed"
    assert s1.active is True
    assert s1.known_chapters == 12
    assert s1.next_check_at == custom_next
    assert s1.consecutive_no_change == 1
    assert s1.last_update_date == date(2026, 11, 15)
    assert s1.update_date_exact is True

    # Verify story 2 was NEVER re-activated because deleted_remotely=1
    s2 = store.get_tracked_story("https://archiveofourown.org/works/2")
    assert s2 is not None
    assert s2.deleted_remotely is True
    assert s2.active is False

    # Verify story 3 was deactivated
    s3 = store.get_tracked_story("https://archiveofourown.org/works/3")
    assert s3 is not None
    assert s3.active is False
    assert s3.deleted_remotely is False

    # Verify story 4 was added
    s4 = store.get_tracked_story("https://archiveofourown.org/works/4")
    assert s4 is not None
    assert s4.active is True
    assert s4.next_check_at == later_next


def test_record_probe_unchanged_advances_baseline_and_logs_event(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "history.db"
    store = PollerStore(db_path)

    initial_next = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)
    store.sync_site_stories(
        "ao3",
        [
            _story(
                "https://archiveofourown.org/works/101",
                title="Unchanged Fic",
                last_update_date=date(2026, 11, 1),
                update_date_exact=False,
            )
        ],
        lambda _s: initial_next,
    )

    checked_at = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    next_check = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    store.record_probe_outcome(
        url="https://archiveofourown.org/works/101",
        site="ao3",
        outcome="unchanged",
        checked_at=checked_at,
        next_check_at=next_check,
        remote_chapters=7,
        remote_updated_at=date(2026, 11, 18),
        remote_status="In-Progress",
        error_message=None,
        advance_baseline=True,
    )

    story = store.get_tracked_story("https://archiveofourown.org/works/101")
    assert story is not None
    assert story.known_chapters == 7
    assert story.remote_status == "In-Progress"
    assert story.last_update_date == date(2026, 11, 18)
    assert story.update_date_exact is True
    assert story.last_checked_at == checked_at
    assert story.next_check_at == next_check
    assert story.consecutive_no_change == 1
    assert story.consecutive_errors == 0
    assert story.last_error is None

    # Verify poll_events row was inserted
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT url, site, checked_at, outcome, remote_chapters, remote_updated_at, error_message "
            "FROM poll_events"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0] == (
        "https://archiveofourown.org/works/101",
        "ao3",
        checked_at.isoformat(),
        "unchanged",
        7,
        "2026-11-18",
        None,
    )


def test_record_probe_update_found_does_not_advance_baseline(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    store = PollerStore(db_path)

    initial_next = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)
    store.sync_site_stories(
        "ao3",
        [
            _story(
                "https://archiveofourown.org/works/202",
                title="Updated Fic",
                last_update_date=date(2026, 11, 5),
                update_date_exact=True,
            )
        ],
        lambda _s: initial_next,
    )

    # First establish baseline of 5 chapters
    first_check = datetime(2026, 11, 22, 10, 5, tzinfo=timezone.utc)
    store.record_probe_outcome(
        url="https://archiveofourown.org/works/202",
        site="ao3",
        outcome="unchanged",
        checked_at=first_check,
        next_check_at=datetime(2026, 11, 23, 10, 5, tzinfo=timezone.utc),
        remote_chapters=5,
        remote_updated_at=date(2026, 11, 5),
        remote_status="In-Progress",
        error_message=None,
        advance_baseline=True,
    )

    # Now probe finds chapter 6, but advance_baseline=False (before Calibre commits)
    second_check = datetime(2026, 11, 23, 11, 0, tzinfo=timezone.utc)
    cooldown_next = datetime(2026, 11, 23, 13, 0, tzinfo=timezone.utc)
    store.record_probe_outcome(
        url="https://archiveofourown.org/works/202",
        site="ao3",
        outcome="update_found",
        checked_at=second_check,
        next_check_at=cooldown_next,
        remote_chapters=6,
        remote_updated_at=date(2026, 11, 23),
        remote_status="In-Progress",
        error_message=None,
        advance_baseline=False,
    )

    story = store.get_tracked_story("https://archiveofourown.org/works/202")
    assert story is not None
    # Baseline must NOT have advanced
    assert story.known_chapters == 5
    assert story.last_update_date == date(2026, 11, 5)
    assert story.last_checked_at == second_check
    assert story.next_check_at == cooldown_next
    assert story.consecutive_errors == 0
    assert story.last_error is None


def test_record_probe_error_increments_consecutive_errors(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    store = PollerStore(db_path)

    initial_next = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)
    store.sync_site_stories(
        "ffnet",
        [_story("https://www.fanfiction.net/s/12345/1/", title="Err Fic")],
        lambda _s: initial_next,
    )

    t1 = datetime(2026, 11, 22, 10, 5, tzinfo=timezone.utc)
    backoff1 = datetime(2026, 11, 23, 10, 5, tzinfo=timezone.utc)
    store.record_probe_outcome(
        url="https://www.fanfiction.net/s/12345/1/",
        site="ffnet",
        outcome="error",
        checked_at=t1,
        next_check_at=backoff1,
        remote_chapters=None,
        remote_updated_at=None,
        remote_status=None,
        error_message="Cloudflare 503",
        advance_baseline=False,
    )

    t2 = datetime(2026, 11, 23, 10, 10, tzinfo=timezone.utc)
    backoff2 = datetime(2026, 11, 25, 10, 10, tzinfo=timezone.utc)
    store.record_probe_outcome(
        url="https://www.fanfiction.net/s/12345/1/",
        site="ffnet",
        outcome="error",
        checked_at=t2,
        next_check_at=backoff2,
        remote_chapters=None,
        remote_updated_at=None,
        remote_status=None,
        error_message="Timeout",
        advance_baseline=False,
    )

    story = store.get_tracked_story("https://www.fanfiction.net/s/12345/1/")
    assert story is not None
    assert story.consecutive_errors == 2
    assert story.last_error == "Timeout"
    assert story.next_check_at == backoff2
    assert story.last_checked_at == t2


def test_mark_story_downloaded_pushes_next_check_forward(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    store = PollerStore(db_path)

    initial_next = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)
    url = "https://archiveofourown.org/works/555"
    store.sync_site_stories(
        "ao3",
        [
            _story(
                url,
                title="Downloaded Fic",
                last_update_date=date(2026, 10, 1),
                update_date_exact=False,
            )
        ],
        lambda _s: initial_next,
    )

    # Simulate some unchanged checks and an error beforehand
    store.record_probe_outcome(
        url=url,
        site="ao3",
        outcome="unchanged",
        checked_at=datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc),
        next_check_at=datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc),
        remote_chapters=10,
        remote_updated_at=None,
        remote_status=None,
        error_message=None,
        advance_baseline=True,
    )
    store.record_probe_outcome(
        url=url,
        site="ao3",
        outcome="error",
        checked_at=datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc),
        next_check_at=datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc),
        remote_chapters=None,
        remote_updated_at=None,
        remote_status=None,
        error_message="Transient 502",
        advance_baseline=False,
    )

    downloaded_at = datetime(2026, 11, 22, 15, 30, tzinfo=timezone.utc)
    pushed_next = datetime(2026, 11, 24, 3, 30, tzinfo=timezone.utc)
    store.mark_story_downloaded(
        url=url,
        downloaded_at=downloaded_at,
        new_next_check_at=pushed_next,
        known_chapters=11,
    )

    story = store.get_tracked_story(url)
    assert story is not None
    assert story.last_update_date == date(2026, 11, 22)
    assert story.update_date_exact is True
    assert story.next_check_at == pushed_next
    assert story.consecutive_no_change == 0
    assert story.consecutive_errors == 0
    assert story.last_error is None
    assert story.known_chapters == 11

    # Non-existent URL is a safe no-op
    store.mark_story_downloaded(
        url="https://archiveofourown.org/works/999999",
        downloaded_at=downloaded_at,
        new_next_check_at=pushed_next,
    )
    assert store.get_tracked_story("https://archiveofourown.org/works/999999") is None


def test_get_checks_in_window_and_site_status(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    store = PollerStore(db_path)
    cfg = SitePollerConfig()
    now = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)

    # Create stories in each tier: hot (<=14d), warm (<=90d), cool (<=365d), dormant (>365d)
    stories = [
        _story(
            "https://archiveofourown.org/works/hot",
            calibre_id="1",
            title="Hot Fic",
            last_update_date=now.date() - timedelta(days=5),
        ),
        _story(
            "https://archiveofourown.org/works/warm",
            calibre_id="2",
            title="Warm Fic",
            last_update_date=now.date() - timedelta(days=40),
        ),
        _story(
            "https://archiveofourown.org/works/cool",
            calibre_id="3",
            title="Cool Fic",
            last_update_date=now.date() - timedelta(days=200),
        ),
        _story(
            "https://archiveofourown.org/works/dormant",
            calibre_id="4",
            title="Dormant Fic",
            last_update_date=now.date() - timedelta(days=500),
        ),
    ]
    next_times = {
        "https://archiveofourown.org/works/hot": now - timedelta(hours=1),
        "https://archiveofourown.org/works/warm": now + timedelta(hours=2),
        "https://archiveofourown.org/works/cool": now + timedelta(days=5),
        "https://archiveofourown.org/works/dormant": now + timedelta(days=30),
    }
    store.sync_site_stories("ao3", stories, lambda s: next_times[s.url])

    # Log 1 old event (>24h ago) and 2 recent events (<24h ago)
    store.record_probe_outcome(
        url="https://archiveofourown.org/works/dormant",
        site="ao3",
        outcome="unchanged",
        checked_at=now - timedelta(hours=30),
        next_check_at=next_times["https://archiveofourown.org/works/dormant"],
        remote_chapters=3,
        remote_updated_at=None,
        remote_status=None,
        error_message=None,
        advance_baseline=True,
    )
    store.record_probe_outcome(
        url="https://archiveofourown.org/works/warm",
        site="ao3",
        outcome="unchanged",
        checked_at=now - timedelta(hours=4),
        next_check_at=next_times["https://archiveofourown.org/works/warm"],
        remote_chapters=8,
        remote_updated_at=None,
        remote_status=None,
        error_message=None,
        advance_baseline=True,
    )
    store.record_probe_outcome(
        url="https://archiveofourown.org/works/hot",
        site="ao3",
        outcome="update_found",
        checked_at=now - timedelta(hours=1),
        next_check_at=next_times["https://archiveofourown.org/works/hot"],
        remote_chapters=15,
        remote_updated_at=now.date(),
        remote_status="In-Progress",
        error_message=None,
        advance_baseline=False,
    )

    assert store.get_checks_in_window("ao3", now - timedelta(hours=24)) == 2
    assert store.get_last_site_check("ao3") == now - timedelta(hours=1)
    assert store.get_last_site_check("ffnet") is None

    due = store.get_due_stories("ao3", now)
    assert [s.url for s in due] == ["https://archiveofourown.org/works/hot"]

    status = store.get_site_status("ao3", cfg, now, up_next_limit=2, recent_limit=2)
    assert status["checks_last_24h"] == 2
    assert status["tracked_count"] == 4
    assert status["tier_counts"] == {
        "hot": 1,
        "warm": 1,
        "cool": 1,
        "dormant": 1,
    }

    up_next = status["up_next"]
    assert isinstance(up_next, list)
    assert len(up_next) == 2
    assert up_next[0]["url"] == "https://archiveofourown.org/works/hot"
    assert up_next[1]["url"] == "https://archiveofourown.org/works/warm"

    recent_events = status["recent_events"]
    assert isinstance(recent_events, list)
    assert len(recent_events) == 2
    assert recent_events[0]["url"] == "https://archiveofourown.org/works/hot"
    assert recent_events[0]["title"] == "Hot Fic"
    assert recent_events[0]["outcome"] == "update_found"
    assert recent_events[1]["url"] == "https://archiveofourown.org/works/warm"
    assert recent_events[1]["title"] == "Warm Fic"

    # Also verify PollEventRecord dataclass is importable and instantiable
    rec = PollEventRecord(
        id=1,
        url="https://archiveofourown.org/works/hot",
        site="ao3",
        checked_at=now,
        outcome="update_found",
        remote_chapters=15,
        remote_updated_at=now.date(),
        error_message=None,
        title="Hot Fic",
    )
    assert rec.title == "Hot Fic"


def test_get_recent_download_timestamps(tmp_path: Path) -> None:
    db_path = tmp_path / "history.db"
    # Populate download_events via SyncHistoryDB
    sync_db = SyncHistoryDB(str(db_path))
    sync_db.connect()
    try:
        t_old = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        t_recent_1 = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
        t_recent_2 = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)
        url = "https://archiveofourown.org/works/777"

        # Old success (before since)
        sync_db.insert_download(
            DownloadEvent(
                url=url,
                site="ao3",
                status=DownloadStatus.SUCCESS,
                started_at=t_old,
                completed_at=t_old,
            )
        )
        # Recent failure (must be excluded)
        sync_db.insert_download(
            DownloadEvent(
                url=url,
                site="ao3",
                status=DownloadStatus.FAILED,
                started_at=t_recent_1,
                completed_at=t_recent_1,
            )
        )
        # Recent successes (must be included, ordered chronologically)
        sync_db.insert_download(
            DownloadEvent(
                url=url,
                site="ao3",
                status=DownloadStatus.SUCCESS,
                started_at=t_recent_2,
                completed_at=t_recent_2,
            )
        )
        sync_db.insert_download(
            DownloadEvent(
                url=url,
                site="ao3",
                status=DownloadStatus.SUCCESS,
                started_at=t_recent_1,
                completed_at=t_recent_1,
            )
        )
    finally:
        sync_db.close()

    store = PollerStore(db_path)
    since = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    timestamps = store.get_recent_download_timestamps(url, since)
    assert timestamps == [t_recent_1, t_recent_2]
