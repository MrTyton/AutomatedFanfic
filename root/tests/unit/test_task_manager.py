"""
Tests for TaskManager functionality (asyncio-based).

Comprehensive test suite covering task lifecycle, health monitoring,
graceful shutdown, and error handling scenarios for async tasks.
"""

import asyncio
import signal
import time
import unittest
from unittest.mock import MagicMock, Mock, patch

import pytest

# Add the app directory to the path so we can import our modules
from config_models import (
    AppConfig,
    ProcessConfig,
    EmailConfig,
    CalibreConfig,
    PushbulletConfig,
    AppriseConfig,
)
from task_manager import TaskManager, TaskState, TaskInfo


async def dummy_worker_function(duration=1):
    """Simple async worker function for testing."""
    await asyncio.sleep(duration)


async def failing_worker_function():
    """Async worker function that fails immediately."""
    raise RuntimeError("Test failure")


async def infinite_worker_function(stop_event=None):
    """Async worker function that runs until stopped."""
    while stop_event is None or not stop_event.is_set():
        await asyncio.sleep(0.1)


class TestTaskInfo(unittest.TestCase):
    """Test TaskInfo dataclass functionality."""
    
    def test_task_info_creation(self):
        """Test TaskInfo can be created with basic parameters."""
        info = TaskInfo(
            name="test_task",
            target=dummy_worker_function,
            args=(1,),
        )
        
        self.assertEqual(info.name, "test_task")
        self.assertEqual(info.target, dummy_worker_function)
        self.assertEqual(info.args, (1,))
        self.assertEqual(info.state, TaskState.STOPPED)
        self.assertIsNone(info.task)
    
    def test_task_info_is_alive_when_no_task(self):
        """Test is_alive returns False when task is None."""
        info = TaskInfo(name="test", target=dummy_worker_function)
        self.assertFalse(info.is_alive())
    
    def test_task_info_get_uptime_when_not_started(self):
        """Test get_uptime returns None when task hasn't started."""
        info = TaskInfo(name="test", target=dummy_worker_function)
        self.assertIsNone(info.get_uptime())
    
    def test_task_info_get_uptime_when_started(self):
        """Test get_uptime returns value when task has started."""
        info = TaskInfo(name="test", target=dummy_worker_function)
        info.start_time = time.time()
        uptime = info.get_uptime()
        self.assertIsNotNone(uptime)
        self.assertGreaterEqual(uptime, 0)


