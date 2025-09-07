"""
Tests for ProcessManager functionality.

Comprehensive test suite covering process lifecycle, health monitoring,
graceful shutdown, and error handling scenarios.
"""

import multiprocessing as mp
import os
import signal
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, Mock, patch
from parameterized import parameterized

# Add the app directory to the path so we can import our modules
from config_models import (
    AppConfig,
    ProcessConfig,
    EmailConfig,
    CalibreConfig,
    ConfigManager,
)
from process_manager import ProcessManager, ProcessState, ProcessInfo


def dummy_worker_function(duration=1):
    """Simple worker function for testing."""
    time.sleep(duration)


def failing_worker_function():
    """Worker function that fails immediately."""
    raise RuntimeError("Test failure")


def infinite_worker_function(stop_event=None):
    """Worker function that runs until stopped."""
    while stop_event is None or not stop_event.is_set():
        time.sleep(0.1)


class TestProcessInfo(unittest.TestCase):
    """Test ProcessInfo dataclass functionality."""

    def test_process_info_initialization(self):
        """Test ProcessInfo initialization with default values."""
        info = ProcessInfo(name="test_process")

        self.assertEqual(info.name, "test_process")
        self.assertIsNone(info.process)
        self.assertIsNone(info.target)
        self.assertEqual(info.args, ())
        self.assertEqual(info.kwargs, {})
        self.assertEqual(info.state, ProcessState.STOPPED)
        self.assertIsNone(info.start_time)
        self.assertIsNone(info.last_health_check)
        self.assertEqual(info.restart_count, 0)
        self.assertIsNone(info.pid)

    def test_process_info_is_alive_no_process(self):
        """Test is_alive returns False when no process is set."""
        info = ProcessInfo(name="test")
        self.assertFalse(info.is_alive())

    def test_process_info_get_uptime_no_start_time(self):
        """Test get_uptime returns None when start_time is not set."""
        info = ProcessInfo(name="test")
        self.assertIsNone(info.get_uptime())

    def test_process_info_get_uptime_with_start_time(self):
        """Test get_uptime calculation."""
        info = ProcessInfo(name="test")
        info.start_time = time.time() - 5.0  # 5 seconds ago

        uptime = info.get_uptime()
        self.assertIsNotNone(uptime)
        if uptime is not None:
            self.assertGreaterEqual(uptime, 4.9)  # Allow for small timing variations
            self.assertLessEqual(uptime, 5.1)


