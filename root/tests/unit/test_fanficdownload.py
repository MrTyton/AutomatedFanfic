"""
Unit tests for the main entry point functionality in fanficdownload.py.

These tests focus on the main() function that orchestrates application startup,
configuration loading, process management initialization, and shutdown handling.
"""

import unittest
from unittest.mock import MagicMock, patch, mock_open
import sys
import argparse
from pathlib import Path

# Add the app directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))

import fanficdownload
from config_models import AppConfig, ConfigError, ConfigValidationError


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
        self.mock_config.email.ffnet_disable = True
        
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
        
        # Set up top-level config
        self.mock_config.max_workers = 4

    def test_parse_arguments_defaults(self):
        """Test parse_arguments with default values."""
        # Mock sys.argv to simulate no command line arguments
        with patch('sys.argv', ['fanficdownload.py']):
            args = fanficdownload.parse_arguments()
            
        self.assertEqual(args.config, "../config.default/config.toml")
        self.assertFalse(args.verbose)

    def test_parse_arguments_custom_config(self):
        """Test parse_arguments with custom config path."""
        with patch('sys.argv', ['fanficdownload.py', '--config', '/custom/config.toml']):
            args = fanficdownload.parse_arguments()
            
        self.assertEqual(args.config, "/custom/config.toml")
        self.assertFalse(args.verbose)

    def test_parse_arguments_verbose_flag(self):
        """Test parse_arguments with verbose flag."""
        with patch('sys.argv', ['fanficdownload.py', '--verbose']):
            args = fanficdownload.parse_arguments()
            
        self.assertEqual(args.config, "../config.default/config.toml")
        self.assertTrue(args.verbose)

    def test_parse_arguments_both_flags(self):
        """Test parse_arguments with both custom config and verbose flag."""
        with patch('sys.argv', ['fanficdownload.py', '--config', '/test/config.toml', '--verbose']):
            args = fanficdownload.parse_arguments()
            
        self.assertEqual(args.config, "/test/config.toml")
        self.assertTrue(args.verbose)

    @patch('fanficdownload.ProcessManager')
    @patch('fanficdownload.notification_wrapper.NotificationWrapper')
    @patch('fanficdownload.url_ingester.EmailInfo')
    @patch('fanficdownload.ConfigManager.load_config')
    @patch('fanficdownload.ff_logging.set_verbose')
    @patch('fanficdownload.ff_logging.log')
    @patch('fanficdownload.parse_arguments')
    def test_main_successful_startup(
        self,
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
        with patch('fanficdownload.mp.Manager') as mock_mp_manager:
            mock_manager_instance = MagicMock()
            mock_mp_manager.return_value.__enter__.return_value = mock_manager_instance
            mock_mp_manager.return_value.__exit__.return_value = None
            
            # Mock queue creation
            mock_queue = MagicMock()
            mock_manager_instance.Queue.return_value = mock_queue
            
            # Mock CalibreInfo
            with patch('fanficdownload.calibre_info.CalibreInfo') as mock_calibre_info:
                mock_cdb = MagicMock()
                mock_calibre_info.return_value = mock_cdb
                
                # Mock regex_parsing.url_parsers
                with patch('fanficdownload.regex_parsing.url_parsers', {'fanfiction.net': None, 'other': None}):
                    # Run main function
                    fanficdownload.main()
                    
                    # Verify argument parsing
                    mock_parse_args.assert_called_once()
                    
                    # Verify logging setup
                    mock_set_verbose.assert_called_once_with(True)
                    
                    # Verify configuration loading
                    mock_load_config.assert_called_once_with("test_config.toml")
                    
                    # Verify process manager initialization
                    mock_process_manager.assert_called_once_with(config=self.mock_config)
                    
                    # Verify CalibreInfo setup
                    mock_calibre_info.assert_called_once_with("test_config.toml", mock_manager_instance)
                    mock_cdb.check_installed.assert_called_once()
                    
                    # Verify process registration calls
                    expected_calls = 3  # email_watcher, waiting_watcher, and 2 worker processes
                    self.assertEqual(mock_pm_instance.register_process.call_count, 4)
                    
                    # Verify process manager lifecycle
                    mock_pm_instance.start_all.assert_called_once()
                    mock_pm_instance.wait_for_all.assert_called_once()

    @patch('fanficdownload.url_ingester.EmailInfo')
    @patch('fanficdownload.notification_wrapper.NotificationWrapper')
    @patch('fanficdownload.ConfigManager.load_config')
    @patch('fanficdownload.ff_logging.set_verbose')
    @patch('fanficdownload.ff_logging.log_failure')
    @patch('fanficdownload.parse_arguments')
    @patch('sys.exit')
    def test_main_config_error(
        self,
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
        mock_log_failure.assert_called_once_with("Configuration error: Invalid configuration file")
        mock_sys_exit.assert_called_once_with(1)

    @patch('fanficdownload.url_ingester.EmailInfo')
    @patch('fanficdownload.notification_wrapper.NotificationWrapper')
    @patch('fanficdownload.ConfigManager.load_config')
    @patch('fanficdownload.ff_logging.set_verbose')
    @patch('fanficdownload.ff_logging.log_failure')
    @patch('fanficdownload.parse_arguments')
    @patch('sys.exit')
    def test_main_config_validation_error(
        self,
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
        mock_log_failure.assert_called_once_with("Configuration validation failed: Validation failed")
        mock_sys_exit.assert_called_once_with(1)

    @patch('fanficdownload.url_ingester.EmailInfo')
    @patch('fanficdownload.notification_wrapper.NotificationWrapper')
    @patch('fanficdownload.ConfigManager.load_config')
    @patch('fanficdownload.ff_logging.set_verbose')
    @patch('fanficdownload.ff_logging.log_failure')
    @patch('fanficdownload.parse_arguments')
    @patch('sys.exit')
    def test_main_unexpected_error(
        self,
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
        mock_log_failure.assert_called_once_with("Unexpected error loading configuration: Unexpected error")
        mock_sys_exit.assert_called_once_with(1)

    @patch('fanficdownload.ProcessManager')
    @patch('fanficdownload.notification_wrapper.NotificationWrapper')
    @patch('fanficdownload.url_ingester.EmailInfo')
    @patch('fanficdownload.ConfigManager.load_config')
    @patch('fanficdownload.ff_logging.set_verbose')
    @patch('fanficdownload.ff_logging.log')
    @patch('fanficdownload.parse_arguments')
    def test_main_keyboard_interrupt_handling(
        self,
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
        mock_pm_instance.wait_for_all.side_effect = [KeyboardInterrupt("Test interrupt"), True]
        
        mock_process_manager.return_value.__enter__.return_value = mock_pm_instance
        mock_process_manager.return_value.__exit__.return_value = None
        
        # Mock multiprocessing Manager
        with patch('fanficdownload.mp.Manager') as mock_mp_manager:
            mock_manager_instance = MagicMock()
            mock_mp_manager.return_value.__enter__.return_value = mock_manager_instance
            mock_mp_manager.return_value.__exit__.return_value = None
            
            # Mock queue creation
            mock_queue = MagicMock()
            mock_manager_instance.Queue.return_value = mock_queue
            
            # Mock CalibreInfo
            with patch('fanficdownload.calibre_info.CalibreInfo') as mock_calibre_info:
                mock_cdb = MagicMock()
                mock_calibre_info.return_value = mock_cdb
                
                # Mock regex_parsing.url_parsers
                with patch('fanficdownload.regex_parsing.url_parsers', {'fanfiction.net': None}):
                    # Run main function
                    fanficdownload.main()
                    
                    # Verify KeyboardInterrupt handling
                    mock_pm_instance.stop_all.assert_called_once()


if __name__ == "__main__":
    unittest.main()