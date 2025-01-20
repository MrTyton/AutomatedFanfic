"""
Base class for implementing Notifications.

This module contains the base class for implementing notifications. The class defines the
`send_notification` function, which sends a notification with a title, body, and site. This
function must be implemented by the derived classes.

It also provides a helper function that can be applied to the `send_notification` function,
as a decorator, to retry it up to 3 times with 10, 20, and 30-second delays between attempts.

The derived classes must mark themselves as `enabled` if they are able to send notifications,
by setting `self.enabled` to True.

The derived classes are responsible for extracting their configuration information from the
TOML file that has been loaded into `self.config`.
"""

import apprise
import ff_logging
import time
import tomllib

from typing import Callable, Any


kSleepTime = 10
kMaxAttempts = 3


def retry_decorator(func: Callable) -> Callable:
    """
    A decorator that retries a function up to 3 times with a 30-second delay between attempts.

    Args:
        func (Callable): The function to be retried.

    Returns:
        Callable: The wrapped function with retry logic.
    """

    def wrapper(*args: Any, **kwargs: Any) -> bool:
        for attempt in range(kMaxAttempts):
            if func(*args, **kwargs):
                return True
            elif attempt < kMaxAttempts - 1:
                time.sleep(kSleepTime * (attempt + 1))
        return False

    return wrapper


class NotificationBase:
    def __init__(self, toml_path: str, sleep_time: int = 10) -> None:
        """
        Initializes the NotificationBase class.
        """
        self.enabled = False

        # Load the configuration from the TOML file
        with open(toml_path, "rb") as file:
            self.config = tomllib.load(file)

        # Load the Apprise configuration from the YAML file
        notification_config = self.config.get("notifications", {})
        if not notification_config:
            ff_logging.log_failure(
                "Notification configuration is missing in the TOML file."
            )
            return
        apprise_config_path = notification_config.get("apprise_config_path")
        if not apprise_config_path:
            ff_logging.log_failure(
                "Apprise configuration path is missing in the TOML file."
            )
            return

        self.apprise = apprise.Apprise()
        added = self.apprise.add(apprise_config_path)
        if not added:
            ff_logging.log_failure(
                f"Failed to load Apprise configuration from {apprise_config_path}"
            )
            return
        self.enabled = True

    @retry_decorator
    def send_notification(self, body: str, title: str, site: str) -> bool:
        """
        Sends a notification using Apprise.

        Args:
            message (str): The formatted notification message.

        Returns:
            bool: True if the notification was sent successfully, False otherwise.
        """
        if not self.enabled:
            return False

        try:
            ff_logging.log(f"\t{site}: Sending notification: {title} - {body}")
            return self.apprise.notify(
                title=title,
                body=body,
            )
        except Exception as e:
            print(f"\t{site}: Failed to send notification: {e}")
            return False