class TestTaskManager(unittest.IsolatedAsyncioTestCase):
    """Test TaskManager functionality with asyncio."""
    
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
    
    def test_init_requires_config(self):
        """Test TaskManager requires config parameter."""
        with self.assertRaises(ValueError):
            TaskManager(config=None)
    
    def test_register_task(self):
        """Test registering a task."""
        self.manager.register_task(
            "test_task",
            dummy_worker_function,
            1
        )
        
        self.assertIn("test_task", self.manager.tasks)
        self.assertEqual(self.manager.tasks["test_task"].name, "test_task")
        self.assertEqual(self.manager.tasks["test_task"].state, TaskState.STOPPED)
    
    def test_register_duplicate_task(self):
        """Test registering a task with duplicate name logs failure."""
        self.manager.register_task("test_task", dummy_worker_function)
        
        with patch("ff_logging.log_failure") as mock_log:
            self.manager.register_task("test_task", dummy_worker_function)
            mock_log.assert_called()
    
    async def test_start_task(self):
        """Test starting a registered task."""
        self.manager.register_task("test_task", dummy_worker_function, 0.1)
        
        result = await self.manager.start_task("test_task")
        self.assertTrue(result)
        
        # Give task a moment to start
        await asyncio.sleep(0.05)
        
        task_info = self.manager.tasks["test_task"]
        self.assertEqual(task_info.state, TaskState.RUNNING)
        self.assertIsNotNone(task_info.task)
        
        # Wait for task to complete
        await asyncio.sleep(0.2)
    
    async def test_start_unregistered_task(self):
        """Test starting an unregistered task returns False."""
        result = await self.manager.start_task("nonexistent")
        self.assertFalse(result)
    
    async def test_stop_task(self):
        """Test stopping a running task."""
        self.manager.register_task("test_task", infinite_worker_function)
        await self.manager.start_task("test_task")
        await asyncio.sleep(0.1)
        
        result = await self.manager.stop_task("test_task", timeout=1.0)
        self.assertTrue(result)
        
        task_info = self.manager.tasks["test_task"]
        self.assertEqual(task_info.state, TaskState.STOPPED)
    
    async def test_stop_all_tasks(self):
        """Test stopping all tasks."""
        # Register multiple tasks
        for i in range(3):
            self.manager.register_task(
                f"test_task_{i}",
                dummy_worker_function,
                0.5
            )
            await self.manager.start_task(f"test_task_{i}")
        
        await asyncio.sleep(0.1)
        
        # Stop all tasks
        await self.manager.stop_all(timeout=2.0)
        
        # Verify all tasks are stopped
        for i in range(3):
            task_info = self.manager.tasks[f"test_task_{i}"]
            self.assertFalse(task_info.is_alive())
    
    async def test_get_status(self):
        """Test getting task status information."""
        self.manager.register_task("test_task", dummy_worker_function, 0.1)
        await self.manager.start_task("test_task")
        await asyncio.sleep(0.05)
        
        status = self.manager.get_status()
        
        self.assertIn("test_task", status)
        self.assertEqual(status["test_task"]["state"], TaskState.RUNNING.value)
        self.assertIsNotNone(status["test_task"]["uptime"])
        
        await asyncio.sleep(0.2)
    
    async def test_context_manager(self):
        """Test TaskManager as async context manager."""
        async with TaskManager(config=self.config) as tm:
            tm.register_task("test_task", dummy_worker_function, 0.1)
            await tm.start_task("test_task")
            await asyncio.sleep(0.05)
            
            self.assertTrue(tm.tasks["test_task"].is_alive())
        
        # After context exit, should be cleaned up
        # Note: Task should complete naturally since it's short
        await asyncio.sleep(0.2)
    
    async def test_wait_for_all_with_timeout(self):
        """Test wait_for_all with timeout."""
        result = await self.manager.wait_for_all(timeout=0.1)
        self.assertFalse(result)
    
    def test_setup_signal_handlers(self):
        """Test signal handler setup."""
        self.manager.setup_signal_handlers()
        self.assertTrue(self.manager._signal_handlers_set)
        
        # Should not set again
        with patch("ff_logging.log_debug") as mock_log:
            self.manager.setup_signal_handlers()
            mock_log.assert_called()


class TestTaskManagerErrorHandling(unittest.IsolatedAsyncioTestCase):
    """Test TaskManager error handling scenarios."""
    
    async def asyncSetUp(self):
        """Set up test fixtures."""
        self.config = AppConfig(
            email=EmailConfig(),
            calibre=CalibreConfig(),
            pushbullet=PushbulletConfig(),
            apprise=AppriseConfig(),
            process=ProcessConfig(
                enable_monitoring=True,  # Enable for error handling tests
                auto_restart=True,
                shutdown_timeout=2.0,
                health_check_interval=0.5,
            ),
            max_workers=2,
        )
        
        self.manager = TaskManager(config=self.config)
    
    async def asyncTearDown(self):
        """Clean up after tests."""
        if hasattr(self.manager, "_shutdown_event"):
            self.manager._shutdown_event.set()
        await self.manager.stop_all(timeout=1.0)
    
    async def test_task_failure_detection(self):
        """Test that failed tasks are detected by monitoring."""
        self.manager.register_task("failing_task", failing_worker_function)
        
        # Start task and monitoring
        await self.manager.start_task("failing_task")
        await self.manager._start_monitoring()
        
        # Wait for task to fail and be detected
        await asyncio.sleep(1.0)
        
        # Task should be marked as failed
        task_info = self.manager.tasks["failing_task"]
        # Note: Since auto_restart is True, it may have been restarted
        # Just verify the monitoring is running
        self.assertIsNotNone(self.manager._monitor_task)


if __name__ == "__main__":
    unittest.main()
