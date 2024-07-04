import multiprocessing as mp
from typing import NamedTuple
import unittest
from unittest.mock import patch, Mock

from freezegun import freeze_time
from parameterized import parameterized

import fanfic_info
import ff_waiter


class TestWaitFunction(unittest.TestCase):
    class CheckTimerProcessingTestCase(NamedTuple):
        repeats: int
        expected_time: int

    @parameterized.expand(
        [
            CheckTimerProcessingTestCase(repeats=0, expected_time=0),
            CheckTimerProcessingTestCase(repeats=1, expected_time=60),
            CheckTimerProcessingTestCase(repeats=2, expected_time=120),
            CheckTimerProcessingTestCase(repeats=3, expected_time=180),
            CheckTimerProcessingTestCase(repeats=4, expected_time=240),
            CheckTimerProcessingTestCase(repeats=5, expected_time=300),
        ]
    )
    @freeze_time("2021-01-01 12:00:00")
    @patch("builtins.print")
    @patch("threading.Timer")
    def test_wait(self, repeats, expected_time, mock_timer, mock_print):
        fanfic = fanfic_info.FanficInfo(site="site", url="url", repeats=repeats)
        queue = mp.Queue()
        processor_queues = {"site": queue}
        ff_waiter.process_fanfic(fanfic, processor_queues)
        mock_print.assert_called_once_with(
            f"\x1b[1m2021-01-01 12:00:00 PM\x1b[0m - \x1b[93mWaiting {repeats} minutes for url in queue site\x1b[0m"
        )
        mock_timer.assert_called_once_with(
            expected_time, ff_waiter.insert_after_time, args=(queue, fanfic)
        )
        mock_timer.return_value.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
