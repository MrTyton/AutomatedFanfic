"""Diagnostic services for external services, anti-bot solver, story autopsy, and dry-runs."""

from pathlib import Path
import re
import time
from typing import Any

from config.ini_resolver import resolve_ini_path
from config.store import ConfigStore
import ff_logging
from models.fanfic_info import FanficInfo
from services import email_client
from web.services.calibre_lookup import get_calibre_metadata

lazy import antibot as anubis_solver
lazy from antibot import flaresolverr as flaresolverr_utils
lazy from fanficfare import adapters as fff_adapters, configurable, geturls
lazy from notifications.apprise_notification import AppriseNotification
lazy from parsers import regex_parsing, url_patterns as auto_url_parsers
lazy from workers import fff_runner


async def check_antibot_status(state: Any) -> dict[str, object]:
    """Test FlareSolverr connectivity and local Anubis Argon2id solver readiness."""
    flaresolverr_endpoint = None
    raw_personal = None
    if getattr(state, "config", None) and getattr(state.config, "calibre", None):
        raw_personal = state.config.calibre.personal_ini
    elif getattr(state, "config_store", None):
        raw_personal = state.config_store.get_resolved_personal_ini()

    personal_path = (
        resolve_ini_path(raw_personal, "personal.ini") if raw_personal else ""
    )
    if personal_path and Path(personal_path).is_file():
        try:
            content = Path(personal_path).read_text(encoding="utf-8")
            m = re.search(
                r"^\s*flaresolverr_proxy\s*[:=]\s*(.+)$", content, re.MULTILINE
            )
            if m:
                flaresolverr_endpoint = m.group(1).strip()
            else:
                fs_cfgs = flaresolverr_utils.get_flaresolverr_configs(personal_path)
                if fs_cfgs:
                    flaresolverr_endpoint = fs_cfgs[0].endpoint
        except Exception:
            pass

    if flaresolverr_endpoint:
        flare_res = flaresolverr_utils.probe_flaresolverr_health(flaresolverr_endpoint)
    else:
        flare_res = {
            "configured": False,
            "endpoint": None,
            "reachable": False,
            "latency_ms": None,
            "error": "flaresolverr_proxy not configured in personal.ini",
        }

    t0 = time.perf_counter()
    try:
        anubis_solver.solve_pow(
            b"diagnostic_synthetic_test_anubis", difficulty=1, use_le=False
        )
        bench_ms = round((time.perf_counter() - t0) * 1000, 2)
        anubis_res = {
            "ready": True,
            "benchmark_ms": bench_ms,
            "error": None,
        }
    except Exception as exc:
        anubis_res = {
            "ready": False,
            "benchmark_ms": None,
            "error": str(exc),
        }

    return {
        "flaresolverr": flare_res,
        "anubis": anubis_res,
    }


