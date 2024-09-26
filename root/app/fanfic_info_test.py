import unittest
from unittest.mock import Mock, patch, mock_open, MagicMock
from fanfic_info import FanficInfo


class TestFanficInfo(unittest.TestCase):
    def setUp(self):
        self.fanfic_info = FanficInfo(
            url="https://www.fanfiction.net/s/1234",
            site="ffnet",
            calibre_id="1234",
            repeats=0,
            max_repeats=10,
            behavior="update",
            title="Test Story",
        )

    def test_increment_repeat(self):
        self.fanfic_info.increment_repeat()
        self.assertEqual(self.fanfic_info.repeats, 1)

    def test_reached_maximum_repeats(self):
        self.fanfic_info.repeats = 10
        self.assertTrue(self.fanfic_info.reached_maximum_repeats())

    @patch("fanfic_info.check_output")
    @patch("builtins.open", new_callable=mock_open)
    @patch("fanfic_info.ff_logging.log")
    def test_get_id_from_calibredb(
        self, mock_ff_logger, mock_open, mock_check_output
    ):
        mock_check_output.return_value = b"1234"
        calibre_information = Mock()
        calibre_information.lock = MagicMock()
        self.assertTrue(
            self.fanfic_info.get_id_from_calibredb(calibre_information)
        )
        self.assertEqual(self.fanfic_info.calibre_id, "1234")
        mock_ff_logger.assert_called_once_with(
            "\t(ffnet) Story is in Calibre with Story ID: 1234", "OKBLUE"
        )

    def test_eq(self):
        other_fanfic_info = FanficInfo(
            url="https://www.fanfiction.net/s/1234",
            site="ffnet",
            calibre_id="1234",
            repeats=0,
            max_repeats=10,
            behavior="update",
            title="Test Story",
        )
        self.assertTrue(self.fanfic_info == other_fanfic_info)

    def test_hash(self):
        fanfic_info_1 = FanficInfo(
            url="https://www.fanfiction.net/s/1234",
            site="ffnet",
            calibre_id="1234",
            repeats=0,
            max_repeats=10,
            behavior="update",
            title="Test Story",
        )
        fanfic_info_2 = FanficInfo(
            url="https://www.fanfiction.net/s/1234",
            site="ffnet",
            calibre_id="1234",
            repeats=0,
            max_repeats=10,
            behavior="update",
            title="Test Story",
        )
        fanfic_info_3 = FanficInfo(
            url="https://www.fanfiction.net/s/5678",
            site="ffnet",
            calibre_id="5678",
            repeats=0,
            max_repeats=10,
            behavior="update",
            title="Another Story",
        )
        self.assertEqual(hash(fanfic_info_1), hash(fanfic_info_2))
        self.assertNotEqual(hash(fanfic_info_1), hash(fanfic_info_3))


if __name__ == "__main__":
    unittest.main()
