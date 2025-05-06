import unittest
from unittest.mock import Mock, patch, MagicMock
from fanfic_info import FanficInfo
from subprocess import CalledProcessError
from typing import NamedTuple, Any  # Added NamedTuple and Any
from parameterized import parameterized  # Added parameterized


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

    def test_init_defaults(self):
        """Test FanficInfo initialization with default values."""
        fanfic_info_default = FanficInfo(
            url="https://archiveofourown.org/works/5678", site="ao3"
        )
        self.assertEqual(
            fanfic_info_default.url,
            "https://archiveofourown.org/works/5678",
        )
        self.assertEqual(fanfic_info_default.site, "ao3")
        self.assertIsNone(fanfic_info_default.calibre_id)
        self.assertEqual(fanfic_info_default.repeats, 0)
        self.assertEqual(fanfic_info_default.max_repeats, 10)
        self.assertIsNone(fanfic_info_default.behavior)
        self.assertIsNone(fanfic_info_default.title)
        self.assertFalse(fanfic_info_default.hail_mary)

    def test_increment_repeat(self):
        self.fanfic_info.increment_repeat()
        self.assertEqual(self.fanfic_info.repeats, 1)
        # Test with None repeats
        self.fanfic_info.repeats = None
        self.fanfic_info.increment_repeat()
        self.assertIsNone(self.fanfic_info.repeats)

    def test_reached_maximum_repeats_false(self):
        """Test when repeats are less than max_repeats."""
        self.fanfic_info.repeats = 5
        reached, hail_mary = self.fanfic_info.reached_maximum_repeats()
        self.assertFalse(reached)
        self.assertFalse(hail_mary)
        self.assertFalse(self.fanfic_info.hail_mary)

    @patch("fanfic_info.ff_logging.log")
    def test_reached_maximum_repeats_true_first_time(self, mock_ff_logger):
        """Test when repeats reach max_repeats for the first time (enable hail mary)."""
        self.fanfic_info.repeats = 10
        reached, hail_mary = self.fanfic_info.reached_maximum_repeats()
        self.assertTrue(reached)
        self.assertFalse(hail_mary)
        self.assertTrue(self.fanfic_info.hail_mary)
        self.assertEqual(
            self.fanfic_info.repeats, 720
        )  # Check if repeats reset for hail mary
        mock_ff_logger.assert_called_once()
        self.assertIn(
            "Enabling Hail-Mary protocol",
            mock_ff_logger.call_args[0][0],
        )

    def test_reached_maximum_repeats_true_hail_mary_active(self):
        """Test when repeats exceed max_repeats and hail mary is active."""
        self.fanfic_info.repeats = 11
        self.fanfic_info.hail_mary = True
        reached, hail_mary = self.fanfic_info.reached_maximum_repeats()
        self.assertTrue(reached)
        self.assertTrue(hail_mary)

    def test_reached_maximum_repeats_none(self):
        """Test when repeats or max_repeats is None."""
        self.fanfic_info.repeats = None
        reached, hail_mary = self.fanfic_info.reached_maximum_repeats()
        self.assertFalse(reached)
        self.assertFalse(hail_mary)

        self.fanfic_info.repeats = 5
        self.fanfic_info.max_repeats = None
        reached, hail_mary = self.fanfic_info.reached_maximum_repeats()
        self.assertFalse(reached)
        self.assertFalse(hail_mary)

    @patch("fanfic_info.check_output")
    @patch("fanfic_info.ff_logging.log")
    def test_get_id_from_calibredb_success(
        self, mock_ff_logger, mock_check_output
    ):
        """Test successfully finding the ID in Calibre."""
        mock_check_output.return_value = b" 1234 \n"  # Simulate Calibre output
        calibre_information = Mock()
        calibre_information.lock = MagicMock()
        calibre_information.__str__ = Mock(
            return_value="--with-library test_library"
        )

        result = self.fanfic_info.get_id_from_calibredb(calibre_information)

        self.assertTrue(result)
        self.assertEqual(self.fanfic_info.calibre_id, "1234")
        mock_check_output.assert_called_once_with(
            'calibredb search "Identifiers:https://www.fanfiction.net/s/1234" --with-library test_library',
            shell=True,
            stderr=-2,  # STDOUT
            stdin=-1,  # PIPE
        )
        mock_ff_logger.assert_called_once_with(
            "\t(ffnet) Story is in Calibre with Story ID: 1234",
            "OKBLUE",
        )

    @patch("fanfic_info.check_output")
    @patch("fanfic_info.ff_logging.log")
    def test_get_id_from_calibredb_not_found(
        self, mock_ff_logger, mock_check_output
    ):
        """Test when the story is not found in Calibre."""
        mock_check_output.side_effect = CalledProcessError(1, "cmd", output=b"")
        calibre_information = Mock()
        calibre_information.lock = MagicMock()
        calibre_information.__str__ = Mock(
            return_value="--with-library test_library"
        )
        # Reset calibre_id to simulate not finding it initially
        self.fanfic_info.calibre_id = None

        result = self.fanfic_info.get_id_from_calibredb(calibre_information)

        self.assertFalse(result)
        self.assertIsNone(self.fanfic_info.calibre_id)  # Should remain None
        mock_check_output.assert_called_once_with(
            'calibredb search "Identifiers:https://www.fanfiction.net/s/1234" --with-library test_library',
            shell=True,
            stderr=-2,  # STDOUT
            stdin=-1,  # PIPE
        )
        mock_ff_logger.assert_called_once_with(
            "\t(ffnet) Story not in Calibre", "WARNING"
        )

    # --- Equality Tests ---
    class CheckEqualityTestCase(NamedTuple):
        """Structure for equality test cases."""

        name: str
        obj1: Any
        obj2: Any
        expected_equality: bool

    @parameterized.expand(
        [
            CheckEqualityTestCase(
                name="equal_same_attributes",
                obj1=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id="1"
                ),
                obj2=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id="1", title="T"
                ),
                expected_equality=True,
            ),
            CheckEqualityTestCase(
                name="equal_none_calibre_id",
                obj1=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id=None
                ),
                obj2=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id=None
                ),
                expected_equality=True,
            ),
            CheckEqualityTestCase(
                name="not_equal_different_url",
                obj1=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id="1"
                ),
                obj2=FanficInfo(
                    url="https://a.com/2", site="s1", calibre_id="1"
                ),
                expected_equality=False,
            ),
            CheckEqualityTestCase(
                name="not_equal_different_site",
                obj1=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id="1"
                ),
                obj2=FanficInfo(
                    url="https://a.com/1", site="s2", calibre_id="1"
                ),
                expected_equality=False,
            ),
            CheckEqualityTestCase(
                name="not_equal_different_calibre_id",
                obj1=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id="1"
                ),
                obj2=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id="2"
                ),
                expected_equality=False,
            ),
            CheckEqualityTestCase(
                name="not_equal_one_none_calibre_id",
                obj1=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id="1"
                ),
                obj2=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id=None
                ),
                expected_equality=False,
            ),
            CheckEqualityTestCase(
                name="not_equal_different_type",
                obj1=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id="1"
                ),
                obj2="not a fanfic info",
                expected_equality=False,
            ),
        ]
    )
    def test_equality(self, name, obj1, obj2, expected_equality):
        """Test the __eq__ method with various inputs."""
        if expected_equality:
            self.assertEqual(
                obj1,
                obj2,
                f"Test case '{name}' failed: Objects should be equal.",
            )
            self.assertTrue(
                obj1 == obj2,
                f"Test case '{name}' failed: == should return True.",
            )
        else:
            self.assertNotEqual(
                obj1,
                obj2,
                f"Test case '{name}' failed: Objects should not be equal.",
            )
            self.assertFalse(
                obj1 == obj2,
                f"Test case '{name}' failed: == should return False.",
            )

    # --- Hash Tests ---
    class CheckHashTestCase(NamedTuple):
        """Structure for hash test cases."""

        name: str
        obj1: FanficInfo
        obj2: FanficInfo
        expected_hash_equality: bool

    @parameterized.expand(
        [
            CheckHashTestCase(
                name="equal_hash_same_key_attributes",
                obj1=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id="1", title="T1"
                ),
                obj2=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id="1", title="T2"
                ),
                expected_hash_equality=True,
            ),
            CheckHashTestCase(
                name="equal_hash_none_calibre_id",
                obj1=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id=None
                ),
                obj2=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id=None
                ),
                expected_hash_equality=True,
            ),
            CheckHashTestCase(
                name="not_equal_hash_different_url",
                obj1=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id="1"
                ),
                obj2=FanficInfo(
                    url="https://a.com/2", site="s1", calibre_id="1"
                ),
                expected_hash_equality=False,
            ),
            CheckHashTestCase(
                name="not_equal_hash_different_site",
                obj1=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id="1"
                ),
                obj2=FanficInfo(
                    url="https://a.com/1", site="s2", calibre_id="1"
                ),
                expected_hash_equality=False,
            ),
            CheckHashTestCase(
                name="not_equal_hash_different_calibre_id",
                obj1=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id="1"
                ),
                obj2=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id="2"
                ),
                expected_hash_equality=False,
            ),
            CheckHashTestCase(
                name="not_equal_hash_one_none_calibre_id",
                obj1=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id="1"
                ),
                obj2=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id=None
                ),
                expected_hash_equality=False,
            ),
        ]
    )
    def test_hash(self, name, obj1, obj2, expected_hash_equality):
        """Test hash consistency and difference based on key attributes."""
        if expected_hash_equality:
            self.assertEqual(
                hash(obj1),
                hash(obj2),
                f"Test case '{name}' failed: Hashes should be equal.",
            )
        else:
            self.assertNotEqual(
                hash(obj1),
                hash(obj2),
                f"Test case '{name}' failed: Hashes should not be equal.",
            )


if __name__ == "__main__":
    unittest.main()
