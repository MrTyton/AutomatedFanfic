import unittest
from unittest.mock import MagicMock

from url_worker import construct_fanficfare_command
from calibre_info import CalibreInfo
from fanfic_info import FanficInfo


class TestConstructFanficfareCommand(unittest.TestCase):
    def setUp(self):
        self.mock_cdb = MagicMock(spec=CalibreInfo)
        self.mock_fanfic = MagicMock(spec=FanficInfo)
        self.path_or_url = "http://test.com/story"
        self.mock_fanfic.url = self.path_or_url
        self.mock_fanfic.site = "test_site"
        self.mock_fanfic.behavior = None

    def test_update_method_update(self):
        self.mock_cdb.update_method = "update"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn(" -u ", command)
        self.assertNotIn(" -U ", command)
        self.assertNotIn(" --force ", command)

    def test_update_method_update_always(self):
        self.mock_cdb.update_method = "update_always"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn(" -U ", command)
        self.assertNotIn(" -u ", command)
        self.assertNotIn(" --force ", command)

    def test_update_method_force(self):
        self.mock_cdb.update_method = "force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn(" -u --force", command)
        self.assertNotIn(" -U ", command)

    def test_fanfic_behavior_force_override(self):
        self.mock_cdb.update_method = "update"
        self.mock_fanfic.behavior = "force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn(" -u --force", command)
        self.assertNotIn(" -U ", command)

    def test_update_no_force_with_force_behavior(self):
        # With the new implementation, update_no_force ignores force requests
        # and always uses normal update behavior
        self.mock_cdb.update_method = "update_no_force"
        self.mock_fanfic.behavior = "force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        # Should use -u instead of --force when update_no_force is set
        self.assertIn(" -u ", command)
        self.assertNotIn(" -U ", command)
        self.assertNotIn(" --force", command)

    def test_update_no_force_without_force_behavior(self):
        self.mock_cdb.update_method = "update_no_force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn(" -u ", command)
        self.assertNotIn(" -U ", command)
        self.assertNotIn(" --force ", command)

    def test_default_update_method_fallback(self):
        # Test that unrecognized update_method defaults to -u
        self.mock_cdb.update_method = "unknown_method"
        self.mock_fanfic.behavior = None
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn(" -u ", command)
        self.assertNotIn(" -U ", command)
        self.assertNotIn(" --force ", command)

    def test_none_behavior_with_various_update_methods(self):
        # Test None behavior with different update methods
        self.mock_fanfic.behavior = None

        # Test with update_always
        self.mock_cdb.update_method = "update_always"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn(" -U ", command)

        # Test with force
        self.mock_cdb.update_method = "force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn(" -u --force", command)

    def test_empty_string_behavior(self):
        # Test empty string behavior (should be treated as no force)
        self.mock_cdb.update_method = "update"
        self.mock_fanfic.behavior = ""
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn(" -u ", command)
        self.assertNotIn(" --force ", command)

    def test_command_structure(self):
        # Test that the command structure is correct
        self.mock_cdb.update_method = "update"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertTrue(command.startswith("python -m fanficfare.cli"))
        self.assertIn("--update-cover", command)
        self.assertIn("--non-interactive", command)
        self.assertIn(f'"{self.path_or_url}"', command)

    def test_force_behavior_precedence_over_update_always(self):
        # Test that force behavior overrides update_always method
        self.mock_cdb.update_method = "update_always"
        self.mock_fanfic.behavior = "force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn(" -u --force", command)
        self.assertNotIn(" -U ", command)

    def test_update_no_force_precedence_over_force_behavior(self):
        # Test that update_no_force method overrides force behavior
        self.mock_cdb.update_method = "update_no_force"
        self.mock_fanfic.behavior = "force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn(" -u ", command)
        self.assertNotIn(" --force", command)
        self.assertNotIn(" -U ", command)

    def test_case_sensitivity_of_behavior(self):
        # Test that behavior is case-sensitive (only "force" should trigger force)
        self.mock_cdb.update_method = "update"
        test_cases = ["Force", "FORCE", "force "]  # Various case variations
        for behavior in test_cases:
            with self.subTest(behavior=behavior):
                self.mock_fanfic.behavior = behavior
                command = construct_fanficfare_command(
                    self.mock_cdb, self.mock_fanfic, self.path_or_url
                )
                self.assertIn(" -u ", command)
                self.assertNotIn(" --force", command)


if __name__ == "__main__":
    unittest.main()
