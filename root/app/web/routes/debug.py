"""Debug REST API routes for queues, coordinator locks, and filtered logs."""

import configparser
from http.cookiejar import LWPCookieJar, MozillaCookieJar
import imaplib
import multiprocessing
from pathlib import Path
from typing import Any
import re
import time
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

lazy from calibre_integration import (
    calibre_info,
    factory as calibre_factory,
)
from models.fanfic_info import FanficInfo
from utils import ff_logging
from utils.system_utils import resolve_ini_path
lazy from config.config_store import ConfigStore
lazy from fanficfare import adapters as fff_adapters, configurable, geturls
lazy from notifications.apprise_notification import AppriseNotification
lazy from parsers import auto_url_parsers, regex_parsing
lazy from utils import anubis_solver
lazy from workers import fff_runner

router = APIRouter(prefix="/api/debug", tags=["debug"])


class _LockFactory:
    """CalibreInfo-compatible lock provider without spawning a manager process."""

    @staticmethod
    def Lock():
        return multiprocessing.Lock()


def _get_calibre_client(request: Request) -> Any | None:
    """Obtain or instantiate CalibreClient if available."""
    client = getattr(request.app.state, "calibre_client", None)
    if client is not None:
        return client
    state = request.app.state.web_state
    if (
        state.config is None
        or getattr(state.config, "calibre", None) is None
        or not getattr(state.config.calibre, "location", None)
    ):
        return None
    try:
        cdb_info = calibre_info.CalibreInfo(state.config.calibre, _LockFactory())
        return calibre_factory.create_calibre_client(cdb_info, state.config_store)
    except Exception:
        return None


def _resolve_calibre_book_id(client: Any, query: str) -> str | int | None:
    """Resolve a query (ID, URL, or title) to a Calibre book ID."""
    q = query.strip()
    if not q:
        return None
    if q.isdigit():
        return int(q)
    if "://" in q or q.startswith(("http://", "https://")):
        if hasattr(client, "search_by_url"):
            try:
                res = client.search_by_url(q)
                if res:
                    return res
            except Exception:
                pass
        if hasattr(client, "get_story_id"):
            try:
                fanfic = FanficInfo(url=q, site="unknown")
                res = client.get_story_id(fanfic)
                if res:
                    return res
            except Exception:
                pass
        return None

    # Title substring search
    if hasattr(client, "search_by_title"):
        try:
            res = client.search_by_title(q)
            if res:
                return res
        except Exception:
            pass
    if hasattr(client, "search"):
        try:
            res = client.search(f'title:"{q}"')
            if res:
                return res[0] if isinstance(res, (list, tuple)) else res
        except Exception:
            pass
    if hasattr(client, "_execute_command_with_output"):
        try:
            out = client._execute_command_with_output(["search", f'title:"{q}"'])
            ids = [x.strip() for x in str(out).split(",") if x.strip()]
            if ids:
                return ids[0]
        except Exception:
            pass
    return None


def _get_calibre_metadata(
    client: Any, book_id: str | int, url: str
) -> dict[str, object] | None:
    """Fetch metadata for a given Calibre book ID."""
    if hasattr(client, "get_story_metadata"):
        try:
            lookup_id = int(book_id) if str(book_id).isdigit() else book_id
            meta = client.get_story_metadata(lookup_id)
            if meta:
                return dict(meta)
            return None
        except Exception:
            try:
                meta = client.get_story_metadata(str(book_id))
                if meta:
                    return dict(meta)
            except Exception:
                pass
            return None

    if hasattr(client, "get_metadata"):
        try:
            fanfic = FanficInfo(url=url, site="unknown", calibre_id=str(book_id))
            meta = client.get_metadata(fanfic)
            if meta:
                return dict(meta)
        except Exception:
            pass
    return None


def _matches_filter(pattern: str, text: str) -> bool:
    """Match text against pattern using regex, falling back to case-insensitive substring."""
    if not pattern:
        return True
    try:
        regex = re.compile(pattern, re.IGNORECASE)
        return bool(regex.search(text))
    except re.error:
        return pattern.lower() in text.lower()


