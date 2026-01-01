from typing import NamedTuple
import unittest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from notifications import notification_base

from notifications.notification_wrapper import NotificationWrapper


class TestNotificationWrapper(unittest.TestCase):
    class SendNotificationTestCase(NamedTuple):
        workers: list
        title: str
        body: str
        site: str
        expected_calls: int

    @parameterized.expand(
        [
            # Test case: No workers
            ([], "title1", "body1", "site1", 0),
            # Test case: One enabled worker
            ([True], "title2", "body2", "site2", 1),
            # Test case: One disabled worker
            ([False], "title3", "body3", "site3", 0),
            # Test case: Multiple workers, mixed enabled and disabled
            ([True, False, True], "title4", "body4", "site4", 2),
        ]
    )
    @patch("notifications.notification_wrapper.ThreadPoolExecutor")
    @patch("notifications.notification_wrapper.AppriseNotification")
    @patch("notifications.notification_wrapper.ff_logging")
    def test_send_notification(
        self,
        workers,
        title,
        body,
        site,
        expected_calls,
        mock_ff_logging,
        mock_apprise_notification,
        mock_executor,
    ):
        # Patch AppriseNotification to not add any real workers
        mock_apprise_notification.return_value.is_enabled.return_value = False
        wrapper = NotificationWrapper()
        wrapper.notification_workers = []  # Clear any workers added by __init__
        mock_workers = []
        for enabled in workers:
            mock_worker = MagicMock(spec=notification_base.NotificationBase)
            mock_worker.enabled = enabled
            mock_workers.append(mock_worker)
        wrapper.notification_workers = mock_workers

        # Mock the executor
        mock_executor_instance = mock_executor.return_value
        mock_executor_instance.__enter__.return_value = mock_executor_instance
        mock_future = MagicMock()
        mock_executor_instance.submit.return_value = mock_future

        # Execution: Send the notification
        wrapper.send_notification(title, body, site)

        # Assertion: Check that the correct number of calls were made
        self.assertEqual(mock_executor_instance.submit.call_count, expected_calls)

        # Get all calls to submit
        submit_calls = mock_executor_instance.submit.call_args_list

        for mock_worker in mock_workers:
            if mock_worker.enabled:
                # Find the call corresponding to this worker
                found_call = False
                for call_args in submit_calls:
                    # call_args is (args, kwargs)
                    # args[0] is the wrapper function
                    # args[1] is the worker
                    # args[2] is title, args[3] is body, args[4] is site
                    args, _ = call_args
                    if (
                        len(args) >= 5
                        and args[1] == mock_worker
                        and args[2] == title
                        and args[3] == body
                        and args[4] == site
                    ):
                        found_call = True
                        break
                self.assertTrue(
                    found_call,
                    f"Submit not called for enabled worker with args {title}, {body}, {site}",
                )
            else:
                # Validate worker was NOT called
                found_call = False
                for call_args in submit_calls:
                    args, _ = call_args
                    if len(args) > 1 and args[1] == mock_worker:
                        found_call = True
                        break
                self.assertFalse(found_call, "Submit called for disabled worker")


if __name__ == "__main__":
    unittest.main()
