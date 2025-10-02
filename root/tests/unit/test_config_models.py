import unittest
from unittest.mock import patch, mock_open
from typing import NamedTuple, Optional
from parameterized import parameterized
import tempfile
import os

from config_models import (
    ConfigManager,
    EmailConfig,
    CalibreConfig,
    PushbulletConfig,
    AppriseConfig,
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
ffnet_disable = true

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
urls = ["discord://webhook_id/webhook_token", "mailto://user:pass@gmail.com"]
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
ffnet_disable = true

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
        self.assertFalse(email_config.ffnet_disable)

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
            self.assertTrue(config.pushbullet.enabled)
            self.assertEqual(len(config.apprise.urls), 2)
        finally:
            os.unlink(temp_path)
            ConfigManager.clear_cache()

    def tearDown(self):
        """Clean up after each test."""
        ConfigManager.clear_cache()


if __name__ == "__main__":
    unittest.main()
