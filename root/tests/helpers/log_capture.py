"""LogCapture: a real-queue-based log capture helper for unit tests.

Usage (pytest fixture style)::

    from helpers.log_capture import LogCapture
    from utils import ff_logging

    @pytest.fixture
    def log_capture():
        cap = LogCapture()
        ff_logging.set_log_forward_queue(cap)
        cap.drain()          # discard buffered entries replayed at attach time
        yield cap
        ff_logging.set_log_forward_queue(None)

Then in a test::

    def test_something(log_capture):
        do_thing_that_logs()
        assert "expected message" in log_capture.messages()
"""

import queue


class LogCapture:
    """Wraps a real ``queue.Queue`` so it satisfies the ``LogQueue`` protocol.

    Attaches to ``ff_logging.set_log_forward_queue`` to capture log entries
    produced by real production code without patching the logging module.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[dict[str, object]] = queue.Queue()

    # ── LogQueue protocol ──────────────────────────────────────────────────

    def put_nowait(self, item: dict[str, object]) -> None:
        self._queue.put_nowait(item)

    def put(
        self,
        item: dict[str, object],
        block: bool = True,
        timeout: float | None = None,
    ) -> None:
        self._queue.put(item, block=block, timeout=timeout)

    def get(
        self,
        block: bool = True,
        timeout: float | None = None,
    ) -> dict[str, object]:
        return self._queue.get(block=block, timeout=timeout)

    def get_nowait(self) -> dict[str, object]:
        return self._queue.get_nowait()

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    # ── Helpers ────────────────────────────────────────────────────────────

    def drain(self) -> None:
        """Discard all currently queued entries (e.g. historical replay)."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def messages(self) -> list[str]:
        """Drain the queue and return the ``message`` field of each entry."""
        msgs: list[str] = []
        while True:
            try:
                entry = self._queue.get_nowait()
                msgs.append(str(entry.get("message", "")))
            except queue.Empty:
                break
        return msgs
