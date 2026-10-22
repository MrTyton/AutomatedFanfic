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
    def test_send_notification(
        self,
        workers,
        title,
        body,
        site,
        expected_calls,
        mock_apprise_notification,
        mock_executor,
    ):
        # Patch AppriseNotification to not add any real workers
        mock_apprise_notification.return_value.is_enabled.return_value = False
        mock_store = MagicMock()
        mock_store.get.return_value = None
        wrapper = NotificationWrapper(MagicMock(), mock_store, MagicMock())
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

        if expected_calls == 0:
            mock_executor_instance.submit.assert_not_called()
            for mock_worker in mock_workers:
                mock_worker.send_notification.assert_not_called()
        elif expected_calls == 1:
            # Single enabled worker is called directly without spawning a ThreadPoolExecutor
            mock_executor_instance.submit.assert_not_called()
            for mock_worker in mock_workers:
                if mock_worker.enabled:
                    mock_worker.send_notification.assert_called_once_with(
                        title, body, site
                    )
                else:
                    mock_worker.send_notification.assert_not_called()
        else:
            # Multiple enabled workers use ThreadPoolExecutor
            self.assertEqual(mock_executor_instance.submit.call_count, expected_calls)
            submit_calls = mock_executor_instance.submit.call_args_list

            for mock_worker in mock_workers:
                if mock_worker.enabled:
                    found_call = False
                    for call_args in submit_calls:
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
                    found_call = False
                    for call_args in submit_calls:
                        args, _ = call_args
                        if len(args) > 1 and args[1] == mock_worker:
                            found_call = True
                            break
                    self.assertFalse(found_call, "Submit called for disabled worker")

    @patch("notifications.notification_wrapper.AppriseNotification")
    def test_init_passes_config_and_config_store_to_apprise(
        self, mock_apprise_notification
    ):
        """NotificationWrapper passes config and config_store directly to AppriseNotification."""
        mock_apprise_notification.return_value.is_enabled.return_value = True
        mock_cfg = MagicMock()
        mock_store = MagicMock()
        mock_store.get.return_value = None
        mock_recorder = MagicMock()

        wrapper = NotificationWrapper(mock_cfg, mock_store, mock_recorder)

        mock_apprise_notification.assert_called_once_with(mock_cfg, mock_store)
        self.assertEqual(len(wrapper.notification_workers), 1)
        self.assertIs(wrapper.history_recorder, mock_recorder)


if __name__ == "__main__":
    unittest.main()
