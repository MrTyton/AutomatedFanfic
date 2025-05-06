import os
import re
import unittest
from typing import NamedTuple, Optional
from unittest.mock import patch

from parameterized import parameterized

import fanfic_info
import regex_parsing


class TestRegexParsing(unittest.TestCase):
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
            CheckFilenameExtractionTestCase(
                input="author-name", expected="author"
            ),
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

    class CheckRegexesTestCase(NamedTuple):
        output: str
        match: str
        message: str
        expected: bool

    @parameterized.expand(
        [
            # Test case: 'test' is in 'test output'
            CheckRegexesTestCase(
                output="test output",
                match="test",
                message="test message",
                expected=True,
            ),
            # Test case: 'not match' is not in 'test output'
            CheckRegexesTestCase(
                output="test output",
                match="not match",
                message="test message",
                expected=False,
            ),
        ]
    )
    @patch("regex_parsing.ff_logging.log_failure")
    def test_check_regexes(
        self,
        test_output,
        test_pattern,
        test_message,
        expected_result,
        mock_log_failure,
    ):
        self.assertEqual(
            regex_parsing.check_regexes(
                test_output, re.compile(test_pattern), test_message
            ),
            expected_result,
        )
        if expected_result:
            mock_log_failure.assert_called_once_with(test_message)
        else:
            mock_log_failure.assert_not_called()

    class CheckRegexFailuresTestCase(NamedTuple):
        output: str
        expected: bool
        message: Optional[str]

    @parameterized.expand(
        [
            # Test case: Output contains 5 chapters, expected failure, with a specific message
            CheckRegexFailuresTestCase(
                output="test output already contains 5 chapters.",
                expected=False,
                message="Issue with story, site is broken. Story likely hasn't updated on site yet.",
            ),
            # Test case: Output doesn't contain any recognizable chapters, expected failure, with a specific message
            CheckRegexFailuresTestCase(
                output="test output doesn't contain any recognizable chapters, probably from a different source.  Not updating.",
                expected=False,
                message="Something is messed up with the site or the epub. No chapters found.",
            ),
            # Test case: Generic output, expected success, no specific message
            CheckRegexFailuresTestCase(
                output="test output", expected=True, message=None
            ),
        ]
    )
    @patch("regex_parsing.ff_logging.log_failure")
    def test_check_failure_regexes(
        self, input, expected, log_message, mock_log_failure
    ):
        self.assertEqual(regex_parsing.check_failure_regexes(input), expected)
        if log_message:
            mock_log_failure.assert_called_once_with(log_message)
        else:
            mock_log_failure.assert_not_called()

    class CheckForceableRegexTestCase(NamedTuple):
        output: str
        expected: bool
        message: Optional[str]

    @parameterized.expand(
        [
            # Test case: Output contains 5 chapters, more than source: 3, expected True, with a specific message
            CheckForceableRegexTestCase(
                output="test output contains 5 chapters, more than source: 3.",
                expected=True,
                message="Chapter difference between source and destination. Forcing update.",
            ),
            # Test case: File has been updated more recently than the story, expected True, with a specific message
            CheckForceableRegexTestCase(
                output="File(test.epub) Updated(2022-01-01) more recently than Story(2021-12-31) - Skipping",
                expected=True,
                message="File has been updated more recently than the story, this is likely a metadata bug. Forcing update.",
            ),
            # Test case: Generic output, expected False, no specific message
            CheckForceableRegexTestCase(
                output="test output", expected=False, message=None
            ),
        ]
    )
    @patch("regex_parsing.ff_logging.log_failure")
    def test_check_forceable_regexes(
        self, input, expected, log_message, mock_log_failure
    ):
        self.assertEqual(regex_parsing.check_forceable_regexes(input), expected)
        if log_message:
            mock_log_failure.assert_called_once_with(log_message)
        else:
            mock_log_failure.assert_not_called()

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
                expected_site="ffnet",
            ),
            CheckGenerateFanficInfoTestCase(
                input_url="http://fanfiction.net/s/12345678",
                expected_url="www.fanfiction.net/s/12345678",
                expected_site="ffnet",
            ),
            # Archive of Our Own (AO3) tests
            CheckGenerateFanficInfoTestCase(
                input_url="https://archiveofourown.org/works/12345678/chapters/98765432",
                expected_url="archiveofourown.org/works/12345678",
                expected_site="ao3",
            ),
            CheckGenerateFanficInfoTestCase(
                input_url="http://archiveofourown.org/works/12345678",
                expected_url="archiveofourown.org/works/12345678",
                expected_site="ao3",
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
                expected_site="sv",
            ),
            # SpaceBattles (SB) tests
            CheckGenerateFanficInfoTestCase(
                input_url="https://forums.spacebattles.com/threads/story-title.12345/reader/",
                expected_url="forums.spacebattles.com/threads/story-title.12345",
                expected_site="sb",
            ),
            # Questionable Questing (QQ) tests
            CheckGenerateFanficInfoTestCase(
                input_url="https://forum.questionablequesting.com/threads/story-title.12345/page-20",
                expected_url="forum.questionablequesting.com/threads/story-title.12345",
                expected_site="qq",
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
        ]
    )
    def test_generate_FanficInfo_from_url(
        self, input_url, expected_url, expected_site
    ):
        """Tests the generate_FanficInfo_from_url function for various sites."""
        fanfic = regex_parsing.generate_FanficInfo_from_url(input_url)
        self.assertIsInstance(fanfic, fanfic_info.FanficInfo)
        self.assertEqual(fanfic.url, expected_url)
        self.assertEqual(fanfic.site, expected_site)


if __name__ == "__main__":
    unittest.main()
