"""Diagnostic services for external services, anti-bot solver, cookie jar, and dry-runs."""

import configparser
from http.cookiejar import LWPCookieJar, MozillaCookieJar
import imaplib
from pathlib import Path
import re
import time
from typing import Any
import urllib.error
import urllib.request

from config.store import ConfigStore
from utils.system_utils import resolve_ini_path

lazy from antibot import flaresolverr as flaresolverr_utils
lazy from fanficfare import adapters as fff_adapters, configurable, geturls
lazy from notifications.apprise_notification import AppriseNotification
lazy from parsers import regex_parsing, url_patterns as auto_url_parsers
lazy import antibot as anubis_solver
lazy from workers import fff_runner


def mask_cookie_value(val: str | None) -> str:
    """Mask secret cookie value while preserving length cue."""
    if not val:
        return ""
    if len(val) > 8:
        return f"{val[:3]}...{val[-3:]}"
    return "********"


def resolve_cookiejar_path(state: Any, domain: str) -> Path | None:
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


async def check_flaresolverr_reachable(endpoint: str) -> dict[str, object]:
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


def inspect_cookiejar_file(state: Any, domain: str) -> dict[str, object]:
    """Inspect cookies for domain without leaking secret tokens."""
    norm_domain = domain.strip().lower()
    jar_path = resolve_cookiejar_path(state, norm_domain)

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
                "value": mask_cookie_value(c.value),
            }
        )

    return {
        "domain": domain,
        "cookie_count": len(cookies_list),
        "cookies": cookies_list,
        "file_path": str(jar_path),
        "message": "Cookiejar loaded successfully",
    }


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

    import sys

    debug_mod = sys.modules.get("web.routes.debug")
    checker_fn = (
        getattr(
            debug_mod, "_check_flaresolverr_reachable", check_flaresolverr_reachable
        )
        if debug_mod
        else check_flaresolverr_reachable
    )

    if flaresolverr_endpoint:
        flare_res = await checker_fn(flaresolverr_endpoint)
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
        "location": getattr(calibre_cfg, "location", ""),
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
