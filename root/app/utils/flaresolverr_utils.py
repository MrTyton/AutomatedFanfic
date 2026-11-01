"""FlareSolverr anti-bot crash detection and session recovery utilities.

When FlareSolverr's underlying Chromium instance experiences an unexpected tab
or page crash, FlareSolverr retains the dead session in memory and fails all subsequent
requests with 'HTTP Error 500: Error solving the challenge. Message: tab crashed'.

This module provides detection for tab crash conditions, parses FlareSolverr proxy
configurations from personal.ini, and orchestrates 'sessions.destroy' commands
so that clean sessions can be re-established automatically.
"""

from dataclasses import dataclass
from pathlib import Path
import configparser
import json
import urllib.error
import urllib.parse
import urllib.request

from utils import ff_logging
from utils.system_utils import resolve_ini_path

CRASH_INDICATORS: tuple[str, ...] = (
    "tab crashed",
    "target window already detached",
    "detachfromtarget",
    "page crash",
    "session deleted because of page crash",
)


@dataclass(frozen=True)
class FlareSolverrEndpointConfig:
    """Discovered FlareSolverr configuration for a specific INI section."""

    endpoint: str
    section: str
    session: str | None


def is_flaresolverr_crash(error: str | BaseException | None) -> bool:
    """Return True if the error indicates a FlareSolverr browser tab crash or detachment."""
    if error is None:
        return False
    msg = str(error).lower()
    return any(indicator in msg for indicator in CRASH_INDICATORS)


def _normalize_endpoint(raw: str) -> str:
    """Normalize raw FlareSolverr URL ensuring scheme and /v1 suffix."""
    url = raw.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"http://{url}"
    if not url.endswith("/v1"):
        url = f"{url.rstrip('/')}/v1"
    return url


def get_flaresolverr_configs(
    personal_ini_path: str | Path | None = None,
) -> list[FlareSolverrEndpointConfig]:
    """Parse personal.ini to discover all configured FlareSolverr endpoints and sessions."""
    resolved_path: Path | None = None
    if personal_ini_path:
        candidate = Path(personal_ini_path)
        if candidate.is_file():
            resolved_path = candidate

    if resolved_path is None:
        try:
            auto_path = resolve_ini_path("", "personal.ini")
            if auto_path and Path(auto_path).is_file():
                resolved_path = Path(auto_path)
        except Exception:
            pass

    if resolved_path is None or not resolved_path.is_file():
        return []

    parser = configparser.RawConfigParser(strict=False)
    try:
        parser.read(str(resolved_path), encoding="utf-8")
    except Exception as exc:
        ff_logging.log_debug(
            f"FlareSolverr: Failed to read INI file at {resolved_path}: {exc}"
        )
        return []

    configs: list[FlareSolverrEndpointConfig] = []
    sections = parser.sections()
    if parser.defaults():
        sections = ["defaults"] + [s for s in sections if s != "defaults"]

    for sec in sections:
        use_proxy = False
        if parser.has_option(sec, "use_flaresolverr_proxy"):
            try:
                use_proxy = parser.getboolean(sec, "use_flaresolverr_proxy")
            except Exception:
                use_proxy = False
        elif parser.has_option(sec, "flaresolverr_proxy") or parser.has_option(
            sec, "flaresolverr_proxy_address"
        ):
            use_proxy = True

        if not use_proxy:
            continue

        endpoint: str
        if parser.has_option(sec, "flaresolverr_proxy"):
            raw_proxy = parser.get(sec, "flaresolverr_proxy").strip()
            endpoint = _normalize_endpoint(raw_proxy)
        else:
            proto = (
                parser.get(sec, "flaresolverr_proxy_protocol", fallback="http").strip()
                or "http"
            )
            addr = (
                parser.get(
                    sec, "flaresolverr_proxy_address", fallback="localhost"
                ).strip()
                or "localhost"
            )
            port = (
                parser.get(sec, "flaresolverr_proxy_port", fallback="8191").strip()
                or "8191"
            )
            endpoint = _normalize_endpoint(f"{proto}://{addr}:{port}")

        session_id: str | None = None
        if parser.has_option(sec, "flaresolverr_session"):
            val = parser.get(sec, "flaresolverr_session").strip()
            if val:
                session_id = val
        elif parser.has_option(sec, "use_flaresolverr_session"):
            try:
                if parser.getboolean(sec, "use_flaresolverr_session"):
                    session_id = "FanFicFareSession"
            except Exception:
                pass

        configs.append(
            FlareSolverrEndpointConfig(
                endpoint=endpoint,
                section=sec,
                session=session_id,
            )
        )

    return configs


