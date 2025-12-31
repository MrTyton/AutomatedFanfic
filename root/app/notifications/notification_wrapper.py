"""Notification coordination wrapper for AutomatedFanfic application.

This module provides a unified notification interface that coordinates multiple
notification providers and manages their lifecycle. It initializes, manages,
and dispatches notifications to all enabled notification workers concurrently
for efficient and reliable notification delivery.

Key Features:
    - Unified interface for multiple notification providers
    - Concurrent notification dispatch using ThreadPoolExecutor
    - Automatic worker initialization and validation
    - Configuration-driven notification provider setup
    - Error handling and logging for failed worker initialization
    - Dynamic worker filtering based on enabled status

Classes:
    NotificationWrapper: Main coordinator for all notification providers

Architecture:
    The wrapper initializes notification workers based on configuration,
    manages their enabled/disabled state, and provides a single send_notification
    interface that dispatches to all enabled workers concurrently. This design
    allows for easy addition of new notification providers and ensures reliable
    delivery through multiple channels.

Example:
    >>> wrapper = NotificationWrapper("config.toml")
    >>> wrapper.send_notification("New Chapter", "Story updated", "ao3")
"""

from . import notification_base
from typing import List
from concurrent.futures import ThreadPoolExecutor
from .apprise_notification import AppriseNotification
from utils import ff_logging


class NotificationWrapper:
    """Unified notification coordinator managing multiple notification providers.

    Provides a single interface for dispatching notifications to multiple enabled
    notification workers concurrently. Handles worker initialization, lifecycle
    management, and concurrent notification delivery using ThreadPoolExecutor
    for optimal performance and reliability.

    The wrapper automatically initializes notification workers based on
    configuration settings, validates their enabled status, and provides
    error handling for failed worker initialization. All enabled workers
    receive notifications concurrently for efficient delivery.

    Attributes:
        notification_workers (List[NotificationBase]): List of initialized
                                                      notification worker instances.
        toml_path (str): Path to the TOML configuration file used for
                        worker initialization and configuration.

    Example:
        >>> wrapper = NotificationWrapper("config.toml")
        >>> wrapper.send_notification("Title", "Message", "site")
    """

    def __init__(self, toml_path: str = "/config/config.toml") -> None:
        """Initializes the notification wrapper and its notification workers.

        Sets up the notification coordination system by initializing the
        configuration path and automatically discovering and initializing
        available notification workers based on configuration settings.

        Args:
            toml_path (str, optional): Path to the TOML configuration file
                                     containing notification provider settings.
                                     Defaults to "/config/config.toml" for
                                     Docker container compatibility.

        Note:
            Worker initialization happens automatically during construction.
            Failed worker initialization is logged but does not prevent
            wrapper creation - only successfully initialized workers are used.

        Example:
            >>> wrapper = NotificationWrapper()  # Uses default path
            >>> wrapper = NotificationWrapper("custom/config.toml")  # Custom path
        """
        # Initialize empty worker list and store configuration path
        self.notification_workers: List[notification_base.NotificationBase] = []
        self.toml_path = toml_path
        # Automatically initialize all available notification workers
        self._initialize_workers()

    def _initialize_workers(self) -> None:
        """Initializes and validates notification workers from configuration.

        Discovers, initializes, and validates available notification workers
        based on configuration settings. Currently initializes AppriseNotification
        as the primary notification handler, which supports multiple notification
        providers through a unified interface.

        The method handles worker initialization errors gracefully, logging
        failures without preventing wrapper operation. Only successfully
        initialized and enabled workers are added to the active worker list.

        Note:
            This is a private method called automatically during wrapper
            initialization. It resets the worker list to ensure clean state
            and validates each worker's enabled status before adding it.

        Raises:
            No exceptions are raised - all errors are caught and logged.
            Failed worker initialization results in warning logs but does
            not prevent wrapper operation.
        """
        # Reset worker list to ensure clean initialization state
        self.notification_workers = []
        try:
            # Initialize AppriseNotification as the primary notification handler
            apprise_worker = AppriseNotification(toml_path=self.toml_path)
            # Validate worker is properly configured and enabled
            if apprise_worker.is_enabled():  # Preferred over direct .enabled access
                self.notification_workers.append(apprise_worker)
            else:
                ff_logging.log_failure(
                    "AppriseNotification worker initialized but is not enabled "
                    "(no valid URLs found/configured, including any auto-added Pushbullet)."
                )
        except Exception as e:
            # Log initialization failure but continue wrapper operation
            ff_logging.log_failure(f"Failed to initialize AppriseNotification: {e}")

    def send_notification(self, title: str, body: str, site: str) -> None:
        """Sends notifications concurrently to all enabled notification workers.

        Dispatches the notification to all enabled notification workers using
        ThreadPoolExecutor for concurrent delivery. This ensures fast notification
        delivery and prevents slow notification providers from blocking others.

        The method filters workers by their enabled status, creates concurrent
        tasks for each enabled worker, and waits for all notifications to complete.
        Any exceptions raised by individual workers are propagated after all
        workers have finished their attempts.

        Args:
            title (str): The notification title/subject line. Should be concise
                        and descriptive of the notification content.
            body (str): The main notification message body containing detailed
                       information about the event or status update.
            site (str): The fanfiction site context (e.g., "archiveofourown.org")
                       for site-specific notification handling or filtering.

        Note:
            Individual worker failures do not prevent other workers from
            attempting notification delivery. All workers execute concurrently
            and any raised exceptions are handled after completion.

        Example:
            >>> wrapper.send_notification(
            ...     "Story Updated",
            ...     "New chapter available for 'My Story'",
            ...     "archiveofourown.org"
            ... )
        """
        # Filter for only enabled notification workers
        enabled_workers = [
            worker for worker in self.notification_workers if worker.enabled
        ]

        # Send notifications concurrently using thread pool for performance
        with ThreadPoolExecutor() as executor:
            # Submit notification tasks for all enabled workers
            futures = [
                executor.submit(worker.send_notification, title, body, site)
                for worker in enabled_workers
            ]

        # Wait for all notifications to complete and handle any exceptions
        for future in futures:
            future.result()  # This will raise an exception if the worker raised one
