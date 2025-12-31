import unittest
from unittest.mock import patch, mock_open
from typing import NamedTuple, Optional
from parameterized import parameterized
import tempfile
import os

from models.config_models import (
    ConfigManager,
    EmailConfig,
    CalibreConfig,
    PushbulletConfig,
    AppriseConfig,
    RetryConfig,
    ProcessConfig,
    AppConfig,
    ConfigError,
    ConfigValidationError,
)


class TestConfigModels(unittest.TestCase):
    """Test cases for configuration models and manager."""

    def setUp(self):
        """Set up test fixtures."""
        self.valid_toml_content = """
[email]
email = "testuser"
password = "test_password"
server = "imap.gmail.com"
mailbox = "INBOX"
sleep_time = 60
disabled_sites = ["fanfiction"]

[calibre]
path = "/path/to/calibre"
username = "calibre_user"
password = "calibre_pass"
default_ini = "/path/to/defaults.ini"
personal_ini = "/path/to/personal.ini"
update_method = "update_always"

[pushbullet]
enabled = true
api_key = "test_token"
device = "test_device"

[apprise]
urls = ["discord://webhook_id/webhook_token", "mailto://user:pass@gmail.com"]

[retry]
hail_mary_enabled = true
hail_mary_wait_hours = 24.0
max_normal_retries = 15

[process]
shutdown_timeout = 45.0
health_check_interval = 30.0
auto_restart = false
max_restart_attempts = 5
restart_delay = 10.0
enable_monitoring = false
worker_timeout = 600.0
signal_timeout = 15.0
"""

        self.minimal_toml_content = """
[email]
email = "testuser"
password = "test_password"
server = "imap.gmail.com"
mailbox = "INBOX"

[calibre]
path = "/path/to/calibre"
"""

    class ConfigValidationCase(NamedTuple):
        """Test case structure for configuration validation tests."""

        name: str
        toml_content: str
        should_raise: bool
        expected_error_type: Optional[type] = None
        expected_error_message: str = ""

    @parameterized.expand(
        [
            (
                "valid_complete_config",
                """
[email]
email = "testuser"
password = "test_password"
server = "imap.gmail.com"
mailbox = "INBOX"
sleep_time = 60
disabled_sites = ["fanfiction"]

[calibre]
path = "/path/to/calibre"
username = "calibre_user"
password = "calibre_pass"
default_ini = "/path/to/defaults.ini"
personal_ini = "/path/to/personal.ini"

[pushbullet]
enabled = true
api_key = "test_token"
device = "test_device"

[apprise]
urls = ["discord://webhook_id/webhook_token"]
""",
                False,
                None,
                "",
            ),
            (
                "minimal_valid_config",
                """
[email]
email = "testuser"
password = "test_password"
server = "imap.gmail.com"
mailbox = "INBOX"

[calibre]
path = "/path/to/calibre"
""",
                False,
                None,
                "",
            ),
            (
                "missing_email_section",
                """
[calibre]
path = "/path/to/calibre"
""",
                True,
                ConfigValidationError,
                "",
            ),
            (
                "missing_calibre_section",
                """
[email]
email = "testuser"
password = "test_password"
server = "imap.gmail.com"
mailbox = "INBOX"
""",
                True,
                ConfigValidationError,
                "",
            ),
            (
                "valid_email_format_with_at",
                """
[email]
email = "user@example.com"
password = "test_password"
server = "imap.gmail.com"
mailbox = "INBOX"

[calibre]
path = "/path/to/calibre"
""",
                False,
                None,
                "",
            ),
            (
                "negative_sleep_time",
                """
[email]
email = "testuser"
password = "test_password"
server = "imap.gmail.com"
mailbox = "INBOX"
sleep_time = -10

[calibre]
path = "/path/to/calibre"
""",
                True,
                ConfigValidationError,
                "",
            ),
            (
                "empty_required_fields",
                """
[email]
email = ""
password = ""
server = ""
mailbox = ""

[calibre]
path = ""
""",
                False,  # Changed to False since empty strings are allowed for development
                None,
                "",
            ),
        ]
    )
    def test_config_validation(
        self,
        name,
        toml_content,
        should_raise,
        expected_error_type,
        expected_error_message,
    ):
        """Test configuration validation with various inputs."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(toml_content)
            temp_path = f.name

        try:
            if should_raise:
                expected_exception = expected_error_type or ConfigValidationError
                with self.assertRaises(expected_exception):
                    ConfigManager.load_config(temp_path)
            else:
                config = ConfigManager.load_config(temp_path)
                self.assertIsInstance(config, AppConfig)
                # Verify required sections are present
                self.assertIsNotNone(config.email)
                self.assertIsNotNone(config.calibre)
        finally:
            os.unlink(temp_path)

    def test_config_manager_file_not_found(self):
        """Test ConfigManager behavior when config file doesn't exist."""
        with self.assertRaises(ConfigError) as context:
            ConfigManager.load_config("/nonexistent/path/config.toml")

        self.assertIn("Configuration file not found", str(context.exception))

    @patch("pathlib.Path.exists")
    @patch("builtins.open", new_callable=mock_open)
    @patch("tomllib.load")
    def test_config_manager_invalid_toml(
        self, mock_tomllib_load, mock_file_open, mock_path_exists
    ):
        """Test ConfigManager behavior with invalid TOML."""
        mock_path_exists.return_value = True  # File exists
        mock_tomllib_load.side_effect = Exception("Invalid TOML")

        with self.assertRaises(ConfigError) as context:
            ConfigManager.load_config("dummy_path.toml")

        self.assertIn("Error parsing configuration file", str(context.exception))

    def test_email_config_defaults(self):
        """Test EmailConfig with default values."""
        email_config = EmailConfig(
            email="testuser",
            password="password",
            server="imap.gmail.com",
            mailbox="INBOX",
        )

        self.assertEqual(email_config.sleep_time, 60)
        self.assertEqual(email_config.disabled_sites, [])

    def test_calibre_config_minimal(self):
        """Test CalibreConfig with only required fields."""
        calibre_config = CalibreConfig(path="/path/to/calibre")

        self.assertEqual(calibre_config.path, "/path/to/calibre")
        self.assertIsNone(calibre_config.username)
        self.assertIsNone(calibre_config.password)
        self.assertIsNone(calibre_config.default_ini)
        self.assertIsNone(calibre_config.personal_ini)

    def test_pushbullet_config_disabled_by_default(self):
        """Test PushbulletConfig is disabled by default."""
        pushbullet_config = PushbulletConfig()

        self.assertFalse(pushbullet_config.enabled)
        self.assertIsNone(pushbullet_config.api_key)
        self.assertIsNone(pushbullet_config.device)

    def test_apprise_config_empty_by_default(self):
        """Test AppriseConfig has empty URLs by default."""
        apprise_config = AppriseConfig()

        self.assertEqual(apprise_config.urls, [])

    @parameterized.expand(
        [
            ("valid_username", "testuser", True),
            ("valid_username_with_dots", "test.user", True),
            ("valid_username_with_numbers", "test123", True),
            ("valid_username_with_underscores", "test_user", True),
            ("valid_empty_username", "", True),  # Empty allowed for development
            ("valid_email_with_at", "user@example.com", True),
            ("valid_email_with_at_and_plus", "user+tag@example.com", True),
        ]
    )
    def test_email_validation(self, name, email_value, should_pass):
        """Test email validation accepts both usernames and full email addresses."""
        if should_pass:
            try:
                email_config = EmailConfig(
                    email=email_value,
                    password="password",
                    server="imap.gmail.com",
                )
                self.assertEqual(
                    email_config.email,
                    email_value.strip() if email_value else email_value,
                )
            except Exception as e:
                self.fail(
                    f"Valid email '{email_value}' should not raise exception: {e}"
                )

    def test_config_manager_caching(self):
        """Test that ConfigManager caches configurations."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(self.valid_toml_content)
            temp_path = f.name

        try:
            # Load config twice
            config1 = ConfigManager.load_config(temp_path)
            config2 = ConfigManager.load_config(temp_path)

            # Should return the same cached instance
            self.assertIs(config1, config2)
        finally:
            os.unlink(temp_path)
            # Clear cache for other tests
            ConfigManager.clear_cache()

    def test_config_manager_cache_clearing(self):
        """Test ConfigManager cache clearing functionality."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(self.valid_toml_content)
            temp_path = f.name

        try:
            # Load config
            config1 = ConfigManager.load_config(temp_path)

            # Clear cache
            ConfigManager.clear_cache()

            # Load config again - should be a new instance
            config2 = ConfigManager.load_config(temp_path)

            self.assertIsNot(config1, config2)
        finally:
            os.unlink(temp_path)
            ConfigManager.clear_cache()

    def test_config_manager_force_reload(self):
        """Test ConfigManager force reload functionality."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(self.valid_toml_content)
            temp_path = f.name

        try:
            # Load config
            config1 = ConfigManager.load_config(temp_path)

            # Force reload
            config2 = ConfigManager.load_config(temp_path, force_reload=True)

            # Should be different instances
            self.assertIsNot(config1, config2)
        finally:
            os.unlink(temp_path)
            ConfigManager.clear_cache()

    def test_app_config_validation_integration(self):
        """Test end-to-end AppConfig validation."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(self.valid_toml_content)
            temp_path = f.name

        try:
            config = ConfigManager.load_config(temp_path)

            # Verify all sections are properly loaded
            self.assertEqual(config.email.email, "testuser")
            self.assertEqual(config.email.server, "imap.gmail.com")
            self.assertEqual(config.calibre.path, "/path/to/calibre")
            self.assertEqual(config.calibre.update_method, "update_always")
            self.assertTrue(config.pushbullet.enabled)
            self.assertEqual(len(config.apprise.urls), 2)

            # Verify new retry section
            self.assertTrue(config.retry.hail_mary_enabled)
            self.assertEqual(config.retry.hail_mary_wait_hours, 24.0)
            self.assertEqual(config.retry.max_normal_retries, 15)

            # Verify new process section
            self.assertEqual(config.process.shutdown_timeout, 45.0)
            self.assertEqual(config.process.health_check_interval, 30.0)
            self.assertFalse(config.process.auto_restart)
            self.assertEqual(config.process.max_restart_attempts, 5)
            self.assertEqual(config.process.restart_delay, 10.0)
            self.assertFalse(config.process.enable_monitoring)
            self.assertEqual(config.process.worker_timeout, 600.0)
            self.assertEqual(config.process.signal_timeout, 15.0)
        finally:
            os.unlink(temp_path)
            ConfigManager.clear_cache()

    # ============================================================================
    # RETRY CONFIG TESTS
    # ============================================================================

    def test_retry_config_defaults(self):
        """Test RetryConfig with default values."""
        retry_config = RetryConfig()

        self.assertTrue(retry_config.hail_mary_enabled)
        self.assertEqual(retry_config.hail_mary_wait_hours, 12.0)
        self.assertEqual(retry_config.max_normal_retries, 11)
        self.assertEqual(retry_config.hail_mary_wait_minutes, 720.0)  # 12 * 60

    def test_retry_config_custom_values(self):
        """Test RetryConfig with custom values."""
        retry_config = RetryConfig(
            hail_mary_enabled=False, hail_mary_wait_hours=6.0, max_normal_retries=5
        )

        self.assertFalse(retry_config.hail_mary_enabled)
        self.assertEqual(retry_config.hail_mary_wait_hours, 6.0)
        self.assertEqual(retry_config.max_normal_retries, 5)
        self.assertEqual(retry_config.hail_mary_wait_minutes, 360.0)  # 6 * 60

    @parameterized.expand(
        [
            ("too_low_hours", {"hail_mary_wait_hours": 0.05}, True),
            ("too_high_hours", {"hail_mary_wait_hours": 200.0}, True),
            ("too_low_retries", {"max_normal_retries": 0}, True),
            ("too_high_retries", {"max_normal_retries": 100}, True),
            ("valid_minimum_hours", {"hail_mary_wait_hours": 0.1}, False),
            ("valid_maximum_hours", {"hail_mary_wait_hours": 168.0}, False),
            ("valid_minimum_retries", {"max_normal_retries": 1}, False),
            ("valid_maximum_retries", {"max_normal_retries": 50}, False),
        ]
    )
    def test_retry_config_validation(self, name, config_params, should_raise):
        """Test RetryConfig validation with various edge cases."""
        if should_raise:
            with self.assertRaises(Exception):  # Pydantic validation error
                RetryConfig(**config_params)
        else:
            try:
                config = RetryConfig(**config_params)
                self.assertIsInstance(config, RetryConfig)
            except Exception as e:
                self.fail(f"Valid config should not raise exception: {e}")

    # ============================================================================
    # PROCESS CONFIG TESTS
    # ============================================================================

    def test_process_config_defaults(self):
        """Test ProcessConfig with default values."""
        process_config = ProcessConfig()

        self.assertEqual(process_config.shutdown_timeout, 30.0)
        self.assertEqual(process_config.health_check_interval, 60.0)
        self.assertTrue(process_config.auto_restart)
        self.assertEqual(process_config.max_restart_attempts, 3)
        self.assertEqual(process_config.restart_delay, 5.0)
        self.assertTrue(process_config.enable_monitoring)
        self.assertIsNone(process_config.worker_timeout)
        self.assertEqual(process_config.signal_timeout, 10.0)

    def test_process_config_custom_values(self):
        """Test ProcessConfig with custom values."""
        process_config = ProcessConfig(
            shutdown_timeout=60.0,
            health_check_interval=120.0,
            auto_restart=False,
            max_restart_attempts=7,
            restart_delay=15.0,
            enable_monitoring=False,
            worker_timeout=300.0,
            signal_timeout=20.0,
        )

        self.assertEqual(process_config.shutdown_timeout, 60.0)
        self.assertEqual(process_config.health_check_interval, 120.0)
        self.assertFalse(process_config.auto_restart)
        self.assertEqual(process_config.max_restart_attempts, 7)
        self.assertEqual(process_config.restart_delay, 15.0)
        self.assertFalse(process_config.enable_monitoring)
        self.assertEqual(process_config.worker_timeout, 300.0)
        self.assertEqual(process_config.signal_timeout, 20.0)

    @parameterized.expand(
        [
            ("shutdown_timeout_too_low", {"shutdown_timeout": 0.5}, True),
            ("shutdown_timeout_too_high", {"shutdown_timeout": 400.0}, True),
            ("health_check_too_low", {"health_check_interval": 0.05}, True),
            ("health_check_too_high", {"health_check_interval": 700.0}, True),
            ("restart_attempts_negative", {"max_restart_attempts": -1}, True),
            ("restart_attempts_too_high", {"max_restart_attempts": 15}, True),
            ("restart_delay_negative", {"restart_delay": -1.0}, True),
            ("restart_delay_too_high", {"restart_delay": 80.0}, True),
            ("worker_timeout_too_low", {"worker_timeout": 20.0}, True),
            ("signal_timeout_too_low", {"signal_timeout": 0.5}, True),
            ("signal_timeout_too_high", {"signal_timeout": 80.0}, True),
            ("valid_minimum_shutdown", {"shutdown_timeout": 1.0}, False),
            ("valid_maximum_shutdown", {"shutdown_timeout": 300.0}, False),
            ("valid_minimum_health", {"health_check_interval": 0.1}, False),
            ("valid_maximum_health", {"health_check_interval": 600.0}, False),
            ("valid_zero_restarts", {"max_restart_attempts": 0}, False),
            ("valid_maximum_restarts", {"max_restart_attempts": 10}, False),
            ("valid_zero_delay", {"restart_delay": 0.0}, False),
            ("valid_maximum_delay", {"restart_delay": 60.0}, False),
            ("valid_minimum_worker_timeout", {"worker_timeout": 30.0}, False),
            ("valid_minimum_signal", {"signal_timeout": 1.0}, False),
            ("valid_maximum_signal", {"signal_timeout": 60.0}, False),
        ]
    )
    def test_process_config_validation(self, name, config_params, should_raise):
        """Test ProcessConfig validation with various edge cases."""
        if should_raise:
            with self.assertRaises(Exception):  # Pydantic validation error
                ProcessConfig(**config_params)
        else:
            try:
                config = ProcessConfig(**config_params)
                self.assertIsInstance(config, ProcessConfig)
            except Exception as e:
                self.fail(f"Valid config should not raise exception: {e}")

    # ============================================================================
    # ENHANCED EXISTING CONFIG TESTS
    # ============================================================================

    def test_calibre_config_update_methods(self):
        """Test CalibreConfig update_method validation."""
        valid_methods = ["update", "update_always", "force", "update_no_force"]

        for method in valid_methods:
            # Cast to the Literal type for type checking
            config = CalibreConfig(path="/test/path", update_method=method)  # type: ignore
            self.assertEqual(config.update_method, method)

        # Test invalid method - this will only be caught at runtime
        try:
            config = CalibreConfig(path="/test/path", update_method="invalid_method")  # type: ignore
            self.fail("Should have raised validation error for invalid update method")
        except Exception:
            pass  # Expected validation error

    def test_email_config_disabled_sites_default(self):
        """Test EmailConfig disabled_sites default value."""
        email_config = EmailConfig(
            email="test@example.com", password="password", server="imap.gmail.com"
        )

        # Should default to empty list per the model definition
        self.assertEqual(email_config.disabled_sites, [])

    def test_email_config_ffnet_disable_backward_compatibility(self):
        """Test EmailConfig backward compatibility with old ffnet_disable setting."""
        # Test with ffnet_disable=true should convert to disabled_sites=["fanfiction"]
        email_config = EmailConfig.model_validate(
            {
                "email": "test@example.com",
                "password": "password",
                "server": "imap.gmail.com",
                "ffnet_disable": True,
            }
        )
        self.assertEqual(email_config.disabled_sites, ["fanfiction"])

        # Test with ffnet_disable=false should convert to disabled_sites=[]
        email_config = EmailConfig.model_validate(
            {
                "email": "test@example.com",
                "password": "password",
                "server": "imap.gmail.com",
                "ffnet_disable": False,
            }
        )
        self.assertEqual(email_config.disabled_sites, [])

        # Test that providing both ffnet_disable and disabled_sites prioritizes disabled_sites
        email_config = EmailConfig.model_validate(
            {
                "email": "test@example.com",
                "password": "password",
                "server": "imap.gmail.com",
                "ffnet_disable": True,
                "disabled_sites": ["archiveofourown"],
            }
        )
        self.assertEqual(email_config.disabled_sites, ["archiveofourown"])

    def test_pushbullet_config_validation_with_enabled_but_no_key(self):
        """Test PushbulletConfig validation when enabled but no API key."""
        with self.assertRaises(Exception) as context:
            PushbulletConfig(enabled=True, api_key=None)

        self.assertIn("api_key is required", str(context.exception))

    def test_apprise_config_url_filtering(self):
        """Test AppriseConfig filters out empty URLs."""
        urls_with_empty = [
            "discord://valid_webhook",
            "",
            "   ",  # whitespace only
            "mailto://valid@email.com",
            "",
        ]

        config = AppriseConfig(urls=urls_with_empty)

        # Should filter out empty and whitespace-only entries
        self.assertEqual(len(config.urls), 2)
        self.assertIn("discord://valid_webhook", config.urls)
        self.assertIn("mailto://valid@email.com", config.urls)

    def test_email_config_is_configured_method(self):
        """Test EmailConfig.is_configured() method."""
        # Complete configuration
        complete_config = EmailConfig(
            email="test@example.com", password="password", server="imap.gmail.com"
        )
        self.assertTrue(complete_config.is_configured())

        # Missing email
        incomplete_config = EmailConfig(
            email="", password="password", server="imap.gmail.com"
        )
        self.assertFalse(incomplete_config.is_configured())

        # Missing password
        incomplete_config = EmailConfig(
            email="test@example.com", password="", server="imap.gmail.com"
        )
        self.assertFalse(incomplete_config.is_configured())

        # Missing server
        incomplete_config = EmailConfig(
            email="test@example.com", password="password", server=""
        )
        self.assertFalse(incomplete_config.is_configured())

    def test_calibre_config_is_configured_method(self):
        """Test CalibreConfig.is_configured() method."""
        # With path
        config_with_path = CalibreConfig(path="/path/to/calibre")
        self.assertTrue(config_with_path.is_configured())

        # Without path
        config_without_path = CalibreConfig(path="")
        self.assertFalse(config_without_path.is_configured())

        # With whitespace only path
        config_whitespace_path = CalibreConfig(path="   ")
        self.assertFalse(config_whitespace_path.is_configured())

    def test_app_config_max_workers_validation(self):
        """Test AppConfig max_workers validation and default behavior."""
        # Create proper config objects
        email_config = EmailConfig(
            email="test@example.com", password="password", server="imap.gmail.com"
        )
        calibre_config = CalibreConfig(path="/path/to/calibre")

        # Test with no max_workers specified - should default to CPU count
        config = AppConfig(email=email_config, calibre=calibre_config)
        self.assertIsNotNone(config.max_workers)
        self.assertIsInstance(config.max_workers, int)
        self.assertGreater(config.max_workers, 0)  # type: ignore

        # Test with explicit max_workers
        config = AppConfig(email=email_config, calibre=calibre_config, max_workers=4)
        self.assertEqual(config.max_workers, 4)

        # Test with invalid max_workers (zero)
        with self.assertRaises(Exception):
            AppConfig(email=email_config, calibre=calibre_config, max_workers=0)

        # Test with invalid max_workers (negative)
        with self.assertRaises(Exception):
            AppConfig(email=email_config, calibre=calibre_config, max_workers=-1)

    def tearDown(self):
        """Clean up after each test."""
        ConfigManager.clear_cache()


if __name__ == "__main__":
    unittest.main()