async def build_story_diagnostics(
    state: Any, client: Any, url: str
) -> dict[str, object]:
    """Retrieve full autopsy diagnostics for a story URL."""
    norm_url = url.strip()

    active_state: dict[str, object] | None = None
    if state.active_urls is not None:
        raw_active = state.active_urls.get(norm_url)
        if raw_active is not None:
            if isinstance(raw_active, dict):
                active_state = dict(raw_active)
            elif isinstance(raw_active, FanficInfo):
                active_state = {
                    "url": raw_active.url,
                    "site": raw_active.site,
                    "status": getattr(raw_active, "last_status", None) or "active",
                    "calibre_id": raw_active.calibre_id,
                    "repeats": raw_active.repeats,
                    "behavior": raw_active.behavior,
                    "title": raw_active.title,
                }
            elif hasattr(raw_active, "to_dict"):
                active_state = raw_active.to_dict()
            else:
                active_state = {
                    "status": getattr(raw_active, "status", str(raw_active))
                }

    history: dict[str, object] | None = None
    latest_download: dict[str, object] | None = None
    retry_attempts: list[dict[str, object]] = []

    if state.history_db is not None:
        try:
            latest_download = await state.history_db.get_latest_download(norm_url)
        except Exception:
            latest_download = None
        try:
            dl_id = latest_download.get("id") if latest_download else None
            retry_attempts = await state.history_db.get_retries_for_url(
                norm_url, download_event_id=dl_id
            )
        except Exception:
            retry_attempts = []

    if latest_download is not None or retry_attempts:
        history = {
            **(latest_download or {}),
            "latest_download": latest_download,
            "retry_attempts": retry_attempts or [],
        }

    calibre: dict[str, object] = {"in_library": False}
    calibre_meta: dict[str, object] | None = None
    if client is not None:
        book_id: str | int | None = None
        if hasattr(client, "search_by_url"):
            try:
                book_id = client.search_by_url(norm_url)
            except Exception:
                book_id = None
        elif hasattr(client, "get_story_id"):
            try:
                book_id = client.get_story_id(FanficInfo(url=norm_url, site="unknown"))
            except Exception:
                book_id = None

        if book_id is not None:
            calibre_meta = get_calibre_metadata(client, book_id, norm_url)
            if calibre_meta is not None:
                calibre = {
                    "in_library": True,
                    "id": book_id,
                    "book_id": book_id,
                    **calibre_meta,
                    "metadata": calibre_meta,
                }
                chapter_count = calibre_meta.get("chapters") or calibre_meta.get(
                    "#chapters"
                )
                if chapter_count is not None:
                    calibre.setdefault("chapter_count", chapter_count)
                calibre.setdefault("formats", calibre_meta.get("formats", []))
            else:
                calibre = {
                    "in_library": True,
                    "id": book_id,
                    "book_id": book_id,
                }

    candidate_titles: list[str] = []
    if active_state and active_state.get("title"):
        candidate_titles.append(str(active_state["title"]))
    if latest_download and latest_download.get("title"):
        candidate_titles.append(str(latest_download["title"]))
    if calibre_meta and calibre_meta.get("title"):
        candidate_titles.append(str(calibre_meta["title"]))

    recent_logs: list[dict[str, object]] = []
    try:
        raw_logs = ff_logging.get_recent_logs(limit=2000)
        for entry in raw_logs:
            msg = str(entry.get("message", ""))
            matched = norm_url in msg
            if not matched and candidate_titles:
                for t in candidate_titles:
                    if t and t in msg:
                        matched = True
                        break
            if matched:
                recent_logs.append(entry)
    except Exception:
        recent_logs = []

    return {
        "url": norm_url,
        "active_state": active_state,
        "history": history,
        "calibre": calibre,
        "recent_logs": recent_logs,
    }


def resolve_config_for_url(state: Any, url: str) -> dict[str, object]:
    """Extract FanFicFare adapter, configuration directives, and Calibre strategy for a URL."""
    clean_url = url.strip()
    config_store = getattr(state, "config_store", None)
    if config_store is not None:
        fff_conf = config_store.get_fff_configuration(clean_url)
    else:
        try:
            sections = fff_adapters.getConfigSectionsFor(clean_url)
        except Exception:
            sections = ["defaults"]
        fff_conf = configurable.Configuration(sections, "EPUB")

    adapter_name = "unknown"
    sections_list: list[str] = []
    options: dict[str, object] = {
        "is_adult": None,
        "cookiejar": None,
        "user_agent": None,
    }

    try:
        sections_list = fff_adapters.getConfigSectionsFor(clean_url)
    except Exception:
        sections_list = []

    try:
        adapter = fff_adapters.getAdapter(fff_conf, clean_url)
        adapter_name = adapter.__class__.__name__
        if hasattr(adapter, "getConfig"):
            options["is_adult"] = adapter.getConfig("is_adult")
            options["cookiejar"] = adapter.getConfig("cookiejar")
            options["user_agent"] = adapter.getConfig("user_agent")
    except Exception as exc:
        adapter_name = f"Error: {exc}"

    calibre_cfg = (
        getattr(state.config, "calibre", None)
        if getattr(state, "config", None)
        else None
    )
    calibre_strategy = {
        "metadata_preservation_mode": getattr(
            calibre_cfg, "metadata_preservation_mode", "preserve_metadata"
        ),
        "update_method": getattr(calibre_cfg, "update_method", "update"),
        "location": getattr(calibre_cfg, "path", ""),
    }

    return {
        "url": clean_url,
        "adapter": adapter_name,
        "sections": sections_list,
        "options": options,
        "calibre_strategy": calibre_strategy,
    }


