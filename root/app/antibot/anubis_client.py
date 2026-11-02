"""Anubis challenge detection, HTTP solving, and cookiejar session management."""

import json
import threading
import time
from typing import cast
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests

from antibot.anubis_pow import solve_pow, solve_sha256_pow
from fanficfare.fetchers.base_fetcher import LWPCookieJar
import ff_logging
from utils import url_utils

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_ANUBIS_AUTH_COOKIE_PREFIX = "techaro.lol-anubis-auth"
_anubis_protected_sites: set[str] = set()
_anubis_sites_lock = threading.Lock()


def mark_site_anubis_protected(site: str) -> None:
    """Record a site as using Anubis anti-bot protection."""
    if not site:
        return
    with _anubis_sites_lock:
        _anubis_protected_sites.add(site.lower())


def is_site_anubis_protected(site: str) -> bool:
    """Check if a site is known to use Anubis anti-bot protection."""
    if not site:
        return False
    with _anubis_sites_lock:
        return site.lower() in _anubis_protected_sites


def clear_anubis_protected_sites() -> None:
    """Reset known Anubis sites back to empty (used in testing)."""
    with _anubis_sites_lock:
        _anubis_protected_sites.clear()


def is_anubis_challenge(html: str) -> bool:
    """Return True if the HTML payload represents an Anubis anti-bot challenge page."""
    if not html:
        return False
    if "anubis_challenge" in html:
        return True
    if "making sure you're not a bot" in html.lower():
        return True
    return False


def _has_valid_anubis_cookie(jar: object) -> bool:
    """Check if the cookiejar contains an unexpired Anubis authentication cookie."""
    if jar is None:
        return False
    try:
        for cookie in cast(list[object], jar):
            name = getattr(cookie, "name", "")
            if _ANUBIS_AUTH_COOKIE_PREFIX in name:
                is_expired_fn = getattr(cookie, "is_expired", None)
                if callable(is_expired_fn):
                    if not is_expired_fn():
                        return True
                else:
                    return True
    except Exception:
        return False
    return False


def _create_lwp_cookiejar() -> LWPCookieJar:
    """Create a new LWPCookieJar compatible with FanFicFare's expectations."""

    jar = LWPCookieJar()
    setattr(jar, "autosave", False)
    jar.filename = None
    return jar


