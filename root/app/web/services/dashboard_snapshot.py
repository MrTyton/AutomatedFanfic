"""Dashboard snapshot building and caching service."""

from datetime import datetime, timezone
import time

from models import active_urls as active_urls_utils
import parsers
from web.dependencies import WebState

# TTL cache for expensive historical DB queries (recent_downloads, recent_activity)
_HISTORY_CACHE_TTL: float = 10.0

_history_cache: dict[str, object] = {
    "recent_downloads": [],
    "recent_activity": [],
    "site_statistics": {},
    "distinct_sites": [],
    "expires_at": 0.0,
}


def invalidate_history_cache() -> None:
    """Reset the historical database queries cache TTL so the next broadcast fetches fresh data."""
    _history_cache["expires_at"] = 0.0


async def build_snapshot(state: WebState) -> dict[str, object]:
    """Build a JSON-serialisable dashboard snapshot from WebState."""
    now_ts = time.time()
    cache = _history_cache
    snapshot: dict[str, object] = {"timestamp": now_ts}

    # ── Active downloads ────────────────────────────────────────
    url_metadata: dict[str, dict[str, object]] = {}  # url -> {site, title, ...}
    if state.active_urls is not None:
        try:
            for url, meta in state.active_urls.items():
                if isinstance(meta, dict):
                    url_metadata[url] = dict(meta)
                else:
                    url_metadata[url] = {}
        except Exception:
            pass

    urls = list(url_metadata.keys())

    # Split active URLs into truly-processing vs waiting-for-retry
    waiting_url_map: dict[str, dict] = {}  # url -> waiting row metadata
    if state.history_db is not None:
        try:
            for row in await state.history_db.get_waiting_urls():
                waiting_url_map[row["url"]] = row
        except Exception:
            pass

    active_urls_list: list[dict] = []
    queued_urls: list[dict] = []
    waiting_urls: list[dict] = []
    for u in urls:
        meta = url_metadata.get(u, {})
        if meta.get("status") == "cancelled":
            continue
        if u in waiting_url_map or meta.get("status") == "waiting":
            w_meta = waiting_url_map.get(u, {})
            sched_at = w_meta.get("scheduled_at")
            if not sched_at:
                wu = meta.get("wait_until")
                if isinstance(wu, (int, float)):
                    sched_at = datetime.fromtimestamp(wu, tz=timezone.utc).isoformat()
                elif isinstance(wu, str):
                    sched_at = wu
                else:
                    sched_at = w_meta.get("updated_at", "")
            att_num = meta.get("retry_count") or w_meta.get("attempt_number") or 1
            action_val = meta.get("action") or w_meta.get("action") or "RETRY"

            waiting_urls.append(
                {
                    "url": u,
                    "updated_at": w_meta.get("updated_at", ""),
                    "scheduled_at": sched_at,
                    "attempt_number": att_num,
                    "action": action_val,
                    "site": meta.get("site") or w_meta.get("site"),
                    "title": meta.get("title") or w_meta.get("title"),
                    "calibre_id": meta.get("calibre_id") or w_meta.get("calibre_id"),
                    "error_message": meta.get("error_message")
                    or w_meta.get("error_message"),
                    **meta,
                }
            )
        elif meta.get("status") == "processing":
            active_urls_list.append({"url": u, **meta})
        else:
            queued_urls.append({"url": u, **meta})

    active_urls_list.sort(
        key=lambda x: (float(x.get("queued_at") or 0.0), str(x.get("url") or ""))
    )
    queued_urls.sort(
        key=lambda x: (float(x.get("queued_at") or 0.0), str(x.get("url") or ""))
    )
    waiting_urls.sort(
        key=lambda x: (float(x.get("queued_at") or 0.0), str(x.get("url") or ""))
    )

    snapshot["active_downloads"] = {
        "items": active_urls_list,
        "count": len(active_urls_list),
    }
    snapshot["queued_downloads"] = {
        "items": queued_urls,
        "count": len(queued_urls),
    }
    snapshot["waiting_downloads"] = {
        "items": waiting_urls,
        "count": len(waiting_urls),
    }

    dismissed_urls = set(state.dismissed_error_urls)
    for u, meta in url_metadata.items():
        if meta.get("error_dismissed"):
            dismissed_urls.add(u)
    snapshot["dismissed_error_urls"] = sorted(dismissed_urls)

    # ── Queue depths ────────────────────────────────────────────
    snapshot["queues"] = active_urls_utils.get_queue_depths(
        state.ingress_queue, state.waiting_queue, state.worker_queues
    )

    # ── Process status ──────────────────────────────────────────
    if state.process_status_callable:
        try:
            raw = state.process_status_callable()
            snapshot["processes"] = {name: str(info) for name, info in raw.items()}
        except Exception:
            snapshot["processes"] = {}
    else:
        snapshot["processes"] = {}

    is_coord_paused = (
        bool(state.coordinator_status.get("paused", False))
        if state.coordinator_status
        else False
    )
    snapshot["coordinator_paused"] = is_coord_paused

    disabled_sites: list[str] = []
    if state.config_store is not None:
        ds = state.config_store.get("email.disabled_sites")
        if isinstance(ds, list):
            disabled_sites = [str(s) for s in ds]
    elif state.config is not None and getattr(state.config, "email", None) is not None:
        disabled_sites = list(state.config.email.disabled_sites)
    snapshot["disabled_sites"] = disabled_sites

    max_normal_retries = 11
    if state.config is not None and getattr(state.config, "retry", None) is not None:
        max_normal_retries = getattr(state.config.retry, "max_normal_retries", 11)
    snapshot["max_normal_retries"] = max_normal_retries

    calibre_server_url: str | None = None
    if state.config is not None and getattr(state.config, "calibre", None) is not None:
        c_path = getattr(state.config.calibre, "path", "")
        if isinstance(c_path, str) and c_path.startswith("http"):
            calibre_server_url = c_path
    snapshot["calibre_server_url"] = calibre_server_url

    daemon_processes = (
        dict(snapshot["processes"])
        if snapshot["processes"]
        else {
            "Coordinator": "paused" if is_coord_paused else "running",
            "EmailWatcher": "running",
            "FFWaiter": "running",
            "WorkerPool": "running",
            "WebServer": "running",
        }
    )
    snapshot["processes"] = daemon_processes

    daemon_roles = {
        "WebServer": "FastAPI Web Dashboard & REST/WebSocket server",
        "Coordinator": "Task scheduler with domain locking politeness policy",
        "EmailWatcher": "IMAP email poller for fanfiction update alerts",
        "UrlIngester": "IMAP email poller for fanfiction update alerts",
        "Waiter": "Exponential backoff retry queue scheduler",
        "FFWaiter": "Exponential backoff retry queue scheduler",
        "WorkerPool": "Site-specific download worker pool",
    }

    uptime_base = getattr(state, "_started_at", None)
    if not isinstance(uptime_base, (int, float)):
        uptime_base = now_ts
        setattr(state, "_started_at", uptime_base)

    daemon_details: dict[str, dict[str, object]] = {}
    for name, status in daemon_processes.items():
        st = "paused" if name == "Coordinator" and is_coord_paused else str(status)
        daemon_details[name] = {
            "name": name,
            "status": st,
            "pid": 0,
            "uptime_sec": max(1, int(now_ts - uptime_base)),
            "restarts": 0,
            "role": daemon_roles.get(name, "Background service daemon"),
        }
    snapshot["daemon_details"] = daemon_details

    # ── Recent history events & statistics (TTL-cached) ────────
    if state.history_db is not None:
        expires_at = cache.get("expires_at", 0.0)
        if isinstance(expires_at, (int, float)) and now_ts >= expires_at:
            try:
                cache["recent_downloads"] = await state.history_db.get_recent_downloads(
                    limit=20
                )
            except Exception:
                cache["recent_downloads"] = []
            try:
                cache["recent_activity"] = await state.history_db.get_recent_activity(
                    limit=20
                )
            except Exception:
                cache["recent_activity"] = []
            try:
                checks = await state.history_db.get_email_checks(limit=1)
                cache["last_email_check"] = checks[0] if checks else None
            except Exception:
                cache["last_email_check"] = None
            try:
                cache["site_statistics"] = await state.history_db.get_site_statistics()
            except Exception:
                cache["site_statistics"] = {}
            try:
                cache["distinct_sites"] = await state.history_db.get_distinct_sites()
            except Exception:
                cache["distinct_sites"] = []
            cache["expires_at"] = now_ts + _HISTORY_CACHE_TTL
        snapshot["recent_downloads"] = cache["recent_downloads"]
        snapshot["recent_activity"] = cache["recent_activity"]
        snapshot["last_email_check"] = cache.get("last_email_check")
    else:
        snapshot["recent_downloads"] = []
        snapshot["recent_activity"] = []
        snapshot["last_email_check"] = None

    # ── Site worker stats (determined algorithmically) ───────────
    adapter_catalog = parsers.get_supported_sites_catalog()
    seen_sites: dict[str, dict[str, str]] = dict(adapter_catalog)

    def _register_dynamic_site(raw_site: str | None) -> None:
        if not raw_site:
            return
        s_norm = str(raw_site).lower().strip()
        site_id = parsers.generate_site_identifier(s_norm, s_norm)
        if site_id not in seen_sites and s_norm not in seen_sites:
            domain = s_norm if "." in s_norm else f"{s_norm}.com"
            display_name = parsers.clean_display_name_from_domain(domain)
            seen_sites[site_id] = {
                "site": site_id,
                "domain": domain,
                "display_name": display_name,
            }

    for a in active_urls_list:
        _register_dynamic_site(a.get("site"))
    for q in queued_urls:
        _register_dynamic_site(q.get("site"))
    for w in waiting_urls:
        _register_dynamic_site(w.get("site"))
    for ds_site in disabled_sites:
        _register_dynamic_site(ds_site)

    history_sites = cache.get("distinct_sites", [])
    if isinstance(history_sites, list):
        for hs in history_sites:
            _register_dynamic_site(str(hs))

    disabled_set = {ds.lower() for ds in disabled_sites} | {
        parsers.generate_site_identifier(ds.lower(), ds.lower())
        for ds in disabled_sites
    }

    site_stats: dict[str, dict[str, int]] = {}
    raw_stats = cache.get("site_statistics")
    if isinstance(raw_stats, dict):
        site_stats = raw_stats

    catalog_sites: list[dict[str, object]] = []
    for site_key, site_info in seen_sites.items():
        if (
            not site_info.get("domain")
            or not site_key
            or site_info.get("display_name") == "Web ()"
        ):
            continue

        domain_lower = site_info["domain"].lower()
        clean_domain = domain_lower.removeprefix("www.")
        clean_site_key = site_key.removeprefix("www.")
        site_aliases = {site_key, domain_lower, clean_domain, clean_site_key}

        active_for_site = [
            a
            for a in active_urls_list
            if str(a.get("site", "")).lower().removeprefix("www.") in site_aliases
            or str(a.get("site", "")).lower() in site_aliases
        ]
        queued_for_site = [
            q
            for q in queued_urls
            if str(q.get("site", "")).lower().removeprefix("www.") in site_aliases
            or str(q.get("site", "")).lower() in site_aliases
        ]
        waiting_for_site = [
            w
            for w in waiting_urls
            if str(w.get("site", "")).lower().removeprefix("www.") in site_aliases
            or str(w.get("site", "")).lower() in site_aliases
        ]

        if (
            site_key in disabled_set
            or domain_lower in disabled_set
            or clean_domain in disabled_set
        ):
            status_str = "disabled"
        elif active_for_site:
            status_str = "downloading"
        elif queued_for_site:
            status_str = "queued"
        elif waiting_for_site:
            status_str = "backoff"
        else:
            status_str = "idle"

        active_fic = (
            active_for_site[0]
            if active_for_site
            else (queued_for_site[0] if queued_for_site else None)
        )
        waiting_fic = waiting_for_site[0] if waiting_for_site else None

        counts = (
            site_stats.get(site_key, {})
            or site_stats.get(domain_lower, {})
            or site_stats.get(clean_domain, {})
        )
        total_dl = counts.get("total", 0)
        failed_dl = counts.get("failed", 0)

        backoff_iso = None
        if waiting_fic:
            wu = waiting_fic.get("wait_until") or waiting_fic.get("scheduled_at")
            if isinstance(wu, (int, float)):
                backoff_iso = datetime.fromtimestamp(wu, tz=timezone.utc).isoformat()
            elif isinstance(wu, str):
                backoff_iso = wu

        catalog_sites.append(
            {
                "site": site_info["domain"],
                "site_id": site_key,
                "display_name": site_info["display_name"],
                "status": status_str,
                "queued_count": len(queued_for_site) + len(active_for_site),
                "total_downloads": total_dl,
                "failed_downloads": failed_dl,
                "active_url": (active_fic.get("url") if active_fic else None)
                or (waiting_fic.get("url") if waiting_fic else None),
                "active_title": (active_fic.get("title") if active_fic else None)
                or (waiting_fic.get("title") if waiting_fic else None),
                "backoff_until": backoff_iso,
                "attempt_number": (
                    waiting_fic.get("attempt_number") or waiting_fic.get("retry_count")
                    if waiting_fic
                    else None
                ),
            }
        )

    status_weights = {
        "downloading": 0,
        "queued": 1,
        "backoff": 2,
        "disabled": 3,
        "idle": 4,
    }
    catalog_sites.sort(
        key=lambda x: (
            status_weights.get(str(x.get("status", "idle")), 4),
            str(x.get("display_name", "")).lower(),
        )
    )
    notable_sites = [s for s in catalog_sites if s.get("status") != "idle"]

    overhead = 4 + (
        1 if getattr(getattr(state.config, "web", None), "enabled", False) else 0
    )
    config_workers = (
        getattr(state.config, "max_workers", 20) if state.config is not None else 20
    )
    fallback_threads = max(1, config_workers - overhead)
    actual_max_threads = (
        len(state.worker_queues)
        if state.worker_queues is not None and len(state.worker_queues) > 0
        else fallback_threads
    )
    snapshot["site_worker_stats"] = {
        "active_threads": len(active_urls_list),
        "max_threads": actual_max_threads,
        "notable_sites": notable_sites,
        "catalog_sites": catalog_sites,
    }

    return snapshot
