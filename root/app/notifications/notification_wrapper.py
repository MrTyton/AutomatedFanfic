"""Notification coordination wrapper for AutomatedFanfic application.

This module provides a unified notification interface that coordinates multiple
notification providers and manages their lifecycle. It initializes, manages,
and dispatches notifications to all enabled notification workers concurrently
for efficient and reliable notification delivery.

Key Features:
    - Unified interface for multiple notification providers
    - Concurrent notification dispatch using ThreadPoolExecutor
    - Automatic worker initialization and validation from AppConfig
    - Hot-reload support via ConfigStore change detection
    - Error handling and logging for failed worker initialization
    - Dynamic worker filtering based on enabled status

Classes:
    NotificationWrapper: Main coordinator for all notification providers

Architecture:
    The wrapper initializes notification workers based on AppConfig and
    ConfigStore settings, manages their enabled/disabled state, and provides
    a single send_notification interface that dispatches to all enabled
    workers concurrently.

Example:
    >>> wrapper = NotificationWrapper(app_config, config_store=config_store)
    >>> wrapper.send_notification("New Chapter", "Story updated", "ao3")
"""

from . import notification_base
from concurrent.futures import ThreadPoolExecutor
from config.config_store import ConfigStore
from history.recorder import HistoryRecorder
from models.config_models import AppConfig
from .apprise_notification import AppriseNotification
from utils import ff_logging


class NotificationWrapper:
    """Unified notification coordinator managing multiple notification providers.

    Provides a single interface for dispatching notifications to multiple enabled
    notification workers concurrently. Handles worker initialization, live
    configuration hot-reload via ConfigStore, and concurrent notification
    delivery using ThreadPoolExecutor.

    Attributes:
        notification_workers (list[NotificationBase]): List of initialized
            notification worker instances.
        config (AppConfig): Base validated application configuration.
        history_recorder (HistoryRecorder): History recorder for persisting
            sent notification events.

    Example:
        >>> wrapper = NotificationWrapper(app_config, config_store, history_recorder)
        >>> wrapper.send_notification("Title", "Message", "site")
    """

    def __init__(
        self,
        config: AppConfig,
        config_store: ConfigStore,
        history_recorder: HistoryRecorder,
    ) -> None:
        """Initializes the notification wrapper and its notification workers.

        Args:
            config (AppConfig): Validated application configuration containing
                notification provider settings.
            config_store (ConfigStore): Shared ConfigStore instance for live
                credential/URL hot-reloading.
            history_recorder (HistoryRecorder): HistoryRecorder for recording
                sent notification events to the history database.
        """
        self.notification_workers: list[notification_base.NotificationBase] = []
        self.config = config
        self._config_store = config_store
        self.history_recorder = history_recorder
        self._notification_hash: int = self._compute_notification_hash()
        # Automatically initialize all available notification workers
        self._initialize_workers()

    def set_config_store(self, config_store: ConfigStore) -> None:
        """Attach a ConfigStore so send_notification() can detect credential changes.

        Args:
            config_store (ConfigStore): Shared ConfigStore instance holding live
                configuration values.
        """
        self._config_store = config_store
        self._notification_hash = self._compute_notification_hash()

    def _compute_notification_hash(self) -> int:
        """Compute a hash of notification-related ConfigStore values.

        Returns:
            int: Hash of the current notification settings in ConfigStore.
        """
        keys = [
            "pushbullet.enabled",
            "pushbullet.api_key",
            "pushbullet.device",
            "apprise.urls",
        ]
        return hash(tuple(str(self._config_store.get(k)) for k in keys))

    def _refresh_if_changed(self) -> None:
        """Rebuild Apprise workers if notification config changed in ConfigStore."""
        new_hash = self._compute_notification_hash()
        if new_hash != self._notification_hash:
            ff_logging.log_debug(
                "NotificationWrapper: config changed, rebuilding notification workers"
            )
            self._initialize_workers()
            self._notification_hash = new_hash

    def _initialize_workers(self) -> None:
        """Initializes and validates notification workers from configuration."""
        # Reset worker list to ensure clean initialization state
        self.notification_workers = []
        try:
            apprise_worker = AppriseNotification(self.config, self._config_store)
            # Validate worker is properly configured and enabled
            if apprise_worker.is_enabled():
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

        Args:
            title (str): Notification title/subject line.
            body (str): Notification message body.
            site (str): Fanfiction site identifier for logging and history recording.
        """
        # Hot-reload: rebuild Apprise client if notification config changed
        self._refresh_if_changed()

        # Filter for only enabled notification workers
        enabled_workers = [
            worker for worker in self.notification_workers if worker.enabled
        ]

        # Capture current thread color to propagate to worker threads
        current_color = getattr(ff_logging._thread_local, "color", None)

        def _send_with_color(worker, title, body, site, color):
            """Helper to propagate thread color context to worker thread."""
            if color:
                ff_logging.set_thread_color(color)
            return worker.send_notification(title, body, site)

        # Send notifications directly for the common single-worker case, or
        # concurrently using a thread pool when multiple workers are enabled.
        if len(enabled_workers) == 1:
            enabled_workers[0].send_notification(title, body, site)
        elif len(enabled_workers) > 1:
            with ThreadPoolExecutor() as executor:
                # Submit notification tasks for all enabled workers
                futures = [
                    executor.submit(
                        _send_with_color, worker, title, body, site, current_color
                    )
                    for worker in enabled_workers
                ]

            # Wait for all notifications to complete and handle any exceptions
            for future in futures:
                future.result()  # This will raise an exception if the worker raised one

        # Record notification in history
        self.history_recorder.record_notification(title, body, site)