@router.get("/queues/inspect")
async def inspect_queues(request: Request) -> dict[str, list[dict[str, object]]]:
    """Inspect and partition active URLs into queued, processing, and waiting lists."""
    state = request.app.state.web_state
    queued: list[dict[str, object]] = []
    processing: list[dict[str, object]] = []
    waiting: list[dict[str, object]] = []

    if state.active_urls is not None:
        try:
            for url, meta in list(state.active_urls.items()):
                if not isinstance(meta, dict):
                    continue
                item = {"url": url, **meta}
                status = meta.get("status")
                if status == "queued":
                    queued.append(item)
                elif status == "processing":
                    processing.append(item)
                elif status == "waiting":
                    waiting.append(item)
        except Exception:
            pass

    return {
        "queued": queued,
        "processing": processing,
        "waiting": waiting,
    }


@router.get("/coordinator")
async def get_coordinator(request: Request) -> dict[str, object]:
    """Return published coordinator status including domain assignments and backlogs."""
    state = request.app.state.web_state
    if state.coordinator_status is None:
        return {
            "assignments": {},
            "idle_workers": [],
            "dormant_workers": [],
            "backlog": {},
        }

    try:
        status = dict(state.coordinator_status)
    except Exception:
        status = {}

    status.setdefault("assignments", {})
    status.setdefault("idle_workers", [])
    status.setdefault("dormant_workers", [])
    status.setdefault("backlog", {})
    return status


@router.get("/logs")
async def get_logs(
    request: Request,
    level: str = Query(default="ALL"),
    component: str = Query(default=""),
    search: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, object]:
    """Query recent logs with level, component, and message search filtering."""
    req_level = level.strip().upper()
    raw_logs = ff_logging.get_recent_logs(limit=2000)

    filtered: list[dict[str, object]] = []
    for entry in raw_logs:
        entry_level = str(entry.get("level", "")).lower()
        if req_level and req_level != "ALL":
            if req_level in ("ERROR", "FAILURE"):
                if entry_level not in ("error", "failure"):
                    continue
            elif req_level == "DEBUG":
                if entry_level != "debug":
                    continue
            elif req_level == "INFO":
                if entry_level != "info":
                    continue
            elif req_level in ("WARNING", "WARN"):
                if entry_level not in ("warning", "warn"):
                    continue
            elif entry_level != req_level.lower():
                continue

        msg = str(entry.get("message", ""))
        if component:
            site = str(entry.get("thread_site") or "")
            if not (
                _matches_filter(component, msg) or _matches_filter(component, site)
            ):
                continue

        if search:
            if not _matches_filter(search, msg):
                continue

        filtered.append(entry)
        if len(filtered) >= limit:
            break

    return {"items": filtered, "count": len(filtered)}


@router.get("/story/diagnostics")
async def get_story_diagnostics(
    request: Request,
    url: str = Query(..., description="Fanfiction story URL"),
) -> dict[str, object]:
    """Retrieve full autopsy diagnostics for a story URL."""
    state = request.app.state.web_state
    norm_url = url.strip()

    # 1. Active state in memory
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

    # 2. History database
    history: dict[str, object] | None = None
    latest_download: dict[str, object] | None = None
    retry_attempts: list[dict[str, object]] = []

    if state.history_db is not None:
        try:
            latest_download = await state.history_db.get_latest_download(norm_url)
        except Exception:
            latest_download = None
        try:
            retry_attempts = await state.history_db.get_retries_for_url(norm_url)
        except Exception:
            retry_attempts = []

    if latest_download is not None or retry_attempts:
        history = {
            **(latest_download or {}),
            "latest_download": latest_download,
            "retry_attempts": retry_attempts or [],
        }

    # 3. Calibre library search & metadata
    calibre: dict[str, object] = {"in_library": False}
    calibre_meta: dict[str, object] | None = None
    client = _get_calibre_client(request)
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
            calibre_meta = _get_calibre_metadata(client, book_id, norm_url)
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

    # 4. Logs matching URL or candidate title
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