def list_flaresolverr_sessions(endpoint: str, timeout: float = 5.0) -> list[str]:
    """Query active session identifiers from a FlareSolverr v1 endpoint."""
    try:
        payload = json.dumps({"cmd": "sessions.list"}).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "AutomatedFanfic/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            sessions = data.get("sessions", [])
            return [str(s) for s in sessions]
    except Exception as exc:
        ff_logging.log_debug(
            f"FlareSolverr: Failed to query active sessions at {endpoint}: {exc}"
        )
        return []


def destroy_flaresolverr_session(
    endpoint: str, session: str, timeout: float = 5.0
) -> bool:
    """Send sessions.destroy for a given session identifier to FlareSolverr."""
    try:
        payload = json.dumps({"cmd": "sessions.destroy", "session": session}).encode(
            "utf-8"
        )
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "AutomatedFanfic/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            status = data.get("status")
            if status == "ok":
                ff_logging.log(
                    f"FlareSolverr: Successfully destroyed session '{session}' at {endpoint}"
                )
                return True
            else:
                msg = data.get("message", "")
                ff_logging.log_debug(
                    f"FlareSolverr: sessions.destroy returned '{status}': {msg}"
                )
                return False
    except Exception as exc:
        ff_logging.log_failure(
            f"FlareSolverr: Failed to destroy session '{session}' at {endpoint}: {exc}"
        )
        return False


def recover_flaresolverr_crashes(
    target_site: str | None = None,
    personal_ini_path: str | Path | None = None,
) -> int:
    """
    Recover from FlareSolverr tab crashes by destroying dead sessions.

    Discovers configured FlareSolverr endpoints from personal.ini.
    If target_site is specified (e.g., 'www.royalroad.com' or 'royalroad'),
    it finds and destroys matching session(s). If no specific target_site is
    specified or if matching active sessions are found, active sessions are cleaned up.

    Returns:
        int: Number of sessions successfully destroyed.
    """
    configs = get_flaresolverr_configs(personal_ini_path)
    if not configs:
        ff_logging.log_debug(
            "FlareSolverr: No FlareSolverr endpoints configured; skipping recovery."
        )
        return 0

    destroyed_count = 0
    endpoints = {c.endpoint for c in configs}

    normalized_target = target_site.strip().lower() if target_site else ""
    target_clean = normalized_target.replace(".", "_") if normalized_target else ""

    for ep in endpoints:
        active_sessions = list_flaresolverr_sessions(ep)
        sessions_to_destroy: set[str] = set()

        if target_clean:
            # 1. Match against active sessions
            for s in active_sessions:
                s_lower = s.lower()
                if (
                    target_clean in s_lower
                    or (normalized_target and normalized_target in s_lower)
                    or ("royalroad" in normalized_target and "royalroad" in s_lower)
                    or ("fanfiction" in normalized_target and "fanfiction" in s_lower)
                ):
                    sessions_to_destroy.add(s)

            # 2. Check personal.ini configs for this target site
            for c in configs:
                if c.endpoint == ep and c.session:
                    sec_clean = c.section.lower().replace(".", "_")
                    if target_clean in sec_clean or (
                        normalized_target and normalized_target in c.section.lower()
                    ):
                        sessions_to_destroy.add(c.session)
        else:
            # Destroy all active sessions if no target site specified
            sessions_to_destroy.update(active_sessions)
            if not sessions_to_destroy:
                for c in configs:
                    if c.endpoint == ep and c.session:
                        sessions_to_destroy.add(c.session)

        for session in sessions_to_destroy:
            if destroy_flaresolverr_session(ep, session):
                destroyed_count += 1

    return destroyed_count