class TestProcessManager(unittest.TestCase):
    """Test ProcessManager functionality."""

    def setUp(self):
        """Set up test configuration and ProcessManager."""
        # Create test configuration
        self.config = AppConfig(
            email=EmailConfig(
                email="testuser",
                password="test_password",
                server="test.server.com",
            ),
            calibre=CalibreConfig(path="/test/path"),
            process=ProcessConfig(
                shutdown_timeout=2.0,
                health_check_interval=1.0,
                auto_restart=True,
                max_restart_attempts=2,
                restart_delay=0.1,
                enable_monitoring=True,
            ),
            max_workers=2,
        )

        # Mock ConfigManager and get_config to return the test config
        with patch.object(ConfigManager, "load_config", return_value=self.config):
            with patch("process_manager.get_config", return_value=self.config):
                # Provide the config directly to the ProcessManager
                self.manager = ProcessManager(config=self.config)
                self.manager.config = self.config  # Ensure config is set
                self.manager.process_config = self.config.process

    def tearDown(self):
        """Clean up after tests."""
        if hasattr(self, "manager"):
            self.manager.stop_all(timeout=1.0)

    def test_process_manager_initialization(self):
        """Test ProcessManager initialization."""
        self.assertIsNotNone(self.manager.config)
        self.assertIsInstance(self.manager.process_config, ProcessConfig)
        self.assertEqual(len(self.manager.processes), 0)
        self.assertIsNone(self.manager.pool)
        self.assertFalse(self.manager._shutdown_event.is_set())
        self.assertIsNone(self.manager._monitor_thread)
        self.assertFalse(self.manager._signal_handlers_set)

    @parameterized.expand(
        [
            ("simple_process", dummy_worker_function, (), {}),
            ("process_with_args", dummy_worker_function, (0.5,), {}),
            ("process_with_kwargs", dummy_worker_function, (), {"duration": 0.5}),
        ]
    )
    def test_register_process(self, name, target, args, kwargs):
        """Test process registration with various configurations."""
        self.manager.register_process(name, target, args, kwargs)

        self.assertIn(name, self.manager.processes)
        process_info = self.manager.processes[name]
        self.assertEqual(process_info.name, name)
        self.assertEqual(process_info.target, target)
        self.assertEqual(process_info.args, args)
        self.assertEqual(process_info.kwargs, kwargs)
        self.assertEqual(process_info.state, ProcessState.STOPPED)

    def test_register_duplicate_process(self):
        """Test registering a process with duplicate name."""
        self.manager.register_process("test", dummy_worker_function)

        # Attempt to register again - should fail
        with patch("ff_logging.log_failure") as mock_log:
            self.manager.register_process("test", dummy_worker_function)
            mock_log.assert_called_once()

    def test_start_process_success(self):
        """Test successful process start."""
        self.manager.register_process("test", dummy_worker_function, (0.5,))

        result = self.manager.start_process("test")
        self.assertTrue(result)

        process_info = self.manager.processes["test"]
        self.assertEqual(process_info.state, ProcessState.RUNNING)
        self.assertIsNotNone(process_info.process)
        self.assertIsNotNone(process_info.pid)
        self.assertIsNotNone(process_info.start_time)
        self.assertTrue(process_info.is_alive())

        # Clean up
        self.manager.stop_process("test")

    def test_start_nonexistent_process(self):
        """Test starting a process that wasn't registered."""
        result = self.manager.start_process("nonexistent")
        self.assertFalse(result)

    def test_start_already_running_process(self):
        """Test starting a process that's already running."""
        self.manager.register_process("test", infinite_worker_function)
        self.manager.start_process("test")

        # Try to start again
        with patch("ff_logging.log_failure") as mock_log:
            result = self.manager.start_process("test")
            self.assertFalse(result)
            mock_log.assert_called_once()

        # Clean up
        self.manager.stop_process("test")

    def test_stop_process_success(self):
        """Test successful process stop."""
        self.manager.register_process("test", dummy_worker_function, (1.0,))
        self.manager.start_process("test")

        result = self.manager.stop_process("test")
        self.assertTrue(result)

        process_info = self.manager.processes["test"]
        self.assertEqual(process_info.state, ProcessState.STOPPED)
        self.assertIsNone(process_info.process)
        self.assertIsNone(process_info.pid)
        self.assertFalse(process_info.is_alive())

    def test_stop_nonexistent_process(self):
        """Test stopping a process that wasn't registered."""
        result = self.manager.stop_process("nonexistent")
        self.assertFalse(result)

    def test_stop_not_running_process(self):
        """Test stopping a process that's not running."""
        self.manager.register_process("test", dummy_worker_function)

        result = self.manager.stop_process("test")
        self.assertTrue(result)  # Should succeed (already stopped)

    @parameterized.expand(
        [
            ("force_kill_timeout", 0.1),  # Very short timeout to force kill
            ("graceful_timeout", 2.0),  # Normal timeout for graceful shutdown
        ]
    )
    def test_stop_process_timeouts(self, name, timeout):
        """Test process stop with different timeout scenarios."""
        # Use a process that will run longer than the timeout
        self.manager.register_process("test", dummy_worker_function, (5.0,))
        self.manager.start_process("test")

        result = self.manager.stop_process("test", timeout=timeout)
        self.assertTrue(result)

        process_info = self.manager.processes["test"]
        self.assertEqual(process_info.state, ProcessState.STOPPED)
        self.assertFalse(process_info.is_alive())

    def test_restart_process_success(self):
        """Test successful process restart."""
        self.manager.register_process("test", dummy_worker_function, (0.5,))
        self.manager.start_process("test")

        # Wait for process to finish naturally
        time.sleep(0.7)

        result = self.manager.restart_process("test")
        self.assertTrue(result)

        process_info = self.manager.processes["test"]
        self.assertEqual(process_info.restart_count, 1)
        self.assertEqual(process_info.state, ProcessState.RUNNING)

    def test_restart_process_max_attempts(self):
        """Test restart process with maximum attempts exceeded."""
        self.manager.register_process("test", failing_worker_function)
        process_info = self.manager.processes["test"]

        # Set restart count to maximum
        process_info.restart_count = self.manager.process_config.max_restart_attempts

        result = self.manager.restart_process("test")
        self.assertFalse(result)
        self.assertEqual(process_info.state, ProcessState.FAILED)

    def test_start_all_processes(self):
        """Test starting all registered processes."""
        self.manager.register_process("test1", dummy_worker_function, (0.5,))
        self.manager.register_process("test2", dummy_worker_function, (0.5,))

        result = self.manager.start_all()
        self.assertTrue(result)

        for name in ["test1", "test2"]:
            process_info = self.manager.processes[name]
            self.assertEqual(process_info.state, ProcessState.RUNNING)
            self.assertTrue(process_info.is_alive())

        # Clean up
        self.manager.stop_all()

    def test_stop_all_processes(self):
        """Test stopping all processes."""
        self.manager.register_process("test1", dummy_worker_function, (1.0,))
        self.manager.register_process("test2", dummy_worker_function, (1.0,))
        self.manager.start_all()

        result = self.manager.stop_all()
        self.assertTrue(result)

        for name in ["test1", "test2"]:
            process_info = self.manager.processes[name]
            self.assertEqual(process_info.state, ProcessState.STOPPED)
            self.assertFalse(process_info.is_alive())

    def test_get_status(self):
        """Test getting process status information."""
        self.manager.register_process("test", dummy_worker_function, (0.5,))
        self.manager.start_process("test")

        status = self.manager.get_status()

        self.assertIn("test", status)
        test_status = status["test"]

        self.assertEqual(test_status["state"], ProcessState.RUNNING.value)
        self.assertTrue(test_status["alive"])
        self.assertIsNotNone(test_status["pid"])
        self.assertIsNotNone(test_status["uptime"])
        self.assertEqual(test_status["restart_count"], 0)

        # Clean up
        self.manager.stop_process("test")

    def test_create_worker_pool(self):
        """Test creating worker pool."""
        pool = self.manager.create_worker_pool(worker_count=2)

        self.assertIsNotNone(pool)
        self.assertEqual(self.manager.pool, pool)

        # Test that creating again returns the same pool
        pool2 = self.manager.create_worker_pool()
        self.assertEqual(pool, pool2)

        # Clean up
        if pool:
            pool.terminate()
            pool.join()

    def test_setup_signal_handlers(self):
        """Test signal handler setup."""
        # Mock signal.signal to avoid actually setting signal handlers
        with patch("signal.signal") as mock_signal:
            self.manager.setup_signal_handlers()

            # Should set handlers for SIGTERM and SIGINT
            self.assertEqual(mock_signal.call_count, 2)
            self.assertTrue(self.manager._signal_handlers_set)

            # Calling again should not set handlers again
            mock_signal.reset_mock()
            self.manager.setup_signal_handlers()
            mock_signal.assert_not_called()

    def test_signal_handler_calls_stop_all(self):
        """Test that the signal handler function calls stop_all when invoked."""
        with patch.object(self.manager, "stop_all") as mock_stop_all:
            # Set up the signal handlers
            self.manager.setup_signal_handlers()

            # Manually call the signal handler that was created
            # We'll access the handler by calling it with the expected signature
            with patch("signal.signal") as mock_signal:
                # Reset and setup again to capture the handler
                self.manager._signal_handlers_set = False
                self.manager.setup_signal_handlers()

                # Get the handler function from the signal.signal calls
                sigint_handler = None
                for call_args in mock_signal.call_args_list:
                    signal_num, handler_func = call_args[0]
                    if signal_num == signal.SIGINT:
                        sigint_handler = handler_func
                        break

                # Test the handler directly
                if sigint_handler and callable(sigint_handler):
                    # Call the handler with mock parameters
                    sigint_handler(signal.SIGINT, None)

                    # Verify stop_all was called
                    mock_stop_all.assert_called_once()
                else:
                    self.fail("SIGINT handler not found or not callable")

    def test_context_manager(self):
        """Test ProcessManager as context manager."""
        with patch.object(self.manager, "setup_signal_handlers") as mock_setup:
            with patch.object(self.manager, "stop_all") as mock_stop:
                with self.manager:
                    pass

                mock_setup.assert_called_once()
                mock_stop.assert_called_once()

    def test_wait_for_all_no_processes(self):
        """Test wait_for_all when no processes are registered."""
        result = self.manager.wait_for_all(timeout=1.0)
        self.assertTrue(result)

    def test_wait_for_all_processes_completed(self):
        """Test wait_for_all when all processes have completed."""
        # Register a mock process that is not alive
        mock_process_info = MagicMock()
        mock_process_info.is_alive.return_value = False
        self.manager.processes["test"] = mock_process_info

        result = self.manager.wait_for_all(timeout=1.0)
        self.assertTrue(result)

    def test_wait_for_all_timeout(self):
        """Test wait_for_all with timeout when processes are still running."""
        # Register a mock process that appears to be running
        mock_process_info = MagicMock()
        mock_process_info.is_alive.return_value = True
        self.manager.processes["test_running"] = mock_process_info

        # Should timeout quickly
        result = self.manager.wait_for_all(timeout=0.1)
        self.assertFalse(result)