@router.get("/calibre/book")
async def get_calibre_book(
    request: Request,
    query: str = Query(..., description="Calibre ID, story URL, or title substring"),
) -> dict[str, object]:
    """Inspect full Calibre metadata for a book resolved by ID, URL, or title."""
    client = _get_calibre_client(request)
    if client is None:
        return {
            "found": False,
            "message": "Calibre is not configured or client unavailable",
        }

    q = query.strip()
    book_id = _resolve_calibre_book_id(client, q)
    if book_id is None:
        return {
            "found": False,
            "message": f"No Calibre book found matching query: {query}",
        }

    meta = _get_calibre_metadata(client, book_id, q if "://" in q else "")
    if meta is None:
        return {
            "found": False,
            "message": f"Book with ID {book_id} has no metadata in Calibre",
        }

    resolved_id = meta.get("id", book_id)
    if str(resolved_id).isdigit():
        resolved_id = int(str(resolved_id))

    custom_cols = {
        k: v for k, v in meta.items() if k.startswith("#") or k.startswith("*")
    }

    return {
        "found": True,
        "id": resolved_id,
        "title": meta.get("title"),
        "authors": meta.get("authors") or meta.get("author", []),
        "formats": meta.get("formats", []),
        "custom_columns": custom_cols,
        "identifiers": meta.get("identifiers", {}),
        "metadata": meta,
    }


class ResolveConfigRequest(BaseModel):
    """Request body for resolving configuration directives for a URL."""

    url: str


class DryRunRequest(BaseModel):
    """Request body for FanFicFare metadata-only dry-run."""

    url: str


class SimulateEmailRequest(BaseModel):
    """Request body for testing URL extraction against raw email subject and body."""

    subject: str
    body: str


def _mask_cookie_value(val: str | None) -> str:
    """Mask secret cookie value while preserving length cue."""
    if not val:
        return ""
    if len(val) > 8:
        return f"{val[:3]}...{val[-3:]}"
    return "********"


def _resolve_cookiejar_path(state: Any, domain: str) -> Path | None:
    """Locate configured or disk cookiejar for a domain."""
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
            parser = configparser.RawConfigParser(strict=False)
            parser.read(personal_path, encoding="utf-8")
            sections = [s for s in parser.sections() if domain.lower() in s.lower()]
            sections.append("defaults")
            for sec in sections:
                if parser.has_option(sec, "cookiejar"):
                    cj = parser.get(sec, "cookiejar").strip()
                    if cj:
                        candidate = Path(cj)
                        if not candidate.is_absolute():
                            candidate = Path(personal_path).parent / candidate
                        return candidate
        except Exception:
            pass

    for candidate in [
        Path(f"{domain}.cookies.txt"),
        Path(f"cookies/{domain}.txt"),
        Path(f"{domain}.txt"),
    ]:
        if candidate.is_file():
            return candidate

    return None


