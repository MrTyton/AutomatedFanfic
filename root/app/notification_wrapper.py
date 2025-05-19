import notification_base
from typing import List
from concurrent.futures import ThreadPoolExecutor
from .apprise_notification import AppriseNotification
from .pushbullet_notification import PushbulletNotification
import ff_logging # Assuming ff_logging is available for potential logging


class NotificationWrapper:
    def __init__(self, toml_path: str = "/config/config.toml"):
        """
        Initializes the NotificationWrapper and its notification workers.
        Args:
            toml_path (str): Path to the TOML configuration file.
        """
        self.notification_workers: List[notification_base.NotificationBase] = []
        self._initialize_workers(toml_path)

    def _initialize_workers(self, toml_path: str) -> None:
        """
        Initializes and configures notification workers based on the provided TOML config.
        """
        try:
            apprise_worker = AppriseNotification(toml_path)
            if apprise_worker.is_enabled():
                self.notification_workers.append(apprise_worker)
                ff_logging.log_info("AppriseNotification worker added.")
        except Exception as e:
            ff_logging.log_error(f"Failed to initialize AppriseNotification: {e}")

        try:
            # We need to check if apprise_worker was successfully initialized first
            # For now, let's assume it might not be if an exception occurred.
            # A more robust way would be to check if apprise_worker exists and is an instance of AppriseNotification
            apprise_can_handle_pb = False
            if 'apprise_worker' in locals() and isinstance(apprise_worker, AppriseNotification):
                apprise_can_handle_pb = apprise_worker.can_handle_pushbullet()

            pushbullet_worker = PushbulletNotification(toml_path)
            if pushbullet_worker.is_enabled():
                if not apprise_can_handle_pb:
                    self.notification_workers.append(pushbullet_worker)
                    ff_logging.log_info("PushbulletNotification worker added as Apprise cannot handle Pushbullet.")
                else:
                    ff_logging.log_info("PushbulletNotification not added as Apprise can handle Pushbullet.")
            elif pushbullet_worker.config.get("pushbullet", {}).get("enabled"):
                 # Log if pushbullet was enabled in config but worker didn't enable (e.g. missing API key)
                 ff_logging.log_warning("Pushbullet was enabled in config but the worker could not be initialized/enabled.")

        except Exception as e:
            ff_logging.log_error(f"Failed to initialize PushbulletNotification: {e}")


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