def run_service_diagnostics(
    state: Any, calibre_client: Any, service: str
) -> dict[str, object]:
    """Run connectivity/health diagnostics for an external service."""
    norm_service = service.strip().lower()

    if norm_service == "calibre":
        if calibre_client is None:
            return {
                "service": "calibre",
                "status": "error",
                "message": "Calibre is not configured or client unavailable",
                "details": None,
            }
        try:
            version = (
                calibre_client.get_version()
                if hasattr(calibre_client, "get_version")
                else "unknown"
            )
            loc = (
                getattr(getattr(state.config, "calibre", None), "path", "")
                if getattr(state, "config", None)
                else ""
            )
            return {
                "service": "calibre",
                "status": "ok",
                "message": "Calibre connection successful",
                "details": {"version": version, "location": loc},
            }
        except Exception as exc:
            return {
                "service": "calibre",
                "status": "error",
                "message": str(exc),
                "details": None,
            }

    if norm_service == "email":
        email_cfg = (
            getattr(state.config, "email", None)
            if getattr(state, "config", None)
            else None
        )
        if email_cfg is None or not getattr(email_cfg, "server", ""):
            return {
                "service": "email",
                "status": "error",
                "message": "Email is not configured",
                "details": None,
            }
        try:
            email_user = getattr(email_cfg, "email", "") or getattr(
                email_cfg, "user", ""
            )
            mailbox = getattr(email_cfg, "mailbox", "INBOX") or "INBOX"
            details = email_client.probe_imap_connection(
                email_cfg.server,
                email_user,
                email_cfg.password,
                mailbox=mailbox,
                timeout=5,
            )
            return {
                "service": "email",
                "status": "ok",
                "message": "IMAP connection successful",
                "details": details,
            }
        except Exception as exc:
            return {
                "service": "email",
                "status": "error",
                "message": str(exc),
                "details": {"server": getattr(email_cfg, "server", None)},
            }

    if norm_service == "notifications":
        apprise_cfg = (
            getattr(state.config, "apprise", None)
            if getattr(state, "config", None)
            else None
        )
        urls = getattr(apprise_cfg, "urls", []) or []
        if not urls:
            return {
                "service": "notifications",
                "status": "error",
                "message": "No notification URLs configured",
                "details": None,
            }
        try:
            config_store = getattr(state, "config_store", None)
            if config_store is None:
                config_store = ConfigStore()
                config_store.initialize_from_config(state.config)
            notifier = AppriseNotification(state.config, config_store)
            ok = notifier.send_notification(
                "AutomatedFanfic Test", "Notification diagnostic test message"
            )
            if ok:
                return {
                    "service": "notifications",
                    "status": "ok",
                    "message": "Notification dispatched successfully",
                    "details": {"targets": len(notifier.apprise_urls)},
                }
            return {
                "service": "notifications",
                "status": "error",
                "message": "Notification delivery returned failure",
                "details": {"targets": len(notifier.apprise_urls)},
            }
        except Exception as exc:
            return {
                "service": "notifications",
                "status": "error",
                "message": str(exc),
                "details": None,
            }

    if norm_service == "fanficfare":
        try:
            ver = fff_runner.get_fanficfare_version()
            return {
                "service": "fanficfare",
                "status": "ok",
                "message": "FanFicFare is installed and accessible",
                "details": {"version": ver},
            }
        except Exception as exc:
            return {
                "service": "fanficfare",
                "status": "error",
                "message": str(exc),
                "details": None,
            }

    return {
        "service": service,
        "status": "error",
        "message": f"Unknown diagnostic service: {service}",
        "details": None,
    }


