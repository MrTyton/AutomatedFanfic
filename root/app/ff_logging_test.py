from typing import NamedTuple
import unittest
from unittest.mock import patch

from freezegun import freeze_time
from parameterized import parameterized

import ff_logging


class TestLogFunction(unittest.TestCase):
    class CheckLogHeaderTestCase(NamedTuple):
        log_type: str
        message: str
        expected_header: str
        expected_color_code: str

    @parameterized.expand(
        [
            CheckLogHeaderTestCase(
                log_type="header",
                message="testing header",
                expected_header="HEADER",
                expected_color_code="95",
            ),
            CheckLogHeaderTestCase(
                log_type="okblue",
                message="testing okblue",
                expected_header="OKBLUE",
                expected_color_code="94",
            ),
            CheckLogHeaderTestCase(
                log_type="okgreen",
                message="testing okgreen",
                expected_header="OKGREEN",
                expected_color_code="92",
            ),
            CheckLogHeaderTestCase(
                log_type="warning",
                message="testing warning",
                expected_header="WARNING",
                expected_color_code="93",
            ),
            CheckLogHeaderTestCase(
                log_type="fail",
                message="testing fail",
                expected_header="FAIL",
                expected_color_code="91",
            ),
            CheckLogHeaderTestCase(
                log_type="endc",
                message="testing endc",
                expected_header="ENDC",
                expected_color_code="0",
            ),
            CheckLogHeaderTestCase(
                log_type="bold",
                message="testing bold",
                expected_header="BOLD",
                expected_color_code="1",
            ),
            CheckLogHeaderTestCase(
                log_type="underline",
                message="testing underline",
                expected_header="UNDERLINE",
                expected_color_code="4",
            ),
        ]
    )
    @freeze_time("2021-01-01 12:00:00")
    @patch("builtins.print")
    def test_log_header(self, name, message, color, code, mock_print):
        ff_logging.log(message, color)
        mock_print.assert_called_once_with(
            f"\x1b[1m2021-01-01 12:00:00 PM\x1b[0m - \x1b[{code}m{message}\x1b[0m"
        )


if __name__ == "__main__":
    unittest.main()