class TestProcessManagerMonitoring(unittest.TestCase):
    """Test ProcessManager monitoring functionality."""

    def setUp(self):
        """Set up test configuration with monitoring enabled."""
        self.config = AppConfig(
            email=EmailConfig(
                email="testuser",
                password="test_password",
                server="test.server.com",
            ),
            calibre=CalibreConfig(path="/test/path"),
            process=ProcessConfig(
                health_check_interval=0.1,  # Very fast for testing
                auto_restart=True,
                max_restart_attempts=1,
                restart_delay=0.05,
                enable_monitoring=True,
            ),
        )

        with patch.object(ConfigManager, "load_config", return_value=self.config):
            with patch("process_manager.get_config", return_value=self.config):
                self.manager = ProcessManager(config=self.config)

    def tearDown(self):
        """Clean up after tests."""
        if hasattr(self, "manager"):
            self.manager.stop_all(timeout=1.0)

    def test_monitoring_thread_start(self):
        """Test that monitoring thread starts when processes are started."""
        self.manager.register_process("test", dummy_worker_function, (0.5,))

        self.manager.start_all()

        # Check that monitoring thread was started
        self.assertIsNotNone(self.manager._monitor_thread)
        if self.manager._monitor_thread:
            self.assertTrue(self.manager._monitor_thread.is_alive())

        # Clean up
        self.manager.stop_all()

    def test_monitoring_disabled(self):
        """Test behavior when monitoring is disabled."""
        self.manager.process_config.enable_monitoring = False
        self.manager.register_process("test", dummy_worker_function, (0.5,))

        self.manager.start_all()

        # Monitoring thread should not be started
        self.assertIsNone(self.manager._monitor_thread)

        # Clean up
        self.manager.stop_all()


