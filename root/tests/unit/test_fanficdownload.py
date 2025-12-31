"""
Unit tests for the main entry point functionality in fanficdownload.py.

These tests focus on the main() function that orchestrates application startup,
configuration loading, process management initialization, and shutdown handling.
"""

import unittest
from unittest.mock import MagicMock, patch
from typing import NamedTuple
from parameterized import parameterized


import fanficdownload  # noqa: E402
from models.config_models import (
    AppConfig,
    ConfigError,
    ConfigValidationError,
)  # noqa: E402


class TestFanficDownloadMain(unittest.TestCase):
    """Test the main() function and argument parsing in fanficdownload.py."""

    def setUp(self):
        """Set up common test fixtures."""
        # Create mock config with nested attribute structure
        self.mock_config = MagicMock(spec=AppConfig)

        # Set up email config
        self.mock_config.email = MagicMock()
        self.mock_config.email.email = "test@example.com"
        self.mock_config.email.server = "imap.gmail.com"
        self.mock_config.email.mailbox = "INBOX"
        self.mock_config.email.sleep_time = 60
        self.mock_config.email.disabled_sites = ["fanfiction"]

        # Set up calibre config
        self.mock_config.calibre = MagicMock()
        self.mock_config.calibre.path = "/test/calibre"
        self.mock_config.calibre.default_ini = None
        self.mock_config.calibre.personal_ini = None
        self.mock_config.calibre.update_method = "update"

        # Set up pushbullet config
        self.mock_config.pushbullet = MagicMock()
        self.mock_config.pushbullet.enabled = False

        # Set up apprise config
        self.mock_config.apprise = MagicMock()
        self.mock_config.apprise.urls = []

        # Set up process config
        self.mock_config.process = MagicMock()
        self.mock_config.process.enable_monitoring = True
        self.mock_config.process.auto_restart = True

        # Set up retry config
        self.mock_config.retry = MagicMock()

        # Set up top-level config
        self.mock_config.max_workers = 4

    class ParseArgumentsTestCase(NamedTuple):
        name: str
        sys_argv: list[str]
        expected_config: str
        expected_verbose: bool

    @parameterized.expand(
        [
            ("defaults", ["fanficdownload.py"], "../config.default/config.toml", False),
            (
                "custom_config",
                ["fanficdownload.py", "--config", "/custom/config.toml"],
                "/custom/config.toml",
                False,
            ),
            (
                "verbose_flag",
                ["fanficdownload.py", "--verbose"],
                "../config.default/config.toml",
                True,
            ),
            (
                "both_flags",
                ["fanficdownload.py", "--config", "/test/config.toml", "--verbose"],
                "/test/config.toml",
                True,
            ),
        ]
    )
    def test_parse_arguments(self, name, sys_argv, expected_config, expected_verbose):
        """Test parse_arguments with various argument combinations."""
        with patch("sys.argv", sys_argv):
            args = fanficdownload.parse_arguments()

        self.assertEqual(args.config, expected_config)
        self.assertEqual(args.verbose, expected_verbose)

    @patch("fanficdownload.ProcessManager")
    @patch("fanficdownload.notification_wrapper.NotificationWrapper")
    @patch("fanficdownload.url_ingester.EmailInfo")
    @patch("fanficdownload.ConfigManager.load_config")
    @patch("fanficdownload.ff_logging.set_verbose")
    @patch("fanficdownload.ff_logging.log")
    @patch("fanficdownload.parse_arguments")
    @patch(
        "fanficdownload.calibredb_utils.CalibreDBClient.get_calibre_version",
        return_value="5.0.0",
    )
    @patch("fanficdownload.calibredb_utils.CalibreDBClient")
    def test_main_successful_startup(
        self,
        mock_calibre_client,
        mock_get_calibre_version,
        mock_parse_args,
        mock_log,
        mock_set_verbose,
        mock_load_config,
        mock_email_info,
        mock_notification,
        mock_process_manager,
    ):
        """Test successful main() execution path."""
        # Set up argument parsing
        mock_args = MagicMock()
        mock_args.config = "test_config.toml"
        mock_args.verbose = True
        mock_parse_args.return_value = mock_args

        # Set up configuration loading
        mock_load_config.return_value = self.mock_config

        # Set up process manager context
        mock_pm_instance = MagicMock()
        mock_process_manager.return_value.__enter__.return_value = mock_pm_instance
        mock_process_manager.return_value.__exit__.return_value = None

        # Mock multiprocessing Manager
        with patch("fanficdownload.mp.Manager") as mock_mp_manager:
            mock_manager_instance = MagicMock()
            mock_mp_manager.return_value.__enter__.return_value = mock_manager_instance
            mock_mp_manager.return_value.__exit__.return_value = None

            # Mock queue creation
            mock_queue = MagicMock()
            mock_manager_instance.Queue.return_value = mock_queue

            # Mock CalibreInfo
            with patch("fanficdownload.calibre_info.CalibreInfo") as mock_calibre_info:
                mock_cdb = MagicMock()
                mock_calibre_info.return_value = mock_cdb

                # Mock auto_url_parsers.generate_url_parsers_from_fanficfare
                with patch(
                    "fanficdownload.auto_url_parsers.generate_url_parsers_from_fanficfare",
                    return_value={"fanfiction": None, "other": None},
                ):
                    # Run main function
                    fanficdownload.main()

                    # Verify argument parsing
                    mock_parse_args.assert_called_once()

                    # Verify logging setup
                    mock_set_verbose.assert_called_once_with(True)

                    # Verify configuration loading
                    mock_load_config.assert_called_once_with("test_config.toml")

                    # Verify process manager initialization
                    mock_process_manager.assert_called_once_with(
                        config=self.mock_config
                    )

                    # Verify CalibreInfo setup
                    mock_calibre_info.assert_called_once_with(
                        "test_config.toml", mock_manager_instance
                    )
                    mock_cdb.check_installed.assert_called_once()

                    # Verify process registration calls
                    # 1 email_watcher
                    # 1 waiting_watcher
                    # 1 coordinator
                    # 4 workers (max_workers=4)
                    self.assertEqual(mock_pm_instance.register_process.call_count, 7)

                    # Verify process manager lifecycle
                    mock_pm_instance.start_all.assert_called_once()
                    mock_pm_instance.wait_for_all.assert_called_once()

    @patch("fanficdownload.url_ingester.EmailInfo")
    @patch("fanficdownload.notification_wrapper.NotificationWrapper")
    @patch("fanficdownload.ConfigManager.load_config")
    @patch("fanficdownload.ff_logging.set_verbose")
    @patch("fanficdownload.ff_logging.log_failure")
    @patch("fanficdownload.parse_arguments")
    @patch("sys.exit")
    @patch(
        "fanficdownload.calibredb_utils.CalibreDBClient.get_calibre_version",
        return_value="5.0.0",
    )
    def test_main_config_error(
        self,
        mock_get_calibre_version,
        mock_sys_exit,
        mock_parse_args,
        mock_log_failure,
        mock_set_verbose,
        mock_load_config,
        mock_notification,
        mock_email_info,
    ):
        """Test main() handles ConfigError correctly."""
        # Set up argument parsing
        mock_args = MagicMock()
        mock_args.config = "invalid_config.toml"
        mock_args.verbose = False
        mock_parse_args.return_value = mock_args

        # Set up configuration loading to raise ConfigError on first call
        mock_load_config.side_effect = ConfigError("Invalid configuration file")

        # Make sys.exit raise SystemExit so function actually exits
        mock_sys_exit.side_effect = SystemExit(1)

        # Run main function and expect SystemExit
        with self.assertRaises(SystemExit):
            fanficdownload.main()

        # Verify error handling
        mock_log_failure.assert_called_once_with(
            "Configuration error: Invalid configuration file"
        )
        mock_sys_exit.assert_called_once_with(1)

    @patch("fanficdownload.url_ingester.EmailInfo")
    @patch("fanficdownload.notification_wrapper.NotificationWrapper")
    @patch("fanficdownload.ConfigManager.load_config")
    @patch("fanficdownload.ff_logging.set_verbose")
    @patch("fanficdownload.ff_logging.log_failure")
    @patch("fanficdownload.parse_arguments")
    @patch("sys.exit")
    @patch(
        "fanficdownload.calibredb_utils.CalibreDBClient.get_calibre_version",
        return_value="5.0.0",
    )
    def test_main_config_validation_error(
        self,
        mock_get_calibre_version,
        mock_sys_exit,
        mock_parse_args,
        mock_log_failure,
        mock_set_verbose,
        mock_load_config,
        mock_notification,
        mock_email_info,
    ):
        """Test main() handles ConfigValidationError correctly."""
        # Set up argument parsing
        mock_args = MagicMock()
        mock_args.config = "invalid_config.toml"
        mock_args.verbose = False
        mock_parse_args.return_value = mock_args

        # Set up configuration loading to raise ConfigValidationError on first call
        mock_load_config.side_effect = ConfigValidationError("Validation failed")

        # Make sys.exit raise SystemExit so function actually exits
        mock_sys_exit.side_effect = SystemExit(1)

        # Run main function and expect SystemExit
        with self.assertRaises(SystemExit):
            fanficdownload.main()

        # Verify error handling
        mock_log_failure.assert_called_once_with(
            "Configuration validation failed: Validation failed"
        )
        mock_sys_exit.assert_called_once_with(1)

    @patch("fanficdownload.url_ingester.EmailInfo")
    @patch("fanficdownload.notification_wrapper.NotificationWrapper")
    @patch("fanficdownload.ConfigManager.load_config")
    @patch("fanficdownload.ff_logging.set_verbose")
    @patch("fanficdownload.ff_logging.log_failure")
    @patch("fanficdownload.parse_arguments")
    @patch("sys.exit")
    @patch(
        "fanficdownload.calibredb_utils.CalibreDBClient.get_calibre_version",
        return_value="5.0.0",
    )
    def test_main_unexpected_error(
        self,
        mock_get_calibre_version,
        mock_sys_exit,
        mock_parse_args,
        mock_log_failure,
        mock_set_verbose,
        mock_load_config,
        mock_notification,
        mock_email_info,
    ):
        """Test main() handles unexpected errors during configuration loading."""
        # Set up argument parsing
        mock_args = MagicMock()
        mock_args.config = "config.toml"
        mock_args.verbose = False
        mock_parse_args.return_value = mock_args

        # Set up configuration loading to raise unexpected error on first call
        mock_load_config.side_effect = Exception("Unexpected error")

        # Make sys.exit raise SystemExit so function actually exits
        mock_sys_exit.side_effect = SystemExit(1)

        # Run main function and expect SystemExit
        with self.assertRaises(SystemExit):
            fanficdownload.main()

        # Verify error handling
        mock_log_failure.assert_called_once_with(
            "Unexpected error loading configuration: Unexpected error"
        )
        mock_sys_exit.assert_called_once_with(1)

    @patch("fanficdownload.ProcessManager")
    @patch("fanficdownload.notification_wrapper.NotificationWrapper")
    @patch("fanficdownload.url_ingester.EmailInfo")
    @patch("fanficdownload.ConfigManager.load_config")
    @patch("fanficdownload.ff_logging.set_verbose")
    @patch("fanficdownload.ff_logging.log")
    @patch("fanficdownload.parse_arguments")
    @patch(
        "fanficdownload.calibredb_utils.CalibreDBClient.get_calibre_version",
        return_value="5.0.0",
    )
    @patch("fanficdownload.calibredb_utils.CalibreDBClient")
    def test_main_keyboard_interrupt_handling(
        self,
        mock_calibre_client,
        mock_get_calibre_version,
        mock_parse_args,
        mock_log,
        mock_set_verbose,
        mock_load_config,
        mock_email_info,
        mock_notification,
        mock_process_manager,
    ):
        """Test main() handles KeyboardInterrupt correctly."""
        # Set up argument parsing
        mock_args = MagicMock()
        mock_args.config = "test_config.toml"
        mock_args.verbose = False
        mock_parse_args.return_value = mock_args

        # Set up configuration loading
        mock_load_config.return_value = self.mock_config

        # Set up process manager to raise KeyboardInterrupt
        mock_pm_instance = MagicMock()
        mock_pm_instance.wait_for_all.side_effect = KeyboardInterrupt("Test interrupt")
        mock_pm_instance._shutdown_event.is_set.return_value = False
        mock_pm_instance.wait_for_all.side_effect = [
            KeyboardInterrupt("Test interrupt"),
            True,
        ]

        mock_process_manager.return_value.__enter__.return_value = mock_pm_instance
        mock_process_manager.return_value.__exit__.return_value = None

        # Mock multiprocessing Manager
        with patch("fanficdownload.mp.Manager") as mock_mp_manager:
            mock_manager_instance = MagicMock()
            mock_mp_manager.return_value.__enter__.return_value = mock_manager_instance
            mock_mp_manager.return_value.__exit__.return_value = None

            # Mock queue creation
            mock_queue = MagicMock()
            mock_manager_instance.Queue.return_value = mock_queue

            # Mock CalibreInfo
            with patch("fanficdownload.calibre_info.CalibreInfo") as mock_calibre_info:
                mock_cdb = MagicMock()
                mock_calibre_info.return_value = mock_cdb

                # Mock auto_url_parsers.generate_url_parsers_from_fanficfare
                with patch(
                    "fanficdownload.auto_url_parsers.generate_url_parsers_from_fanficfare",
                    return_value={"fanfiction": None},
                ):
                    # Run main function
                    fanficdownload.main()

                    # Verify KeyboardInterrupt handling
                    mock_pm_instance.stop_all.assert_called_once()


if __name__ == "__main__":
    unittest.main()
