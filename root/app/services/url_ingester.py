"""
Email URL Ingestion for AutomatedFanfic

This module handles the automated monitoring of email accounts for fanfiction
URLs, extracting them using FanFicFare's geturls functionality, and routing
them to appropriate processing queues based on the detected fanfiction site.

Key Features:
    - IMAP email monitoring with configurable polling intervals
    - Automatic URL extraction from email content using FanFicFare
    - Site-specific URL routing to dedicated processing queues
    - Network timeout management for email operations
    - Logging suppression during URL extraction for clean output
    - Special handling for problematic sites (e.g., FFNet disable)

Architecture:
    The module implements a continuous monitoring loop that polls an email
    account, extracts URLs from new messages, identifies the fanfiction site,
    and routes URLs to site-specific worker queues for processing.

Email Processing Flow:
    1. Connect to IMAP server with configured credentials
    2. Poll mailbox for new/unread messages at specified intervals
    3. Extract fanfiction URLs using FanFicFare's geturls library
    4. Parse URLs to identify source fanfiction sites
    5. Route URLs to appropriate processor queues
    6. Handle special cases (FFNet notifications vs. processing)
    7. Sleep until next polling cycle

Example:
    ```python
    from url_ingester import EmailInfo, email_watcher
    import multiprocessing as mp

    # Configure email monitoring
    email_info = EmailInfo("config.toml")

    # Set up processing queues
    queues = {
        "archiveofourown.org": mp.Queue(),
        "fanfiction.net": mp.Queue(),
        "other": mp.Queue()
    }

    # Start monitoring (typically in a separate process)
    email_watcher(email_info, notification_wrapper, queues)
    ```

Configuration:
    Email settings are loaded from TOML configuration:
    - email: Email authentication (username only or full email address)
    - password: App password or account password
    - server: IMAP server address
    - mailbox: Mailbox to monitor (typically "INBOX")
    - sleep_time: Seconds between polling cycles
    - disabled_sites: List of site identifiers to disable processing for

Dependencies:
    - fanficfare.geturls: For URL extraction from emails
    - regex_parsing: For URL site identification
    - notification_wrapper: For sending notifications
    - config_models: For configuration management

Thread Safety:
    The email watcher is designed to run in a separate process via
    multiprocessing. It communicates with other processes through
    shared queues and is safe for concurrent operation.
"""

import os
import socket
import time
import logging
import threading
from typing import Any
from contextlib import contextmanager
lazy from fanficfare import adapters, configurable, geturls
from utils import ff_logging
from parsers import regex_parsing
from notifications import notification_wrapper
from models.config_models import EmailConfig
from models.queue_types import IngressQueue


def _make_fff_get_configuration(
    default_ini_path: str | None = None,
    personal_ini_path: str | None = None,
    config_store: Any | None = None,
):
    """
    Return a get_configuration callable for fanficfare.geturls.GetURLs.

    The callable receives a URL from FFF and returns a Configuration object
    loaded with our defaults.ini and personal.ini so that site-specific
    credentials (e.g. Royal Road username/password) are available during
    email URL extraction – required since RR email-click links now need an
    authenticated session to resolve to a story URL (FFF issue #1429).
    """
    if config_store is not None and not default_ini_path and not personal_ini_path:
        return config_store.get_fff_get_configuration_callable()

    def get_configuration(url: str):
        try:
            sections = adapters.getConfigSectionsFor(url)
        except Exception:
            sections = ["test1.com"]
        config = configurable.Configuration(sections, "EPUB")
        ini_files = []
        if default_ini_path and os.path.isfile(default_ini_path):
            ini_files.append(default_ini_path)
        if personal_ini_path and os.path.isfile(personal_ini_path):
            ini_files.append(personal_ini_path)
        if ini_files:
            config.read(ini_files)
        return config

    return get_configuration


