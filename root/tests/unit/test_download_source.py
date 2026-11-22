"""Unit tests for download source tracking (email / poller / manual / unknown)."""

import asyncio
import queue
import sqlite3
import threading
from unittest.mock import MagicMock

from history.async_db import AsyncHistoryDB
from history.models import DownloadEvent
from history.recorder import HistoryRecorder
from history.sync_db import SyncHistoryDB
from models.active_urls import (
    ActiveUrlsDict,
    mark_url_processing,
    mark_url_queued,
    mark_url_waiting,
)
from models.fanfic_info import FanficInfo
from services.email_watcher import email_watcher
from web.services import queue_controller
from web.services.dashboard_snapshot import (
    _collect_active_and_waiting_urls,
    get_active_downloads_summary,
)


def test_fanfic_info_source_syncs_with_from_email() -> None:
    """FanficInfo.source and from_email stay synchronized on construction."""
    from_email_fic = FanficInfo("u", "fanfiction", from_email=True)
    assert from_email_fic.source == "email"
    assert from_email_fic.from_email is True

    email_source_fic = FanficInfo("u", "fanfiction", source="email")
    assert email_source_fic.source == "email"
    assert email_source_fic.from_email is True

    poller_fic = FanficInfo("u", "fanfiction", source="poller")
    assert poller_fic.source == "poller"
    assert poller_fic.from_email is False

    default_fic = FanficInfo("u", "fanfiction")
    assert default_fic.source == "manual"
    assert default_fic.from_email is False


def test_active_urls_preserves_source() -> None:
    """mark_url_queued stores source and mark_url_processing / mark_url_waiting preserve it."""
    active: ActiveUrlsDict = {}
    mark_url_queued(active, "u", "fanfiction", source="poller")
    assert active["u"].get("source") == "poller"
    assert active["u"]["status"] == "queued"

    mark_url_processing(active, "u", "fanfiction")
    assert active["u"]["status"] == "processing"
    assert active["u"].get("source") == "poller"

    mark_url_waiting(active, "u", "fanfiction", retry_count=1)
    assert active["u"]["status"] == "waiting"
    assert active["u"].get("source") == "poller"


def _create_legacy_db_without_source(db_path: str) -> None:
    """Create a SQLite DB with the pre-source download_events schema and one legacy row."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE download_events (
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
        INSERT INTO download_events (url, site, status, started_at)
        VALUES ('https://example.com/legacy', 'fanfiction', 'success', '2026-01-01T00:00:00+00:00');
    """)
    conn.commit()
    conn.close()