def run_dry_run_extraction(state: Any, url: str) -> dict[str, object]:
    """Run FanFicFare metadata extraction without downloading chapters."""
    config_store = getattr(state, "config_store", None)
    if config_store is not None:
        fff_conf = config_store.get_fff_configuration(url)
    else:
        try:
            sections = fff_adapters.getConfigSectionsFor(url)
        except Exception:
            sections = ["defaults"]
        fff_conf = configurable.Configuration(sections, "EPUB")

    def _extract():
        adapter = fff_adapters.getAdapter(fff_conf, url)
        story = (
            adapter.getStoryMetadataOnly()
            if hasattr(adapter, "getStoryMetadataOnly")
            else None
        )
        title = None
        author = None
        if hasattr(adapter, "getMetadata"):
            title = adapter.getMetadata("title")
            author = adapter.getMetadata("author")
        if not title and story and hasattr(story, "getMetadata"):
            title = story.getMetadata("title")
            author = story.getMetadata("author")

        num_chapters = 0
        if hasattr(adapter, "num_chapters"):
            num_chapters = adapter.num_chapters()
        elif hasattr(adapter, "get_chapters"):
            num_chapters = len(adapter.get_chapters())

        site = (
            adapter.getSiteDomain()
            if hasattr(adapter, "getSiteDomain")
            else getattr(adapter, "site", "unknown")
        )

        return {
            "url": url,
            "site": site,
            "title": title,
            "author": author,
            "chapters": num_chapters,
            "status": "ok",
            "metadata": {
                "title": title,
                "author": author,
                "chapters": num_chapters,
                "site": site,
            },
        }

    try:
        return _extract()
    except Exception as exc:
        if flaresolverr_utils.is_flaresolverr_crash(exc):
            personal_path = ""
            if getattr(state, "config", None) and getattr(
                state.config, "calibre", None
            ):
                personal_path = state.config.calibre.personal_ini
            elif getattr(state, "config_store", None):
                personal_path = state.config_store.get_resolved_personal_ini()
            recovered = flaresolverr_utils.recover_flaresolverr_crashes(
                target_site=url,
                personal_ini_path=personal_path,
            )
            if recovered > 0:
                try:
                    return _extract()
                except Exception as retry_exc:
                    return {
                        "url": url,
                        "status": "error",
                        "error": str(retry_exc),
                    }
        return {
            "url": url,
            "status": "error",
            "error": str(exc),
        }


def simulate_email_parse(subject: str, body: str) -> dict[str, object]:
    """Simulate URL extraction against sample email text."""
    text = f"{subject}\n{body}"
    gu = geturls.GetURLs()
    raw_urls = gu.get_urls_from_text(text) or []
    for m in re.finditer(r"https?://[^\s<>\"']+", text):
        cleaned = m.group(0).rstrip(".,;!?:")
        if cleaned not in raw_urls:
            raw_urls.append(cleaned)

    url_parsers = auto_url_parsers.generate_url_parsers_from_fanficfare()
    matches: list[dict[str, str]] = []
    seen: set[str] = set()

    for u in raw_urls:
        if u in seen:
            continue
        seen.add(u)
        try:
            fic = regex_parsing.generate_FanficInfo_from_url(u, url_parsers)
            matches.append({"url": fic.url, "site": fic.site})
        except Exception:
            matches.append({"url": u, "site": "unknown"})

    return {
        "count": len(matches),
        "matches": matches,
        "urls": [m["url"] for m in matches],
    }
