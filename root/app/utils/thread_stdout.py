"""
Thread-local stdout proxy and capture utility.
"""

from contextlib import contextmanager
import io
import sys
import threading
from typing import IO


class ThreadLocalStdout:
    """Thread-safe sys.stdout proxy with per-thread capture capability."""

    def __init__(self, wrapped: IO[str]) -> None:
        self._wrapped = wrapped
        self._local = threading.local()

    def write(self, s: str) -> int:
        buf = getattr(self._local, "capture_buffer", None)
        if buf is not None:
            return buf.write(s)
        return self._wrapped.write(s)

    def flush(self) -> None:
        buf = getattr(self._local, "capture_buffer", None)
        if buf is not None:
            buf.flush()
        else:
            self._wrapped.flush()

    def fileno(self) -> int:
        try:
            return self._wrapped.fileno()
        except AttributeError, io.UnsupportedOperation:
            raise io.UnsupportedOperation("fileno")

    @property
    def encoding(self) -> str:
        return getattr(self._wrapped, "encoding", None) or "utf-8"

    @property
    def errors(self) -> str:
        return getattr(self._wrapped, "errors", None) or "strict"

    @contextmanager
    def capture(self):
        """Capture this thread's stdout into a StringIO for the duration of the block."""
        self._local.capture_buffer = io.StringIO()
        try:
            yield self._local.capture_buffer
        finally:
            self._local.capture_buffer = None


_tl_stdout: ThreadLocalStdout | None = None
_tl_stdout_lock = threading.Lock()


def ensure_tl_stdout() -> ThreadLocalStdout:
    """Install the thread-local stdout proxy the first time it is needed."""
    global _tl_stdout
    if _tl_stdout is None:
        with _tl_stdout_lock:
            if _tl_stdout is None:
                _tl_stdout = ThreadLocalStdout(sys.stdout)
                sys.stdout = _tl_stdout
    return _tl_stdout
