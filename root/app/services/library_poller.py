"""Adaptive Calibre library update poller service running inside Supervisor."""

from collections.abc import Mapping, MutableMapping
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import random
import re
from types import MappingProxyType

from calibre_integration.client_interface import (
    CalibreClient,
    build_site_poll_query,
    extract_story_base_url,
)
from config.ini_resolver import resolve_status_tags_from_ini
from config.schemas.poller import LibraryPollerConfig, SitePollerConfig
from config.store import ConfigStore
import ff_logging
from history.poller_store import PollerStore
from models.active_urls import ActiveUrlsDict, is_url_active
from models.fanfic_info import FanficInfo
from models.queue_types import IngressQueue, ShutdownEvent, SyncPollerEvent
from parsers import regex_parsing, url_patterns
from services.poller_scheduler import (
    compute_initial_staggered_check,
    select_next_candidate,
)

_EMPTY_PARSERS: Mapping[str, tuple[object, str]] = MappingProxyType({})
_PATTERN_DOMAIN_RE = re.compile(r"https\?://\(?([a-zA-Z0-9\\.-]+\\.[a-zA-Z0-9-]+)")
_ACTIVE_POLL_STALE_SECONDS: float = 900.0

_KNOWN_SITE_DOMAINS: dict[str, str] = {
    "fanfiction": "fanfiction.net",
    "ffnet": "fanfiction.net",
    "archiveofourown": "archiveofourown.org",
    "ao3": "archiveofourown.org",
    "royalroad": "royalroad.com",
    "spacebattles": "forums.spacebattles.com",
    "sb": "forums.spacebattles.com",
    "sufficientvelocity": "forums.sufficientvelocity.com",
    "sv": "forums.sufficientvelocity.com",
    "questionablequesting": "forum.questionablequesting.com",
    "qq": "forum.questionablequesting.com",
    "scribblehub": "scribblehub.com",
    "fictionpress": "fictionpress.com",
    "webnovel": "webnovel.com",
    "wattpad": "wattpad.com",
    "fimfiction": "fimfiction.net",
    "alternatehistory": "alternatehistory.com",
}


