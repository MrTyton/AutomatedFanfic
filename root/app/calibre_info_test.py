from parameterized import parameterized
from unittest.mock import MagicMock, patch
import unittest
import os
from pydantic import ValidationError

from calibre_info import CalibreInfo
from config_models import (
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
    @patch("config_models.ConfigManager.load_config")
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
    @patch("config_models.ConfigManager.load_config")
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
    @patch("calibre_info.call")
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
    @patch("config_models.ConfigManager.load_config")
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


if __name__ == "__main__":
    unittest.main()
