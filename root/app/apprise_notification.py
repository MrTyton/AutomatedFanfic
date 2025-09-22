"""Apprise-based notification provider with Pushbullet integration.

This module implements the notification interface using the Apprise library,
which supports multiple notification services including Pushbullet, Discord,
Slack, email, and many others. It provides automatic Pushbullet integration
with device ID resolution and comprehensive error handling.

Key Features:
    - Multi-service notification support via Apprise library
    - Automatic Pushbullet configuration and device ID resolution
    - Duplicate URL detection and prevention
    - Comprehensive error handling and logging
    - Retry mechanism via decorator inheritance
    - Dynamic service discovery and validation

Classes:
    AppriseNotification: Main notification provider using Apprise library

Dependencies:
    - apprise: Multi-platform notification library
    - requests: For Pushbullet API device resolution

Example:
    >>> notifier = AppriseNotification("config.toml")
    >>> if notifier.is_enabled():
    ...     notifier.send_notification("Title", "Message", "site")
"""

import apprise
import ff_logging
import notification_base
import requests


class AppriseNotification(notification_base.NotificationBase):
    """Apprise-based notification provider with automatic Pushbullet integration.

    Implements notification delivery using the Apprise library, which provides
    a unified interface to multiple notification services. Automatically
    integrates Pushbullet configuration with device ID resolution and supports
    multiple notification targets simultaneously.

    The class handles configuration loading, URL validation, device ID resolution
    for Pushbullet, and maintains a set of unique notification targets. It
    provides comprehensive error handling and logging for all operations.

    Attributes:
        apprise_urls (list): List of validated notification service URLs.
        apobj (apprise.Apprise): The Apprise object managing notification targets.
        enabled (bool): Whether the service is configured and ready for notifications.

    Example:
        >>> notifier = AppriseNotification("config.toml")
        >>> if notifier.is_enabled():
        ...     success = notifier.send_notification("Title", "Body", "site")
    """

    def __init__(self, toml_path: str) -> None:
        """Initializes Apprise notification provider with configuration loading.

        Sets up the Apprise notification system by loading configuration,
        processing Apprise URLs, automatically integrating Pushbullet settings,
        and validating all notification targets. Handles device ID resolution
        for Pushbullet and ensures no duplicate URLs are added.

        Args:
            toml_path (str): Path to the TOML configuration file containing
                           Apprise URLs and Pushbullet configuration settings.

        Note:
            If configuration loading fails, the service will be disabled.
            Pushbullet integration is automatic if enabled in configuration.
            Device nicknames are resolved to device IDs via Pushbullet API.

        Raises:
            No exceptions are raised - all errors are caught and logged.
            Configuration or API failures result in service being disabled.
        """
        # Initialize parent class with configuration loading
        super().__init__(toml_path)
        # Use set initially to prevent URL duplicates during configuration
        self.apprise_urls = set()
        # Create Apprise object for notification management
        self.apobj = apprise.Apprise()
        # Start disabled until configuration validation completes
        self.enabled = False

        # Skip initialization if config loading failed
        if self.config is None:
            return

        try:
            # Load configured Apprise notification URLs
            if self.config.apprise.urls:
                for url in self.config.apprise.urls:
                    self.apprise_urls.add(url)

            # Automatically integrate Pushbullet configuration if enabled
            if self.config.pushbullet.enabled and self.config.pushbullet.api_key:
                pb_api_key = self.config.pushbullet.api_key
                # Start with basic Pushbullet URL
                pb_url = f"pbul://{pb_api_key}"
                pb_device = self.config.pushbullet.device
                # Resolve device nickname to device ID if specified
                if pb_device:
                    ff_logging.log_debug(
                        f"Pushbullet device specified: {pb_device}. Finding device ID..."
                    )
                    # Query Pushbullet API to find the device ID by nickname
                    r = requests.get(
                        "https://api.pushbullet.com/v2/devices",
                        headers={"Access-Token": pb_api_key},
                    )
                    devices = r.json().get("devices", [])
                    # Find active, pushable device matching the specified nickname
                    matched_device = next(
                        (
                            device
                            for device in devices
                            if device.get("active")
                            and device.get("pushable")
                            and device.get("nickname") == pb_device
                        ),
                        None,
                    )
                    if matched_device:
                        # Use the resolved device ID in the URL for targeting
                        pb_device = matched_device.get("iden")
                        ff_logging.log_debug(f"Found device ID: {pb_device}")
                        pb_url += f"/{pb_device}"
                    else:
                        ff_logging.log_failure(
                            f"Pushbullet device '{pb_device}' not found or not pushable. "
                            "Using default Pushbullet URL."
                        )

                # Add Pushbullet URL if not already present from Apprise config
                if pb_url not in self.apprise_urls:
                    self.apprise_urls.add(pb_url)
                    ff_logging.log_debug(
                        f"Automatically added Pushbullet URL to Apprise: {pb_url}"
                    )
                else:
                    ff_logging.log_debug(
                        f"Pushbullet URL {pb_url} was already present in Apprise config."
                    )

        except Exception as e:
            # Log configuration processing errors but continue initialization
            ff_logging.log_failure(
                f"Error processing Apprise/Pushbullet configuration: {e}"
            )

        # Disable service if no URLs are configured after processing
        if not self.apprise_urls:
            ff_logging.log(
                "No Apprise URLs configured (including auto-added Pushbullet). Apprise disabled."
            )
            self.enabled = False
            return

        # Add all unique URLs to the Apprise object for validation
        for url in self.apprise_urls:
            if not self.apobj.add(url):
                ff_logging.log_failure(
                    f"Failed to add Apprise URL: {url}. It might be invalid or unsupported."
                )

        # Validate that at least one URL was successfully added to Apprise
        urls_list = list(self.apobj.urls())
        if urls_list:
            self.enabled = True
            ff_logging.log(
                f"Apprise enabled with {len(urls_list)} notification target(s)."
            )
        else:
            ff_logging.log_failure(
                "Apprise configured with URLs, but none could be successfully added to Apprise. "
                "Apprise disabled."
            )
            self.enabled = False
        # Convert set back to list for consistent interface
        self.apprise_urls = list(self.apprise_urls)

    @notification_base.retry_decorator
    def send_notification(self, title: str, body: str, site: str) -> bool:
        """Sends notifications to all configured Apprise targets with retry logic.

        Delivers the notification to all successfully configured notification
        targets using the Apprise library. The method is decorated with retry
        logic that will attempt delivery up to 3 times with exponential backoff
        delays in case of transient failures.

        Args:
            title (str): The notification title/subject line. Should be concise
                        and descriptive of the notification content.
            body (str): The main notification message body containing detailed
                       information about the event or status update.
            site (str): The fanfiction site identifier used for logging context
                       and potential site-specific notification handling.

        Returns:
            bool: True if the notification was sent successfully to all configured
                 targets, False if any failures occurred or service is disabled.

        Note:
            This method uses the retry_decorator which provides automatic retry
            logic with exponential backoff (10s, 20s, 30s delays). Individual
            target failures within Apprise are handled by the library itself.

        Example:
            >>> success = notifier.send_notification(
            ...     "Story Updated",
            ...     "New chapter available",
            ...     "archiveofourown.org"
            ... )
        """
        # Verify service is enabled and Apprise object is available
        if not self.enabled or not self.apobj:
            return False

        # Get current target count for logging (URLs already added in __init__)
        urls_list = list(self.apobj.urls())
        target_count = len(urls_list)

        # Attempt to send notification to all configured targets
        if self.apobj.notify(body=body, title=title):
            ff_logging.log(
                f"({site}) Apprise notification for '{title}':'{body}' sent successfully "
                f"to {target_count} {'target' if target_count == 1 else 'targets'}"
            )
            return True
        else:
            ff_logging.log_failure(
                f"({site}) Failed to send Apprise notification to {target_count} target(s)."
            )
            return False

    def is_enabled(self) -> bool:
        """Checks if the Apprise notification service is operational.

        Validates that the notification service is properly configured with
        at least one working notification target and ready to send notifications.
        This method provides a consistent interface for checking service status.

        Returns:
            bool: True if the service is enabled and has valid notification
                 targets configured, False if disabled or misconfigured.

        Example:
            >>> notifier = AppriseNotification("config.toml")
            >>> if notifier.is_enabled():
            ...     notifier.send_notification("Title", "Body", "site")
        """
        return self.enabled

    def get_service_name(self) -> str:
        """Returns the human-readable name of this notification service.

        Provides a consistent identifier for this notification provider that
        can be used for logging, debugging, and user interface purposes.

        Returns:
            str: The service name "Apprise" identifying this notification provider.

        Example:
            >>> notifier = AppriseNotification("config.toml")
            >>> print(f"Using {notifier.get_service_name()} for notifications")
            Using Apprise for notifications
        """
        return "Apprise"
