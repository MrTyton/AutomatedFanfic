"""Unit tests for the Supervisor LibraryPoller service and scheduler tick logic."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from queue import Empty, Queue
import random
import re
import threading
from unittest.mock import MagicMock, patch

from calibre_integration.models import CalibreConnectionError, CalibreStorySummary
from config.schemas.poller import LibraryPollerConfig, SitePollerConfig
from config.store import ConfigStore
from history.poller_store import PollerStore
from models.active_urls import ActiveUrlEntry
from models.context import SharedIPCContext, WorkerContext
from models.fanfic_info import FanficInfo
from models.queue_types import IngressItem
from services.library_poller import (
    LibraryPoller,
    resolve_site_domain,
    run_library_poller,
)
from workers import pool_runner


def _make_config_store(
    *,
    enabled: bool = True,
    library_sync_interval_hours: float = 6.0,
    tick_interval_seconds: float = 60.0,
    sites: dict[str, SitePollerConfig] | None = None,
    disabled_sites: list[str] | None = None,
) -> ConfigStore:
    site_map = (
        sites if sites is not None else {"fanfiction": SitePollerConfig(enabled=True)}
    )
    poller_cfg = LibraryPollerConfig(
        enabled=enabled,
        library_sync_interval_hours=library_sync_interval_hours,
        tick_interval_seconds=tick_interval_seconds,
        sites=site_map,
    )
    store = ConfigStore({})
    store.update_many(
        {
            "library_poller.enabled": poller_cfg.enabled,
            "library_poller.library_sync_interval_hours": poller_cfg.library_sync_interval_hours,
            "library_poller.tick_interval_seconds": poller_cfg.tick_interval_seconds,
            "library_poller.sites": {
                k: v.model_dump() for k, v in poller_cfg.sites.items()
            },
            "email.disabled_sites": list(disabled_sites or []),
        }
    )
    return store


def _seed_due_story(
    store: PollerStore,
    *,
    url: str,
    site: str = "fanfiction",
    calibre_id: str = "101",
    title: str = "Test Story",
    last_update_date: date = date(2026, 11, 20),
    next_check_at: datetime = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc),
) -> None:
    summary = CalibreStorySummary(
        calibre_id=calibre_id,
        title=title,
        url=url,
        tags=["In-Progress"],
        last_modified=datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc),
        last_update_date=last_update_date,
        update_date_exact=True,
    )
    store.sync_site_stories(
        site=site,
        stories=[summary],
        initial_next_check_fn=lambda _s: next_check_at,
    )


def _make_poller(
    tmp_path: Path,
    *,
    config_store: ConfigStore,
    calibre_client: MagicMock | None = None,
    coordinator_status: dict[str, object] | None = None,
    active_polls: dict[str, object] | None = None,
    poller_last_sync: dict[str, str] | None = None,
    active_urls: dict[str, ActiveUrlEntry] | None = None,
    sync_event: threading.Event | None = None,
) -> tuple[
    LibraryPoller,
    PollerStore,
    Queue[IngressItem],
    dict[str, object],
    dict[str, str],
    threading.Event,
    MagicMock,
]:
    store = PollerStore(tmp_path / "history.db")
    ingress_queue: Queue[IngressItem] = Queue()
    client = calibre_client if calibre_client is not None else MagicMock()
    if calibre_client is None:
        client.list_stories_by_query.return_value = []
    coord_status: dict[str, object] = (
        coordinator_status
        if coordinator_status is not None
        else {"assignments": {}, "backlog": {}}
    )
    polls: dict[str, object] = active_polls if active_polls is not None else {}
    last_sync: dict[str, str] = poller_last_sync if poller_last_sync is not None else {}
    urls: dict[str, ActiveUrlEntry] = active_urls if active_urls is not None else {}
    ev = sync_event if sync_event is not None else threading.Event()
    poller = LibraryPoller(
        calibre_client=client,
        poller_store=store,
        ingress_queue=ingress_queue,
        active_urls=urls,
        config_store=config_store,
        coordinator_status=coord_status,
        active_polls=polls,
        poller_last_sync=last_sync,
        sync_poller_event=ev,
        rng=random.Random(42),
    )
    return poller, store, ingress_queue, polls, last_sync, ev, client


def test_tick_skips_when_disabled_or_hot_reloaded_off(tmp_path: Path) -> None:
    """Disabled globally, per-site, in disabled_sites, or hot-reloaded off -> zero tasks."""
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)

    # 1. Globally disabled
    cfg_store = _make_config_store(enabled=False)
    poller, store, ingress_q, polls, last_sync, _ev, _client = _make_poller(
        tmp_path / "global_off",
        config_store=cfg_store,
        poller_last_sync={"fanfiction": (now - timedelta(minutes=5)).isoformat()},
    )
    _seed_due_story(
        store,
        url="https://www.fanfiction.net/s/1001/1/",
        next_check_at=now - timedelta(hours=1),
    )
    assert poller.tick(now) == []
    assert ingress_q.empty()
    assert polls == {}

    # 2. Per-site disabled
    cfg_store = _make_config_store(
        enabled=True,
        sites={"fanfiction": SitePollerConfig(enabled=False)},
    )
    poller, store, ingress_q, polls, last_sync, _ev, _client = _make_poller(
        tmp_path / "site_off",
        config_store=cfg_store,
        poller_last_sync={"fanfiction": (now - timedelta(minutes=5)).isoformat()},
    )
    _seed_due_story(
        store,
        url="https://www.fanfiction.net/s/1002/1/",
        next_check_at=now - timedelta(hours=1),
    )
    assert poller.tick(now) == []
    assert ingress_q.empty()

    # 3. Site in email.disabled_sites
    cfg_store = _make_config_store(
        enabled=True,
        sites={"fanfiction": SitePollerConfig(enabled=True)},
        disabled_sites=["fanfiction"],
    )
    poller, store, ingress_q, polls, last_sync, _ev, _client = _make_poller(
        tmp_path / "disabled_sites",
        config_store=cfg_store,
        poller_last_sync={"fanfiction": (now - timedelta(minutes=5)).isoformat()},
    )
    _seed_due_story(
        store,
        url="https://www.fanfiction.net/s/1003/1/",
        next_check_at=now - timedelta(hours=1),
    )
    assert poller.tick(now) == []
    assert ingress_q.empty()

    # 4. Hot-reloaded off between ticks
    cfg_store = _make_config_store(enabled=True)
    poller, store, ingress_q, polls, last_sync, _ev, _client = _make_poller(
        tmp_path / "hot_reload_off",
        config_store=cfg_store,
        poller_last_sync={"fanfiction": (now - timedelta(minutes=5)).isoformat()},
    )
    _seed_due_story(
        store,
        url="https://www.fanfiction.net/s/1004/1/",
        next_check_at=now - timedelta(hours=1),
    )
    cfg_store.update("library_poller.enabled", False)
    assert poller.tick(now) == []
    assert ingress_q.empty()


def test_tick_skips_when_site_busy_in_coordinator_or_poll_in_flight(
    tmp_path: Path,
) -> None:
    """Busy in coordinator (assigned or backlogged) or active_polls set -> zero tasks."""
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    cfg_store = _make_config_store(enabled=True)
    coord_status: dict[str, object] = {
        "assignments": {"fanfiction": "worker_0"},
        "backlog": {},
    }
    poller, store, ingress_q, polls, _last_sync, _ev, _client = _make_poller(
        tmp_path,
        config_store=cfg_store,
        coordinator_status=coord_status,
        poller_last_sync={"fanfiction": (now - timedelta(minutes=5)).isoformat()},
    )
    _seed_due_story(
        store,
        url="https://www.fanfiction.net/s/2001/1/",
        next_check_at=now - timedelta(hours=2),
    )

    # Assigned worker holds site lock
    assert poller.tick(now) == []
    assert ingress_q.empty()

    # Worker released, but backlog has pending task for site
    coord_status["assignments"] = {}
    coord_status["backlog"] = {
        "fanfiction": [{"url": "https://www.fanfiction.net/s/9999/1/"}]
    }
    assert poller.tick(now) == []
    assert ingress_q.empty()

    # Coordinator idle, but active_polls already has an in-flight probe
    coord_status["backlog"] = {}
    polls["fanfiction"] = {"url": "https://www.fanfiction.net/s/2001/1/"}
    assert poller.tick(now) == []
    assert ingress_q.empty()


def test_tick_respects_daily_budget_and_min_interval(tmp_path: Path) -> None:
    """Blocks dispatch when 24h count >= max_checks_per_day or elapsed < min_interval_minutes."""
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    site_cfg = SitePollerConfig(
        enabled=True,
        max_checks_per_day=2,
        min_interval_minutes=30.0,
    )
    cfg_store = _make_config_store(enabled=True, sites={"fanfiction": site_cfg})
    poller, store, ingress_q, polls, _last_sync, _ev, _client = _make_poller(
        tmp_path,
        config_store=cfg_store,
        poller_last_sync={"fanfiction": (now - timedelta(minutes=5)).isoformat()},
    )
    _seed_due_story(
        store,
        url="https://www.fanfiction.net/s/3001/1/",
        next_check_at=now - timedelta(hours=3),
    )

    # Record 1 recent check 10 minutes ago -> violates min_interval_minutes (30m)
    store.record_probe_outcome(
        url="https://www.fanfiction.net/s/other/1/",
        site="fanfiction",
        outcome="unchanged",
        checked_at=now - timedelta(minutes=10),
        next_check_at=now + timedelta(days=1),
        remote_chapters=10,
        remote_updated_at=date(2026, 11, 20),
        remote_status="In-Progress",
        error_message=None,
        advance_baseline=True,
    )
    assert poller.tick(now) == []
    assert ingress_q.empty()

    # Record a second check 2 hours ago -> now 24h count == 2 (hits max_checks_per_day)
    store.record_probe_outcome(
        url="https://www.fanfiction.net/s/other2/1/",
        site="fanfiction",
        outcome="unchanged",
        checked_at=now - timedelta(hours=2),
        next_check_at=now + timedelta(days=1),
        remote_chapters=10,
        remote_updated_at=date(2026, 11, 20),
        remote_status="In-Progress",
        error_message=None,
        advance_baseline=True,
    )
    # Even 45 minutes later (past min_interval_minutes), daily budget is still full (2/2)
    later = now + timedelta(minutes=45)
    assert poller.tick(later) == []
    assert ingress_q.empty()

    # Once the 2-hour-old check ages past 24h (so 24h count drops to 1/2) -> dispatches!
    after_budget_reset = now + timedelta(hours=22, minutes=5)
    poller.poller_last_sync["fanfiction"] = (
        after_budget_reset - timedelta(minutes=5)
    ).isoformat()
    dispatched = poller.tick(after_budget_reset)
    assert len(dispatched) == 1
    assert dispatched[0].url == "https://www.fanfiction.net/s/3001/1/"
    assert "fanfiction" in polls


def test_tick_dispatches_highest_scoring_due_story(tmp_path: Path) -> None:
    """Enqueues highest-scoring eligible FanficInfo(behavior='poll_check', source='poller') and updates active_polls."""
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    cfg_store = _make_config_store(enabled=True)
    active_urls: dict[str, ActiveUrlEntry] = {
        "https://www.fanfiction.net/s/4000/1/": {"status": "processing"}
    }
    poller, store, ingress_q, polls, _last_sync, _ev, _client = _make_poller(
        tmp_path,
        config_store=cfg_store,
        active_urls=active_urls,
        poller_last_sync={"fanfiction": (now - timedelta(minutes=5)).isoformat()},
    )

    # Most overdue story is already in active_urls -> must be excluded
    story_active = CalibreStorySummary(
        calibre_id="4000",
        title="Already Downloading",
        url="https://www.fanfiction.net/s/4000/1/",
        tags=["In-Progress"],
        last_modified=now - timedelta(days=1),
        last_update_date=date(2026, 11, 21),
        update_date_exact=True,
    )
    # Hot story overdue by 3 days (ratio = 3 / 1.5 = 2.0) -> highest eligible
    story_hot = CalibreStorySummary(
        calibre_id="4001",
        title="Hot Story",
        url="https://www.fanfiction.net/s/4001/1/",
        tags=["In-Progress"],
        last_modified=now - timedelta(days=2),
        last_update_date=date(2026, 11, 20),
        update_date_exact=True,
    )
    # Warm story overdue by 1 day (ratio = 1 / 7.0 = 0.14) -> lower score
    story_warm = CalibreStorySummary(
        calibre_id="4002",
        title="Warm Story",
        url="https://www.fanfiction.net/s/4002/1/",
        tags=["In-Progress"],
        last_modified=now - timedelta(days=40),
        last_update_date=date(2026, 10, 10),
        update_date_exact=True,
    )
    next_checks = {
        story_active.url: now - timedelta(days=10),
        story_hot.url: now - timedelta(days=3),
        story_warm.url: now - timedelta(days=1),
    }
    store.sync_site_stories(
        site="fanfiction",
        stories=[story_active, story_hot, story_warm],
        initial_next_check_fn=lambda s: next_checks[s.url],
    )

    dispatched = poller.tick(now)
    assert len(dispatched) == 1
    task = dispatched[0]
    assert isinstance(task, FanficInfo)
    assert task.url == "https://www.fanfiction.net/s/4001/1/"
    assert task.site == "fanfiction"
    assert task.calibre_id == "4001"
    assert task.title == "Hot Story"
    assert task.behavior == "poll_check"
    assert task.source == "poller"

    queued_item = ingress_q.get(timeout=5.0)
    assert isinstance(queued_item, FanficInfo)
    assert queued_item.url == task.url
    assert queued_item.behavior == "poll_check"
    assert queued_item.source == "poller"

    assert polls["fanfiction"] == {
        "url": "https://www.fanfiction.net/s/4001/1/",
        "title": "Hot Story",
        "started_at": now.isoformat(),
    }


def test_sync_calibre_error_preserves_existing_rows(tmp_path: Path) -> None:
    """When list_stories_by_query raises CalibreConnectionError, logs WARNING and preserves existing rows."""
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    cfg_store = _make_config_store(enabled=True)
    client = MagicMock()
    client.list_stories_by_query.side_effect = CalibreConnectionError(
        "Calibre server unreachable"
    )
    poller, store, _ingress_q, _polls, last_sync, _ev, _client = _make_poller(
        tmp_path,
        config_store=cfg_store,
        calibre_client=client,
    )
    _seed_due_story(
        store,
        url="https://www.fanfiction.net/s/5001/1/",
        calibre_id="5001",
        title="Existing Story",
        next_check_at=now - timedelta(hours=1),
    )

    with patch("services.library_poller.ff_logging") as mock_logging:
        result = poller.sync_site("fanfiction", SitePollerConfig(enabled=True), now)

    assert result is None
    assert "fanfiction" not in last_sync
    mock_logging.log.assert_called()
    warning_calls = [
        call
        for call in mock_logging.log.call_args_list
        if len(call.args) >= 2 and call.args[1] == "WARNING"
    ]
    assert warning_calls, "Expected a WARNING log on Calibre sync failure"

    # Existing tracked row must remain active and untouched
    tracked = store.get_tracked_story("https://www.fanfiction.net/s/5001/1/")
    assert tracked is not None
    assert tracked.active is True
    assert tracked.title == "Existing Story"


def test_manual_sync_event_triggers_immediate_sync(tmp_path: Path) -> None:
    """Setting sync_poller_event forces sync before library_sync_interval_hours elapses and clears event."""
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    cfg_store = _make_config_store(enabled=True, library_sync_interval_hours=6.0)
    client = MagicMock()
    client.list_stories_by_query.return_value = [
        CalibreStorySummary(
            calibre_id="6001",
            title="Newly Discovered",
            url="https://www.fanfiction.net/s/6001/1/",
            tags=["In-Progress"],
            last_modified=now - timedelta(days=1),
            last_update_date=date(2026, 11, 21),
            update_date_exact=True,
        )
    ]
    recent_sync = (now - timedelta(minutes=10)).isoformat()
    poller, store, _ingress_q, _polls, last_sync, sync_ev, _client = _make_poller(
        tmp_path,
        config_store=cfg_store,
        calibre_client=client,
        poller_last_sync={"fanfiction": recent_sync},
    )

    # Without event set, sync interval (6h) has not elapsed -> no Calibre query
    poller.tick(now)
    client.list_stories_by_query.assert_not_called()
    assert last_sync["fanfiction"] == recent_sync

    # Set manual sync event -> forces immediate sync and clears the event
    sync_ev.set()
    poller.tick(now)
    assert not sync_ev.is_set()
    client.list_stories_by_query.assert_called_once()
    query_arg = client.list_stories_by_query.call_args.args[0]
    assert 'identifiers:"fanfiction.net"' in query_arg
    assert last_sync["fanfiction"] == now.isoformat()
    tracked = store.get_tracked_story("https://www.fanfiction.net/s/6001/1/")
    assert tracked is not None
    assert tracked.title == "Newly Discovered"


def test_resolve_site_domain_mappings() -> None:
    """Canonical site keys map to expected domain strings."""
    assert resolve_site_domain("fanfiction") == "fanfiction.net"
    assert resolve_site_domain("archiveofourown") == "archiveofourown.org"
    assert resolve_site_domain("royalroad") == "royalroad.com"
    assert resolve_site_domain("custom.example.org") == "custom.example.org"
    assert resolve_site_domain("www.example.com") == "example.com"


def test_run_library_poller_wakes_early_on_sync_and_shutdown(tmp_path: Path) -> None:
    """run_library_poller wakes early on sync_poller_event and exits promptly on shutdown_event."""
    cfg_store = _make_config_store(enabled=True, tick_interval_seconds=30.0)
    store = PollerStore(tmp_path / "loop.db")
    ingress_q: Queue[IngressItem] = Queue()
    client = MagicMock()
    sync_completed = threading.Event()

    def _list_stories(_query: str) -> list[CalibreStorySummary]:
        if client.list_stories_by_query.call_count >= 2:
            sync_completed.set()
        return []

    client.list_stories_by_query.side_effect = _list_stories
    shutdown_ev = threading.Event()
    sync_ev = threading.Event()
    last_sync: dict[str, str] = {}

    thread = threading.Thread(
        target=run_library_poller,
        args=(
            ingress_q,
            {},
            cfg_store,
            shutdown_ev,
            {"assignments": {}, "backlog": {}},
            {},
            last_sync,
            sync_ev,
            client,
            store,
            {},
            False,
        ),
        daemon=True,
    )
    thread.start()
    try:
        # Wait for initial sync from first tick, then trigger manual sync event
        deadline = datetime.now(timezone.utc) + timedelta(seconds=5)
        while "fanfiction" not in last_sync and datetime.now(timezone.utc) < deadline:
            threading.Event().wait(0.05)
        assert "fanfiction" in last_sync

        sync_ev.set()
        assert sync_completed.wait(
            timeout=3.0
        ), "Poller did not wake early on sync_poller_event"
        assert not sync_ev.is_set()
    finally:
        shutdown_ev.set()
        thread.join(timeout=3.0)
    assert not thread.is_alive()


def test_pool_runner_wires_poller_dependencies_into_worker_context(
    tmp_path: Path,
) -> None:
    """run_worker_pool passes poller_store, active_polls, and config_store into WorkerContext."""
    poller_store = PollerStore(tmp_path / "worker.db")
    active_polls: dict[str, object] = {}
    config_store = _make_config_store(enabled=True)
    shutdown_event = MagicMock()
    shutdown_event.is_set.side_effect = [False, True]
    scale_queue = MagicMock()
    scale_queue.get.side_effect = Empty

    ipc = SharedIPCContext(
        ingress_queue=MagicMock(),
        waiting_queue=MagicMock(),
        worker_queues={"worker_0": MagicMock()},
        active_urls={},
        history_recorder=MagicMock(),
        config_store=config_store,
        scale_queue=scale_queue,
        shutdown_event=shutdown_event,
        active_polls=active_polls,
        poller_store=poller_store,
    )

    with (
        patch("workers.pool_runner.threading.Thread") as mock_thread_cls,
        patch("workers.pool_runner.signal.signal"),
        patch("workers.pool_runner.ff_logging"),
    ):
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        mock_thread_cls.return_value = mock_thread
        pool_runner.run_worker_pool(
            ipc,
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

    assert mock_thread_cls.call_count == 1
    worker_ctx = mock_thread_cls.call_args.kwargs["args"][1]
    assert isinstance(worker_ctx, WorkerContext)
    assert worker_ctx.poller_store is poller_store
    assert worker_ctx.active_polls is active_polls
    assert worker_ctx.config_store is config_store


def test_tick_clears_sync_event_when_disabled(tmp_path: Path) -> None:
    """tick() clears sync_poller_event when library_poller.enabled is False to prevent busy-spin."""
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    cfg_store = _make_config_store(enabled=False)
    poller, _store, ingress_q, _polls, _last_sync, sync_ev, client = _make_poller(
        tmp_path,
        config_store=cfg_store,
    )
    sync_ev.set()

    assert poller.tick(now) == []
    assert not sync_ev.is_set()
    client.list_stories_by_query.assert_not_called()
    assert ingress_q.empty()


def test_sync_site_normalizes_urls_with_url_parsers(tmp_path: Path) -> None:
    """sync_site normalizes Calibre URLs via url_parsers to canonical FanficInfo format."""
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    cfg_store = _make_config_store(enabled=True)
    client = MagicMock()
    client.list_stories_by_query.return_value = [
        CalibreStorySummary(
            calibre_id="7001",
            title="FFNet Fic",
            url="https://www.fanfiction.net/s/12345/7/Some-Slug",
            tags=["In-Progress"],
            last_modified=now - timedelta(days=1),
            last_update_date=date(2026, 11, 21),
            update_date_exact=True,
        ),
        CalibreStorySummary(
            calibre_id="7002",
            title="AO3 Fic",
            url="https://archiveofourown.org/works/99999/chapters/123",
            tags=["In-Progress"],
            last_modified=now - timedelta(days=1),
            last_update_date=date(2026, 11, 21),
            update_date_exact=True,
        ),
    ]
    url_parsers: dict[str, tuple[object, str]] = {
        "fanfiction": (
            re.compile(
                r"(?:https?://(?:www\.)?fanfiction\.net(/s/\d+/\d+/?).*|https?://(?:www\.)?fanfiction\.net(/s/\d+)/?$)"
            ),
            "www.fanfiction.net",
        ),
        "archiveofourown": (
            re.compile(r"https?://(archiveofourown\.org/(?:works|series)/\d+)/?.*"),
            "",
        ),
    }
    store = PollerStore(tmp_path / "norm.db")
    poller = LibraryPoller(
        calibre_client=client,
        poller_store=store,
        ingress_queue=Queue(),
        active_urls={},
        config_store=cfg_store,
        coordinator_status={"assignments": {}, "backlog": {}},
        active_polls={},
        poller_last_sync={},
        sync_poller_event=threading.Event(),
        url_parsers=url_parsers,
        rng=random.Random(42),
    )

    summary = poller.sync_site("fanfiction", SitePollerConfig(enabled=True), now)
    assert summary == {"added": 2, "updated": 0, "deactivated": 0}
    assert store.get_tracked_story("www.fanfiction.net/s/12345/1/") is not None
    assert store.get_tracked_story("archiveofourown.org/works/99999") is not None
    assert (
        store.get_tracked_story("https://www.fanfiction.net/s/12345/7/Some-Slug")
        is None
    )


def test_is_story_active_matches_scheme_and_base_url_variants(tmp_path: Path) -> None:
    """_is_story_active catches scheme-stripped and extract_story_base_url equivalents, ignoring cancelled."""
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    cfg_store = _make_config_store(enabled=True)
    active_urls: dict[str, ActiveUrlEntry] = {
        "www.fanfiction.net/s/12345/1/": {"status": "processing"},
        "https://m.fanfiction.net/s/54321/5/Some-Slug": {"status": "queued"},
        "www.fanfiction.net/s/77777/1/": {"status": "cancelled"},
    }
    poller, store, ingress_q, _polls, _last_sync, _ev, _client = _make_poller(
        tmp_path,
        config_store=cfg_store,
        active_urls=active_urls,
        poller_last_sync={"fanfiction": (now - timedelta(minutes=5)).isoformat()},
    )
    assert poller._is_story_active("https://www.fanfiction.net/s/12345/1/") is True
    assert poller._is_story_active("https://www.fanfiction.net/s/54321/1/") is True
    assert poller._is_story_active("https://www.fanfiction.net/s/77777/1/") is False

    _seed_due_story(
        store,
        url="https://www.fanfiction.net/s/54321/1/",
        calibre_id="54321",
        next_check_at=now - timedelta(hours=2),
    )
    assert poller.tick(now) == []
    assert ingress_q.empty()


def test_is_site_disabled_matches_www_and_scheme_prefixed_domains(
    tmp_path: Path,
) -> None:
    """disabled_sites entries like 'www.fanfiction.net' and 'https://www.fanfiction.net' disable 'fanfiction'."""
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    for disabled_entry in (
        "www.fanfiction.net",
        "https://www.fanfiction.net",
        "fanfiction.net",
        "fanfiction",
    ):
        cfg_store = _make_config_store(
            enabled=True,
            sites={"fanfiction": SitePollerConfig(enabled=True)},
            disabled_sites=[disabled_entry],
        )
        poller, store, ingress_q, _polls, _last_sync, _ev, _client = _make_poller(
            tmp_path / disabled_entry.replace("://", "_").replace(".", "_"),
            config_store=cfg_store,
            poller_last_sync={"fanfiction": (now - timedelta(minutes=5)).isoformat()},
        )
        _seed_due_story(
            store,
            url="www.fanfiction.net/s/8888/1/",
            next_check_at=now - timedelta(hours=1),
        )
        assert poller.tick(now) == []
        assert ingress_q.empty()


def test_tick_evicts_stale_active_poll_when_coordinator_idle(tmp_path: Path) -> None:
    """active_polls entry older than 15 minutes is evicted when coordinator is idle, self-healing polling."""
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    cfg_store = _make_config_store(enabled=True)
    coord_status: dict[str, object] = {"assignments": {}, "backlog": {}}
    polls: dict[str, object] = {
        "fanfiction": {
            "url": "www.fanfiction.net/s/old/1/",
            "title": "Stuck Story",
            "started_at": (now - timedelta(minutes=16)).isoformat(),
        }
    }
    poller, store, ingress_q, polls_ref, _last_sync, _ev, _client = _make_poller(
        tmp_path,
        config_store=cfg_store,
        coordinator_status=coord_status,
        active_polls=polls,
        poller_last_sync={"fanfiction": (now - timedelta(minutes=5)).isoformat()},
    )
    _seed_due_story(
        store,
        url="www.fanfiction.net/s/9001/1/",
        calibre_id="9001",
        title="Fresh Story",
        next_check_at=now - timedelta(hours=1),
    )

    # Fresh entry (< 15 min) must NOT be evicted
    polls_ref["fanfiction"] = {
        "url": "www.fanfiction.net/s/old/1/",
        "started_at": (now - timedelta(minutes=10)).isoformat(),
    }
    assert poller.tick(now) == []
    assert ingress_q.empty()

    # Stale entry (> 15 min) while coordinator is busy must NOT be evicted
    polls_ref["fanfiction"] = {
        "url": "www.fanfiction.net/s/old/1/",
        "started_at": (now - timedelta(minutes=20)).isoformat(),
    }
    coord_status["assignments"] = {"fanfiction": "worker_0"}
    assert poller.tick(now) == []
    assert "fanfiction" in polls_ref

    # Stale entry (> 15 min) while coordinator is idle MUST be evicted and re-dispatched
    coord_status["assignments"] = {}
    with patch("services.library_poller.ff_logging") as mock_logging:
        dispatched = poller.tick(now)

    assert len(dispatched) == 1
    assert dispatched[0].url == "www.fanfiction.net/s/9001/1/"
    assert polls_ref["fanfiction"] == {
        "url": "www.fanfiction.net/s/9001/1/",
        "title": "Fresh Story",
        "started_at": now.isoformat(),
    }
    warning_calls = [
        call
        for call in mock_logging.log.call_args_list
        if len(call.args) >= 2 and call.args[1] == "WARNING"
    ]
    assert warning_calls, "Expected WARNING log when evicting stale active_polls entry"