def test_download_events_schema_migration_adds_source(tmp_path) -> None:
    """Migrating a pre-existing DB adds source='unknown' and persists new DownloadEvent.source."""
    db_path = str(tmp_path / "legacy_sync.db")
    _create_legacy_db_without_source(db_path)

    # Migrate via SyncHistoryDB.connect() (calls ensure_schema_sync)
    sync_db = SyncHistoryDB(db_path)
    sync_db.connect()
    try:
        # Legacy row should have defaulted to 'unknown'
        cur = sync_db.conn.execute(
            "SELECT source FROM download_events WHERE url = ?",
            ("https://example.com/legacy",),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "unknown"

        # Inserting a DownloadEvent with source='poller' persists and reads back
        event = DownloadEvent(
            url="https://example.com/poller-story",
            site="fanfiction",
            source="poller",
        )
        sync_db.insert_download(event)

        cur = sync_db.conn.execute(
            "SELECT source FROM download_events WHERE url = ?",
            ("https://example.com/poller-story",),
        )
        poller_row = cur.fetchone()
        assert poller_row is not None
        assert poller_row[0] == "poller"

        # Uncompleted downloads query includes source
        uncompleted = sync_db.get_uncompleted_downloads()
        assert len(uncompleted) == 1
        assert uncompleted[0]["source"] == "poller"
    finally:
        sync_db.close()


def test_async_schema_migration_and_reads_source(tmp_path) -> None:
    """AsyncHistoryDB.ensure_schema migrates legacy DB and read queries return source."""
    db_path = str(tmp_path / "legacy_async.db")
    _create_legacy_db_without_source(db_path)

    async def _run() -> None:
        async_db = AsyncHistoryDB(db_path)
        await async_db.ensure_schema()

        downloads = await async_db.get_downloads()
        assert len(downloads) == 1
        assert downloads[0]["source"] == "unknown"

        # Insert a poller event via SyncHistoryDB and read back via AsyncHistoryDB
        sync_db = SyncHistoryDB(db_path)
        sync_db.connect()
        try:
            sync_db.insert_download(
                DownloadEvent(
                    url="https://example.com/poller-async",
                    site="archiveofourown",
                    source="poller",
                )
            )
        finally:
            sync_db.close()

        latest = await async_db.get_latest_download("https://example.com/poller-async")
        assert latest is not None
        assert latest["source"] == "poller"

        recent = await async_db.get_recent_downloads(limit=10)
        by_url = {r["url"]: r for r in recent}
        assert by_url["https://example.com/poller-async"]["source"] == "poller"
        assert by_url["https://example.com/legacy"]["source"] == "unknown"

        uncompleted = await async_db.get_uncompleted_downloads()
        assert len(uncompleted) == 1
        assert uncompleted[0]["source"] == "poller"

        await async_db.close()

    asyncio.run(_run())


def test_history_recorder_record_download_created_source() -> None:
    """HistoryRecorder.record_download_created includes source (default 'manual')."""
    q: queue.Queue = queue.Queue()
    recorder = HistoryRecorder(q)  # type: ignore[arg-type]

    recorder.record_download_created("https://example.com/1", "fanfiction")
    msg1 = q.get(timeout=2.0)
    assert msg1["payload"]["source"] == "manual"

    recorder.record_download_created(
        "https://example.com/2", "archiveofourown", behavior="force", source="poller"
    )
    msg2 = q.get(timeout=2.0)
    assert msg2["payload"]["source"] == "poller"


def test_monitoring_and_dashboard_snapshot_include_source() -> None:
    """Active, queued, and waiting entries expose source when present."""
    active: ActiveUrlsDict = {}
    mark_url_queued(active, "https://example.com/q", "fanfiction", source="email")
    mark_url_queued(active, "https://example.com/p", "archiveofourown", source="poller")
    mark_url_processing(active, "https://example.com/p", "archiveofourown")
    mark_url_queued(active, "https://example.com/w", "royalroad", source="manual")
    mark_url_waiting(active, "https://example.com/w", "royalroad", retry_count=1)

    state = MagicMock()
    state.active_urls = active
    state.history_db = None

    summary = get_active_downloads_summary(state)
    items_by_url = {item["url"]: item for item in summary["items"]}  # type: ignore[index]
    assert items_by_url["https://example.com/q"]["source"] == "email"
    assert items_by_url["https://example.com/p"]["source"] == "poller"
    assert items_by_url["https://example.com/w"]["source"] == "manual"

    async def _run() -> None:
        _, _, active_list, queued_list, waiting_list = (
            await _collect_active_and_waiting_urls(state)
        )
        assert active_list[0]["source"] == "poller"
        assert queued_list[0]["source"] == "email"
        assert waiting_list[0]["source"] == "manual"

    asyncio.run(_run())


def test_email_watcher_sets_email_source(monkeypatch) -> None:
    """EmailWatcher tags FanficInfo, active_urls, and history_recorder with source='email'."""
    shutdown_event = threading.Event()
    check_emails_event = threading.Event()
    ingress_queue: queue.Queue = queue.Queue()
    active_urls: ActiveUrlsDict = {}

    email_info = MagicMock()
    email_info.update_from_config_store.return_value = False
    email_info.get_urls.side_effect = lambda: (
        shutdown_event.set() or ["https://www.fanfiction.net/s/12345/1/"]
    )
    email_info.disabled_sites = []
    email_info.imap_idle = False
    email_info.sleep_time = 0

    history_recorder = MagicMock()
    config_store = MagicMock()
    notification_info = MagicMock()

    monkeypatch.setattr(
        "parsers.regex_parsing.generate_FanficInfo_from_url",
        lambda url, _parsers: FanficInfo(url, "fanfiction"),
    )

    email_watcher(
        email_info=email_info,
        notification_info=notification_info,
        ingress_queue=ingress_queue,  # type: ignore[arg-type]
        url_parsers={},
        active_urls=active_urls,
        verbose=False,
        shutdown_event=shutdown_event,
        history_recorder=history_recorder,
        config_store=config_store,
        check_emails_event=check_emails_event,
    )

    fic = ingress_queue.get(timeout=2.0)
    assert fic.source == "email"
    assert fic.from_email is True
    assert active_urls[fic.url].get("source") == "email"
    history_recorder.record_download_created.assert_called_once_with(
        fic.url, fic.site, fic.behavior, source="email"
    )


def test_queue_controller_sets_manual_source(monkeypatch) -> None:
    """Manual URL ingestion tags FanficInfo, active_urls, and history_recorder with source='manual'."""
    state = MagicMock()
    state.active_urls = {}
    state.ingress_queue = queue.Queue()
    state.history_recorder = MagicMock()

    monkeypatch.setattr(
        "parsers.regex_parsing.generate_FanficInfo_from_url",
        lambda url, _parsers: FanficInfo(url, "archiveofourown"),
    )

    accepted, _msg = queue_controller.ingest_single_url(
        state,
        "https://archiveofourown.org/works/99999",
        {},
        source="manual",
    )
    assert accepted is True
    fic = state.ingress_queue.get(timeout=2.0)
    assert fic.source == "manual"
    assert fic.from_email is False
    assert state.active_urls[fic.url].get("source") == "manual"
    state.history_recorder.record_download_created.assert_called_once_with(
        fic.url, fic.site, fic.behavior, source="manual"
    )
