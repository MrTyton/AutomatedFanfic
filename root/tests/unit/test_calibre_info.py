from parameterized import parameterized
from unittest.mock import MagicMock, patch
import unittest
from pydantic import ValidationError


from calibre_integration.calibre_info import CalibreInfo
from models.config_models import (
    AppConfig,
    EmailConfig,
    CalibreConfig,
    AppriseConfig,
    PushbulletConfig,
)


class TestCalibreInfo(unittest.TestCase):
    @parameterized.expand(
        [
            (
                "full_config",
                "/test/path",
                "test_user",
                "test_pass",
                "/config/defaults.ini",
                "/config/personal.ini",
            ),
            ("minimal_config", "/simple/path", "", "", "", ""),
            (
                "complex_path",
                "/usr/local/calibre/lib",
                "admin",
                "secret123",
                "/etc/calibre/defaults.ini",
                "/home/user/personal.ini",
            ),
        ]
    )
    @patch("models.config_models.ConfigManager.load_config")
    @patch("multiprocessing.Manager")
    @patch("os.path.isfile")
    def test_calibre_info_init_success(
        self,
        name,
        path,
        username,
        password,
        default_ini,
        personal_ini,
        mock_isfile,
        mock_manager,
        mock_load_config,
    ):
        # Setup mock config
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(
                path=path,
                username=username,
                password=password,
                default_ini=default_ini,
                personal_ini=personal_ini,
            ),
            apprise=AppriseConfig(),
            pushbullet=PushbulletConfig(),
        )
        mock_load_config.return_value = mock_config
        mock_manager.return_value = MagicMock()
        mock_isfile.return_value = True

        calibre_info = CalibreInfo("test_path.toml", mock_manager())

        self.assertEqual(calibre_info.location, path)
        self.assertEqual(calibre_info.username, username)
        self.assertEqual(calibre_info.password, password)
        self.assertEqual(calibre_info.default_ini, default_ini)
        self.assertEqual(calibre_info.personal_ini, personal_ini)

    @parameterized.expand(
        [
            ("empty_path", ""),
            ("none_path_validation", None),  # Test Pydantic validation behavior
        ]
    )
    @patch("models.config_models.ConfigManager.load_config")
    @patch("multiprocessing.Manager")
    def test_calibre_info_init_missing_path(
        self, name, path, mock_manager, mock_load_config
    ):
        # Setup mock config with empty path
        if path is None:
            # Test that Pydantic validation properly rejects None paths
            with self.assertRaises(ValidationError):
                CalibreConfig(path=path)
            return  # Exit early since we've tested the validation

        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path=path),  # Empty path should cause error
            apprise=AppriseConfig(),
            pushbullet=PushbulletConfig(),
        )
        mock_load_config.return_value = mock_config
        mock_manager.return_value = MagicMock()

        with self.assertRaises(ValueError) as context:
            CalibreInfo("test_path.toml", mock_manager())

        self.assertIn("Calibre library location not set", str(context.exception))

    @parameterized.expand(
        [
            ("success_case", 0, True),
            ("failure_case", 1, False),
        ]
    )
    @patch("calibre_integration.calibre_info.call")
    def test_check_installed(self, name, return_code, expected_result, mock_call):
        if name == "success_case":
            mock_call.return_value = return_code
        else:
            mock_call.side_effect = OSError("Command not found")

        result = CalibreInfo.check_installed()
        self.assertEqual(result, expected_result)

    @parameterized.expand(
        [
            (
                "full_repr",
                "/test/path",
                "test_user",
                "test_pass",
                ' --with-library "/test/path" --username "test_user" --password "test_pass"',
            ),
            ("no_auth", "/simple/path", "", "", ' --with-library "/simple/path"'),
            (
                "long_path",
                "/very/long/path/to/calibre/library",
                "admin",
                "secret",
                ' --with-library "/very/long/path/to/calibre/library" --username "admin" --password "secret"',
            ),
        ]
    )
    @patch("models.config_models.ConfigManager.load_config")
    @patch("multiprocessing.Manager")
    @patch("os.path.isfile")
    def test_str_representation(
        self,
        name,
        path,
        username,
        password,
        expected_str,
        mock_isfile,
        mock_manager,
        mock_load_config,
    ):
        # Setup mock config with specified fields
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(path=path, username=username, password=password),
            apprise=AppriseConfig(),
            pushbullet=PushbulletConfig(),
        )
        mock_load_config.return_value = mock_config
        mock_manager.return_value = MagicMock()
        mock_isfile.return_value = True

        calibre_info = CalibreInfo("test_path.toml", mock_manager())

        self.assertEqual(str(calibre_info), expected_str)


