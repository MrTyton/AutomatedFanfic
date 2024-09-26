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

import time
import tomllib
from typing import Callable, Any

kSleepTime = 10
kMaxAttempts = 3


class NotificationBase:
    def __init__(self, toml_path: str, sleep_time: int = 10) -> None:
        """
        Initializes the NotificationBase class.
        """
        self.enabled = False

        # Load the configuration from the TOML file
        with open(toml_path, "rb") as file:
            self.config = tomllib.load(file)

    def send_notification(self, title: str, body: str, site: str) -> bool:
        """
        Sends a notification. This method must be implemented in derived classes.

        Args:
            title (str): The title of the notification.
            body (str): The body of the notification.
            site (str): The site to which the notification is sent.
        """
        raise NotImplementedError(
            "send_notification method must be implemented in derived classes"
        )


def retry_decorator(func: Callable) -> Callable:
    """
    A decorator that retries a function up to 3 times with a 30-second delay between attempts.

    Args:
        func (Callable): The function to be retried.

    Returns:
        Callable: The wrapped function with retry logic.
    """

    def wrapper(*args: Any, **kwargs: Any) -> None:
        for attempt in range(kMaxAttempts):
            if func(*args, **kwargs):
                return
            elif attempt < kMaxAttempts - 1:
                time.sleep(kSleepTime * (attempt + 1))

    return wrapper
