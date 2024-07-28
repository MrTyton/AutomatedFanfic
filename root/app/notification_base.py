import time
from typing import Callable, Any


class NotificationBase:
    def __init__(self):
        """
        Initializes the NotificationBase class.
        """
        self.enabled = False

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
        attempts = 3
        for attempt in range(attempts):
            if func(*args, **kwargs):
                return
            else:
                time.sleep(10 * (attempt + 1))

    return wrapper