@contextmanager
def set_timeout(timeout_duration):
    """
    Temporarily set socket timeout for network operations.

    This context manager provides a safe way to modify the global socket
    timeout for network operations while ensuring the original timeout
    is restored regardless of how the context exits.

    Args:
        timeout_duration (int): Timeout duration in seconds for socket
                               operations during the context.

    Example:
        ```python
        with set_timeout(30):
            # All socket operations in this block have 30-second timeout
            response = urllib.request.urlopen(url)

        # Original timeout is restored here
        ```

    Note:
        This affects all socket operations in the current thread during
        the context. Use carefully in multithreaded environments.
    """
    # Store current timeout setting for restoration
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout_duration)
    try:
        yield
    finally:
        # Always restore original timeout setting
        socket.setdefaulttimeout(old_timeout)


@contextmanager
def suppress_logging():
    """
    Temporarily suppress all logging output during URL extraction.

    This context manager disables logging by setting the global disable level
    to CRITICAL, effectively suppressing all log messages during URL extraction
    operations. This prevents FanFicFare's verbose output from cluttering the
    application logs during email processing.

    Example:
        ```python
        with suppress_logging():
            # FanFicFare operations here won't produce log output
            urls = geturls.GetURLs().get_urls_from_imap(server, email, password, mailbox)

        # Normal logging resumes here
        ```

    Note:
        This affects the global logging state and should be used carefully.
        The original logging level is always restored when the context exits,
        even if an exception occurs.

    Thread Safety:
        This modifies global logging state and may affect other threads.
        Consider using thread-local logging configuration if needed.
    """
    # Save current global logging disable level
    old_level = logging.root.manager.disable

    # Disable all logging by setting to highest level
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        # Restore original logging state
        logging.disable(old_level)


