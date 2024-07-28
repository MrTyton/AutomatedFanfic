import notification_base
from typing import List
from concurrent.futures import ThreadPoolExecutor


class NotificationWrapper:
    def __init__(self):
        """
        Initializes the NotificationWrapper with an empty list of notification workers.
        """
        self.notification_workers: List[notification_base.NotificationBase] = []

    def add_notification_worker(
        self, notification_worker: notification_base.NotificationBase
    ) -> None:
        """
        Adds a notification worker to the list.

        Args:
            notification_worker (notification_base.NotificationBase): The notification worker to add.
        """
        self.notification_workers.append(notification_worker)

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
