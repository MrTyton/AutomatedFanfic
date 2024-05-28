from typing import NamedTuple, Union
from unittest.mock import MagicMock, mock_open, patch
from parameterized import parameterized
import unittest

from calibre_info import CalibreInfo


class TestCalibreInfo(unittest.TestCase):
    class ConfigCase(NamedTuple):
        toml_path: str
        config: str
        expected_config: dict

    @parameterized.expand(
        [
            # Test case: Valid configuration
            ConfigCase(
                toml_path="path/to/config.toml",
                config="""
                [calibre]
                path = "test_path"
                username = "test_username"
                password = "test_password"
                default_ini = "test_default_ini"
                personal_ini = "test_personal_ini"
                """,
                expected_config={
                    "calibre": {
                        "path": "test_path",
                        "username": "test_username",
                        "password": "test_password",
                        "default_ini": "test_default_ini\\defaults.ini",
                        "personal_ini": "test_personal_ini\\personal.ini",
                    }
                },
            ),
            # Test case: default_ini and personal_ini already end with "/defaults.ini" and "/personal.ini"
            ConfigCase(
                toml_path="path/to/yet_another_config.toml",
                config="""
                [calibre]
                path = "yet_another_test_path"
                username = "yet_another_test_username"
                password = "yet_another_test_password"
                default_ini = "yet_another_test_default_ini/defaults.ini"
                personal_ini = "yet_another_test_personal_ini/personal.ini"
                """,
                expected_config={
                    "calibre": {
                        "path": "yet_another_test_path",
                        "username": "yet_another_test_username",
                        "password": "yet_another_test_password",
                        "default_ini": "yet_another_test_default_ini/defaults.ini",
                        "personal_ini": "yet_another_test_personal_ini/personal.ini",
                    }
                },
            ),
            # Test case: Missing path in configuration
            ConfigCase(
                toml_path="path/to/another_config.toml",
                config="""
                [calibre]
                username = "another_test_username"
                password = "another_test_password"
                default_ini = "another_test_default_ini"
                personal_ini = "another_test_personal_ini"
                """,
                expected_config=ValueError,
            ),
        ]
    )
    @patch("os.path.isfile")
    @patch("builtins.open", new_callable=mock_open)
    @patch("multiprocessing.Manager")
    @patch("calibre_info.ff_logging.log_failure")
    def test_calibre_info_init(
        self, toml_path, config, expected_config, mock_log, mock_manager, mock_file, mock_isfile
    ):
        mock_file.return_value.read.return_value = str(config).encode()
        mock_manager.return_value = MagicMock()
        # TODO: Actually test this.
        mock_isfile.return_value = True
        if isinstance(expected_config, dict):
            calibre_info = CalibreInfo(toml_path, mock_manager())
            self.assertEqual(calibre_info.location, expected_config["calibre"]["path"])
            self.assertEqual(
                calibre_info.username, expected_config["calibre"]["username"]
            )
            self.assertEqual(
                calibre_info.password, expected_config["calibre"]["password"]
            )
            self.assertEqual(
                calibre_info.default_ini, expected_config["calibre"]["default_ini"]
            )
            self.assertEqual(
                calibre_info.personal_ini,
                expected_config["calibre"]["personal_ini"],
            )
            mock_log.assert_not_called()  # Ensure that log_failure was not called

        else:
            with self.assertRaises(expected_config):
                CalibreInfo(toml_path, mock_manager)
            mock_log.assert_called_once()  # Ensure that log_failure was called once

    class CheckInstalledCase(NamedTuple):
        call_return: Union[int, Exception]
        expected_result: bool

    @parameterized.expand(
        [
            CheckInstalledCase(call_return=0, expected_result=True),
            CheckInstalledCase(call_return=OSError(), expected_result=False),
        ]
    )
    @patch("multiprocessing.Manager")
    @patch("calibre_info.call")
    @patch("builtins.open", new_callable=mock_open)
    @patch("calibre_info.ff_logging.log_failure")
    def test_check_installed(
        self,
        call_return: int,
        expected_result: bool,
        mock_log,
        mock_file,
        mock_call,
        mock_manager,
    ):
        if isinstance(call_return, Exception):
            mock_call.side_effect = call_return
        else:
            mock_call.return_value = call_return
        mock_manager.return_value = MagicMock()
        mock_file.return_value.read.return_value = str("""
                [calibre]
                path = "test_path"
                """).encode()

        calibre_info = CalibreInfo("path/to/config.toml", mock_manager())
        result = calibre_info.check_installed()

        self.assertEqual(result, expected_result)
        if expected_result:
            mock_log.assert_not_called()
        else:
            mock_log.assert_called_once()

    class StrRepresentationCase(NamedTuple):
        location: str
        username: str
        password: str
        expected_result: str

    @parameterized.expand(
        [
            StrRepresentationCase(
                location="test_path",
                username=None,
                password=None,
                expected_result=' --with-library "test_path"',
            ),
            StrRepresentationCase(
                location="test_path",
                username="test_user",
                password=None,
                expected_result=' --with-library "test_path" --username "test_user"',
            ),
            StrRepresentationCase(
                location="test_path",
                username="test_user",
                password="test_pass",
                expected_result=' --with-library "test_path" --username "test_user" --password "test_pass"',
            ),
        ]
    )
    @patch("multiprocessing.Manager")
    @patch("builtins.open", new_callable=mock_open)
    def test_str_representation(
        self, location, username, password, expected_result, mock_file, mock_manager
    ):
        mock_manager.return_value = MagicMock()

        mock_file.return_value.read.return_value = str("""
                [calibre]
                path = "test_path"
                """).encode()
        calibre_info = CalibreInfo("path/to/config.toml", mock_manager())
        calibre_info.location = location
        calibre_info.username = username
        calibre_info.password = password

        result = str(calibre_info)

        self.assertEqual(result, expected_result)


if __name__ == "__main__":
    unittest.main()
