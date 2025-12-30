import unittest

from fanfic_info import FanficInfo
from typing import NamedTuple, Any  # Added NamedTuple and Any
from parameterized import parameterized  # Added parameterized


class TestFanficInfo(unittest.TestCase):
    def setUp(self):
        self.fanfic_info = FanficInfo(
            url="https://www.fanfiction.net/s/1234",
            site="ffnet",
            calibre_id="1234",
            repeats=0,
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
        self.assertIsNone(fanfic_info_default.behavior)
        self.assertIsNone(fanfic_info_default.title)
        self.assertIsNone(fanfic_info_default.retry_decision)

    def test_increment_repeat(self):
        self.fanfic_info.increment_repeat()
        self.assertEqual(self.fanfic_info.repeats, 1)
        # Test with None repeats
        self.fanfic_info.repeats = None
        self.fanfic_info.increment_repeat()
        self.assertIsNone(self.fanfic_info.repeats)

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
                obj1=FanficInfo(url="https://a.com/1", site="s1", calibre_id="1"),
                obj2=FanficInfo(
                    url="https://a.com/1", site="s1", calibre_id="1", title="T"
                ),
                expected_equality=True,
            ),
            CheckEqualityTestCase(
                name="equal_none_calibre_id",
                obj1=FanficInfo(url="https://a.com/1", site="s1", calibre_id=None),
                obj2=FanficInfo(url="https://a.com/1", site="s1", calibre_id=None),
                expected_equality=True,
            ),
            CheckEqualityTestCase(
                name="not_equal_different_url",
                obj1=FanficInfo(url="https://a.com/1", site="s1", calibre_id="1"),
                obj2=FanficInfo(url="https://a.com/2", site="s1", calibre_id="1"),
                expected_equality=False,
            ),
            CheckEqualityTestCase(
                name="not_equal_different_site",
                obj1=FanficInfo(url="https://a.com/1", site="s1", calibre_id="1"),
                obj2=FanficInfo(url="https://a.com/1", site="s2", calibre_id="1"),
                expected_equality=False,
            ),
            CheckEqualityTestCase(
                name="not_equal_different_calibre_id",
                obj1=FanficInfo(url="https://a.com/1", site="s1", calibre_id="1"),
                obj2=FanficInfo(url="https://a.com/1", site="s1", calibre_id="2"),
                expected_equality=False,
            ),
            CheckEqualityTestCase(
                name="not_equal_one_none_calibre_id",
                obj1=FanficInfo(url="https://a.com/1", site="s1", calibre_id="1"),
                obj2=FanficInfo(url="https://a.com/1", site="s1", calibre_id=None),
                expected_equality=False,
            ),
            CheckEqualityTestCase(
                name="not_equal_different_type",
                obj1=FanficInfo(url="https://a.com/1", site="s1", calibre_id="1"),
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
                obj1=FanficInfo(url="https://a.com/1", site="s1", calibre_id=None),
                obj2=FanficInfo(url="https://a.com/1", site="s1", calibre_id=None),
                expected_hash_equality=True,
            ),
            CheckHashTestCase(
                name="not_equal_hash_different_url",
                obj1=FanficInfo(url="https://a.com/1", site="s1", calibre_id="1"),
                obj2=FanficInfo(url="https://a.com/2", site="s1", calibre_id="1"),
                expected_hash_equality=False,
            ),
            CheckHashTestCase(
                name="not_equal_hash_different_site",
                obj1=FanficInfo(url="https://a.com/1", site="s1", calibre_id="1"),
                obj2=FanficInfo(url="https://a.com/1", site="s2", calibre_id="1"),
                expected_hash_equality=False,
            ),
            CheckHashTestCase(
                name="not_equal_hash_different_calibre_id",
                obj1=FanficInfo(url="https://a.com/1", site="s1", calibre_id="1"),
                obj2=FanficInfo(url="https://a.com/1", site="s1", calibre_id="2"),
                expected_hash_equality=False,
            ),
            CheckHashTestCase(
                name="not_equal_hash_one_none_calibre_id",
                obj1=FanficInfo(url="https://a.com/1", site="s1", calibre_id="1"),
                obj2=FanficInfo(url="https://a.com/1", site="s1", calibre_id=None),
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
