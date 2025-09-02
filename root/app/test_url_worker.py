import unittest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

# Add app directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from url_worker import construct_fanficfare_command
from calibre_info import CalibreInfo
from fanfic_info import FanficInfo
from notification_wrapper import NotificationWrapper


class TestConstructFanficfareCommand(unittest.TestCase):
    def setUp(self):
        self.mock_cdb = MagicMock(spec=CalibreInfo)
        self.mock_cdb.config = MagicMock()
        self.mock_cdb.config.calibre = MagicMock()
        self.mock_fanfic = MagicMock(spec=FanficInfo)
        self.mock_notification_info = MagicMock(spec=NotificationWrapper)
        self.path_or_url = "http://test.com/story"
        self.mock_fanfic.url = self.path_or_url
        self.mock_fanfic.site = "test_site"
        self.mock_fanfic.behavior = None

    def test_update_method_update(self):
        self.mock_cdb.config.calibre.update_method = "update"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url, self.mock_notification_info
        )
        self.assertIn(" -u ", command)
        self.assertNotIn(" -U ", command)
        self.assertNotIn(" --force ", command)

    def test_update_method_update_always(self):
        self.mock_cdb.config.calibre.update_method = "update_always"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url, self.mock_notification_info
        )
        self.assertIn(" -U ", command)
        self.assertNotIn(" -u ", command)
        self.assertNotIn(" --force ", command)

    def test_update_method_force(self):
        self.mock_cdb.config.calibre.update_method = "force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url, self.mock_notification_info
        )
        self.assertIn(" --force", command)
        self.assertNotIn(" -u ", command)
        self.assertNotIn(" -U ", command)

    def test_fanfic_behavior_force_override(self):
        self.mock_cdb.config.calibre.update_method = "update"
        self.mock_fanfic.behavior = "force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url, self.mock_notification_info
        )
        self.assertIn(" --force", command)
        self.assertNotIn(" -u ", command)
        self.assertNotIn(" -U ", command)

    def test_update_no_force_with_force_behavior(self):
        self.mock_cdb.config.calibre.update_method = "update_no_force"
        self.mock_fanfic.behavior = "force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url, self.mock_notification_info
        )
        self.assertEqual(command, "")
        self.mock_notification_info.send_notification.assert_called_once_with(
            "Fanfiction Update Skipped",
            f"Update for {self.path_or_url} was skipped because a force was requested but the update method is set to 'update_no_force'.",
            "test_site",
        )

    def test_update_no_force_without_force_behavior(self):
        self.mock_cdb.config.calibre.update_method = "update_no_force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url, self.mock_notification_info
        )
        self.assertIn(" -u ", command)
        self.assertNotIn(" -U ", command)
        self.assertNotIn(" --force ", command)
        self.mock_notification_info.send_notification.assert_not_called()


if __name__ == "__main__":
    unittest.main()
