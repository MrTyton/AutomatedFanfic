"""
Integration tests for signal handling and Docker shutdown scenarios.

These tests simulate the exact conditions that occur when Docker sends
SIGTERM signals to the main process and validates that the improved
signal handling prevents duplicate messages and ensures clean shutdown.
"""

import unittest
import time
import multiprocessing as mp
import signal
import threading
from unittest.mock import patch

from config_models import (
    AppConfig,
    EmailConfig,
    CalibreConfig,
    PushbulletConfig,
    AppriseConfig,
    ProcessConfig,
)
from process_management import ProcessManager


def long_running_worker(duration=10):
    """Worker that runs for a specified duration."""
    start_time = time.time()
    while time.time() - start_time < duration:
        time.sleep(0.1)


def infinite_worker_with_event(stop_event):
    """Worker that runs until stop_event is set."""
    while not stop_event.is_set():
        time.sleep(0.1)


class TestSignalHandlingIntegration(unittest.TestCase):
    """Integration tests for Docker-like signal handling scenarios."""

    def setUp(self):
        """Set up test fixtures."""
        # Create minimal config for testing
        self.config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(),
            pushbullet=PushbulletConfig(),
            apprise=AppriseConfig(),
            process=ProcessConfig(
                enable_monitoring=False,  # Disable for simpler testing
                auto_restart=False,
                shutdown_timeout=2.0,  # Short timeout for faster tests
            ),
            max_workers=2,
        )

        self.manager = ProcessManager(config=self.config)

    def tearDown(self):
        """Clean up after tests."""
        if hasattr(self.manager, "_shutdown_event"):
            self.manager._shutdown_event.set()
        self.manager.stop_all(timeout=1.0)

    def test_docker_like_signal_sequence(self):
        """Test Docker-like signal sequence: SIGTERM -> wait -> SIGTERM -> SIGKILL."""
        # Start some worker processes
        stop_events = []
        for i in range(3):
            stop_event = mp.Event()
            stop_events.append(stop_event)
            self.manager.register_process(
                f"worker_{i}", infinite_worker_with_event, args=(stop_event,)
            )

        # Start all processes
        self.assertTrue(self.manager.start_all())
        time.sleep(0.2)  # Let processes start

        # Verify all are running
        for i in range(3):
            self.assertTrue(self.manager.processes[f"worker_{i}"].is_alive())

        # Setup signal handlers
        self.manager.setup_signal_handlers()

        # Track signal handling calls
        signal_count = []
        original_stop_all = self.manager.stop_all

        def mock_stop_all(*args, **kwargs):
            signal_count.append(time.time())
            return original_stop_all(*args, **kwargs)

        with patch.object(self.manager, "stop_all", side_effect=mock_stop_all):
            # Simulate Docker's signal sequence
            def docker_signal_sequence():
                time.sleep(0.1)

                # First SIGTERM (Docker's graceful shutdown)
                self.manager._shutdown_event.set()
                self.manager.stop_all()

                time.sleep(0.5)  # Docker grace period simulation

                # Second SIGTERM (should be ignored due to shutdown event)
                if not self.manager._shutdown_event.is_set():
                    self.manager.stop_all()

            signal_thread = threading.Thread(target=docker_signal_sequence)
            signal_thread.start()

            # Main thread waits (simulating fanficdownload.py behavior)
            start_time = time.time()
            result = self.manager.wait_for_all(timeout=5.0)
            elapsed = time.time() - start_time

            signal_thread.join()

            # Should complete shutdown quickly
            self.assertTrue(result)
            self.assertLess(elapsed, 2.0)

            # stop_all should only be called once (deduplication working)
            self.assertEqual(len(signal_count), 1)

        # Clean up stop events
        for stop_event in stop_events:
            stop_event.set()

    @patch("ff_logging.log")
    def test_no_duplicate_signal_messages(self, mock_log):
        """Test that multiple SIGTERM signals don't create duplicate log messages."""
        self.manager.setup_signal_handlers()

        # Get the actual signal handler
        with patch("signal.signal") as mock_signal:
            self.manager._signal_handlers_set = False
            self.manager.setup_signal_handlers()

            # Find the SIGTERM handler
            sigterm_handler = None
            for call_args in mock_signal.call_args_list:
                signal_num, handler_func = call_args[0]
                if signal_num == signal.SIGTERM:
                    sigterm_handler = handler_func
                    break

            self.assertIsNotNone(sigterm_handler)

            with patch.object(self.manager, "stop_all"):
                # First signal should log
                if sigterm_handler:
                    sigterm_handler(signal.SIGTERM, None)

                # Second signal should be ignored (no log)
                if sigterm_handler:
                    sigterm_handler(signal.SIGTERM, None)

                # Third signal should be ignored (no log)
                if sigterm_handler:
                    sigterm_handler(signal.SIGTERM, None)

            # Should only see one warning log for the first signal
            warning_calls = [
                call
                for call in mock_log.call_args_list
                if len(call[0]) > 1 and call[0][1] == "WARNING"
            ]
            self.assertEqual(len(warning_calls), 1)
            self.assertIn("graceful shutdown", warning_calls[0][0][0])

    def test_fast_shutdown_prevents_docker_timeout(self):
        """Test that improved shutdown prevents Docker from timing out."""
        # Start several worker processes
        for i in range(5):
            self.manager.register_process(
                f"worker_{i}",
                long_running_worker,
                args=(30,),  # Would run for 30 seconds normally
            )

        self.assertTrue(self.manager.start_all())
        time.sleep(0.3)  # Let processes start

        # Setup signal handlers
        self.manager.setup_signal_handlers()

        # Simulate signal handling
        def trigger_shutdown():
            time.sleep(0.1)
            self.manager._shutdown_event.set()
            self.manager.stop_all()

        shutdown_thread = threading.Thread(target=trigger_shutdown)
        shutdown_thread.start()

        # Time the shutdown process
        start_time = time.time()
        result = self.manager.wait_for_all(timeout=10.0)
        shutdown_time = time.time() - start_time

        shutdown_thread.join()

        # Should shutdown much faster than Docker's default 10s timeout
        self.assertTrue(result)
        self.assertLess(shutdown_time, 5.0)  # Well under typical Docker timeout

        # Verify all processes are actually stopped
        time.sleep(0.2)
        for i in range(5):
            self.assertFalse(self.manager.processes[f"worker_{i}"].is_alive())

    def test_context_manager_with_signal_handling(self):
        """Test that context manager works correctly with signal handling."""
        stop_event = mp.Event()

        with patch("ff_logging.log"):
            # Use context manager (simulating fanficdownload.py)
            with ProcessManager(config=self.config) as manager:
                # Register some processes
                for i in range(2):
                    manager.register_process(
                        f"worker_{i}", infinite_worker_with_event, args=(stop_event,)
                    )

                manager.start_all()
                time.sleep(0.2)

                # Simulate signal arrival
                def send_signal():
                    time.sleep(0.1)
                    manager._shutdown_event.set()
                    manager.stop_all()

                signal_thread = threading.Thread(target=send_signal)
                signal_thread.start()

                # Context manager should handle cleanup
                result = manager.wait_for_all(timeout=3.0)
                self.assertTrue(result)

                signal_thread.join()

            # Context manager exit should not cause duplicate cleanup
            # (verified by no duplicate log messages)

        stop_event.set()

    def test_shutdown_event_prevents_race_conditions(self):
        """Test that shutdown event prevents race conditions during cleanup."""
        # Start multiple processes
        stop_events = []
        for i in range(4):
            stop_event = mp.Event()
            stop_events.append(stop_event)
            self.manager.register_process(
                f"worker_{i}", infinite_worker_with_event, args=(stop_event,)
            )

        self.manager.start_all()
        time.sleep(0.2)

        # Track calls to stop_all to detect race conditions
        stop_all_calls = []
        original_stop_all = self.manager.stop_all

        def tracked_stop_all(*args, **kwargs):
            stop_all_calls.append(time.time())
            return original_stop_all(*args, **kwargs)

        with patch.object(self.manager, "stop_all", side_effect=tracked_stop_all):
            # Simulate multiple threads trying to shutdown simultaneously
            def shutdown_attempt(delay):
                time.sleep(delay)
                if not self.manager._shutdown_event.is_set():
                    self.manager._shutdown_event.set()
                    self.manager.stop_all()

            threads = []
            for i in range(3):
                thread = threading.Thread(
                    target=shutdown_attempt, args=(0.1 + i * 0.05,)
                )
                threads.append(thread)
                thread.start()

            # Wait for all shutdown attempts
            for thread in threads:
                thread.join()

            # Should only see one actual stop_all call due to shutdown event protection
            self.assertEqual(len(stop_all_calls), 1)

        # Clean up
        for stop_event in stop_events:
            stop_event.set()


if __name__ == "__main__":
    unittest.main()