class EmailInfo:
    """
    Email account configuration and URL extraction for fanfiction monitoring.

    This class encapsulates all email-related configuration and provides
    methods for extracting fanfiction URLs from email messages. It handles
    IMAP connection details and provides a clean interface for URL retrieval.

    Attributes:
        email (str): Email authentication (username only or full email address)
        password (str): Account password or app-specific password
        server (str): IMAP server hostname (e.g., "imap.gmail.com")
        mailbox (str): Mailbox to monitor (typically "INBOX")
        sleep_time (int): Seconds to wait between email checks
        disabled_sites (List[str]): List of site identifiers to disable processing for

    Example:
        ```python
        email_info = EmailInfo("config.toml")

        # Extract URLs from email
        urls = email_info.get_urls()
        for url in urls:
            process_fanfiction_url(url)
        ```

    Configuration Format:
        The TOML configuration should contain an [email] section:
        ```toml
        [email]
        email = "username"  # Username only or full email address
        password = "app_password"
        server = "imap.gmail.com"
        mailbox = "INBOX"
        sleep_time = 60
        disabled_sites = ["fanfiction", "wattpad"]  # Sites to disable processing for
        ```

    Security Note:
        Store passwords securely and consider using app-specific passwords
        rather than main account passwords for IMAP access.
    """

    def __init__(
        self,
        email_config: EmailConfig,
        default_ini: str | None = None,
        personal_ini: str | None = None,
        config_store: Any | None = None,
    ):
        """
        Initialize EmailInfo with email configuration object.

        Takes a pre-loaded and validated email configuration object instead of
        loading from file. This avoids redundant config parsing when the
        configuration has already been loaded in the main process.

        Args:
            email_config (config_models.EmailConfig): Pre-loaded email configuration
                                                     containing all email settings.
            default_ini (str | None): Path to FanFicFare defaults.ini, passed through
                                     to GetURLs so site-specific settings are available
                                     during email URL extraction (e.g. RR login).
            personal_ini (str | None): Path to FanFicFare personal.ini, passed through
                                       to GetURLs so credentials are available during
                                       email URL extraction (e.g. RR login).
            config_store (Any | None): Shared ConfigStore instance for live updates
                                       and automatic INI path resolution.

        Example:
            ```python
            # In main process
            config = ConfigManager.load_config("config.toml")
            email_info = EmailInfo(config.email, config_store=config_store)
            print(f"Monitoring {email_info.email}@{email_info.server}")
            ```
        """
        # Set instance attributes from the provided configuration object
        self.email = email_config.email
        self.password = email_config.password
        self.server = email_config.server
        self.mailbox = email_config.mailbox
        self.sleep_time = email_config.sleep_time
        self.disabled_sites = email_config.disabled_sites
        self.imap_idle = email_config.imap_idle
        self.config_store = config_store
        if config_store is not None:
            self.default_ini = (
                default_ini
                if default_ini is not None
                else config_store.get_resolved_default_ini()
            )
            self.personal_ini = (
                personal_ini
                if personal_ini is not None
                else config_store.get_resolved_personal_ini()
            )
        else:
            self.default_ini = default_ini or ""
            self.personal_ini = personal_ini or ""
        self._build_geturls()

    # ------------------------------------------------------------------
    # Pickling support for multiprocessing (forkserver / spawn)
    # The _geturls instance holds a closure that cannot be pickled.
    # We exclude it from the pickled state and rebuild it on the other side.
    # ------------------------------------------------------------------
    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state.pop("_geturls", None)
        state.pop("_geturls_ini_mtime", None)
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        self._build_geturls()

    def update_from_config_store(self, config_store) -> bool:
        """Sync email credentials and INI paths from ConfigStore.

        Called at the top of each poll cycle so credential or INI path changes
        made via the web dashboard are picked up without restarting the process.

        Returns:
            True if any field changed (caller should rebuild GetURLs).
        """
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

        self.config_store = config_store
        ini_changed = False
        resolved_default = config_store.get_resolved_default_ini()
        if resolved_default != self.default_ini:
            self.default_ini = resolved_default
            changed = True
            ini_changed = True

        resolved_personal = config_store.get_resolved_personal_ini()
        if resolved_personal != self.personal_ini:
            self.personal_ini = resolved_personal
            changed = True
            ini_changed = True

        if ini_changed:
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

    def _build_geturls(self) -> None:
        """(Re)create the GetURLs instance from the current ini files.

        Stores the ini modification time so get_urls() can detect when
        personal.ini or defaults.ini has changed and rebuild accordingly.
        """
        _get_config = None
        _initial_config = None
        if self.config_store is not None or self.default_ini or self.personal_ini:
            if self.config_store is not None:
                _get_config = _make_fff_get_configuration(
                    self.default_ini or None,
                    self.personal_ini or None,
                    config_store=self.config_store,
                )
            else:
                _get_config = _make_fff_get_configuration(
                    self.default_ini or None,
                    self.personal_ini or None,
                )
            # Pre-build the initial Configuration so GetURLs.__init__ can set
            # self.configuration before any get_configuration() call tries to
            # copy the cache from it (chicken-and-egg guard).
            _initial_config = _get_config("test1.com")
        self._geturls = geturls.GetURLs(config=_initial_config, get_config=_get_config)
        self._geturls_ini_mtime = self._ini_mtime()

    def get_urls(self) -> set[str]:
        """
        Extract fanfiction URLs from the configured email mailbox.

        This method connects to the IMAP server and uses FanFicFare's geturls
        functionality to extract fanfiction URLs from email messages in the
        specified mailbox. Network operations are performed with timeout
        protection and logging is suppressed to reduce noise.

        Returns:
            set[str]: Set of unique fanfiction URLs found in email messages.
                     Empty set if no URLs found or if an error occurs.

        Example:
            ```python
            email_info = EmailInfo("config.toml")
            urls = email_info.get_urls()

            print(f"Found {len(urls)} fanfiction URLs:")
            for url in urls:
                print(f"  {url}")
            ```

        Error Handling:
            All exceptions during URL extraction are caught and logged as
            failures. The method returns an empty set on error rather than
            propagating exceptions to maintain stable operation.

        Network Timeout:
            Uses a 55-second timeout for all network operations to prevent
            hanging on slow or unresponsive email servers.

        Note:
            This method processes all messages in the mailbox that contain
            recognizable fanfiction URLs. It does not mark messages as read
            or modify the mailbox state in any way.
        """
        # Rebuild if ini files have been modified since last build – ensures
        # credential changes take effect without requiring a process restart.
        if self._ini_mtime() > self._geturls_ini_mtime:
            ff_logging.log("EmailWatcher: ini files changed, rebuilding URL extractor")
            self._build_geturls()

        urls = set()

        # Use timeout protection and suppress verbose logging during extraction
        with set_timeout(55), suppress_logging():
            try:
                urls = set(
                    self._geturls.get_urls_from_imap(
                        self.server, self.email, self.password, self.mailbox
                    )
                )
            except Exception as e:
                ff_logging.log_failure(f"Failed to get URLs: {e}")

        return urls

    def _idle_wait_for_notification(
        self, shutdown_event: threading.Event | None = None
    ) -> bool:
        """
        Block using IMAP IDLE until the server signals new mail or shutdown.

        Opens a dedicated IMAPClient connection, enters IDLE mode, and checks
        for unsolicited EXISTS/RECENT responses every 30 seconds so that the
        shutdown_event is honoured promptly.  IDLE is re-issued every 9
        minutes (many servers, including Gmail, drop connections at 10 minutes;
        staying under that threshold prevents dead sockets).  A NOOP is sent
        after DONE to flush any messages that arrived in the DONE/re-IDLE gap.

        Args:
            shutdown_event: Optional event; when set the method exits cleanly.

        Returns:
            True  – new mail notification received (or re-IDLE timeout fired),
                    caller should call get_urls().
            False – shutdown_event was set; caller should stop the loop.
        """
        from imapclient import IMAPClient  # lazy import – only needed when idle enabled

        IDLE_REISSUE_SECONDS = (
            9 * 60
        )  # re-issue IDLE every 9 minutes (Gmail times out at 10)
        CHECK_INTERVAL = 30  # how often to check shutdown_event (seconds)

        try:
            with IMAPClient(host=self.server, ssl=True) as client:
                client.login(self.email, self.password)
                client.select_folder(self.mailbox)

                idle_start = time.monotonic()
                client.idle()
                ff_logging.log_debug("EmailWatcher: entered IMAP IDLE mode")

                while True:
                    if shutdown_event and shutdown_event.is_set():
                        client.idle_done()
                        return False

                    responses = client.idle_check(timeout=CHECK_INTERVAL)

                    # Server signalled new/changed messages
                    if any(
                        len(r) >= 2 and r[1] in (b"EXISTS", b"RECENT")
                        for r in responses
                    ):
                        ff_logging.log_debug(
                            "EmailWatcher: IMAP IDLE notification received"
                        )
                        client.idle_done()
                        return True

                    # Re-issue IDLE every 9 minutes to keep the connection alive.
                    # After DONE, send NOOP to flush any messages that arrived
                    # in the DONE/re-IDLE gap before going back into IDLE.
                    if time.monotonic() - idle_start >= IDLE_REISSUE_SECONDS:
                        client.idle_done()
                        noop_responses = client.noop()
                        if any(
                            isinstance(r, (list, tuple))
                            and len(r) >= 2
                            and r[1] in (b"EXISTS", b"RECENT")
                            for r in noop_responses
                        ):
                            ff_logging.log_debug(
                                "EmailWatcher: IMAP IDLE notification received via NOOP"
                            )
                            return True
                        if shutdown_event and shutdown_event.is_set():
                            return False
                        client.idle()
                        idle_start = time.monotonic()
                        ff_logging.log_debug("EmailWatcher: re-issued IMAP IDLE")

        except Exception as e:
            ff_logging.log_failure(
                f"EmailWatcher: IMAP IDLE error ({e}), falling back to immediate check"
            )
            return True  # fall through to get_urls() on next iteration


