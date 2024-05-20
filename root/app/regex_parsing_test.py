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
            # Test case: Extract 'story' from 'story-name-1234'
            CheckFilenameExtractionTestCase(input="story-name-1234", expected="story"),
            # Test case: Extract 'author' from 'author-name'
            CheckFilenameExtractionTestCase(input="author-name", expected="author"),
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
        self, test_output, test_pattern, test_message, expected_result, mock_log_failure
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

    @parameterized.expand([
        # Test case: Output contains 5 chapters, expected failure, with a specific message
        CheckRegexFailuresTestCase(
            output="test output already contains 5 chapters.",
            expected=False,
            message="Issue with story, site is broken. Story likely hasn't updated on site yet."
        ),

        # Test case: Output doesn't contain any recognizable chapters, expected failure, with a specific message
        CheckRegexFailuresTestCase(
            output="test output doesn't contain any recognizable chapters, probably from a different source.  Not updating.",
            expected=False,
            message="Something is messed up with the site or the epub. No chapters found."
        ),

        # Test case: Generic output, expected success, no specific message
        CheckRegexFailuresTestCase(
            output="test output",
            expected=True,
            message=None
        ),
    ])
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

    @parameterized.expand([
        # Test case: Output contains 5 chapters, more than source: 3, expected True, with a specific message
        CheckForceableRegexTestCase(
            output="test output contains 5 chapters, more than source: 3.",
            expected=True,
            message="Chapter difference between source and destination. Forcing update."
        ),

        # Test case: File has been updated more recently than the story, expected True, with a specific message
        CheckForceableRegexTestCase(
            output="File(test.epub) Updated(2022-01-01) more recently than Story(2021-12-31) - Skipping",
            expected=True,
            message="File has been updated more recently than the story, this is likely a metadata bug. Forcing update."
        ),

        # Test case: Generic output, expected False, no specific message
        CheckForceableRegexTestCase(
            output="test output",
            expected=False,
            message=None
        ),
    ])
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
        url: str
        expected_url: str
        expected_site: str

    @parameterized.expand([
        # Test case: Fanfiction.net URL
        CheckGenerateFanficInfoTestCase(
            url="https://www.fanfiction.net/s/1234",
            expected_url="www.fanfiction.net/s/1234",
            expected_site="ffnet"
        ),

        # Test case: Archive of Our Own URL
        CheckGenerateFanficInfoTestCase(
            url="https://archiveofourown.org/works/5678",
            expected_url="archiveofourown.org/works/5678",
            expected_site="ao3"
        ),
    ])
    def test_generate_FanficInfo_from_url(self, input_url, expected_url, expected_site):
        fanfic = regex_parsing.generate_FanficInfo_from_url(input_url)
        self.assertIsInstance(fanfic, fanfic_info.FanficInfo)
        self.assertEqual(fanfic.url, expected_url)
        self.assertEqual(fanfic.site, expected_site)


if __name__ == "__main__":
    unittest.main()
