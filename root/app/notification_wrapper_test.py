from typing import NamedTuple, Optional, Type
import unittest
from unittest.mock import call, MagicMock, patch

from parameterized import parameterized

import notification_base
from notification_wrapper import NotificationWrapper


class TestNotificationWrapper(unittest.TestCase):
    class AddNotificationWorkerTestCase(NamedTuple):
        worker_enabled: bool
        expected_length: int

    @parameterized.expand(
        [
            # Test case: Adding an enabled notification worker
            AddNotificationWorkerTestCase(
                worker_enabled=True,
                expected_length=1,
            ),
            # Test case: Adding a disabled notification worker
            AddNotificationWorkerTestCase(
                worker_enabled=False,
                expected_length=1,
            ),
        ]
    )
    def test_add_notification_worker(self, worker_enabled, expected_length):
        # Setup: Create a NotificationWrapper instance and a mock notification worker
        wrapper = NotificationWrapper()
        mock_worker = MagicMock(spec=notification_base.NotificationBase)
        mock_worker.enabled = worker_enabled

        # Execution: Add the notification worker
        wrapper.add_notification_worker(mock_worker)

        # Assertion: Check that the worker was added
        self.assertEqual(len(wrapper.notification_workers), expected_length)
        self.assertEqual(wrapper.notification_workers[0], mock_worker)

    class SendNotificationTestCase(NamedTuple):
        workers: list
        title: str
        body: str
        site: str
        expected_calls: int

    @parameterized.expand(
        [
            # Test case: No workers
            SendNotificationTestCase(
                workers=[],
                title="title1",
                body="body1",
                site="site1",
                expected_calls=0,
            ),
            # Test case: One enabled worker
            SendNotificationTestCase(
                workers=[True],
                title="title2",
                body="body2",
                site="site2",
                expected_calls=1,
            ),
            # Test case: One disabled worker
            SendNotificationTestCase(
                workers=[False],
                title="title3",
                body="body3",
                site="site3",
                expected_calls=0,
            ),
            # Test case: Multiple workers, mixed enabled and disabled
            SendNotificationTestCase(
                workers=[True, False, True],
                title="title4",
                body="body4",
                site="site4",
                expected_calls=2,
            ),
        ]
    )
    @patch("notification_wrapper.ThreadPoolExecutor")
    def test_send_notification(
        self,
        workers,
        title,
        body,
        site,
        expected_calls,
        mock_executor,
    ):
        # Setup: Create a NotificationWrapper instance and mock notification workers
        wrapper = NotificationWrapper()
        mock_workers = []
        for enabled in workers:
            mock_worker = MagicMock(spec=notification_base.NotificationBase)
            mock_worker.enabled = enabled
            mock_workers.append(mock_worker)
            wrapper.add_notification_worker(mock_worker)

        # Mock the executor
        mock_executor_instance = mock_executor.return_value
        mock_executor_instance.__enter__.return_value = mock_executor_instance
        mock_future = MagicMock()
        mock_executor_instance.submit.return_value = mock_future

        # Execution: Send the notification
        wrapper.send_notification(title, body, site)

        # Assertion: Check that the correct number of calls were made
        self.assertEqual(
            mock_executor_instance.submit.call_count, expected_calls
        )
        for mock_worker in mock_workers:
            if mock_worker.enabled:
                mock_executor_instance.submit.assert_any_call(
                    mock_worker.send_notification, title, body, site
                )
            else:
                assert (
                    call(mock_worker.send_notification, title, body, site)
                    not in mock_executor_instance.submit
                )


if __name__ == "__main__":
    unittest.main()
