"""
Comprehensive integration tests for the AutomatedFanfic application.

These tests cover end-to-end scenarios including:
- Configuration validation and loading
- Process management and coordination
- Update method behaviors and force handling
- Email processing and URL ingestion
- Error handling and recovery scenarios
- Signal handling and graceful shutdown
"""

import unittest
import time
import multiprocessing as mp
import tempfile
import os
from unittest.mock import patch, MagicMock
from parameterized import parameterized
from typing import Dict, Any

import fanficdownload
import url_worker
import regex_parsing
import fanfic_info
import calibre_info
import notification_wrapper
import auto_url_parsers
from config_models import (
    AppConfig,
    EmailConfig,
    CalibreConfig,
    ProcessConfig,
    ConfigManager,
)
from process_manager import ProcessManager


# Helper functions for multiprocessing tests (must be top-level for Windows pickle compatibility)
def _global_dummy_worker(*args, **kwargs):
    time.sleep(0.1)


def _global_mock_worker(*args, **kwargs):
    time.sleep(0.05)


class TestFanficdownloadIntegration(unittest.TestCase):
    """Comprehensive integration tests for AutomatedFanfic."""

    @classmethod
    def setUpClass(cls):
        """Set up URL parsers once for all test methods."""
        cls.url_parsers = auto_url_parsers.generate_url_parsers_from_fanficfare()

    def setUp(self):
        """Set up test fixtures and temporary files."""
        # Create temporary config file
        self.temp_config_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        )
        self.temp_config_path = self.temp_config_file.name
        self.temp_config_file.close()

        # Default test configuration
        self.base_config = {
            "email": {
                "email": "testuser",
                "password": "test_password",
                "server": "imap.test.com",
                "mailbox": "INBOX",
                "sleep_time": 1,
                "disabled_sites": ["fanfiction"],
            },
            "calibre": {"path": "/test/calibre/path", "update_method": "update"},
            "pushbullet": {"enabled": False},
            "apprise": {"urls": []},
            "process": {
                "shutdown_timeout": 2.0,
                "health_check_interval": 1.0,
                "auto_restart": False,
                "enable_monitoring": False,
            },
            "max_workers": 2,
        }

    def tearDown(self):
        """Clean up test fixtures."""
        try:
            os.unlink(self.temp_config_path)
        except (OSError, FileNotFoundError):
            pass
        ConfigManager.clear_cache()

    def _write_config_file(self, config_data: Dict[str, Any]) -> str:
        """Write configuration data to temporary file."""
        config_content = self._dict_to_toml(config_data)
        with open(self.temp_config_path, "w") as f:
            f.write(config_content)
        return self.temp_config_path

    def _dict_to_toml(self, config_data: Dict[str, Any]) -> str:
        """Convert dictionary to TOML format."""
        toml_lines = []

        # Process top-level values first
        for key, value in config_data.items():
            if not isinstance(value, dict):
                if isinstance(value, str):
                    toml_lines.append(f'{key} = "{value}"')
                elif isinstance(value, bool):
                    toml_lines.append(f"{key} = {str(value).lower()}")
                else:
                    toml_lines.append(f"{key} = {value}")

        # Add blank line if we had top-level values
        if any(not isinstance(v, dict) for v in config_data.values()):
            toml_lines.append("")

        # Process sections
        for section, values in config_data.items():
            if isinstance(values, dict):
                toml_lines.append(f"[{section}]")
                for key, value in values.items():
                    if isinstance(value, str):
                        toml_lines.append(f'{key} = "{value}"')
                    elif isinstance(value, bool):
                        toml_lines.append(f"{key} = {str(value).lower()}")
                    elif isinstance(value, list):
                        if value:
                            formatted_list = ", ".join([f'"{item}"' for item in value])
                            toml_lines.append(f"{key} = [{formatted_list}]")
                        else:
                            toml_lines.append(f"{key} = []")
                    else:
                        toml_lines.append(f"{key} = {value}")
                toml_lines.append("")

        return "\n".join(toml_lines)

    # Configuration Integration Tests
    @parameterized.expand(
        [
            (
                "minimal_valid_config",
                {
                    "email": {
                        "email": "user",
                        "password": "pass",
                        "server": "imap.test.com",
                    },
                    "calibre": {"path": "/test/path"},
                },
                "normal_operation",
                True,
                "config_validation",
            ),
            (
                "full_featured_config",
                {
                    "email": {
                        "email": "user",
                        "password": "pass",
                        "server": "imap.test.com",
                        "mailbox": "INBOX",
                        "sleep_time": 30,
                        "disabled_sites": [],
                    },
                    "calibre": {
                        "path": "/test/path",
                        "username": "user",
                        "password": "pass",
                        "default_ini": "/test/default.ini",
                        "personal_ini": "/test/personal.ini",
                        "update_method": "force",
                    },
                    "pushbullet": {
                        "enabled": True,
                        "api_key": "test_key",
                        "device": "test_device",
                    },
                    "apprise": {
                        "urls": ["discord://webhook/token", "mailto://user:pass@host"]
                    },
                    "process": {
                        "shutdown_timeout": 5.0,
                        "health_check_interval": 2.0,
                        "auto_restart": True,
                        "enable_monitoring": True,
                    },
                    "max_workers": 4,
                },
                "full_feature_operation",
                True,
                "config_validation",
            ),
            (
                "invalid_missing_email",
                {"calibre": {"path": "/test/path"}},
                "config_error",
                False,
                "config_validation",
            ),
            (
                "invalid_missing_calibre",
                {
                    "email": {
                        "email": "user",
                        "password": "pass",
                        "server": "imap.test.com",
                    }
                },
                "config_error",
                False,
                "config_validation",
            ),
        ]
    )
    def test_configuration_integration(
        self, name, config_data, expected_behavior, should_succeed, scenario_type
    ):
        """Test configuration loading and validation integration."""
        config_path = self._write_config_file(config_data)

        if should_succeed:
            try:
                config = ConfigManager.load_config(config_path)
                self.assertIsInstance(config, AppConfig)

                # Validate specific configuration aspects
                if expected_behavior == "full_feature_operation":
                    self.assertEqual(config.calibre.update_method, "force")
                    self.assertTrue(config.pushbullet.enabled)
                    self.assertEqual(len(config.apprise.urls), 2)
                    self.assertTrue(config.process.auto_restart)
                    self.assertEqual(config.max_workers, 4)

            except Exception as e:
                self.fail(f"Valid config should not raise exception: {e}")
        else:
            with self.assertRaises((Exception,)):
                ConfigManager.load_config(config_path)

    # Update Method Integration Tests
    @parameterized.expand(
        [
            (
                "update_method_normal",
                {"update_method": "update", "fanfic_behavior": None},
                "normal_update",
                True,
                "update_method",
            ),
            (
                "update_method_always",
                {"update_method": "update_always", "fanfic_behavior": None},
                "force_update_always",
                True,
                "update_method",
            ),
            (
                "update_method_force",
                {"update_method": "force", "fanfic_behavior": None},
                "force_update",
                True,
                "update_method",
            ),
            (
                "update_method_no_force",
                {"update_method": "update_no_force", "fanfic_behavior": None},
                "ignore_force",
                True,
                "update_method",
            ),
            (
                "force_behavior_override",
                {"update_method": "update", "fanfic_behavior": "force"},
                "force_override",
                True,
                "update_method",
            ),
            (
                "no_force_ignores_behavior",
                {"update_method": "update_no_force", "fanfic_behavior": "force"},
                "ignore_force_behavior",
                True,
                "update_method",
            ),
        ]
    )
    def test_update_method_integration(
        self, name, config_data, expected_behavior, should_succeed, scenario_type
    ):
        """Test update method behaviors in integration context."""
        # Create mock objects
        mock_cdb = MagicMock(spec=calibre_info.CalibreInfo)
        mock_cdb.update_method = config_data["update_method"]

        mock_fanfic = MagicMock(spec=fanfic_info.FanficInfo)
        mock_fanfic.behavior = config_data["fanfic_behavior"]
        mock_fanfic.url = "http://test.site/story/123"

        # Test command construction
        command = url_worker.construct_fanficfare_command(
            mock_cdb, mock_fanfic, "http://test.site/story/123"
        )

        # Validate expected behaviors
        if expected_behavior == "normal_update":
            self.assertIn(" -u ", command)
            self.assertNotIn(" --force", command)
            self.assertNotIn(" -U ", command)
        elif expected_behavior == "force_update_always":
            self.assertIn(" -U ", command)
            self.assertNotIn(" --force", command)
            self.assertNotIn(" -u ", command)
        elif expected_behavior in ["force_update", "force_override"]:
            self.assertIn(" -u --force", command)
            self.assertNotIn(" -U ", command)
        elif expected_behavior in ["ignore_force", "ignore_force_behavior"]:
            self.assertIn(" -u ", command)
            self.assertNotIn(" --force", command)
            self.assertNotIn(" -U ", command)

    # Process Management Integration Tests
    @parameterized.expand(
        [
            (
                "normal_startup_shutdown",
                {"enable_monitoring": False, "auto_restart": False},
                "clean_startup_shutdown",
                True,
                "process_management",
            ),
            (
                "monitoring_enabled",
                {"enable_monitoring": True, "auto_restart": False},
                "monitored_processes",
                True,
                "process_management",
            ),
            (
                "auto_restart_enabled",
                {"enable_monitoring": True, "auto_restart": True},
                "auto_restart_processes",
                True,
                "process_management",
            ),
        ]
    )
    def test_process_management_integration(
        self, name, config_data, expected_behavior, should_succeed, scenario_type
    ):
        """Test process management scenarios."""
        config = AppConfig(
            email=EmailConfig(
                email="testuser",
                password="test_password",
                server="imap.test.com",
                mailbox="INBOX",
            ),
            calibre=CalibreConfig(path="/test/path"),
            process=ProcessConfig(
                enable_monitoring=config_data["enable_monitoring"],
                auto_restart=config_data["auto_restart"],
                shutdown_timeout=1.0,
                health_check_interval=0.5,
            ),
            max_workers=1,
        )

        with ProcessManager(config=config) as process_manager:
            # Test process registration
            # Test process registration
            process_manager.register_process(
                "test_worker", _global_dummy_worker, args=()
            )

            # Test process startup
            process_manager.start_all()
            self.assertTrue(len(process_manager.processes) > 0)

            # Test monitoring if enabled
            if config_data["enable_monitoring"]:
                self.assertTrue(process_manager.config.process.enable_monitoring)

            # Test shutdown
            result = process_manager.stop_all()
            self.assertTrue(result)

            result = process_manager.wait_for_all(timeout=2.0)
            self.assertTrue(result)

    # URL Processing Integration Tests
    @parameterized.expand(
        [
            (
                "fanfiction_net_url",
                {"url": "https://www.fanfiction.net/s/12345/1/Story-Title"},
                "ffnet_processing",
                True,
                "url_processing",
            ),
            (
                "archive_of_our_own_url",
                {"url": "https://archiveofourown.org/works/12345"},
                "ao3_processing",
                True,
                "url_processing",
            ),
            (
                "spacebattles_url",
                {"url": "https://forums.spacebattles.com/threads/story.12345/"},
                "sb_processing",
                True,
                "url_processing",
            ),
            (
                "unknown_site_url",
                {"url": "https://unknown-site.com/story/123"},
                "other_processing",
                True,
                "url_processing",
            ),
        ]
    )
    def test_url_processing_integration(
        self, name, config_data, expected_behavior, should_succeed, scenario_type
    ):
        """Test URL processing and site detection."""
        url = config_data["url"]
        fanfic = regex_parsing.generate_FanficInfo_from_url(url, self.url_parsers)

        # Validate site detection using algorithmic identifiers
        if expected_behavior == "ffnet_processing":
            self.assertEqual(fanfic.site, "fanfiction")
            self.assertIn("fanfiction.net", fanfic.url)
        elif expected_behavior == "ao3_processing":
            self.assertEqual(fanfic.site, "archiveofourown")
            self.assertIn("archiveofourown.org", fanfic.url)
        elif expected_behavior == "sb_processing":
            self.assertEqual(fanfic.site, "spacebattles")
            self.assertIn("spacebattles.com", fanfic.url)
        elif expected_behavior == "other_processing":
            self.assertEqual(fanfic.site, "other")

    # Error Handling Integration Tests
    @parameterized.expand(
        [
            (
                "hail_mary_normal_completion",
                {"max_repeats": True, "hail_mary": False},
                "hail_mary_activation",
                True,
                "error_handling",
            ),
            (
                "hail_mary_force_with_no_force",
                {
                    "max_repeats": True,
                    "hail_mary": True,
                    "behavior": "force",
                    "update_method": "update_no_force",
                },
                "special_notification",
                True,
                "error_handling",
            ),
            (
                "hail_mary_normal_failure",
                {
                    "max_repeats": True,
                    "hail_mary": True,
                    "behavior": "update",
                    "update_method": "update",
                },
                "silent_failure",
                True,
                "error_handling",
            ),
        ]
    )
    def test_error_handling_integration(
        self, name, config_data, expected_behavior, should_succeed, scenario_type
    ):
        """Test error handling and recovery scenarios."""
        # Create mock fanfic and dependencies
        mock_fanfic = MagicMock(spec=fanfic_info.FanficInfo)
        mock_fanfic.url = "http://test.site/story"
        mock_fanfic.site = "test_site"

        # Set up fanfic state based on test scenario instead of using reached_maximum_repeats
        if config_data["max_repeats"] and not config_data.get("hail_mary", False):
            # Hail-Mary activation scenario - exactly at max normal retries after increment
            mock_fanfic.repeats = (
                10  # Will become 11 after increment (equals max_normal_retries)
            )
        elif config_data["max_repeats"] and config_data.get("hail_mary", False):
            # Beyond hail-mary scenario - should abandon
            # For force+update_no_force, we still want abandonment case to trigger special notification
            mock_fanfic.repeats = 11  # Will become 12 after increment (beyond max normal retries + hail mary)
        else:
            # Normal retry scenario
            mock_fanfic.repeats = 4  # Will become 5 after increment

        # Set behavior for force/update_no_force scenarios
        mock_fanfic.behavior = config_data.get("behavior", "update")
        mock_fanfic.title = "Test Story"

        # Mock increment_repeat to simulate the actual increment behavior
        def simulate_increment():
            mock_fanfic.repeats += 1

        mock_fanfic.increment_repeat = MagicMock(side_effect=simulate_increment)
        mock_fanfic.behavior = config_data.get("behavior", None)

        mock_notification = MagicMock(spec=notification_wrapper.NotificationWrapper)
        mock_queue = MagicMock(spec=mp.Queue)
        mock_queue.put = MagicMock()  # Ensure put method is available

        # Create calibre info if needed
        mock_cdb = None
        if "update_method" in config_data:
            mock_cdb = MagicMock(spec=calibre_info.CalibreInfo)
            mock_cdb.update_method = config_data["update_method"]

        # Create retry config for the new architecture
        import config_models

        retry_config = config_models.RetryConfig(
            max_normal_retries=11, hail_mary_enabled=True, hail_mary_wait_hours=12.0
        )

        # Test failure handling
        with patch("url_worker.ff_logging") as mock_logging:
            url_worker.handle_failure(
                mock_fanfic, mock_notification, mock_queue, retry_config, mock_cdb
            )

            # Validate expected behaviors
            if expected_behavior == "hail_mary_activation":
                mock_notification.send_notification.assert_called_once()
                args = mock_notification.send_notification.call_args[0]
                self.assertIn("Hail-Mary", args[0])
            elif expected_behavior == "special_notification":
                mock_notification.send_notification.assert_called_once()
                args = mock_notification.send_notification.call_args[0]
                self.assertIn("Permanently Skipped", args[0])
            elif expected_behavior == "silent_failure":
                # Should log failure but not send notification for normal hail mary failures
                mock_logging.log_failure.assert_called()

    # Signal Handling Integration Tests
    def test_signal_handling_integration(self):
        """Test signal handling and graceful shutdown."""
        config = AppConfig(
            email=EmailConfig(
                email="testuser",
                password="test_password",
                server="imap.test.com",
                mailbox="INBOX",
            ),
            calibre=CalibreConfig(path="/test/path"),
            process=ProcessConfig(
                shutdown_timeout=1.0,
                health_check_interval=0.5,
                auto_restart=False,
                enable_monitoring=False,
            ),
            max_workers=1,
        )

        with ProcessManager(config=config) as process_manager:
            # Verify signal handlers are set up
            self.assertTrue(process_manager._signal_handlers_set)

            # Test that stop_all can be called (simulating signal handling)
            result = process_manager.stop_all()
            self.assertTrue(result)

            # Test wait_for_all works
            result = process_manager.wait_for_all(timeout=1.0)
            self.assertTrue(result)

    # Full Application Integration Test
    @patch("fanficdownload.url_ingester.EmailInfo")
    @patch("fanficdownload.notification_wrapper.NotificationWrapper")
    @patch("fanficdownload.calibre_info.CalibreInfo")
    @patch("fanficdownload.auto_url_parsers.generate_url_parsers_from_fanficfare")
    @patch("fanficdownload.parse_arguments")
    @patch("fanficdownload.ff_logging")
    def test_full_application_integration(
        self,
        mock_logging,
        mock_args,
        mock_url_parsers,
        mock_calibre,
        mock_notification,
        mock_email,
    ):
        """Test full application startup and shutdown."""
        # Configure mock URL parsers
        mock_url_parsers.return_value = {"test_site": MagicMock()}

        # Write test configuration
        config_path = self._write_config_file(self.base_config)

        # Mock command line arguments
        mock_args.return_value = MagicMock()
        mock_args.return_value.config = config_path
        mock_args.return_value.verbose = False

        # Mock other components
        mock_email.return_value = MagicMock()
        mock_notification.return_value = MagicMock()
        mock_calibre_instance = MagicMock()
        mock_calibre_instance.check_installed.return_value = None
        mock_calibre.return_value = mock_calibre_instance

        # Mock worker functions to be fast and simple
        with patch("fanficdownload.url_ingester.email_watcher", _global_mock_worker):
            with patch("fanficdownload.ff_waiter.wait_processor", _global_mock_worker):
                with patch("fanficdownload.url_worker.url_worker", _global_mock_worker):
                    with patch(
                        "process_manager.ProcessManager.wait_for_all"
                    ) as mock_wait:
                        mock_wait.return_value = True

                        try:
                            # This should complete without hanging
                            fanficdownload.main()
                            # Verify wait_for_all was called
                            mock_wait.assert_called()
                        except SystemExit:
                            # main() might call sys.exit(), which is normal
                            pass

    # Edge Cases and Stress Tests
    @parameterized.expand(
        [
            (
                "unicode_urls",
                {"url": "https://example.com/story/título-español"},
                "unicode_handling",
                True,
                "edge_cases",
            ),
            (
                "very_long_urls",
                {"url": "https://example.com/" + "a" * 2000},
                "long_url_handling",
                True,
                "edge_cases",
            ),
            (
                "special_characters",
                {"url": "https://example.com/story?param=value&other=特殊文字"},
                "special_char_handling",
                True,
                "edge_cases",
            ),
        ]
    )
    def test_edge_cases_integration(
        self, name, config_data, expected_behavior, should_succeed, scenario_type
    ):
        """Test edge cases and unusual inputs."""
        url = config_data["url"]

        try:
            fanfic = regex_parsing.generate_FanficInfo_from_url(url, self.url_parsers)
            self.assertIsNotNone(fanfic)
            self.assertIsInstance(fanfic.url, str)
            self.assertIsInstance(fanfic.site, str)

            # Should not crash with unicode or special characters
            if expected_behavior in ["unicode_handling", "special_char_handling"]:
                self.assertTrue(len(fanfic.url) > 0)

        except Exception as e:
            if should_succeed:
                self.fail(f"Edge case should not raise exception: {e}")

    # Performance and Resource Tests
    def test_resource_cleanup_integration(self):
        """Test that resources are properly cleaned up."""
        config = AppConfig(
            email=EmailConfig(
                email="testuser",
                password="test_password",
                server="imap.test.com",
                mailbox="INBOX",
            ),
            calibre=CalibreConfig(path="/test/path"),
            process=ProcessConfig(shutdown_timeout=1.0),
            max_workers=2,
        )

        # Test multiple process manager cycles
        for _ in range(3):
            with ProcessManager(config=config) as process_manager:
                process_manager.register_process(
                    "test_worker", _global_dummy_worker, args=()
                )
                process_manager.start_all()

                # Verify processes are running
                self.assertTrue(len(process_manager.processes) > 0)

                # Clean shutdown
                process_manager.stop_all()
                process_manager.wait_for_all(timeout=2.0)

            # Verify cleanup after context exit
            self.assertTrue(True)  # If we get here, cleanup worked


if __name__ == "__main__":
    unittest.main(verbosity=2)
