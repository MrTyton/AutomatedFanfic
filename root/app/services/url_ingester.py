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

import multiprocessing as mp
import socket
import time
import logging
from contextlib import contextmanager
from fanficfare import geturls
from utils import ff_logging
from parsers import regex_parsing
from notifications import notification_wrapper
from models.config_models import EmailConfig


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
            urls = geturls.get_urls_from_imap(server, email, password, mailbox)

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

    def __init__(self, email_config: EmailConfig):
        """
        Initialize EmailInfo with email configuration object.

        Takes a pre-loaded and validated email configuration object instead of
        loading from file. This avoids redundant config parsing when the
        configuration has already been loaded in the main process.

        Args:
            email_config (config_models.EmailConfig): Pre-loaded email configuration
                                                     containing all email settings.

        Example:
            ```python
            # In main process
            config = ConfigManager.load_config("config.toml")
            email_info = EmailInfo(config.email)
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
        urls = set()

        # Use timeout protection and suppress verbose logging during extraction
        with set_timeout(55), suppress_logging():
            try:
                # Extract URLs using FanFicFare's IMAP functionality
                urls = geturls.get_urls_from_imap(
                    self.server, self.email, self.password, self.mailbox
                )
            except Exception as e:
                ff_logging.log_failure(f"Failed to get URLs: {e}")

        return urls


def email_watcher(
    email_info: EmailInfo,
    notification_info: notification_wrapper.NotificationWrapper,
    ingress_queue: mp.Queue,
    url_parsers: dict,
    active_urls: dict | None = None,
    verbose: bool = False,
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

    Processing Flow:
        1. Extract URLs from email using FanFicFare's geturls functionality
        2. Parse each URL to identify the source fanfiction site
        3. Handle special cases (e.g., FFNet disable notifications)
        4. Check for duplicates in active_urls
        5. Route URLs to appropriate site-specific processing queues
        6. Sleep until next polling cycle

    Special Handling:
        - Disabled Sites: URLs from sites listed in disabled_sites only send
                         notifications without being added to processing queues
        - Unknown Sites: URLs that don't match known patterns are routed
                        to the "other" queue

    Example:
        ```python
        # Typically run in a separate process
        email_info = EmailInfo("config.toml")
        notification_wrapper = NotificationWrapper(config)

        ingress_queue = mp.Queue()

        # This runs indefinitely until process termination
        email_watcher(email_info, notification_wrapper, ingress_queue)
        ```

    Infinite Loop:
        This function runs indefinitely and should be executed in a separate
        process. It only exits when the process is terminated externally.

    Thread Safety:
        This function is designed for multiprocessing environments. All
        communication with other processes occurs through the provided
        queue objects, which are thread/process-safe.

    Note:
        The sleep interval between email checks is configured via
        email_info.sleep_time to balance responsiveness with email
        server load considerations.
    """
    # Initialize logging for this process
    ff_logging.set_verbose(verbose)

    while True:
        # Extract URLs from the configured email account
        urls = email_info.get_urls()
        fics_to_add = set()

        # Process each URL found in email messages
        for url in urls:
            # Parse URL to identify site and normalize format
            fanfic = regex_parsing.generate_FanficInfo_from_url(url, url_parsers)

            # Skip processing for disabled sites - notification only
            if fanfic.site in email_info.disabled_sites:
                notification_info.send_notification(
                    "New Fanfiction Download", fanfic.url, fanfic.site
                )
                continue

            # Check if URL is already active
            if active_urls is not None and fanfic.url in active_urls:
                ff_logging.log(
                    f"Skipping {fanfic.url} - already in queue or processing",
                    "WARNING",
                )
                continue

            # Add to processing set for queue routing
            fics_to_add.add(fanfic)

            # Mark as active
            if active_urls is not None:
                active_urls[fanfic.url] = True

        # Route each fanfiction to appropriate processing queue
        for fic in fics_to_add:
            ff_logging.log(
                f"Adding {fic.url} to the ingestion queue (Site: {fic.site})",
                "HEADER",
            )
            # Route to ingress queue
            ingress_queue.put(fic)

        # Wait before next email check cycle
        time.sleep(email_info.sleep_time)