def email_watcher(
    email_info: EmailInfo,
    notification_info: notification_wrapper.NotificationWrapper,
    ingress_queue: IngressQueue,
    url_parsers: dict,
    active_urls: dict | None = None,
    verbose: bool = False,
    shutdown_event: threading.Event | None = None,
    history_recorder=None,
    config_store=None,
):
    """
    Continuously monitor email for fanfiction URLs and route to processing queues.

    This function implements the main email monitoring loop for the AutomatedFanfic
    application. It polls the configured email account at regular intervals,
    extracts fanfiction URLs, identifies the source sites, and routes URLs to
    appropriate processing queues.

    Args:
        email_info (EmailInfo): Configured email account information including
                               credentials, server details, and polling settings.
        notification_info (notification_wrapper.NotificationWrapper): Notification
                                                                     system for sending alerts about new URLs.
        ingress_queue (mp.Queue): Queue for all new fanfiction tasks.
        url_parsers (dict): Dictionary of compiled regex patterns for site recognition.
                           Generated from FanFicFare adapters in the main process.
        active_urls (dict, optional): Shared dictionary tracking URLs currently in
                                     queues or being processed to prevent duplicates.
        verbose (bool): Enable verbose logging.
        shutdown_event (threading.Event, optional): Event to signal shutdown.
    """
    # Initialize logging for this process
    ff_logging.set_verbose(verbose)
    ff_logging.set_thread_color("\033[93m")  # Yellow

    while True:
        # Check for shutdown signal
        if shutdown_event and shutdown_event.is_set():
            ff_logging.log_debug("EmailWatcher received shutdown signal")
            break

        # Hot-reload: sync credentials from ConfigStore if they changed
        if config_store is not None:
            if email_info.update_from_config_store(config_store):
                ff_logging.log_debug(
                    "EmailWatcher: credentials updated from ConfigStore, rebuilding URL extractor"
                )
                email_info._build_geturls()

        # Extract URLs from the configured email account
        urls = email_info.get_urls()
        fics_to_add = set()

        # Track usage within this batch to prevent duplicate logs for same-normalized URLs
        processed_in_batch = set()

        # History tracking counters
        urls_found = len(urls)
        urls_new = 0
        urls_duplicate = 0
        urls_disabled_site = 0

        # Process each URL found in email messages
        for url in urls:
            # Normalize URL: add https:// if no protocol present (parsers require it for site detection)
            if url and not url.startswith(("http://", "https://")):
                url = "https://" + url
            # Parse URL to identify site and normalize format
            fanfic = regex_parsing.generate_FanficInfo_from_url(url, url_parsers)

            # Silent partial dedup: if we already processed this normalized URL in this batch, skip it
            if fanfic.url in processed_in_batch:
                continue
            processed_in_batch.add(fanfic.url)

            # Skip processing for disabled sites - notification only
            if fanfic.site in email_info.disabled_sites:
                urls_disabled_site += 1
                notification_info.send_notification(
                    "New Fanfiction Download", fanfic.url, fanfic.site
                )
                continue

            # Check if URL is already active (ignore cancelled entries awaiting heap cleanup)
            if active_urls is not None and fanfic.url in active_urls:
                existing_meta = active_urls.get(fanfic.url, {})
                if not (
                    isinstance(existing_meta, dict)
                    and existing_meta.get("status") == "cancelled"
                ):
                    urls_duplicate += 1
                    ff_logging.log(
                        f"Skipping {fanfic.url} - already in queue or processing",
                        "WARNING",
                    )
                    continue

            # Add to processing set for queue routing
            urls_new += 1
            fics_to_add.add(fanfic)

            # Mark as active
            if active_urls is not None:
                active_urls[fanfic.url] = {"site": fanfic.site, "status": "queued"}

        # Route each fanfiction to appropriate processing queue
        for fic in fics_to_add:
            ff_logging.log(
                f"Adding {fic.url} to the ingestion queue (Site: {fic.site})"
            )
            # Route to ingress queue
            ingress_queue.put(fic)
            if history_recorder:
                history_recorder.record_download_created(
                    fic.url, fic.site, fic.behavior
                )

        # Record email check event
        if history_recorder:
            history_recorder.record_email_check(
                urls_found=urls_found,
                urls_new=urls_new,
                urls_duplicate=urls_duplicate,
                urls_disabled_site=urls_disabled_site,
                trigger="idle" if email_info.imap_idle else "poll",
            )

        # Wait before next email check cycle
        if email_info.imap_idle:
            # Push mode: block in IMAP IDLE until the server notifies us
            if not email_info._idle_wait_for_notification(shutdown_event):
                break  # shutdown signalled inside IDLE wait
        elif shutdown_event:
            if shutdown_event.wait(timeout=email_info.sleep_time):
                break
        else:
            time.sleep(email_info.sleep_time)
