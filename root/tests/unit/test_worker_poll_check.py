"""Unit tests for worker poll_check pipeline, handoff, handlers, and coordinator integration."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import queue as stdlib_queue
import threading
from unittest.mock import MagicMock, patch

from calibre_integration import calibredb_utils
from calibre_integration.models import CalibreStorySummary
import config
from config.schemas.poller import SitePollerConfig
from config.store import ConfigStore
from history.poller_store import PollerStore
from models.context import WorkerContext
from models.fanfic_info import FanficInfo
from notifications import notification_wrapper
from services.coordinator import Coordinator
from workers import handlers, pipeline
from workers.fff_runner import FanFicFareResult, MetadataProbeResult


def _make_store_with_story(
    tmp_path: Path,
    url: str = "https://archiveofourown.org/works/12345",
    site: str = "archiveofourown",
    calibre_id: str = "42",
    title: str = "Test Story",
    last_update_date: date | None = date(2026, 10, 1),
    update_date_exact: bool = True,
    known_chapters: int | None = 10,
) -> PollerStore:
    store = PollerStore(tmp_path / "history.db")
    now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    story = CalibreStorySummary(
        calibre_id=calibre_id,
        url=url,
        title=title,
        tags=["In-Progress"],
        last_modified=now,
        last_update_date=last_update_date,
        update_date_exact=update_date_exact,
    )
    store.sync_site_stories(site, [story], lambda _s: now - timedelta(hours=1))
    if known_chapters is not None:
        store.record_probe_outcome(
            url=url,
            site=site,
            outcome="unchanged",
            checked_at=now - timedelta(days=2),
            next_check_at=now - timedelta(hours=1),
            remote_chapters=known_chapters,
            remote_updated_at=last_update_date if update_date_exact else None,
            remote_status="In-Progress",
            error_message=None,
            advance_baseline=True,
        )
    return store


@dataclass
class _WorkerHarness:
    ctx: WorkerContext
    history_recorder: MagicMock
    waiting_queue: MagicMock
    notification_info: MagicMock


def _make_worker_harness(
    poller_store: PollerStore | None,
    active_polls: dict[str, object] | None = None,
    site_cfg: SitePollerConfig | None = None,
    site: str = "archiveofourown",
) -> _WorkerHarness:
    mock_client = MagicMock(spec=calibredb_utils.CalibreDBClient)
    mock_client.cdb_info = MagicMock()
    mock_client.cdb_info.personal_ini = "/config/personal.ini"
    mock_client.cdb_info.default_ini = "/config/defaults.ini"
    mock_client.cdb_info.update_method = "update"
    mock_client.cdb_info.update_only = False
    mock_client.cdb_info.metadata_preservation_mode = (
        config.MetadataPreservationMode.ADD_FORMAT
    )

    store_dict: dict[str, object] = {}
    if site_cfg is not None:
        store_dict["library_poller.sites"] = {site: site_cfg}
    config_store = ConfigStore(store_dict)

    notification_info = MagicMock(spec=notification_wrapper.NotificationWrapper)
    waiting_queue = MagicMock()
    history_recorder = MagicMock()

    ctx = WorkerContext(
        calibre_client=mock_client,
        notification_info=notification_info,
        ingress_queue=MagicMock(),
        waiting_queue=waiting_queue,
        retry_config=config.RetryConfig(),
        history_recorder=history_recorder,
        active_urls={},
        poller_store=poller_store,
        active_polls=active_polls,
        config_store=config_store,
    )
    return _WorkerHarness(
        ctx=ctx,
        history_recorder=history_recorder,
        waiting_queue=waiting_queue,
        notification_info=notification_info,
    )


def test_poll_check_unchanged_skips_calibre_export_and_download_events(
    tmp_path: Path,
) -> None:
    url = "https://archiveofourown.org/works/12345"
    site = "archiveofourown"
    store = _make_store_with_story(
        tmp_path,
        url=url,
        site=site,
        last_update_date=date(2026, 10, 1),
        update_date_exact=True,
        known_chapters=10,
    )
    active_polls: dict[str, object] = {site: url}
    h = _make_worker_harness(store, active_polls=active_polls)
    fanfic = FanficInfo(
        url=url,
        site=site,
        calibre_id="42",
        behavior="poll_check",
        title="Test Story",
        source="poller",
    )

    probe = MetadataProbeResult(
        num_chapters=10,
        date_updated=date(2026, 10, 1),
        status="In-Progress",
        title="Test Story",
    )

    with (
        patch("workers.pipeline.fff_runner.probe_story_metadata", return_value=probe),
        patch("workers.pipeline.common.get_path_or_url") as mock_get_path,
        patch("workers.pipeline.fff_runner.execute_fanficfare_direct") as mock_download,
    ):
        result = pipeline._process_task(fanfic, h.ctx)

    assert result is True
    assert site not in active_polls
    mock_get_path.assert_not_called()
    mock_download.assert_not_called()
    assert url not in h.ctx.active_urls
    h.history_recorder.record_download_created.assert_not_called()
    h.history_recorder.record_download_processing.assert_not_called()
    h.waiting_queue.put.assert_not_called()
    h.notification_info.send_notification.assert_not_called()

    tracked = store.get_tracked_story(url)
    assert tracked is not None
    assert tracked.known_chapters == 10
    assert tracked.consecutive_no_change == 2
    assert tracked.next_check_at > datetime.now(timezone.utc)


def test_poll_check_update_detected_hands_off_without_premature_baseline_advance(
    tmp_path: Path,
) -> None:
    url = "https://archiveofourown.org/works/12345"
    site = "archiveofourown"
    store = _make_store_with_story(
        tmp_path,
        url=url,
        site=site,
        last_update_date=date(2026, 10, 1),
        update_date_exact=True,
        known_chapters=10,
    )
    active_polls: dict[str, object] = {site: url}
    h = _make_worker_harness(store, active_polls=active_polls)
    fanfic = FanficInfo(
        url=url,
        site=site,
        calibre_id="42",
        behavior="poll_check",
        title="Test Story",
        source="poller",
    )

    probe = MetadataProbeResult(
        num_chapters=11,
        date_updated=date(2026, 11, 20),
        status="In-Progress",
        title="Test Story",
    )

    with patch("workers.pipeline.fff_runner.probe_story_metadata", return_value=probe):
        should_download = pipeline._handle_poll_check(fanfic, h.ctx)

    assert should_download is True
    assert site not in active_polls
    assert fanfic.behavior is None
    assert fanfic.source == "poller"
    assert url in h.ctx.active_urls
    assert h.ctx.active_urls[url].get("source") == "poller"
    h.history_recorder.record_download_created.assert_called_once_with(
        url,
        site,
        behavior=None,
        source="poller",
    )

    # Baseline MUST NOT advance until Calibre actually succeeds,
    # but next_check_at MUST move into the future to prevent immediate re-trigger loops
    tracked = store.get_tracked_story(url)
    assert tracked is not None
    assert tracked.known_chapters == 10
    assert tracked.last_update_date == date(2026, 10, 1)
    assert tracked.next_check_at > datetime.now(timezone.utc)


def test_poll_check_first_probe_exact_vs_approximate_date(tmp_path: Path) -> None:
    site = "archiveofourown"
    approx_url = "https://archiveofourown.org/works/11111"
    exact_url = "https://archiveofourown.org/works/22222"

    store = PollerStore(tmp_path / "history.db")
    now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    stories = [
        CalibreStorySummary(
            calibre_id="1",
            url=approx_url,
            title="Approx Story",
            tags=["In-Progress"],
            last_modified=now,
            last_update_date=date(2026, 1, 1),
            update_date_exact=False,
        ),
        CalibreStorySummary(
            calibre_id="2",
            url=exact_url,
            title="Exact Story",
            tags=["In-Progress"],
            last_modified=now,
            last_update_date=date(2026, 1, 1),
            update_date_exact=True,
        ),
    ]
    store.sync_site_stories(site, stories, lambda _s: now - timedelta(hours=1))

    probe = MetadataProbeResult(
        num_chapters=15,
        date_updated=date(2026, 5, 1),
        status="In-Progress",
        title="Story",
    )

    # Approximate date: first probe records baseline without false-positive download
    h_approx = _make_worker_harness(store, active_polls={site: approx_url})
    fanfic_approx = FanficInfo(
        url=approx_url,
        site=site,
        calibre_id="1",
        behavior="poll_check",
        source="poller",
    )
    with patch("workers.pipeline.fff_runner.probe_story_metadata", return_value=probe):
        assert pipeline._handle_poll_check(fanfic_approx, h_approx.ctx) is False

    approx_tracked = store.get_tracked_story(approx_url)
    assert approx_tracked is not None
    assert approx_tracked.known_chapters == 15
    assert approx_tracked.last_update_date == date(2026, 5, 1)
    assert approx_tracked.update_date_exact is True

    # Exact date: remote date newer than exact Calibre date triggers handoff
    h_exact = _make_worker_harness(store, active_polls={site: exact_url})
    fanfic_exact = FanficInfo(
        url=exact_url,
        site=site,
        calibre_id="2",
        behavior="poll_check",
        source="poller",
    )
    with patch("workers.pipeline.fff_runner.probe_story_metadata", return_value=probe):
        assert pipeline._handle_poll_check(fanfic_exact, h_exact.ctx) is True

    exact_tracked = store.get_tracked_story(exact_url)
    assert exact_tracked is not None
    assert exact_tracked.known_chapters is None
    assert exact_tracked.last_update_date == date(2026, 1, 1)


def test_poll_check_deleted_story_marks_deleted_remotely(tmp_path: Path) -> None:
    url = "https://archiveofourown.org/works/99999"
    site = "archiveofourown"
    store = _make_store_with_story(tmp_path, url=url, site=site)
    active_polls: dict[str, object] = {site: url}
    h = _make_worker_harness(store, active_polls=active_polls)
    fanfic = FanficInfo(
        url=url,
        site=site,
        calibre_id="42",
        behavior="poll_check",
        source="poller",
    )

    probe = MetadataProbeResult(
        story_deleted=True,
        error="Story does not exist",
    )

    with patch("workers.pipeline.fff_runner.probe_story_metadata", return_value=probe):
        should_download = pipeline._handle_poll_check(fanfic, h.ctx)

    assert should_download is False
    assert site not in active_polls
    assert url not in h.ctx.active_urls
    h.waiting_queue.put.assert_not_called()
    h.notification_info.send_notification.assert_not_called()
    h.history_recorder.record_download_created.assert_not_called()

    tracked = store.get_tracked_story(url)
    assert tracked is not None
    assert tracked.deleted_remotely is True
    assert tracked.active is False


def test_poll_check_transient_error_recovers_flaresolverr_and_backs_off(
    tmp_path: Path,
) -> None:
    url = "https://fanfiction.net/s/12345/1/"
    site = "fanfiction"
    store = _make_store_with_story(tmp_path, url=url, site=site)
    active_polls: dict[str, object] = {site: url}
    h = _make_worker_harness(store, active_polls=active_polls, site=site)
    fanfic = FanficInfo(
        url=url,
        site=site,
        calibre_id="42",
        behavior="poll_check",
        source="poller",
    )

    probe = MetadataProbeResult(
        error="HTTP 500: FlareSolverr says: Error: tab crashed",
    )

    with (
        patch("workers.pipeline.fff_runner.probe_story_metadata", return_value=probe),
        patch(
            "workers.pipeline.flaresolverr.recover_flaresolverr_crashes",
            return_value=1,
        ) as mock_recover,
    ):
        should_download = pipeline._handle_poll_check(fanfic, h.ctx)

    assert should_download is False
    assert site not in active_polls
    mock_recover.assert_called_once_with(
        target_site=site,
        personal_ini_path=h.ctx.cdb_info.personal_ini,
    )
    h.waiting_queue.put.assert_not_called()
    h.notification_info.send_notification.assert_not_called()
    assert url not in h.ctx.active_urls

    tracked = store.get_tracked_story(url)
    assert tracked is not None
    assert tracked.consecutive_errors == 1
    assert tracked.last_error is not None
    assert "tab crashed" in tracked.last_error
    assert tracked.next_check_at > datetime.now(timezone.utc) + timedelta(hours=23)


def test_poller_download_equal_chapters_silent_noop(tmp_path: Path) -> None:
    url = "https://archiveofourown.org/works/12345"
    site = "archiveofourown"
    store = _make_store_with_story(
        tmp_path,
        url=url,
        site=site,
        last_update_date=date(2026, 10, 1),
        update_date_exact=True,
        known_chapters=10,
    )
    h = _make_worker_harness(store)
    h.ctx.active_urls[url] = {"status": "processing", "site": site, "source": "poller"}
    fanfic = FanficInfo(
        url=url,
        site=site,
        calibre_id="42",
        behavior=None,
        title="Test Story",
        source="poller",
    )

    fff_res = FanFicFareResult(
        failure_messages=["Test Story-42.epub already contains 10 chapters."],
    )

    with (
        patch(
            "workers.pipeline.common.get_path_or_url",
            return_value="/tmp/Test Story-42.epub",
        ),
        patch(
            "workers.pipeline.fff_runner.execute_fanficfare_direct",
            return_value=fff_res,
        ),
        patch("workers.pipeline.system_utils.temporary_directory") as mock_tmp,
    ):
        mock_tmp.return_value.__enter__.return_value = "/tmp"
        should_remove = pipeline._process_task(fanfic, h.ctx)

    assert should_remove is True
    assert fanfic.retry_decision is None
    h.waiting_queue.put.assert_not_called()
    h.notification_info.send_notification.assert_not_called()
    h.history_recorder.record_retry.assert_not_called()
    h.history_recorder.record_download_abandoned.assert_not_called()
    h.history_recorder.record_download_success.assert_called_once()

    tracked = store.get_tracked_story(url)
    assert tracked is not None
    assert tracked.known_chapters == 10
    assert tracked.next_check_at > datetime.now(timezone.utc)


def test_any_successful_download_refreshes_poller_schedule(tmp_path: Path) -> None:
    url = "https://archiveofourown.org/works/12345"
    site = "archiveofourown"
    store = _make_store_with_story(
        tmp_path,
        url=url,
        site=site,
        last_update_date=date(2026, 1, 1),
        update_date_exact=False,
        known_chapters=10,
    )
    h = _make_worker_harness(store)
    # Email-triggered download (not poller!) should still refresh poller schedule
    fanfic = FanficInfo(
        url=url,
        site=site,
        calibre_id="42",
        behavior=None,
        title="Test Story",
        source="email",
    )

    mock_strategy = MagicMock()
    mock_strategy.execute.return_value = (True, None)

    with patch(
        "workers.handlers.update_strategies.AddFormatStrategy",
        return_value=mock_strategy,
    ):
        should_remove = handlers.process_fanfic_addition(
            fanfic,
            h.ctx,
            temp_dir=str(tmp_path),
            path_or_url=str(tmp_path / "Test Story-42.epub"),
        )

    assert should_remove is True
    tracked = store.get_tracked_story(url)
    assert tracked is not None
    assert tracked.last_update_date == datetime.now(timezone.utc).date()
    assert tracked.update_date_exact is True
    assert tracked.consecutive_no_change == 0
    assert tracked.consecutive_errors == 0
    assert tracked.next_check_at > datetime.now(timezone.utc)


def test_coordinator_skips_series_expansion_for_poll_check() -> None:
    ingress_q: stdlib_queue.Queue = stdlib_queue.Queue()
    worker_q: stdlib_queue.Queue = stdlib_queue.Queue()
    active_urls: dict = {}
    history_recorder = MagicMock()
    scale_q: stdlib_queue.Queue = stdlib_queue.Queue()

    coordinator = Coordinator(
        ingress_queue=ingress_q,  # type: ignore[arg-type]
        worker_queues={"worker_0": worker_q},  # type: ignore[arg-type]
        shutdown_event=threading.Event(),
        active_urls=active_urls,
        history_recorder=history_recorder,
        url_parsers={},
        config_store=ConfigStore({}),
        scale_queue=scale_q,  # type: ignore[arg-type]
        coordinator_status={},
    )

    task = FanficInfo(
        url="https://archiveofourown.org/works/12345",
        site="archiveofourown",
        calibre_id="42",
        behavior="poll_check",
        source="poller",
    )

    with patch("services.coordinator.series.process_url") as mock_series:
        coordinator._handle_new_task(task)

    mock_series.assert_not_called()
    assert active_urls == {}
    history_recorder.record_download_created.assert_not_called()
    routed = worker_q.get(timeout=2.0)
    assert routed is task
    assert coordinator.state.assignments["archiveofourown"] == "worker_0"


def test_poll_check_completed_status_hands_off_and_updates_baseline_on_calibre_success(
    tmp_path: Path,
) -> None:
    url = "https://archiveofourown.org/works/55555"
    site = "archiveofourown"
    store = _make_store_with_story(
        tmp_path,
        url=url,
        site=site,
        last_update_date=date(2026, 10, 1),
        update_date_exact=True,
        known_chapters=10,
    )
    active_polls: dict[str, object] = {site: url}
    h = _make_worker_harness(store, active_polls=active_polls)
    fanfic = FanficInfo(
        url=url,
        site=site,
        calibre_id="42",
        behavior="poll_check",
        title="Test Story",
        source="poller",
    )

    probe = MetadataProbeResult(
        num_chapters=10,
        date_updated=date(2026, 10, 1),
        status="Completed",
        title="Test Story",
    )
    mock_strategy = MagicMock()
    mock_strategy.execute.return_value = (True, None)

    with (
        patch("workers.pipeline.fff_runner.probe_story_metadata", return_value=probe),
        patch(
            "workers.pipeline.common.get_path_or_url",
            return_value=str(tmp_path / "Test Story-42.epub"),
        ),
        patch(
            "workers.pipeline.fff_runner.execute_fanficfare_direct",
            return_value=FanFicFareResult(),
        ),
        patch("workers.pipeline.system_utils.temporary_directory") as mock_tmp,
        patch(
            "workers.handlers.update_strategies.AddFormatStrategy",
            return_value=mock_strategy,
        ),
    ):
        mock_tmp.return_value.__enter__.return_value = str(tmp_path)
        result = pipeline._process_task(fanfic, h.ctx)

    assert result is True
    assert site not in active_polls
    assert fanfic.behavior is None
    assert fanfic.source == "poller"
    h.history_recorder.record_download_created.assert_called_once_with(
        url,
        site,
        behavior=None,
        source="poller",
    )
    h.history_recorder.record_download_success.assert_called_once()

    status_summary = store.get_site_status(
        site, SitePollerConfig(), datetime.now(timezone.utc)
    )
    recent_events = status_summary["recent_events"]
    assert isinstance(recent_events, list)
    assert recent_events[0]["outcome"] == "completed"

    # Completed story must be marked Completed and deactivated (active=False) so add_format does not loop
    tracked = store.get_tracked_story(url)
    assert tracked is not None
    assert tracked.remote_status == "Completed"
    assert tracked.active is False


def test_url_worker_poll_check_unchanged_never_touches_active_urls_or_history(
    tmp_path: Path,
) -> None:
    url = "https://archiveofourown.org/works/77777"
    site = "archiveofourown"
    store = _make_store_with_story(
        tmp_path,
        url=url,
        site=site,
        last_update_date=date(2026, 10, 1),
        update_date_exact=True,
        known_chapters=10,
    )
    active_polls: dict[str, object] = {site: url}
    h = _make_worker_harness(store, active_polls=active_polls)
    fanfic = FanficInfo(
        url=url,
        site=site,
        calibre_id="42",
        behavior="poll_check",
        title="Test Story",
        source="poller",
    )

    worker_q: stdlib_queue.Queue = stdlib_queue.Queue()
    worker_q.put(fanfic)
    worker_q.put(None)

    probe = MetadataProbeResult(
        num_chapters=10,
        date_updated=date(2026, 10, 1),
        status="In-Progress",
        title="Test Story",
    )

    with patch("workers.pipeline.fff_runner.probe_story_metadata", return_value=probe):
        pipeline.url_worker(worker_q, h.ctx, "worker_0", verbose=False)  # type: ignore[arg-type]

    assert site not in active_polls
    assert h.ctx.active_urls == {}
    h.history_recorder.record_download_created.assert_not_called()
    h.history_recorder.record_download_processing.assert_not_called()
    h.waiting_queue.put.assert_not_called()
    h.notification_info.send_notification.assert_not_called()


def test_url_worker_poll_check_preserves_existing_active_urls_entry(
    tmp_path: Path,
) -> None:
    url = "https://archiveofourown.org/works/88888"
    site = "archiveofourown"
    store = _make_store_with_story(
        tmp_path,
        url=url,
        site=site,
        last_update_date=date(2026, 10, 1),
        update_date_exact=True,
        known_chapters=10,
    )
    active_polls: dict[str, object] = {site: url}
    h = _make_worker_harness(store, active_polls=active_polls)
    # Pre-existing concurrent download entry for the same URL
    h.ctx.active_urls[url] = {
        "status": "queued",
        "site": site,
        "source": "email",
    }
    fanfic = FanficInfo(
        url=url,
        site=site,
        calibre_id="42",
        behavior="poll_check",
        title="Test Story",
        source="poller",
    )

    worker_q: stdlib_queue.Queue = stdlib_queue.Queue()
    worker_q.put(fanfic)
    worker_q.put(None)

    probe = MetadataProbeResult(
        num_chapters=10,
        date_updated=date(2026, 10, 1),
        status="In-Progress",
        title="Test Story",
    )

    with patch("workers.pipeline.fff_runner.probe_story_metadata", return_value=probe):
        pipeline.url_worker(worker_q, h.ctx, "worker_0", verbose=False)  # type: ignore[arg-type]

    assert site not in active_polls
    assert url in h.ctx.active_urls
    assert h.ctx.active_urls[url]["status"] == "queued"
    assert h.ctx.active_urls[url].get("source") == "email"


def test_poll_check_date_only_update_equal_chapters_advances_last_update_date(
    tmp_path: Path,
) -> None:
    url = "https://archiveofourown.org/works/66666"
    site = "archiveofourown"
    store = _make_store_with_story(
        tmp_path,
        url=url,
        site=site,
        last_update_date=date(2026, 10, 1),
        update_date_exact=True,
        known_chapters=10,
    )
    active_polls: dict[str, object] = {site: url}
    h = _make_worker_harness(store, active_polls=active_polls)
    fanfic = FanficInfo(
        url=url,
        site=site,
        calibre_id="42",
        behavior="poll_check",
        title="Test Story",
        source="poller",
    )

    # Author edited an existing chapter: date_updated advanced, num_chapters unchanged
    probe = MetadataProbeResult(
        num_chapters=10,
        date_updated=date(2026, 11, 20),
        status="In-Progress",
        title="Test Story",
    )
    fff_res = FanFicFareResult(
        failure_messages=["Test Story-42.epub already contains 10 chapters."],
    )

    with (
        patch("workers.pipeline.fff_runner.probe_story_metadata", return_value=probe),
        patch(
            "workers.pipeline.common.get_path_or_url",
            return_value="/tmp/Test Story-42.epub",
        ),
        patch(
            "workers.pipeline.fff_runner.execute_fanficfare_direct",
            return_value=fff_res,
        ),
        patch("workers.pipeline.system_utils.temporary_directory") as mock_tmp,
    ):
        mock_tmp.return_value.__enter__.return_value = "/tmp"
        should_remove = pipeline._process_task(fanfic, h.ctx)

    assert should_remove is True
    tracked = store.get_tracked_story(url)
    assert tracked is not None
    assert tracked.last_update_date == date(2026, 11, 20)
    assert tracked.known_chapters == 10

    # Subsequent poll with the same remote metadata must NOT trigger another download
    next_fanfic = FanficInfo(
        url=url,
        site=site,
        calibre_id="42",
        behavior="poll_check",
        title="Test Story",
        source="poller",
    )
    with patch("workers.pipeline.fff_runner.probe_story_metadata", return_value=probe):
        assert pipeline._handle_poll_check(next_fanfic, h.ctx) is False


def test_poll_check_completed_equal_chapters_deactivates_story(tmp_path: Path) -> None:
    """When a Completed story hits equal_chapters no-op, it is marked Completed and deactivated."""
    url = "https://archiveofourown.org/works/55556"
    site = "archiveofourown"
    store = _make_store_with_story(
        tmp_path,
        url=url,
        site=site,
        last_update_date=date(2026, 10, 1),
        update_date_exact=True,
        known_chapters=10,
    )
    active_polls: dict[str, object] = {site: url}
    h = _make_worker_harness(store, active_polls=active_polls)
    fanfic = FanficInfo(
        url=url,
        site=site,
        calibre_id="42",
        behavior="poll_check",
        title="Completed Story",
        source="poller",
    )

    probe = MetadataProbeResult(
        num_chapters=10,
        date_updated=date(2026, 10, 1),
        status="Completed",
        title="Completed Story",
    )
    fff_res = FanFicFareResult(
        failure_messages=["Completed Story-42.epub already contains 10 chapters."],
    )

    with (
        patch("workers.pipeline.fff_runner.probe_story_metadata", return_value=probe),
        patch(
            "workers.pipeline.common.get_path_or_url",
            return_value="/tmp/Completed Story-42.epub",
        ),
        patch(
            "workers.pipeline.fff_runner.execute_fanficfare_direct",
            return_value=fff_res,
        ),
        patch("workers.pipeline.system_utils.temporary_directory") as mock_tmp,
    ):
        mock_tmp.return_value.__enter__.return_value = "/tmp"
        should_remove = pipeline._process_task(fanfic, h.ctx)

    assert should_remove is True
    tracked = store.get_tracked_story(url)
    assert tracked is not None
    assert tracked.remote_status == "Completed"
    assert tracked.active is False
