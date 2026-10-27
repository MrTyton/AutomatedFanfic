import io
import sys
import threading
import unittest

from utils.thread_stdout import ThreadLocalStdout, ensure_tl_stdout


class TestThreadStdout(unittest.TestCase):
    def test_capture_captures_in_context(self):
        buf = io.StringIO()
        tls = ThreadLocalStdout(buf)
        with tls.capture() as captured:
            tls.write("hello in capture")
        self.assertEqual(captured.getvalue(), "hello in capture")
        self.assertEqual(buf.getvalue(), "")

    def test_write_passthrough_outside_capture(self):
        buf = io.StringIO()
        tls = ThreadLocalStdout(buf)
        tls.write("direct write")
        self.assertEqual(buf.getvalue(), "direct write")

    def test_flush_passthrough_and_capture(self):
        buf = io.StringIO()
        tls = ThreadLocalStdout(buf)
        with tls.capture():
            tls.write("captured")
            tls.flush()
        tls.flush()
        self.assertEqual(buf.getvalue(), "")

    def test_fileno_behavior(self):
        buf = io.StringIO()
        tls = ThreadLocalStdout(buf)
        with self.assertRaises(io.UnsupportedOperation):
            tls.fileno()

    def test_encoding_and_errors(self):
        buf = io.StringIO()
        tls = ThreadLocalStdout(buf)
        self.assertIsInstance(tls.encoding, str)
        self.assertIsInstance(tls.errors, str)

    def test_threads_are_isolated(self):
        buf = io.StringIO()
        tls = ThreadLocalStdout(buf)
        results: dict[int, str] = {}

        def worker(tid: int, text: str):
            with tls.capture() as cap:
                tls.write(text)
                results[tid] = cap.getvalue()

        t1 = threading.Thread(target=worker, args=(1, "thread1"))
        t2 = threading.Thread(target=worker, args=(2, "thread2"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        self.assertEqual(results[1], "thread1")
        self.assertEqual(results[2], "thread2")

    def test_ensure_tl_stdout_replaces_sys_stdout(self):
        original_stdout = sys.stdout
        try:
            proxy = ensure_tl_stdout()
            self.assertIs(sys.stdout, proxy)
            self.assertIsInstance(proxy, ThreadLocalStdout)
        finally:
            sys.stdout = original_stdout


if __name__ == "__main__":
    unittest.main()
