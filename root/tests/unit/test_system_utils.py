import os
from typing import NamedTuple, Optional
import unittest
from unittest.mock import patch

from parameterized import parameterized

from utils.system_utils import (
    get_files,
    get_installed_package_version,
    get_packaged_defaults_ini_path,
    get_system_environment_summary,
    is_docker_environment,
    temporary_directory,
)


class TestSystemUtils(unittest.TestCase):
    @patch("utils.system_utils.mkdtemp", return_value="/fake/temp/dir")
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
    @patch("pathlib.Path.is_file", return_value=True)
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

    def test_get_packaged_defaults_ini_path_cached(self):
        """get_packaged_defaults_ini_path caches result across repeated calls via lru_cache."""
        get_packaged_defaults_ini_path.cache_clear()
        p1 = get_packaged_defaults_ini_path()
        p2 = get_packaged_defaults_ini_path()
        self.assertEqual(p1, p2)
        info = get_packaged_defaults_ini_path.cache_info()
        self.assertEqual(info.misses, 1)
        self.assertEqual(info.hits, 1)

    def test_get_packaged_defaults_ini_path_returns_empty_when_package_file_missing(
        self,
    ):
        """get_packaged_defaults_ini_path returns empty string when fanficfare package defaults.ini is missing (no repo fallback)."""
        get_packaged_defaults_ini_path.cache_clear()
        try:
            with patch(
                "utils.system_utils.fanficfare.__file__",
                "/nonexistent/site-packages/fanficfare/__init__.py",
            ):
                self.assertEqual(get_packaged_defaults_ini_path(), "")
        finally:
            get_packaged_defaults_ini_path.cache_clear()

    def test_environment_and_version_helpers(self):
        """Test Docker detection, package version retrieval, and environment summary."""
        summary = get_system_environment_summary()
        self.assertIn("python", summary)
        self.assertIn("platform", summary)
        self.assertIn("is_docker", summary)
        self.assertIsInstance(summary["is_docker"], bool)

        # Nonexistent package should return unknown without error
        self.assertEqual(
            get_installed_package_version("nonexistent_package_xyz_123"), "unknown"
        )

        with patch("os.path.exists", return_value=True):
            self.assertTrue(is_docker_environment())


if __name__ == "__main__":
    unittest.main()