class TestCalibreInfoEdgeCases(unittest.TestCase):
    """Test edge cases and error handling in CalibreInfo."""

    @patch("models.config_models.ConfigManager.load_config")
    @patch("multiprocessing.Manager")
    def test_config_load_failure(self, mock_manager, mock_load_config):
        """Test handling of configuration load failures."""
        from models.config_models import ConfigError

        # Simulate config loading error
        mock_load_config.side_effect = ConfigError("Failed to load config")
        mock_manager.return_value = MagicMock()

        with self.assertRaises(ValueError) as context:
            CalibreInfo("nonexistent.toml", mock_manager())

        self.assertIn("Failed to load configuration", str(context.exception))

    @patch("models.config_models.ConfigManager.load_config")
    @patch("multiprocessing.Manager")
    def test_config_validation_failure(self, mock_manager, mock_load_config):
        """Test handling of configuration validation failures."""
        from pydantic import ValidationError

        # Simulate validation error
        mock_load_config.side_effect = ValidationError.from_exception_data(
            "test",
            [
                {
                    "type": "missing",
                    "loc": ("field",),
                    "msg": "field required",
                    "input": {},
                }
            ],
        )
        mock_manager.return_value = MagicMock()

        # ValidationError should propagate or be caught by the exception handler
        with self.assertRaises((ValueError, ValidationError)):
            CalibreInfo("invalid.toml", mock_manager())

    @patch("models.config_models.ConfigManager.load_config")
    @patch("multiprocessing.Manager")
    @patch("os.path.isfile")
    def test_missing_default_ini_file(
        self, mock_isfile, mock_manager, mock_load_config
    ):
        """Test behavior when default.ini file is specified but doesn't exist."""
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(
                path="/test/path", default_ini="/path/to/missing/defaults.ini"
            ),
            apprise=AppriseConfig(),
            pushbullet=PushbulletConfig(),
        )
        mock_load_config.return_value = mock_config
        mock_manager.return_value = MagicMock()

        # Only the default_ini file doesn't exist
        def isfile_side_effect(path):
            return not path.endswith("defaults.ini")

        mock_isfile.side_effect = isfile_side_effect

        calibre_info = CalibreInfo("test.toml", mock_manager())

        # Should succeed but return empty string for default_ini
        self.assertEqual(calibre_info.default_ini, "")

    @patch("models.config_models.ConfigManager.load_config")
    @patch("multiprocessing.Manager")
    @patch("os.path.isfile")
    def test_missing_personal_ini_file(
        self, mock_isfile, mock_manager, mock_load_config
    ):
        """Test behavior when personal.ini file is specified but doesn't exist."""
        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(
                path="/test/path", personal_ini="/path/to/missing/personal.ini"
            ),
            apprise=AppriseConfig(),
            pushbullet=PushbulletConfig(),
        )
        mock_load_config.return_value = mock_config
        mock_manager.return_value = MagicMock()

        # Only the personal_ini file doesn't exist
        def isfile_side_effect(path):
            return not path.endswith("personal.ini")

        mock_isfile.side_effect = isfile_side_effect

        calibre_info = CalibreInfo("test.toml", mock_manager())

        # Should succeed but return empty string for personal_ini
        self.assertEqual(calibre_info.personal_ini, "")

    @patch("models.config_models.ConfigManager.load_config")
    @patch("multiprocessing.Manager")
    @patch("os.path.isfile")
    @patch("shutil.copyfile")
    @patch("utils.ff_logging.log_debug")
    def test_copy_configs_to_temp_dir_missing_files(
        self, mock_log_debug, mock_copyfile, mock_isfile, mock_manager, mock_load_config
    ):
        """Test copy_configs_to_temp_dir when ini files don't exist."""
        import tempfile

        mock_config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(
                path="/test/path",
                default_ini="/path/to/defaults.ini",
                personal_ini="/path/to/personal.ini",
            ),
            apprise=AppriseConfig(),
            pushbullet=PushbulletConfig(),
        )
        mock_load_config.return_value = mock_config
        mock_manager.return_value = MagicMock()

        # Simulate that ini files don't exist
        mock_isfile.return_value = False

        calibre_info = CalibreInfo("test.toml", mock_manager())

        # Create a temp directory and try to copy configs
        with tempfile.TemporaryDirectory() as temp_dir:
            calibre_info.copy_configs_to_temp_dir(temp_dir)

            # copyfile should not have been called since files don't exist
            mock_copyfile.assert_not_called()

            # Should have logged that files weren't found
            debug_calls = [call[0][0] for call in mock_log_debug.call_args_list]
            self.assertTrue(
                any("No defaults.ini found" in call for call in debug_calls),
                "Should log that defaults.ini was not found",
            )
            self.assertTrue(
                any("No personal.ini found" in call for call in debug_calls),
                "Should log that personal.ini was not found",
            )


if __name__ == "__main__":
    unittest.main()
