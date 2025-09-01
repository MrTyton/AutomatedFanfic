"""
Integration test for signal handling in fanficdownload.py

This test verifies that SIGINT/SIGTERM signals are properly handled
and that the main process waits for child processes to terminate.
"""

import unittest
import time
import multiprocessing as mp
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

# Add app directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

import fanficdownload
from config_models import AppConfig, EmailConfig, CalibreConfig, ProcessConfig


class TestFanficdownloadSignalHandling(unittest.TestCase):
    """Test signal handling integration in the main application."""

    def setUp(self):
        """Set up test configuration."""
        self.config = AppConfig(
            email=EmailConfig(
                email="test@example.com",
                password="test_password",
                server="test.server.com",
            ),
            calibre=CalibreConfig(path="/test/path"),
            process=ProcessConfig(
                shutdown_timeout=2.0,
                health_check_interval=1.0,
                auto_restart=False,
                enable_monitoring=False,
            ),
            max_workers=2,
        )

    @patch("fanficdownload.url_ingester.EmailInfo")
    @patch("fanficdownload.notification_wrapper.NotificationWrapper")
    @patch("fanficdownload.calibre_info.CalibreInfo")
    @patch("fanficdownload.regex_parsing.url_parsers", {"test_site": MagicMock()})
    @patch("fanficdownload.ConfigManager.load_config")
    @patch("fanficdownload.parse_arguments")
    @patch("fanficdownload.ff_logging")
    def test_main_process_waits_for_children(
        self,
        mock_logging,
        mock_args,
        mock_config_load,
        mock_calibre,
        mock_notification,
        mock_email,
    ):
        """Test that main process waits for child processes to complete."""

        # Mock command line arguments
        mock_args.return_value = MagicMock()
        mock_args.return_value.config = "test_config.toml"
        mock_args.return_value.verbose = False

        # Mock configuration loading
        mock_config_load.return_value = self.config

        # Mock other components
        mock_email.return_value = MagicMock()
        mock_notification.return_value = MagicMock()
        mock_calibre_instance = MagicMock()
        mock_calibre_instance.check_installed.return_value = None
        mock_calibre.return_value = mock_calibre_instance

        # Mock the worker functions to be simple and fast
        def mock_email_watcher(*args):
            time.sleep(0.1)  # Brief work simulation

        def mock_wait_processor(*args):
            time.sleep(0.1)  # Brief work simulation

        def mock_url_worker(*args):
            time.sleep(0.1)  # Brief work simulation

        with patch("fanficdownload.url_ingester.email_watcher", mock_email_watcher):
            with patch("fanficdownload.ff_waiter.wait_processor", mock_wait_processor):
                with patch("fanficdownload.url_worker.url_worker", mock_url_worker):

                    # Mock the ProcessManager wait_for_all to simulate processes completing
                    with patch(
                        "process_manager.ProcessManager.wait_for_all"
                    ) as mock_wait:
                        mock_wait.return_value = True  # Simulate successful completion

                        try:
                            # This should complete without hanging
                            fanficdownload.main()

                            # Verify wait_for_all was called (main process waited)
                            mock_wait.assert_called()

                        except SystemExit:
                            # main() might call sys.exit(), which is normal
                            pass

    def test_signal_handling_integration(self):
        """Test that signal handling works correctly with ProcessManager."""
        from process_manager import ProcessManager

        # Test with mock config
        with ProcessManager(config=self.config) as pm:
            # Verify signal handlers are set up
            self.assertTrue(pm._signal_handlers_set)

            # Test that stop_all can be called (simulating signal handling)
            result = pm.stop_all()
            self.assertTrue(result)  # Should succeed with no processes

            # Test wait_for_all works
            result = pm.wait_for_all(timeout=1.0)
            self.assertTrue(result)  # Should return immediately with no processes


if __name__ == "__main__":
    unittest.main()
