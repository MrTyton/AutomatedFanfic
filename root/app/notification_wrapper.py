import notification_base
from typing import List
from concurrent.futures import ThreadPoolExecutor
from apprise_notification import AppriseNotification
import ff_logging
from config_models import ConfigManager, ConfigError, ConfigValidationError


class NotificationWrapper:
    def __init__(self, toml_path: str = "/config/config.toml"):
        """
        Initializes the NotificationWrapper and its notification workers.
        Args:
            toml_path (str): Path to the TOML configuration file.
        """
        self.notification_workers: List[notification_base.NotificationBase] = []
        self.toml_path = toml_path
        self._initialize_workers()

    def _initialize_workers(self) -> None:
        """
        Initializes the AppriseNotification worker.
        AppriseNotification is now the sole notification handler.
        """
        self.notification_workers = []  # Ensure it's reset
        try:
            # Pass self.toml_path, which was set in __init__
            apprise_worker = AppriseNotification(toml_path=self.toml_path)
            if (
                apprise_worker.is_enabled()
            ):  # is_enabled() is preferred over direct .enabled
                self.notification_workers.append(apprise_worker)
            else:
                ff_logging.log_failure(
                    "AppriseNotification worker initialized but is not enabled (no valid URLs found/configured, including any auto-added Pushbullet)."
                )
        except Exception as e:
            ff_logging.log_failure(f"Failed to initialize AppriseNotification: {e}")

    def send_notification(self, title: str, body: str, site: str) -> None:
        """
        Sends a notification using all enabled notification workers.

        Args:
            title (str): The title of the notification.
            body (str): The body of the notification.
            site (str): The site to which the notification is sent.
        """
        enabled_workers = [
            worker for worker in self.notification_workers if worker.enabled
        ]

        with ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(worker.send_notification, title, body, site)
                for worker in enabled_workers
            ]

        # Optionally, you can wait for all futures to complete if needed
        for future in futures:
            future.result()  # This will raise an exception if the worker raised one