def _to_utc(dt: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def resolve_site_domain(
    site: str,
    url_parsers: Mapping[str, tuple[object, str]] = _EMPTY_PARSERS,
) -> str:
    """Map a canonical site identifier (e.g. 'fanfiction') to its Calibre URL domain."""
    site_key = site.strip().lower()
    if "." in site_key:
        return site_key.removeprefix("www.")

    if site_key in _KNOWN_SITE_DOMAINS:
        return _KNOWN_SITE_DOMAINS[site_key]

    parser_entry = url_parsers.get(site_key)
    if parser_entry is not None:
        compiled_pattern, prefix = parser_entry
        if isinstance(prefix, str) and prefix.strip():
            return prefix.strip().lower().removeprefix("www.")
        raw_pattern = getattr(compiled_pattern, "pattern", "")
        if isinstance(raw_pattern, str):
            match = _PATTERN_DOMAIN_RE.search(raw_pattern)
            if match is not None:
                return match.group(1).replace("\\.", ".").lower().removeprefix("www.")

    return site_key


def load_poller_config(config_store: ConfigStore) -> LibraryPollerConfig:
    """Load the current LibraryPollerConfig from ConfigStore for hot-reload support."""
    raw_whole = config_store.get("library_poller")
    if isinstance(raw_whole, LibraryPollerConfig):
        return raw_whole

    if isinstance(raw_whole, dict):
        try:
            return LibraryPollerConfig.model_validate(raw_whole)
        except Exception as exc:
            ff_logging.log(
                f"LibraryPoller: Invalid library_poller config in store: {exc}",
                "WARNING",
            )
            return LibraryPollerConfig()

    raw_enabled = config_store.get("library_poller.enabled")
    raw_sync_hours = config_store.get("library_poller.library_sync_interval_hours")
    raw_tick_seconds = config_store.get("library_poller.tick_interval_seconds")
    raw_sites = config_store.get("library_poller.sites")

    payload: dict[str, object] = {}
    if isinstance(raw_enabled, bool):
        payload["enabled"] = raw_enabled
    if isinstance(raw_sync_hours, (int, float)):
        payload["library_sync_interval_hours"] = float(raw_sync_hours)
    if isinstance(raw_tick_seconds, (int, float)):
        payload["tick_interval_seconds"] = float(raw_tick_seconds)
    if isinstance(raw_sites, dict):
        payload["sites"] = raw_sites

    if not payload:
        return LibraryPollerConfig()

    try:
        return LibraryPollerConfig.model_validate(payload)
    except Exception as exc:
        ff_logging.log(
            f"LibraryPoller: Invalid library_poller fields in store: {exc}",
            "WARNING",
        )
        return LibraryPollerConfig()


def _get_disabled_sites(config_store: ConfigStore) -> set[str]:
    """Return normalized lowercase site identifiers currently disabled in ConfigStore."""
    raw = config_store.get("email.disabled_sites")
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {str(item).strip().lower() for item in raw if str(item).strip()}


def _is_site_disabled(
    site: str,
    disabled_sites: set[str],
    url_parsers: Mapping[str, tuple[object, str]],
) -> bool:
    """Return True if `site` (or its resolved domain) is in `disabled_sites`."""
    if not disabled_sites:
        return False
    site_key = site.strip().lower()
    domain = resolve_site_domain(site_key, url_parsers)

    for raw_entry in disabled_sites:
        entry = raw_entry.strip().lower()
        if not entry:
            continue
        cleaned = (
            entry.removeprefix("https://")
            .removeprefix("http://")
            .split("/", 1)[0]
            .removeprefix("www.")
        )
        if site_key in (entry, cleaned) or domain in (entry, cleaned):
            return True
        if "." in cleaned:
            derived_id = url_patterns.generate_site_identifier(cleaned, cleaned)
            if derived_id == site_key:
                return True
            if url_parsers:
                try:
                    parsed = regex_parsing.generate_FanficInfo_from_url(
                        f"https://{cleaned}/", dict(url_parsers)
                    )
                    if (
                        parsed.site != "other"
                        and parsed.site.strip().lower() == site_key
                    ):
                        return True
                except Exception:
                    pass
    return False


class LibraryPoller:
    """Coordinates periodic Calibre library syncs and polite per-site probe dispatch."""

    def __init__(
        self,
        calibre_client: CalibreClient,
        poller_store: PollerStore,
        ingress_queue: IngressQueue,
        active_urls: ActiveUrlsDict,
        config_store: ConfigStore,
        coordinator_status: MutableMapping[str, object],
        active_polls: MutableMapping[str, object],
        poller_last_sync: MutableMapping[str, str],
        sync_poller_event: SyncPollerEvent,
        url_parsers: Mapping[str, tuple[object, str]] = _EMPTY_PARSERS,
        rng: random.Random | None = None,
    ) -> None:
        self.calibre_client = calibre_client
        self.poller_store = poller_store
        self.ingress_queue = ingress_queue
        self.active_urls = active_urls
        self.config_store = config_store
        self.coordinator_status = coordinator_status
        self.active_polls = active_polls
        self.poller_last_sync = poller_last_sync
        self.sync_poller_event = sync_poller_event
        self.url_parsers = url_parsers
        self._rng = rng if rng is not None else random.Random()

    def _sync_due(
        self, site: str, now_utc: datetime, sync_interval_seconds: float
    ) -> bool:
        """Return True if `site` has never synced or its sync interval has elapsed."""
        last_sync_raw = self.poller_last_sync.get(site)
        if not isinstance(last_sync_raw, str) or not last_sync_raw:
            return True
        try:
            last_sync_dt = _to_utc(datetime.fromisoformat(last_sync_raw))
        except ValueError:
            return True
        return (now_utc - last_sync_dt).total_seconds() >= sync_interval_seconds

    def _is_site_busy_in_coordinator(self, site: str) -> bool:
        """Return True if Coordinator currently holds a lock or backlog for `site`."""
        try:
            assignments = self.coordinator_status.get("assignments")
            if isinstance(assignments, Mapping) and site in assignments:
                return True

            site_locks = self.coordinator_status.get("site_locks")
            if isinstance(site_locks, (Mapping, set, list, tuple)) and (
                site in site_locks
            ):
                return True

            backlog = self.coordinator_status.get("backlog")
            if isinstance(backlog, Mapping) and bool(backlog.get(site)):
                return True
        except Exception as exc:
            ff_logging.log_debug(
                f"LibraryPoller: Error reading coordinator_status for '{site}': {exc}"
            )
            return True
        return False

    def _normalize_story_url(self, url: str) -> str:
        """Normalize a Calibre story URL to the canonical FanficInfo format."""
        if not self.url_parsers:
            return url
        try:
            parsed = regex_parsing.generate_FanficInfo_from_url(
                url, dict(self.url_parsers)
            )
            if parsed.url:
                return parsed.url
        except Exception as exc:
            ff_logging.log_debug(
                f"LibraryPoller: Failed to normalize URL '{url}': {exc}"
            )
        return url

    def _is_story_active(self, url: str) -> bool:
        """Return True if `url` (across scheme/canonical/base variants) is active."""
        if is_url_active(self.active_urls, url):
            return True

        stripped = url.removeprefix("https://").removeprefix("http://")
        for candidate in (stripped, f"https://{stripped}", f"http://{stripped}"):
            if candidate != url and is_url_active(self.active_urls, candidate):
                return True

        canonical = self._normalize_story_url(url)
        if canonical != url:
            if is_url_active(self.active_urls, canonical):
                return True
            canonical_stripped = canonical.removeprefix("https://").removeprefix(
                "http://"
            )
            if canonical_stripped != canonical and is_url_active(
                self.active_urls, canonical_stripped
            ):
                return True

        try:
            active_items = list(self.active_urls.items())
        except Exception:
            return False

        target_stripped = stripped.lower()
        target_canonical_stripped = (
            canonical.removeprefix("https://").removeprefix("http://").lower()
        )
        target_base: str | None = None

        for active_key, meta in active_items:
            if isinstance(meta, Mapping) and meta.get("status") == "cancelled":
                continue
            active_stripped = (
                active_key.removeprefix("https://").removeprefix("http://").lower()
            )
            if active_stripped in (target_stripped, target_canonical_stripped):
                return True
            if target_base is None:
                target_base = extract_story_base_url(url).lower()
            if (
                target_base
                and extract_story_base_url(active_key).lower() == target_base
            ):
                return True

        return False

    def _evict_stale_active_poll(self, site: str, now_utc: datetime) -> bool:
        """Evict a stale active_polls entry older than 15 minutes when coordinator is idle."""
        entry = self.active_polls.get(site)
        if not isinstance(entry, Mapping):
            return False
        started_raw = entry.get("started_at")
        if not isinstance(started_raw, str) or not started_raw:
            return False
        try:
            started_dt = _to_utc(datetime.fromisoformat(started_raw))
        except ValueError:
            return False
        age_seconds = (now_utc - started_dt).total_seconds()
        if age_seconds > _ACTIVE_POLL_STALE_SECONDS:
            self.active_polls.pop(site, None)
            ff_logging.log(
                f"LibraryPoller: Evicted stale active_polls entry for '{site}' "
                f"(age={age_seconds:.0f}s > {_ACTIVE_POLL_STALE_SECONDS:.0f}s while coordinator idle)",
                "WARNING",
            )
            return True
        return False

    def sync_site(
        self,
        site: str,
        site_cfg: SitePollerConfig,
        now: datetime,
    ) -> dict[str, int] | None:
        """Sync tracked stories for `site` from Calibre into PollerStore.

        On any Calibre error, logs a WARNING and returns None without modifying
        existing `poll_tracked_stories` rows.
        """
        now_utc = _to_utc(now)
        domain = resolve_site_domain(site, self.url_parsers)
        include_tags = site_cfg.include_tags
        exclude_tags = site_cfg.exclude_tags
        if not site_cfg.calibre_search_override and (
            not include_tags or not exclude_tags
        ):
            detected_include, detected_exclude = resolve_status_tags_from_ini(
                personal_ini_path=self.config_store.get_resolved_personal_ini(),
                default_ini_path=self.config_store.get_resolved_default_ini() or None,
                site=domain,
            )
            if not include_tags:
                include_tags = detected_include
            if not exclude_tags:
                exclude_tags = detected_exclude
        query = build_site_poll_query(
            domain,
            include_tags,
            exclude_tags,
            site_cfg.calibre_search_override,
        )

        try:
            stories = self.calibre_client.list_stories_by_query(query)
        except Exception as exc:
            ff_logging.log(
                f"LibraryPoller: Calibre sync failed for '{site}': {exc}",
                "WARNING",
            )
            return None

        normalized_stories = [
            (
                replace(story, url=normalized_url)
                if (normalized_url := self._normalize_story_url(story.url)) != story.url
                else story
            )
            for story in stories
        ]

        summary = self.poller_store.sync_site_stories(
            site=site,
            stories=normalized_stories,
            initial_next_check_fn=lambda story: compute_initial_staggered_check(
                now_utc, story.last_update_date, site_cfg, self._rng
            ),
        )
        self.poller_last_sync[site] = now_utc.isoformat()
        ff_logging.log(
            f"LibraryPoller: Synced '{site}' from Calibre "
            f"(matched={len(normalized_stories)}, added={summary['added']}, "
            f"updated={summary['updated']}, deactivated={summary['deactivated']})"
        )
        return summary

    def tick(self, now: datetime | None = None) -> list[FanficInfo]:
        """Execute one scheduler tick: reload config, sync if due, and dispatch probes."""
        now_utc = _to_utc(now if now is not None else datetime.now(timezone.utc))
        poller_cfg = load_poller_config(self.config_store)
        if not poller_cfg.enabled:
            if self.sync_poller_event.is_set():
                self.sync_poller_event.clear()
            return []

        force_sync = self.sync_poller_event.is_set()
        if force_sync:
            self.sync_poller_event.clear()

        disabled_sites = _get_disabled_sites(self.config_store)
        sync_interval_seconds = poller_cfg.library_sync_interval_hours * 3600.0
        dispatched: list[FanficInfo] = []

        for site, site_cfg in poller_cfg.sites.items():
            if not site_cfg.enabled:
                continue
            if _is_site_disabled(site, disabled_sites, self.url_parsers):
                continue

            if force_sync or self._sync_due(site, now_utc, sync_interval_seconds):
                self.sync_site(site, site_cfg, now_utc)

            if self._is_site_busy_in_coordinator(site):
                continue

            if site in self.active_polls:
                if not self._evict_stale_active_poll(site, now_utc):
                    continue

            checks_24h = self.poller_store.get_checks_in_window(
                site, now_utc - timedelta(hours=24)
            )
            if checks_24h >= site_cfg.max_checks_per_day:
                continue

            last_check = self.poller_store.get_last_site_check(site)
            if (
                last_check is not None
                and (now_utc - _to_utc(last_check)).total_seconds()
                < site_cfg.min_interval_minutes * 60.0
            ):
                continue

            due_stories = self.poller_store.get_due_stories(site, now_utc)
            eligible = [
                story for story in due_stories if not self._is_story_active(story.url)
            ]
            candidate = select_next_candidate(eligible, now_utc, site_cfg)
            if candidate is None:
                continue

            task = FanficInfo(
                url=candidate.url,
                site=site,
                calibre_id=candidate.calibre_id,
                title=candidate.title,
                behavior="poll_check",
                source="poller",
            )
            self.active_polls[site] = {
                "url": candidate.url,
                "title": candidate.title,
                "started_at": now_utc.isoformat(),
            }
            try:
                self.ingress_queue.put(task)
            except Exception as exc:
                self.active_polls.pop(site, None)
                ff_logging.log_failure(
                    f"LibraryPoller: Failed to enqueue poll_check for ({site}) {candidate.url}: {exc}"
                )
                continue

            dispatched.append(task)
            ff_logging.log(
                f"LibraryPoller: Dispatched poll_check for ({site}) "
                f"{candidate.title or candidate.url}"
            )

        return dispatched


def run_library_poller(
    ingress_queue: IngressQueue,
    active_urls: ActiveUrlsDict,
    config_store: ConfigStore,
    shutdown_event: ShutdownEvent,
    coordinator_status: MutableMapping[str, object],
    active_polls: MutableMapping[str, object],
    poller_last_sync: MutableMapping[str, str],
    sync_poller_event: SyncPollerEvent,
    calibre_client: CalibreClient | None,
    poller_store: PollerStore | None,
    url_parsers: Mapping[str, tuple[object, str]],
    verbose: bool = False,
) -> None:
    """Supervisor thread entry point for the adaptive library update poller."""
    ff_logging.set_verbose(verbose)
    ff_logging.log_debug("LibraryPoller thread started")

    if calibre_client is None or poller_store is None:
        ff_logging.log_debug(
            "LibraryPoller: Running in standby (calibre_client or poller_store not provided)"
        )
        while not shutdown_event.is_set():
            shutdown_event.wait(timeout=1.0)
        ff_logging.log_debug("LibraryPoller thread stopped")
        return

    poller = LibraryPoller(
        calibre_client=calibre_client,
        poller_store=poller_store,
        ingress_queue=ingress_queue,
        active_urls=active_urls,
        config_store=config_store,
        coordinator_status=coordinator_status,
        active_polls=active_polls,
        poller_last_sync=poller_last_sync,
        sync_poller_event=sync_poller_event,
        url_parsers=url_parsers,
    )

    while not shutdown_event.is_set():
        try:
            poller.tick()
        except Exception as exc:
            ff_logging.log_failure(f"LibraryPoller: Error during tick: {exc}")

        tick_interval = max(0.1, load_poller_config(config_store).tick_interval_seconds)
        remaining = tick_interval
        while remaining > 0.0 and not shutdown_event.is_set():
            if sync_poller_event.is_set():
                break
            step = min(1.0, remaining)
            if shutdown_event.wait(timeout=step):
                break
            remaining -= step

    ff_logging.log_debug("LibraryPoller thread stopped")
