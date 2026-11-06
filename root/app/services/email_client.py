"""Email client and URL extraction for AutomatedFanfic."""

import hashlib
import logging
import os
import socket
import time
from collections.abc import Callable
from contextlib import contextmanager

from config import EmailConfig
from config.ini_resolver import read_ini_file_cached
from config.store import ConfigStore
import ff_logging
from models.queue_types import CheckEmailsEvent, ShutdownEvent

lazy from fanficfare import geturls
lazy import imapclient
lazy from antibot import flaresolverr
lazy from utils import system_utils


@contextmanager
def set_timeout(timeout_duration):
    """Temporarily set socket timeout for network operations."""
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout_duration)
    try:
        yield
    finally:
        socket.setdefaulttimeout(old_timeout)


class _GetUrlsLogCaptureHandler(logging.Handler):
    """Capture ERROR logs and Royal Road click-through diagnostics from fanficfare.geturls."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []
        self.saw_royalroad_clickthrough: bool = False
        self.royalroad_redirects: list[str] = []
        self.on_error_callbacks: list[Callable[[], None]] = []

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if record.levelno >= logging.ERROR:
            self.messages.append(msg)
            for callback in self.on_error_callbacks:
                callback()
        elif "Doing royalroad click through link workaround" in msg:
            self.saw_royalroad_clickthrough = True
        elif msg.startswith("Royalroad redirect to:"):
            self.royalroad_redirects.append(
                msg.removeprefix("Royalroad redirect to:").strip()
            )

    def reset(self) -> None:
        """Clear captured messages and Royal Road click-through state before a retry."""
        self.messages.clear()
        self.saw_royalroad_clickthrough = False
        self.royalroad_redirects.clear()


@contextmanager
def suppress_logging():
    """Suppress general logging output while capturing fanficfare.geturls errors and Royal Road diagnostics."""
    old_disable = logging.root.manager.disable
    old_root_level = logging.root.level
    geturls_logger = logging.getLogger("fanficfare.geturls")
    old_geturls_level = geturls_logger.level
    old_propagate = geturls_logger.propagate
    handler = _GetUrlsLogCaptureHandler()
    geturls_logger.addHandler(handler)
    geturls_logger.setLevel(logging.DEBUG)
    geturls_logger.propagate = False
    logging.disable(logging.NOTSET)
    logging.root.setLevel(logging.CRITICAL + 1)
    try:
        yield handler
    finally:
        logging.root.setLevel(old_root_level)
        logging.disable(old_disable)
        geturls_logger.removeHandler(handler)
        geturls_logger.setLevel(old_geturls_level)
        geturls_logger.propagate = old_propagate


class EmailInfo:
    """Email account configuration and URL extraction for fanfiction monitoring."""

    def __init__(
        self,
        email_config: EmailConfig,
        config_store: ConfigStore,
        *,
        lazy: bool = False,
    ) -> None:
        self.email = email_config.email
        self.password = email_config.password
        self.server = email_config.server
        self.mailbox = email_config.mailbox
        self.sleep_time = email_config.sleep_time
        self.disabled_sites = email_config.disabled_sites
        self.imap_idle = email_config.imap_idle

        self.config_store = config_store
        self._geturls = None
        self._geturls_ini_mtime = 0.0
        self._last_ini_hash = ""
        self._last_seen_unseen_uids: set[int] = set()
        if not lazy:
            self._build_geturls()

    @property
    def default_ini(self) -> str:
        """Resolved path to defaults.ini from ConfigStore."""
        return self.config_store.get_resolved_default_ini()

    @property
    def personal_ini(self) -> str:
        """Resolved path to personal.ini from ConfigStore."""
        return self.config_store.get_resolved_personal_ini()

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state.pop("_geturls", None)
        state.pop("_geturls_ini_mtime", None)
        state.pop("_last_ini_hash", None)
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        if not hasattr(self, "_last_seen_unseen_uids"):
            self._last_seen_unseen_uids = set()
        self._build_geturls()

    def update_from_config_store(self, config_store: ConfigStore) -> bool:
        """Sync email credentials from ConfigStore."""
        changed = False
        mapping = [
            ("email", "email.email"),
            ("password", "email.password"),
            ("server", "email.server"),
            ("mailbox", "email.mailbox"),
            ("imap_idle", "email.imap_idle"),
            ("sleep_time", "email.sleep_time"),
            ("disabled_sites", "email.disabled_sites"),
        ]
        for attr, key in mapping:
            val = config_store.get(key)
            if val is not None and val != getattr(self, attr):
                setattr(self, attr, val)
                changed = True

        old_default = self.default_ini
        old_personal = self.personal_ini
        self.config_store = config_store
        if self.default_ini != old_default or self.personal_ini != old_personal:
            changed = True
            self._build_geturls()

        return changed

    def _ini_mtime(self) -> float:
        """Return the latest mtime across ini files, or 0.0 if none exist."""
        latest = 0.0
        for path in (self.default_ini, self.personal_ini):
            if path:
                try:
                    latest = max(latest, os.path.getmtime(path))
                except OSError:
                    pass
        return latest

    def _current_ini_hash(self) -> str:
        """Return a combined hash of defaults.ini and personal.ini contents."""
        has_content = False
        hasher = hashlib.sha256()
        for path in (self.default_ini, self.personal_ini):
            if path and os.path.isfile(path):
                content = read_ini_file_cached(path)
                if content is not None:
                    hasher.update(path.encode("utf-8", errors="replace"))
                    hasher.update(content.encode("utf-8", errors="replace"))
                    has_content = True
        return hasher.hexdigest() if has_content else ""

    def _build_geturls(self) -> None:
        """(Re)create the GetURLs instance from ConfigStore."""
        _get_config = None
        _initial_config = None

        if self.config_store is not None and (
            self.config_store.get("calibre.default_ini")
            or self.config_store.get("calibre.personal_ini")
        ):
            _get_config = self.config_store.get_fff_get_configuration_callable()
            _initial_config = _get_config("test1.com")

        self._geturls = geturls.GetURLs(config=_initial_config, get_config=_get_config)
        self._geturls_ini_mtime = self._ini_mtime()
        self._last_ini_hash = self._current_ini_hash()

    def _reset_geturls_state(self) -> None:
        """Reset cached Royal Road adapter, BasicCache, and CookieJar on _geturls."""
        if self._geturls is None:
            return
        self._geturls.saved_royalroad_adapter = None
        cfg = getattr(self._geturls, "configuration", None)
        if cfg is not None:
            try:
                basic_cache = cfg.get_basic_cache()
                if basic_cache is not None and hasattr(basic_cache, "basic_cache"):
                    basic_cache.basic_cache.clear()
            except Exception:
                pass
            try:
                cookiejar = cfg.get_cookiejar()
                if cookiejar is not None and hasattr(cookiejar, "clear"):
                    cookiejar.clear()
            except Exception:
                pass

    def get_urls(self) -> set[str]:
        """Extract fanfiction URLs from the configured email mailbox."""
        current_hash = self._current_ini_hash()
        if self._geturls is None:
            self._build_geturls()
        elif (self._last_ini_hash and current_hash != self._last_ini_hash) or (
            not self._last_ini_hash and self._ini_mtime() > self._geturls_ini_mtime
        ):
            ff_logging.log("EmailWatcher: ini files changed, rebuilding URL extractor")
            self._build_geturls()
        assert self._geturls is not None

        urls: set[str] = set()
        self._reset_geturls_state()

        with set_timeout(180), suppress_logging() as log_capture:
            log_capture.on_error_callbacks.append(self._reset_geturls_state)
            errors_to_check: list[str] = []
            try:
                urls = set(
                    self._geturls.get_urls_from_imap(
                        self.server, self.email, self.password, self.mailbox
                    )
                )
            except Exception as e:
                ff_logging.log_failure(f"Failed to get URLs: {e}")
                errors_to_check.append(str(e))

            for err_msg in log_capture.messages:
                ff_logging.log_failure(f"EmailWatcher: {err_msg}")
                errors_to_check.append(err_msg)

            flaresolverr_err = next(
                (
                    err
                    for err in errors_to_check
                    if flaresolverr.is_flaresolverr_crash(err)
                    or "timed out" in err.lower()
                    or "timeout" in err.lower()
                ),
                None,
            )

            has_royalroad_url = any("royalroad" in u.lower() for u in urls)
            if (
                flaresolverr_err is None
                and log_capture.saw_royalroad_clickthrough
                and not has_royalroad_url
                and not errors_to_check
            ):
                redirects_str = (
                    ", ".join(log_capture.royalroad_redirects)
                    if log_capture.royalroad_redirects
                    else "none"
                )
                flaresolverr_err = f"Royal Road email click-through failed to resolve any story URLs (redirects: {redirects_str})"
                ff_logging.log_failure(f"EmailWatcher: {flaresolverr_err}")

            if flaresolverr_err is not None:
                ff_logging.log(
                    f"EmailWatcher: Detected FlareSolverr issue ({flaresolverr_err}) during email URL extraction; attempting auto-recovery..."
                )
                self._reset_geturls_state()
                recovered = flaresolverr.recover_flaresolverr_crashes(
                    target_site=None,
                    personal_ini_path=self.personal_ini,
                )
                ff_logging.log(
                    f"EmailWatcher: FlareSolverr recovery completed ({recovered} session(s) destroyed); retrying URL extraction..."
                )
                log_capture.reset()
                try:
                    urls.update(
                        self._geturls.get_urls_from_imap(
                            self.server, self.email, self.password, self.mailbox
                        )
                    )
                    for retry_err_msg in log_capture.messages:
                        ff_logging.log_failure(
                            f"EmailWatcher: Retry after FlareSolverr recovery failed: {retry_err_msg}"
                        )
                except Exception as retry_err:
                    ff_logging.log_failure(
                        f"EmailWatcher: Retry after FlareSolverr recovery failed: {retry_err}"
                    )

        if urls:
            system_utils.reclaim_memory()

        return urls

    def _idle_wait_for_notification(
        self,
        shutdown_event: ShutdownEvent,
        check_emails_event: CheckEmailsEvent,
    ) -> bool:
        """Block using IMAP IDLE until the server signals new mail or shutdown."""
        IDLE_REISSUE_SECONDS = 9 * 60
        CHECK_INTERVAL = 30

        try:
            with imapclient.IMAPClient(host=self.server, ssl=True) as client:
                client.login(self.email, self.password)
                client.select_folder(self.mailbox)

                unseen_list = client.search("UNSEEN")
                unseen = set(unseen_list) if unseen_list else set()
                new_unseen = unseen - self._last_seen_unseen_uids
                if new_unseen:
                    ff_logging.log_debug(
                        f"EmailWatcher: found {len(new_unseen)} new unread email(s) before entering IDLE"
                    )
                    self._last_seen_unseen_uids.update(unseen)
                    return True

                self._last_seen_unseen_uids.intersection_update(unseen)

                idle_start = time.monotonic()
                client.idle()
                ff_logging.log_debug("EmailWatcher: entered IMAP IDLE mode")

                while True:
                    if shutdown_event.is_set():
                        client.idle_done()
                        return False

                    if check_emails_event.is_set():
                        ff_logging.log_debug(
                            "EmailWatcher: manual email check triggered during IMAP IDLE"
                        )
                        client.idle_done()
                        return True

                    responses = client.idle_check(timeout=min(2, CHECK_INTERVAL))

                    if any(
                        len(r) >= 2 and r[1] in (b"EXISTS", b"RECENT")
                        for r in responses
                    ):
                        ff_logging.log_debug(
                            "EmailWatcher: IMAP IDLE notification received"
                        )
                        client.idle_done()
                        return True

                    if time.monotonic() - idle_start >= IDLE_REISSUE_SECONDS:
                        ff_logging.log_debug(
                            "EmailWatcher: IDLE refresh timeout reached, checking mail"
                        )
                        client.idle_done()
                        return True

        except Exception as e:
            ff_logging.log_failure(
                f"EmailWatcher: IMAP IDLE error ({e}), falling back to delayed check"
            )
            shutdown_event.wait(timeout=min(float(self.sleep_time), 5.0))
            return True


def probe_imap_connection(
    server: str,
    username: str,
    password: str,
    mailbox: str = "INBOX",
    port: int = 993,
    use_ssl: bool = True,
    timeout: float = 10.0,
) -> dict[str, int | str]:
    """Probe IMAP server connectivity, login, folder selection, and unread message count via IMAPClient."""
    with imapclient.IMAPClient(
        server, port=port, ssl=use_ssl, timeout=timeout
    ) as client:
        client.login(username, password)
        client.select_folder(mailbox, readonly=True)
        unread_ids = client.search("UNSEEN")
        unread_count = len(unread_ids) if unread_ids else 0
    return {
        "server": server,
        "mailbox": mailbox,
        "unread_count": unread_count,
    }
