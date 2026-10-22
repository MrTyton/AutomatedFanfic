import os
import re
import unittest
from typing import NamedTuple

from parameterized import parameterized

from parsers import auto_url_parsers
from models import fanfic_info
from parsers import regex_parsing


class TestRegexParsing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Generate URL parsers once for all tests."""
        cls.url_parsers = auto_url_parsers.generate_url_parsers_from_fanficfare()

    class CheckFilenameExtractionTestCase(NamedTuple):
        input: str
        expected: str

    @parameterized.expand(
        [
            # Test case: Extract 'story-name' from 'story-name-1234'
            CheckFilenameExtractionTestCase(
                input="story-name-1234", expected="story-name"
            ),
            # Test case: Extract 'author' from 'author-name'
            CheckFilenameExtractionTestCase(input="author-name", expected="author"),
            # Test case: Extract 'story-name' from '/path/story-name-1234.epub'
            CheckFilenameExtractionTestCase(
                input=os.path.join("path", "story-name-1234.epub"),
                expected="story-name",
            ),
            # Test case: Extract 'story-name' from '\\path\\to\\story-name-1234.epub'
            CheckFilenameExtractionTestCase(
                input=os.path.join("path", "to", "story-name-1234.epub"),
                expected="story-name",
            ),
        ]
    )
    def test_extract_filename(self, input, expected):
        self.assertEqual(regex_parsing.extract_filename(input), expected)

    class NormalizeUrlTestCase(NamedTuple):
        input_url: str
        expected: str

    @parameterized.expand(
        [
            NormalizeUrlTestCase(
                input_url="archiveofourown.org/works/12345",
                expected="https://archiveofourown.org/works/12345",
            ),
            NormalizeUrlTestCase(
                input_url="  www.fanfiction.net/s/123/1/  ",
                expected="https://www.fanfiction.net/s/123/1/",
            ),
            NormalizeUrlTestCase(
                input_url="https://archiveofourown.org/works/12345",
                expected="https://archiveofourown.org/works/12345",
            ),
            NormalizeUrlTestCase(
                input_url="http://fanfiction.net/s/12345",
                expected="http://fanfiction.net/s/12345",
            ),
            NormalizeUrlTestCase(
                input_url="   ",
                expected="",
            ),
        ]
    )
    def test_normalize_url(self, input_url, expected):
        self.assertEqual(regex_parsing.normalize_url(input_url), expected)

    class CheckGenerateFanficInfoTestCase(NamedTuple):
        input_url: str
        expected_url: str
        expected_site: str

    @parameterized.expand(
        [
            # Fanfiction.net tests
            CheckGenerateFanficInfoTestCase(
                input_url="https://www.fanfiction.net/s/12345678/1/Story-Title",
                expected_url="www.fanfiction.net/s/12345678/1/",
                expected_site="fanfiction",
            ),
            CheckGenerateFanficInfoTestCase(
                input_url="http://fanfiction.net/s/12345678",
                expected_url="www.fanfiction.net/s/12345678/1/",
                expected_site="fanfiction",
            ),
            CheckGenerateFanficInfoTestCase(
                input_url="www.fanfiction.net/s/12345678/1/",
                expected_url="www.fanfiction.net/s/12345678/1/",
                expected_site="fanfiction",
            ),
            # Archive of Our Own (AO3) tests
            CheckGenerateFanficInfoTestCase(
                input_url="https://archiveofourown.org/works/12345678/chapters/98765432",
                expected_url="archiveofourown.org/works/12345678",
                expected_site="archiveofourown",
            ),
            CheckGenerateFanficInfoTestCase(
                input_url="http://archiveofourown.org/works/12345678",
                expected_url="archiveofourown.org/works/12345678",
                expected_site="archiveofourown",
            ),
            CheckGenerateFanficInfoTestCase(
                input_url="archiveofourown.org/works/12345678",
                expected_url="archiveofourown.org/works/12345678",
                expected_site="archiveofourown",
            ),
            # FictionPress tests
            CheckGenerateFanficInfoTestCase(
                input_url="https://www.fictionpress.com/s/12345678/1/Story-Title",
                expected_url="fictionpress.com/s/12345678",
                expected_site="fictionpress",
            ),
            # Royal Road tests
            CheckGenerateFanficInfoTestCase(
                input_url="https://www.royalroad.com/fiction/12345/story-title/chapter/987654/chapter-title",
                expected_url="royalroad.com/fiction/12345",
                expected_site="royalroad",
            ),
            # Sufficient Velocity (SV) tests
            CheckGenerateFanficInfoTestCase(
                input_url="https://forums.sufficientvelocity.com/threads/story-title.12345/page-10",
                expected_url="forums.sufficientvelocity.com/threads/story-title.12345",
                expected_site="sufficientvelocity",
            ),
            # SpaceBattles (SB) tests
            CheckGenerateFanficInfoTestCase(
                input_url="https://forums.spacebattles.com/threads/story-title.12345/reader/",
                expected_url="forums.spacebattles.com/threads/story-title.12345",
                expected_site="spacebattles",
            ),
            # Questionable Questing (QQ) tests
            CheckGenerateFanficInfoTestCase(
                input_url="https://forum.questionablequesting.com/threads/story-title.12345/page-20",
                expected_url="forum.questionablequesting.com/threads/story-title.12345",
                expected_site="questionablequesting",
            ),
            # ScribbleHub test
            CheckGenerateFanficInfoTestCase(
                input_url="https://www.scribblehub.com/series/12345/story-title/",
                expected_url="scribblehub.com/series/12345",
                expected_site="scribblehub",
            ),
            # Other/Unknown URL test
            CheckGenerateFanficInfoTestCase(
                input_url="https://www.some-other-site.com/story/123",
                expected_url="www.some-other-site.com/story/123",  # Keeps the full path after domain
                expected_site="other",
            ),
            CheckGenerateFanficInfoTestCase(
                input_url="http://another-unknown.net/fic/abc",
                expected_url="another-unknown.net/fic/abc",
                expected_site="other",
            ),
            CheckGenerateFanficInfoTestCase(
                input_url="schemeless-unknown.net/fic/abc",
                expected_url="schemeless-unknown.net/fic/abc",
                expected_site="other",
            ),
        ]
    )
    def test_generate_FanficInfo_from_url(self, input_url, expected_url, expected_site):
        """Tests the generate_FanficInfo_from_url function for various sites."""
        fanfic = regex_parsing.generate_FanficInfo_from_url(input_url, self.url_parsers)
        self.assertIsInstance(fanfic, fanfic_info.FanficInfo)
        self.assertEqual(fanfic.url, expected_url)
        self.assertEqual(fanfic.site, expected_site)

    class FanfictionNetChapterTestCase(NamedTuple):
        """Test case for fanfiction.net chapter number handling."""

        input_url: str
        expected_url: str
        description: str

    @parameterized.expand(
        [
            # URLs without chapter numbers should get /1/ added
            FanfictionNetChapterTestCase(
                input_url="https://www.fanfiction.net/s/14534655",
                expected_url="www.fanfiction.net/s/14534655/1/",
                description="URL without chapter should get /1/ added",
            ),
            FanfictionNetChapterTestCase(
                input_url="https://www.fanfiction.net/s/14534655/",
                expected_url="www.fanfiction.net/s/14534655/1/",
                description="URL with trailing slash should get /1/ added",
            ),
            FanfictionNetChapterTestCase(
                input_url="http://fanfiction.net/s/12345678",
                expected_url="www.fanfiction.net/s/12345678/1/",
                description="URL without www should get /1/ added and protocol normalized",
            ),
            # URLs with chapter numbers should be preserved
            FanfictionNetChapterTestCase(
                input_url="https://www.fanfiction.net/s/14534655/1/",
                expected_url="www.fanfiction.net/s/14534655/1/",
                description="URL with /1/ should be preserved",
            ),
            FanfictionNetChapterTestCase(
                input_url="https://www.fanfiction.net/s/14534655/23/",
                expected_url="www.fanfiction.net/s/14534655/1/",
                description="URL with /23/ should be normalized to /1/",
            ),
            FanfictionNetChapterTestCase(
                input_url="https://www.fanfiction.net/s/14534655/23/Story-Title",
                expected_url="www.fanfiction.net/s/14534655/1/",
                description="URL with chapter and title should normalize to /1/",
            ),
            FanfictionNetChapterTestCase(
                input_url="http://fanfiction.net/s/9876543/7",
                expected_url="www.fanfiction.net/s/9876543/1/",
                description="URL with chapter but no trailing slash should normalize to /1/",
            ),
        ]
    )
    def test_fanfiction_net_chapter_handling(
        self, input_url, expected_url, description
    ):
        """Test that fanfiction.net URLs always have chapter numbers."""
        fanfic = regex_parsing.generate_FanficInfo_from_url(input_url, self.url_parsers)

        # Check that site is correctly identified
        self.assertEqual(
            fanfic.site, "fanfiction", f"Site should be 'fanfiction' for {description}"
        )

        # Check that URL matches expected format
        self.assertEqual(
            fanfic.url,
            expected_url,
            f"URL mismatch for {description}: expected {expected_url}, got {fanfic.url}",
        )

        # Verify that the URL contains a chapter number (format: /s/ID/CHAPTER/)
        chapter_pattern = r"/s/\d+/\d+/"
        self.assertIsNotNone(
            re.search(chapter_pattern, fanfic.url),
            f"URL should contain chapter number pattern for {description}: {fanfic.url}",
        )


class TestCheckFailureFromMessage(unittest.TestCase):
    """Tests for check_failure_from_message() single-message helper."""

    class Case(NamedTuple):
        msg: str
        expected: bool

    @parameterized.expand(
        [
            Case(msg="story already contains 5 chapters.", expected=True),
            Case(
                msg="story doesn't contain any recognizable chapters, probably from a different source.  Not updating.",
                expected=True,
            ),
            Case(msg="No story URL found in epub to update.", expected=True),
            Case(
                msg="Login Failed on non-interactive process. Set username and password in personal.ini.",
                expected=True,
            ),
            Case(
                msg="400 Client Error: Bad Request for url: https://example.com",
                expected=True,
            ),
            Case(
                msg="403 Client Error: Forbidden for url: https://example.com",
                expected=True,
            ),
            Case(
                msg="Connection to flaresolverr proxy server failed",
                expected=True,
            ),
            Case(msg="Download complete.", expected=False),
            Case(msg="", expected=False),
        ]
    )
    def test_check_failure_from_message(self, msg, expected):
        self.assertEqual(regex_parsing.check_failure_from_message(msg), expected)


class TestCheckForceableFromMessage(unittest.TestCase):
    """Tests for check_forceable_from_message() single-message helper."""

    class Case(NamedTuple):
        msg: str
        expected: bool

    @parameterized.expand(
        [
            Case(
                msg="story contains 5 chapters, more than source: 3.",
                expected=True,
            ),
            Case(
                msg="File(test.epub) Updated(2022-01-01) more recently than Story(2021-12-31) - Skipping",
                expected=True,
            ),
            Case(msg="Download complete.", expected=False),
            Case(msg="", expected=False),
            # Failure patterns must NOT trigger forceable
            Case(msg="story already contains 5 chapters.", expected=False),
        ]
    )
    def test_check_forceable_from_message(self, msg, expected):
        self.assertEqual(regex_parsing.check_forceable_from_message(msg), expected)


if __name__ == "__main__":
    unittest.main()