async def _check_flaresolverr_reachable(endpoint: str) -> dict[str, object]:
    """Test responsiveness of a FlareSolverr proxy endpoint."""
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(
            endpoint, headers={"User-Agent": "AutomatedFanfic/1.0"}
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            status = getattr(resp, "status", 200)
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            return {
                "configured": True,
                "endpoint": endpoint,
                "reachable": status < 500,
                "latency_ms": latency_ms,
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "configured": True,
            "endpoint": endpoint,
            "reachable": exc.code < 500,
            "latency_ms": latency_ms,
            "error": None if exc.code < 500 else str(exc),
        }
    except Exception as exc:
        return {
            "configured": True,
            "endpoint": endpoint,
            "reachable": False,
            "latency_ms": None,
            "error": str(exc),
        }


@router.get("/cookiejar/{domain}")
async def inspect_cookiejar(request: Request, domain: str) -> dict[str, object]:
    """Inspect cookies for domain without leaking secret tokens."""
    state = request.app.state.web_state
    norm_domain = domain.strip().lower()
    jar_path = _resolve_cookiejar_path(state, norm_domain)

    if jar_path is None or not jar_path.is_file():
        return {
            "domain": domain,
            "cookie_count": 0,
            "cookies": [],
            "file_path": None,
            "message": "No cookiejar found",
        }

    jar = LWPCookieJar(str(jar_path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        try:
            m_jar = MozillaCookieJar(str(jar_path))
            m_jar.load(ignore_discard=True, ignore_expires=True)
            jar = m_jar
        except Exception as exc:
            return {
                "domain": domain,
                "cookie_count": 0,
                "cookies": [],
                "file_path": str(jar_path),
                "message": f"Failed to parse cookiejar: {exc}",
            }

    cookies_list: list[dict[str, object]] = []
    for c in jar:
        cookies_list.append(
            {
                "name": c.name,
                "domain": c.domain,
                "path": c.path,
                "expires": c.expires,
                "secure": c.secure,
                "discard": c.discard,
                "value": _mask_cookie_value(c.value),
            }
        )

    return {
        "domain": domain,
        "cookie_count": len(cookies_list),
        "cookies": cookies_list,
        "file_path": str(jar_path),
        "message": "Cookiejar loaded successfully",
    }


@router.get("/antibot")
async def get_antibot_status(request: Request) -> dict[str, object]:
    """Test FlareSolverr connectivity and local Anubis Argon2id solver readiness."""
    state = request.app.state.web_state

    # 1. FlareSolverr
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
        except Exception:
            pass

    if flaresolverr_endpoint:
        flare_res = await _check_flaresolverr_reachable(flaresolverr_endpoint)
    else:
        flare_res = {
            "configured": False,
            "endpoint": None,
            "reachable": False,
            "latency_ms": None,
            "error": "flaresolverr_proxy not configured in personal.ini",
        }

    # 2. Anubis
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


@router.post("/resolve-config")
async def resolve_config(
    request: Request, body: ResolveConfigRequest
) -> dict[str, object]:
    """Extract FanFicFare adapter, configuration directives, and Calibre strategy for a URL."""
    state = request.app.state.web_state
    url = body.url.strip()

    config_store = getattr(state, "config_store", None)
    if config_store is not None:
        fff_conf = config_store.get_fff_configuration(url)
    else:
        try:
            sections = fff_adapters.getConfigSectionsFor(url)
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
        sections_list = fff_adapters.getConfigSectionsFor(url)
    except Exception:
        sections_list = []

    try:
        adapter = fff_adapters.getAdapter(fff_conf, url)
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
        "location": getattr(calibre_cfg, "location", ""),
    }

    return {
        "url": url,
        "adapter": adapter_name,
        "sections": sections_list,
        "options": options,
        "calibre_strategy": calibre_strategy,
    }


@router.post("/diagnostics/{service}")
async def run_diagnostics(request: Request, service: str) -> dict[str, object]:
    """Run connectivity/health diagnostics for an external service."""
    state = request.app.state.web_state
    norm_service = service.strip().lower()

    if norm_service == "calibre":
        client = _get_calibre_client(request)
        if client is None:
            return {
                "service": "calibre",
                "status": "error",
                "message": "Calibre is not configured or client unavailable",
                "details": None,
            }
        try:
            version = (
                client.get_version() if hasattr(client, "get_version") else "unknown"
            )
            loc = (
                getattr(getattr(state.config, "calibre", None), "location", "")
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
            client = imaplib.IMAP4_SSL(email_cfg.server, timeout=5)
            email_user = getattr(email_cfg, "email", "") or getattr(
                email_cfg, "user", ""
            )
            client.login(email_user, email_cfg.password)
            mailbox = getattr(email_cfg, "mailbox", "INBOX") or "INBOX"
            client.select(mailbox)
            _status, msgs = client.search(None, "UNSEEN")
            unread_count = len(msgs[0].split()) if msgs and msgs[0] else 0
            client.logout()
            return {
                "service": "email",
                "status": "ok",
                "message": "IMAP connection successful",
                "details": {
                    "server": email_cfg.server,
                    "mailbox": mailbox,
                    "unread_count": unread_count,
                },
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
                config_store = ConfigStore(state.config)
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

    raise HTTPException(
        status_code=400,
        detail=f"Unknown diagnostic service: {service}. Valid services: calibre, email, notifications, fanficfare",
    )


@router.post("/dry-run")
async def dry_run_fanfic(request: Request, body: DryRunRequest) -> dict[str, object]:
    """Run FanFicFare metadata extraction without downloading chapters."""
    state = request.app.state.web_state
    url = body.url.strip()

    config_store = getattr(state, "config_store", None)
    if config_store is not None:
        fff_conf = config_store.get_fff_configuration(url)
    else:
        try:
            sections = fff_adapters.getConfigSectionsFor(url)
        except Exception:
            sections = ["defaults"]
        fff_conf = configurable.Configuration(sections, "EPUB")

    try:
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
    except Exception as exc:
        return {
            "url": url,
            "status": "error",
            "error": str(exc),
        }


@router.post("/simulate-email")
async def simulate_email(
    request: Request, body: SimulateEmailRequest
) -> dict[str, object]:
    """Simulate URL extraction against sample email text."""
    text = f"{body.subject}\n{body.body}"
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
