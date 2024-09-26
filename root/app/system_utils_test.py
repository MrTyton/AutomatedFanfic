import unittest
from unittest.mock import patch, MagicMock
from parameterized import parameterized
from system_utils import (
    temporary_directory,
    get_files,
    copy_configs_to_temp_dir,
)
import os
from typing import NamedTuple, Optional


class TestSystemUtils(unittest.TestCase):
    @patch("system_utils.mkdtemp", return_value="/fake/temp/dir")
    @patch("shutil.rmtree")
    def test_temporary_directory(self, mock_rmtree, mock_mkdtemp):
        # Test the creation and cleanup of a temporary directory
        with temporary_directory() as temp_dir:
            self.assertEqual(temp_dir, "/fake/temp/dir")
        mock_mkdtemp.assert_called_once()
        mock_rmtree.assert_called_once_with("/fake/temp/dir")

    class GetFilesTestCase(NamedTuple):
        directory_path: str
        file_extension: Optional[str]
        return_full_path: bool
        expected_files: list

    @parameterized.expand(
        [
            GetFilesTestCase(
                directory_path=os.path.join("fake", "dir"),
                file_extension=None,
                return_full_path=False,
                expected_files=["file1.txt", "file2.py", "file3.txt"],
            ),
            GetFilesTestCase(
                directory_path=os.path.join("fake", "dir"),
                file_extension=".txt",
                return_full_path=False,
                expected_files=["file1.txt", "file3.txt"],
            ),
            GetFilesTestCase(
                directory_path=os.path.join("fake", "dir"),
                file_extension=None,
                return_full_path=True,
                expected_files=[
                    os.path.join("fake", "dir", "file1.txt"),
                    os.path.join("fake", "dir", "file2.py"),
                    os.path.join("fake", "dir", "file3.txt"),
                ],
            ),
        ]
    )
    @patch("os.listdir", return_value=["file1.txt", "file2.py", "file3.txt"])
    @patch("os.path.isfile", return_value=True)
    def test_get_files(
        self,
        directory_path,
        file_extension,
        return_full_path,
        expected_files,
        mock_isfile,
        mock_listdir,
    ):
        # Test retrieving files from a directory
        files = get_files(directory_path, file_extension, return_full_path)
        self.assertEqual(files, expected_files)
        mock_listdir.assert_called_once_with(directory_path)
        self.assertEqual(mock_isfile.call_count, 3)

    class CopyConfigsTestCase(NamedTuple):
        default_ini: Optional[str]
        personal_ini: Optional[str]
        expected_calls: list

    @parameterized.expand(
        [
            CopyConfigsTestCase(
                default_ini=os.path.join("fake", "path", "defaults.ini"),
                personal_ini=os.path.join("fake", "path", "personal.ini"),
                expected_calls=[
                    (
                        os.path.join("fake", "path", "defaults.ini"),
                        os.path.join("fake", "temp", "dir", "defaults.ini"),
                    ),
                    (
                        os.path.join("fake", "path", "personal.ini"),
                        os.path.join("fake", "temp", "dir", "personal.ini"),
                    ),
                ],
            ),
            CopyConfigsTestCase(
                default_ini=None,
                personal_ini=os.path.join("fake", "path", "personal.ini"),
                expected_calls=[
                    (
                        os.path.join("fake", "path", "personal.ini"),
                        os.path.join("fake", "temp", "dir", "personal.ini"),
                    ),
                ],
            ),
            CopyConfigsTestCase(
                default_ini=os.path.join("fake", "path", "defaults.ini"),
                personal_ini=None,
                expected_calls=[
                    (
                        os.path.join("fake", "path", "defaults.ini"),
                        os.path.join("fake", "temp", "dir", "defaults.ini"),
                    ),
                ],
            ),
        ]
    )
    @patch("shutil.copyfile")
    def test_copy_configs_to_temp_dir(
        self,
        default_ini,
        personal_ini,
        expected_calls,
        mock_copyfile,
    ):
        # Test copying configuration files to a temporary directory
        cdb = MagicMock()
        cdb.default_ini = default_ini
        cdb.personal_ini = personal_ini
        copy_configs_to_temp_dir(cdb, os.path.join("fake", "temp", "dir"))
        for call_args in expected_calls:
            mock_copyfile.assert_any_call(*call_args)
        self.assertEqual(mock_copyfile.call_count, len(expected_calls))


if __name__ == "__main__":
    unittest.main()
