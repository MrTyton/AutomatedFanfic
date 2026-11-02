"""Email client and URL extraction for AutomatedFanfic."""

import hashlib
import logging
import os
import socket
import time
from contextlib import contextmanager

from config import EmailConfig
from config.store import ConfigStore, read_ini_file_cached
import ff_logging
from models.queue_types import CheckEmailsEvent, ShutdownEvent

lazy from fanficfare import geturls
lazy import imapclient
lazy from antibot import flaresolverr as flaresolverr_utils
lazy from utils import system_utils


def _make_fff_get_configuration(config_store: ConfigStore):
    """Return a get_configuration callable for fanficfare.geturls.GetURLs using ConfigStore."""
    return config_store.get_fff_configuration


@contextmanager
def set_timeout(timeout_duration):
    """Temporarily set socket timeout for network operations."""
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout_duration)
    try:
        yield
    finally:
        socket.setdefaulttimeout(old_timeout)


@contextmanager
def suppress_logging():
    """Temporarily suppress all logging output during URL extraction."""
    old_level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(old_level)


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
            _get_config = _make_fff_get_configuration(self.config_store)
            _initial_config = _get_config("test1.com")

        self._geturls = geturls.GetURLs(config=_initial_config, get_config=_get_config)
        self._geturls_ini_mtime = self._ini_mtime()
        self._last_ini_hash = self._current_ini_hash()

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

        urls = set()

        with set_timeout(55), suppress_logging():
            try:
                urls = set(
                    self._geturls.get_urls_from_imap(
                        self.server, self.email, self.password, self.mailbox
                    )
                )
            except Exception as e:
                ff_logging.log_failure(f"Failed to get URLs: {e}")
                if flaresolverr_utils.is_flaresolverr_crash(e):
                    ff_logging.log(
                        "EmailWatcher: Detected FlareSolverr crash during email URL extraction; attempting auto-recovery..."
                    )
                    recovered = flaresolverr_utils.recover_flaresolverr_crashes(
                        personal_ini_path=self.personal_ini
                    )
                    if recovered > 0:
                        ff_logging.log(
                            f"EmailWatcher: Recovered {recovered} FlareSolverr session(s); retrying URL extraction..."
                        )
                        try:
                            urls = set(
                                self._geturls.get_urls_from_imap(
                                    self.server, self.email, self.password, self.mailbox
                                )
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
        check_emails_event: CheckEmailsEvent | None = None,
    ) -> bool:
        """Block using IMAP IDLE until the server signals new mail or shutdown."""
        IDLE_REISSUE_SECONDS = 9 * 60
        CHECK_INTERVAL = 30

        try:
            with imapclient.IMAPClient(host=self.server, ssl=True) as client:
                client.login(self.email, self.password)
                client.select_folder(self.mailbox)

                unseen = client.search("UNSEEN")
                if unseen:
                    ff_logging.log_debug(
                        f"EmailWatcher: found {len(unseen)} unread email(s) before entering IDLE"
                    )
                    return True

                idle_start = time.monotonic()
                client.idle()
                ff_logging.log_debug("EmailWatcher: entered IMAP IDLE mode")

                while True:
                    if shutdown_event.is_set():
                        client.idle_done()
                        return False

                    if check_emails_event is not None and check_emails_event.is_set():
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
                f"EmailWatcher: IMAP IDLE error ({e}), falling back to immediate check"
            )
            return True
