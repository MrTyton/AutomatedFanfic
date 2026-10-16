from parameterized import parameterized
from pathlib import Path
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
    @patch("pathlib.Path.is_file")
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
    @patch("pathlib.Path.is_file")
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
    @patch("pathlib.Path.is_file")
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

        # default_ini path doesn't exist (personal_ini is None so is_file won't be called for it)
        mock_isfile.return_value = False

        calibre_info = CalibreInfo("test.toml", mock_manager())

        # Should succeed but return empty string for default_ini
        self.assertEqual(calibre_info.default_ini, "")

    @patch("models.config_models.ConfigManager.load_config")
    @patch("multiprocessing.Manager")
    @patch("pathlib.Path.is_file")
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

        # personal_ini path doesn't exist (default_ini is None so is_file won't be called for it)
        mock_isfile.return_value = False

        calibre_info = CalibreInfo("test.toml", mock_manager())

        # Should succeed but return empty string for personal_ini
        self.assertEqual(calibre_info.personal_ini, "")

    @patch("models.config_models.ConfigManager.load_config")
    @patch("multiprocessing.Manager")
    @patch("pathlib.Path.is_file")
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


class TestCalibreInfoUpdateFromConfigStore(unittest.TestCase):
    """Tests for update_from_config_store.

    This method is called before every calibredb operation to hot-reload config
    changes made via the web dashboard.  The INI path fields require special
    handling: the config store holds the *raw* user value (which may be a
    directory like ``/config``) while ``self.personal_ini`` / ``self.default_ini``
    must be *resolved* full file paths (``/config/personal.ini``).
    """

    def _make_cdb(self, personal_ini="", default_ini="", location="/library"):
        """Create a CalibreInfo bypassing __init__ with known field values.

        This lets us test update_from_config_store in isolation without wiring
        up config loading, file-system checks, or multiprocessing.

        Paths are normalised through Path() so comparisons are platform-safe
        (resolve_ini_path uses str(Path(dir) / filename) internally).
        """
        cdb = CalibreInfo.__new__(CalibreInfo)
        cdb.location = location
        cdb.username = ""
        cdb.password = ""
        cdb.personal_ini = str(Path(personal_ini)) if personal_ini else ""
        cdb.default_ini = str(Path(default_ini)) if default_ini else ""
        cdb.update_method = "update"
        cdb.metadata_preservation_mode = "remove_add"
        cdb.lock = MagicMock()
        return cdb

    def _p(self, *parts) -> str:
        """Platform-safe path: str(Path(parts[0]) / parts[1] / ...)."""
        return str(Path(*parts))

    def _store(self, **kwargs):
        """Build a minimal config-store mock whose .get() returns the given keys."""
        m = MagicMock()
        m.get = lambda key, default=None: kwargs.get(key, default)
        return m

    # ------------------------------------------------------------------ #
    # Regression: raw directory path must be resolved to the file path    #
    # ------------------------------------------------------------------ #

    @patch("pathlib.Path.is_file", return_value=True)
    def test_directory_path_resolved_for_personal_ini(self, _mock_isfile):
        """Raw dir value (/config) must be resolved to /config/personal.ini.

        Regression: previously the raw value was stored directly, overwriting
        the resolved path produced at __init__ time.
        """
        cdb = self._make_cdb(personal_ini=self._p("/config/personal.ini"))
        cdb.update_from_config_store(self._store(**{"calibre.personal_ini": "/config"}))
        self.assertEqual(cdb.personal_ini, self._p("/config", "personal.ini"))

    @patch("pathlib.Path.is_file", return_value=True)
    def test_directory_path_resolved_for_default_ini(self, _mock_isfile):
        """Raw dir value (/config) must be resolved to /config/defaults.ini."""
        cdb = self._make_cdb(default_ini=self._p("/config/defaults.ini"))
        cdb.update_from_config_store(self._store(**{"calibre.default_ini": "/config"}))
        self.assertEqual(cdb.default_ini, self._p("/config", "defaults.ini"))

    @patch("pathlib.Path.is_file", return_value=True)
    def test_no_spurious_change_when_dir_resolves_to_same_path(self, _mock_isfile):
        """Returns False when the resolved path equals the current value.

        The raw-vs-resolved mismatch must not be treated as a real change.
        """
        cdb = self._make_cdb(
            personal_ini=self._p("/config", "personal.ini"),
            default_ini=self._p("/config", "defaults.ini"),
        )
        changed = cdb.update_from_config_store(
            self._store(
                **{
                    "calibre.personal_ini": "/config",
                    "calibre.default_ini": "/config",
                }
            )
        )
        self.assertFalse(changed)

    # ------------------------------------------------------------------ #
    # Full file path passes through unchanged                             #
    # ------------------------------------------------------------------ #

    @patch("pathlib.Path.is_file", return_value=True)
    def test_full_file_path_passes_through_unchanged(self, _mock_isfile):
        """If config store already has the full path, it is kept as-is."""
        full_path = self._p("/config", "personal.ini")
        cdb = self._make_cdb(personal_ini=full_path)
        changed = cdb.update_from_config_store(
            self._store(**{"calibre.personal_ini": full_path})
        )
        self.assertFalse(changed)
        self.assertEqual(cdb.personal_ini, full_path)

    # ------------------------------------------------------------------ #
    # Genuine path changes are detected and applied                       #
    # ------------------------------------------------------------------ #

    @patch("pathlib.Path.is_file", return_value=True)
    def test_change_detected_when_ini_dir_actually_differs(self, _mock_isfile):
        """Returns True and updates path when config store points to a new dir."""
        cdb = self._make_cdb(personal_ini=self._p("/old-config/personal.ini"))
        changed = cdb.update_from_config_store(
            self._store(**{"calibre.personal_ini": "/new-config"})
        )
        self.assertTrue(changed)
        self.assertEqual(cdb.personal_ini, self._p("/new-config", "personal.ini"))

    @patch("pathlib.Path.is_file", return_value=False)
    def test_ini_set_to_empty_when_resolved_file_missing(self, _mock_isfile):
        """If resolved file does not exist, personal_ini is set to empty string."""
        cdb = self._make_cdb(personal_ini=self._p("/config/personal.ini"))
        changed = cdb.update_from_config_store(
            self._store(**{"calibre.personal_ini": "/missing"})
        )
        self.assertTrue(changed)
        self.assertEqual(cdb.personal_ini, "")

    # ------------------------------------------------------------------ #
    # Non-INI fields                                                      #
    # ------------------------------------------------------------------ #

    def test_non_ini_fields_updated_directly(self):
        """Regular fields (location, username, password) are assigned directly."""
        cdb = self._make_cdb(location="/old/lib")
        changed = cdb.update_from_config_store(
            self._store(
                **{
                    "calibre.path": "/new/lib",
                    "calibre.username": "admin",
                    "calibre.password": "secret",
                }
            )
        )
        self.assertTrue(changed)
        self.assertEqual(cdb.location, "/new/lib")
        self.assertEqual(cdb.username, "admin")
        self.assertEqual(cdb.password, "secret")

    def test_returns_false_when_store_has_no_values(self):
        """Returns False when config store returns None for every key."""
        cdb = self._make_cdb(
            personal_ini=self._p("/config/personal.ini"),
            default_ini=self._p("/config/defaults.ini"),
        )
        changed = cdb.update_from_config_store(self._store())
        self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