class TestProcessManagerErrorHandling(unittest.TestCase):
    """Test ProcessManager error handling scenarios."""

    def setUp(self):
        """Set up test configuration."""
        self.config = AppConfig(
            email=EmailConfig(
                email="testuser",
                password="test_password",
                server="test.server.com",
            ),
            calibre=CalibreConfig(path="/test/path"),
            process=ProcessConfig(),
        )

        with patch.object(ConfigManager, "load_config", return_value=self.config):
            with patch("process_manager.get_config", return_value=self.config):
                self.manager = ProcessManager(config=self.config)

    def tearDown(self):
        """Clean up after tests."""
        if hasattr(self, "manager"):
            self.manager.stop_all(timeout=1.0)

    def test_process_manager_no_config(self):
        """Test ProcessManager initialization without configuration."""
        with patch("process_manager.get_config", return_value=None):
            with self.assertRaises(ValueError):
                ProcessManager()

    def test_start_process_exception(self):
        """Test handling of exception during process start."""
        # Register a process that will fail to start
        with patch("multiprocessing.Process") as mock_process_class:
            mock_process = Mock()
            mock_process.start.side_effect = RuntimeError("Start failed")
            mock_process_class.return_value = mock_process

            self.manager.register_process("test", dummy_worker_function)
            result = self.manager.start_process("test")

            self.assertFalse(result)
            process_info = self.manager.processes["test"]
            self.assertEqual(process_info.state, ProcessState.FAILED)

    def test_stop_process_exception(self):
        """Test handling of exception during process stop."""
        self.manager.register_process("test", dummy_worker_function, (1.0,))
        self.manager.start_process("test")

        # Mock the process to raise an exception during termination
        process_info = self.manager.processes["test"]
        original_process = process_info.process
        process_info.process = Mock()
        process_info.process.is_alive.return_value = True
        process_info.process.terminate.side_effect = RuntimeError("Terminate failed")

        result = self.manager.stop_process("test")
        self.assertFalse(result)
        self.assertEqual(process_info.state, ProcessState.FAILED)

        # Clean up the real process
        if original_process and original_process.is_alive():
            original_process.terminate()
            original_process.join(1.0)

    def test_signal_handler_deduplication(self):
        """Test that signal handler prevents repeated signal handling."""
        with patch.object(self.manager, "stop_all") as mock_stop_all:
            # Set up the signal handlers
            self.manager.setup_signal_handlers()

            # Capture the handler function
            with patch("signal.signal") as mock_signal:
                self.manager._signal_handlers_set = False
                self.manager.setup_signal_handlers()

                # Get the handler function
                sigterm_handler = None
                for call_args in mock_signal.call_args_list:
                    signal_num, handler_func = call_args[0]
                    if signal_num == signal.SIGTERM:
                        sigterm_handler = handler_func
                        break

                if sigterm_handler and callable(sigterm_handler):
                    # First call should work
                    sigterm_handler(signal.SIGTERM, None)
                    self.assertEqual(mock_stop_all.call_count, 1)
                    self.assertTrue(self.manager._shutdown_event.is_set())

                    # Second call should be ignored due to shutdown event
                    sigterm_handler(signal.SIGTERM, None)
                    # stop_all should not be called again
                    self.assertEqual(mock_stop_all.call_count, 1)
                else:
                    self.fail("SIGTERM handler not found or not callable")

    def test_wait_for_all_respects_shutdown_event(self):
        """Test that wait_for_all exits when shutdown event is set."""
        # Register a long-running process
        self.manager.register_process(
            "long_running",
            infinite_worker_function,
            args=()
        )
        
        # Start the process
        self.assertTrue(self.manager.start_process("long_running"))
        
        # Set shutdown event in a separate thread after a short delay
        def set_shutdown_after_delay():
            time.sleep(0.5)
            self.manager._shutdown_event.set()
        
        shutdown_thread = threading.Thread(target=set_shutdown_after_delay)
        shutdown_thread.start()
        
        # wait_for_all should exit quickly due to shutdown event
        start_time = time.time()
        result = self.manager.wait_for_all(timeout=10)  # Long timeout, but should exit early
        elapsed = time.time() - start_time
        
        # Should exit in less than 2 seconds due to shutdown event
        self.assertTrue(result)
        self.assertLess(elapsed, 2.0)
        
        # Clean up
        shutdown_thread.join()
        self.manager.stop_all()

    def test_context_manager_avoids_duplicate_cleanup(self):
        """Test that context manager exit doesn't duplicate cleanup if already shutting down."""
        with patch.object(self.manager, "stop_all") as mock_stop_all:
            # Simulate shutdown already in progress
            self.manager._shutdown_event.set()
            
            # Context manager exit should not call stop_all again
            self.manager.__exit__(None, None, None)
            
            mock_stop_all.assert_not_called()

    def test_wait_for_all_exits_on_shutdown_event_quickly(self):
        """Test that wait_for_all exits immediately when shutdown event is set."""
        # Start a long-running process
        self.manager.register_process(
            "long_runner", 
            infinite_worker_function
        )
        self.manager.start_process("long_runner")
        
        # Set shutdown event in a separate thread after a delay
        def set_shutdown():
            time.sleep(0.2)
            self.manager._shutdown_event.set()
        
        shutdown_thread = threading.Thread(target=set_shutdown)
        shutdown_thread.start()
        
        # wait_for_all should exit quickly due to shutdown event
        start_time = time.time()
        result = self.manager.wait_for_all(timeout=5.0)
        elapsed = time.time() - start_time
        
        # Should exit in less than 1 second due to shutdown event
        self.assertLess(elapsed, 1.0)
        self.assertTrue(result)
        
        # Clean up
        shutdown_thread.join()
        self.manager.stop_all()

    @patch('ff_logging.log')
    @patch('ff_logging.log_debug')
    def test_signal_handler_logging_messages(self, mock_log_debug, mock_log):
        """Test that signal handler logs appropriate messages."""
        self.manager.setup_signal_handlers()
        
        with patch.object(self.manager, "stop_all"):
            # Use the handler function directly to test logging
            with patch("signal.signal") as mock_signal:
                self.manager._signal_handlers_set = False
                self.manager.setup_signal_handlers()

                # Get the handler function
                sigterm_handler = None
                for call_args in mock_signal.call_args_list:
                    signal_num, handler_func = call_args[0]
                    if signal_num == signal.SIGTERM:
                        sigterm_handler = handler_func
                        break

                if sigterm_handler and callable(sigterm_handler):
                    # First signal should log shutdown message
                    sigterm_handler(signal.SIGTERM, None)
                    mock_log.assert_called_with(
                        "Received signal SIGTERM, initiating graceful shutdown...",
                        "WARNING"
                    )
                    
                    # Second signal should log ignore message
                    sigterm_handler(signal.SIGTERM, None)
                    mock_log_debug.assert_called_with("Signal already being handled, ignoring")

    def test_signal_integration_with_real_child_processes(self):
        """Integration test: signal handling with actual child processes."""
        stop_event = mp.Event()
        
        # Register processes that will run until stopped
        for i in range(3):
            self.manager.register_process(
                f"worker_{i}",
                infinite_worker_function,
                args=(stop_event,)
            )
        
        # Start all processes
        self.assertTrue(self.manager.start_all())
        
        # Verify all processes are running
        time.sleep(0.2)
        for i in range(3):
            self.assertTrue(self.manager.processes[f"worker_{i}"].is_alive())
        
        # Setup signal handlers and simulate signal handling
        self.manager.setup_signal_handlers()
        
        # Use threading to simulate signal arrival
        def send_signal():
            time.sleep(0.1)
            self.manager._shutdown_event.set()
            self.manager.stop_all()
        
        signal_thread = threading.Thread(target=send_signal)
        signal_thread.start()
        
        # wait_for_all should exit quickly
        start_time = time.time()
        result = self.manager.wait_for_all(timeout=10.0)
        elapsed = time.time() - start_time
        
        # Should complete shutdown in reasonable time
        self.assertLess(elapsed, 3.0)
        self.assertTrue(result)
        
        # Verify all processes are stopped
        time.sleep(0.5)
        for i in range(3):
            self.assertFalse(self.manager.processes[f"worker_{i}"].is_alive())
        
        signal_thread.join()
        stop_event.set()


if __name__ == "__main__":
    unittest.main()
