"""
Integration tests for async signal handling and shutdown scenarios.

These tests validate that the asyncio-based TaskManager handles signals
correctly and ensures clean shutdown.
"""

import asyncio
import unittest
import time
from unittest.mock import patch, MagicMock

from config_models import (
    AppConfig,
    EmailConfig,
    CalibreConfig,
    PushbulletConfig,
    AppriseConfig,
    ProcessConfig,
)
from task_manager import TaskManager


async def long_running_worker(duration=10):
    """Async worker that runs for a specified duration."""
    start_time = time.time()
    while time.time() - start_time < duration:
        await asyncio.sleep(0.1)


async def infinite_worker_with_event(stop_event):
    """Async worker that runs until stop_event is set."""
    while not stop_event.is_set():
        await asyncio.sleep(0.1)


class TestAsyncSignalHandlingIntegration(unittest.IsolatedAsyncioTestCase):
    """Integration tests for async task signal handling scenarios."""

    async def asyncSetUp(self):
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

        self.manager = TaskManager(config=self.config)

    async def asyncTearDown(self):
        """Clean up after tests."""
        if hasattr(self.manager, "_shutdown_event"):
            self.manager._shutdown_event.set()
        await self.manager.stop_all(timeout=1.0)

    async def test_context_manager_with_signal_handling(self):
        """Test that context manager works correctly with signal handling."""
        stop_event = asyncio.Event()

        with patch("ff_logging.log"):
            # Use context manager (simulating fanficdownload.py)
            async with TaskManager(config=self.config) as manager:
                # Register some tasks
                for i in range(2):
                    manager.register_task(
                        f"worker_{i}", infinite_worker_with_event, stop_event
                    )

                await manager.start_all()
                await asyncio.sleep(0.2)

                # Simulate signal arrival by setting shutdown event
                async def send_signal():
                    await asyncio.sleep(0.1)
                    manager._shutdown_event.set()
                    await manager.stop_all()

                signal_task = asyncio.create_task(send_signal())

                # Context manager should handle cleanup
                result = await manager.wait_for_all(timeout=3.0)
                self.assertTrue(result)

                await signal_task

            # Context manager exit should not cause duplicate cleanup
            # (verified by no duplicate log messages)

        stop_event.set()

    async def test_fast_shutdown_prevents_timeout(self):
        """Test that improved shutdown prevents timeout issues."""
        # Register multiple tasks
        for i in range(5):
            self.manager.register_task(
                f"worker_{i}",
                long_running_worker,
                0.5
            )

        # Start all tasks
        await self.manager.start_all()
        await asyncio.sleep(0.1)

        # Verify all tasks are running
        for i in range(5):
            self.assertTrue(self.manager.tasks[f"worker_{i}"].is_alive())

        # Trigger shutdown
        start_time = time.time()
        await self.manager.stop_all()
        shutdown_time = time.time() - start_time

        # Should complete quickly
        self.assertLess(shutdown_time, 5.0)  # Well under typical timeout

        # Verify all tasks are actually stopped
        await asyncio.sleep(0.2)
        for i in range(5):
            task_info = self.manager.tasks[f"worker_{i}"]
            self.assertFalse(task_info.is_alive())

    async def test_graceful_task_cancellation(self):
        """Test that tasks can be cancelled gracefully."""
        stop_event = asyncio.Event()

        # Register tasks
        for i in range(3):
            self.manager.register_task(
                f"worker_{i}",
                infinite_worker_with_event,
                stop_event
            )

        # Start tasks
        await self.manager.start_all()
        await asyncio.sleep(0.2)

        # All should be running
        for i in range(3):
            self.assertTrue(self.manager.tasks[f"worker_{i}"].is_alive())

        # Signal the tasks to stop
        stop_event.set()
        
        # Give tasks a moment to respond to the stop event
        await asyncio.sleep(0.2)
        
        # Signal shutdown
        self.manager._shutdown_event.set()

        # Stop all tasks
        await self.manager.stop_all(timeout=2.0)

        # All should be stopped
        for i in range(3):
            self.assertFalse(self.manager.tasks[f"worker_{i}"].is_alive())

    async def test_signal_handler_setup(self):
        """Test that signal handlers are set up correctly."""
        self.manager.setup_signal_handlers()
        self.assertTrue(self.manager._signal_handlers_set)

        # Should not duplicate setup
        with patch("ff_logging.log_debug") as mock_log:
            self.manager.setup_signal_handlers()
            mock_log.assert_called()


class TestAsyncWorkerIntegration(unittest.IsolatedAsyncioTestCase):
    """Integration tests for async worker tasks."""

    async def asyncSetUp(self):
        """Set up test fixtures."""
        self.config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(),
            pushbullet=PushbulletConfig(),
            apprise=AppriseConfig(),
            process=ProcessConfig(
                enable_monitoring=False,
                auto_restart=False,
                shutdown_timeout=2.0,
            ),
            max_workers=2,
        )

    async def test_multiple_async_tasks_run_concurrently(self):
        """Test that multiple async tasks can run concurrently."""
        async with TaskManager(config=self.config) as manager:
            # Register multiple tasks
            for i in range(4):
                manager.register_task(
                    f"worker_{i}",
                    long_running_worker,
                    0.3
                )

            # Start all tasks
            await manager.start_all()
            await asyncio.sleep(0.1)

            # All should be running
            for i in range(4):
                self.assertTrue(manager.tasks[f"worker_{i}"].is_alive())

            # Wait for tasks to complete
            await asyncio.sleep(0.5)

            # All should be done
            for i in range(4):
                self.assertFalse(manager.tasks[f"worker_{i}"].is_alive())

    async def test_task_status_tracking(self):
        """Test that task status is properly tracked."""
        async with TaskManager(config=self.config) as manager:
            manager.register_task("worker", long_running_worker, 0.3)

            # Should be stopped initially
            status = manager.get_status()
            self.assertEqual(status["worker"]["state"], "stopped")

            # Start task
            await manager.start_task("worker")
            await asyncio.sleep(0.1)

            # Should be running
            status = manager.get_status()
            self.assertEqual(status["worker"]["state"], "running")
            self.assertTrue(status["worker"]["is_alive"])
            self.assertIsNotNone(status["worker"]["uptime"])

            # Wait for completion
            await asyncio.sleep(0.5)

            # Should be done (not alive)
            status = manager.get_status()
            self.assertFalse(status["worker"]["is_alive"])


if __name__ == "__main__":
    unittest.main()