def solve_anubis_challenge(
    session: requests.Session,
    page_url: str,
    html: str,
    user_agent: str,
) -> bool:
    """Extract challenge parameters, fulfill extensions, compute PoW, and submit solution."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        challenge_tag = soup.find("script", id="anubis_challenge")
        if not challenge_tag or not challenge_tag.string:
            ff_logging.log_debug("Anubis challenge script tag missing or empty.")
            return False

        challenge_data = json.loads(challenge_tag.string)
        rules = challenge_data.get("rules", {})
        challenge = challenge_data.get("challenge", {})

        challenge_id = challenge.get("id")
        random_hex = challenge.get("randomData")
        if not challenge_id or not random_hex:
            ff_logging.log_debug("Anubis challenge payload missing id or randomData.")
            return False

        session.headers["User-Agent"] = user_agent

        page_url_str = str(page_url)
        parsed_url = urlparse(page_url_str)
        origin = f"{parsed_url.scheme}://{parsed_url.netloc}"

        # 1. Handle challenge extensions (e.g. css-load)
        extensions = rules.get("extensions") or []
        if "css-load" in extensions:
            css_url = (
                f"{origin}/.within.website/x/cmd/anubis/ext/css-load/{challenge_id}"
            )
            try:
                css_resp = session.get(css_url, timeout=10)
                ff_logging.log_debug(
                    f"Anubis css-load satisfied (HTTP {css_resp.status_code})"
                )
            except Exception as e:
                ff_logging.log_debug(f"Anubis css-load request failed: {e}")

        # 2. Compute proof-of-work based on challenge algorithm
        algorithm = str(rules.get("algorithm", "fast")).lower()
        difficulty = int(rules.get("difficulty", 4))

        t0 = time.time()
        if algorithm == "argon2id":
            data_bytes = bytes.fromhex(random_hex)
            use_le = data_bytes[-1] >= 128 if data_bytes else True
            nonce, found_hash_bytes = solve_pow(data_bytes, difficulty, use_le)
            found_hash = found_hash_bytes.hex()
        else:
            nonce, found_hash = solve_sha256_pow(random_hex, difficulty)
        elapsed_ms = int((time.time() - t0) * 1000)

        ff_logging.log(
            f"Anubis proof-of-work solved ({algorithm}, difficulty {difficulty}, nonce {nonce}, {elapsed_ms}ms)"
        )

        # 3. Submit solution to pass-challenge endpoint
        pass_url = f"{origin}/.within.website/x/cmd/anubis/api/pass-challenge"
        params = {
            "id": challenge_id,
            "response": found_hash,
            "nonce": str(nonce),
            "redir": page_url_str,
            "elapsedTime": str(elapsed_ms),
        }

        pass_resp = session.get(
            pass_url,
            params=params,
            headers={"Referer": page_url_str},
            allow_redirects=True,
            timeout=15,
        )
        history_list = getattr(pass_resp, "history", None)
        has_302_in_history = (
            any(getattr(r, "status_code", None) == 302 for r in history_list)
            if isinstance(history_list, list)
            else False
        )
        if (
            pass_resp.status_code in (200, 302)
            or has_302_in_history
            or _has_valid_anubis_cookie(session.cookies)
        ):
            ff_logging.log("Anubis authentication granted successfully.")
            return True

        ff_logging.log_failure(
            f"Anubis pass-challenge failed with HTTP {pass_resp.status_code}"
        )
        return False
    except Exception as e:
        ff_logging.log_failure(f"Error solving Anubis challenge: {e}")
        return False


def probe_and_solve_anubis(
    url: str,
    user_agent: str,
    cookiejar: LWPCookieJar | None,
) -> tuple[bool, LWPCookieJar]:
    """Probe URL to test if Anubis is blocking it, and solve the challenge if present."""

    target_jar: LWPCookieJar
    if cookiejar is not None and (
        isinstance(cookiejar, LWPCookieJar) or hasattr(cookiejar, "set_cookie")
    ):
        target_jar = cast(LWPCookieJar, cookiejar)
    else:
        target_jar = _create_lwp_cookiejar()

    if not url:
        return False, target_jar

    normalized_url = url_utils.normalize_url(url)
    if not normalized_url.startswith(("http://", "https://")):
        return False, target_jar

    session = requests.Session()
    session.headers["User-Agent"] = user_agent

    for cookie in target_jar:
        session.cookies.set_cookie(cookie)

    try:
        probe_resp = session.get(normalized_url, timeout=15)
        if is_anubis_challenge(probe_resp.text):
            resp_url = getattr(probe_resp, "url", None)
            final_url = (
                resp_url if isinstance(resp_url, str) and resp_url else normalized_url
            )
            ff_logging.log(
                f"Detected Anubis anti-bot challenge on {final_url}. Solving..."
            )
            solved = solve_anubis_challenge(
                session=session,
                page_url=final_url,
                html=probe_resp.text,
                user_agent=user_agent,
            )
            if solved:
                for c in session.cookies:
                    target_jar.set_cookie(c)
                return True, target_jar
            return False, target_jar
    except Exception as e:
        ff_logging.log_debug(f"Anubis probe exception for {normalized_url}: {e}")

    return False, target_jar


def ensure_anubis_session(
    site: str,
    url: str,
    user_agent: str,
    cookiejar: LWPCookieJar | None,
) -> LWPCookieJar:
    """Ensure the cookiejar contains an active Anubis session if site requires it."""

    target_jar: LWPCookieJar
    if cookiejar is not None and (
        isinstance(cookiejar, LWPCookieJar) or hasattr(cookiejar, "set_cookie")
    ):
        target_jar = cast(LWPCookieJar, cookiejar)
    else:
        target_jar = _create_lwp_cookiejar()

    if not is_site_anubis_protected(site):
        return target_jar

    if _has_valid_anubis_cookie(target_jar):
        return target_jar

    if not url:
        return target_jar

    normalized_url = url_utils.normalize_url(url)
    if not normalized_url.startswith(("http://", "https://")):
        return target_jar

    _, updated_jar = probe_and_solve_anubis(normalized_url, user_agent, target_jar)
    return updated_jar
