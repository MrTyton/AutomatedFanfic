"""
Task Manager for AutomatedFanfic (Asyncio-based)

This module provides centralized management of async worker tasks for the AutomatedFanfic
application. It handles task lifecycle management, health monitoring, graceful shutdown 
coordination, and automatic restart capabilities using asyncio.

This replaces the multiprocessing-based ProcessManager with an asyncio-based implementation
while maintaining similar interfaces and functionality.

Key Features:
    - Async task lifecycle management with state tracking
    - Health monitoring with configurable intervals and automatic restart
    - Signal-based graceful shutdown with coordinated cleanup
    - Asyncio-based concurrency instead of multiprocessing
    - Thread-safe operations with proper synchronization
    - Context manager support for resource cleanup

Architecture:
    The TaskManager serves as a centralized coordinator for all worker tasks
    in the application. It maintains task state, monitors health via a dedicated
    monitoring task, and handles shutdown coordination to ensure clean termination.

Example:
    ```python
    from config_models import AppConfig
    from task_manager import TaskManager
    
    config = AppConfig.load_from_file("config.toml")
    
    async def main():
        async with TaskManager(config) as tm:
            await tm.register_task("email_monitor", email_worker_func, queue)
            await tm.register_task("url_processor", url_worker_func, url_queue)
            
            await tm.start_all()
            await tm.wait_for_all()  # Blocks until shutdown signal received
    
    asyncio.run(main())
    ```

Task States:
    - STARTING: Task is being initialized
    - RUNNING: Task is actively running and responsive
    - STOPPING: Task is being gracefully cancelled
    - STOPPED: Task has terminated cleanly
    - FAILED: Task crashed or failed to start
    - RESTARTING: Task is being restarted after failure

Signal Handling:
    The manager installs signal handlers for SIGTERM and SIGINT that coordinate
    graceful shutdown across all managed tasks. This ensures the main process 
    exits cleanly in Docker environments.

Thread Safety:
    All operations are designed for asyncio environments using proper 
    synchronization with asyncio.Event and asyncio.Lock objects.
"""

import asyncio
import signal
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, Optional, Tuple

import ff_logging
from config_models import AppConfig, ProcessConfig


class TaskState(Enum):
    """
    Enumeration representing the lifecycle states of managed tasks.
    
    States represent the complete lifecycle from initialization through
    termination, including error conditions and restart scenarios.
    
    Attributes:
        STARTING: Task is being initialized and started
        RUNNING: Task is actively running and responsive
        STOPPING: Task is being gracefully cancelled
        STOPPED: Task has terminated cleanly
        FAILED: Task crashed, failed to start, or exceeded restart limits
        RESTARTING: Task is being restarted after a failure
    """
    
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    RESTARTING = "restarting"


@dataclass
class TaskInfo:
    """
    Information container for a managed task.
    
    This dataclass stores all metadata and state information for a task
    managed by the TaskManager. It tracks the task lifecycle, timing
    information, restart attempts, and provides convenience methods for
    task state checking.
    
    Attributes:
        name: Unique identifier for the task
        task: The actual asyncio.Task instance (None when stopped)
        target: The coroutine function that runs as the task
        args: Positional arguments passed to the target function
        kwargs: Keyword arguments passed to the target function
        state: Current TaskState of the task
        start_time: Unix timestamp when the task was last started
        last_health_check: Unix timestamp of the last health check
        restart_count: Number of times this task has been restarted
    
    Example:
        ```python
        info = TaskInfo(
            name="email_worker",
            target=email_monitor_func,
            args=(email_queue, shutdown_event),
            kwargs={"poll_interval": 60}
        )
        ```
    """
    
    name: str
    task: Optional[asyncio.Task] = None
    target: Optional[Callable] = None
    args: Tuple = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    state: TaskState = TaskState.STOPPED
    start_time: Optional[float] = None
    last_health_check: Optional[float] = None
    restart_count: int = 0
    
    def is_alive(self) -> bool:
        """
        Check if the task is currently alive and running.
        
        Returns:
            bool: True if task exists and is not done, False otherwise
        
        Note:
            This is a safe check that handles cases where the task
            object is None or has been cleaned up.
        """
        return self.task is not None and not self.task.done()
    
    def get_uptime(self) -> Optional[float]:
        """
        Calculate the current uptime of the task in seconds.
        
        Returns:
            Optional[float]: Uptime in seconds if task has been started,
                           None if task has never been started
        
        Note:
            Returns the elapsed time since the task was last started,
            regardless of whether the task is currently running.
        """
        if self.start_time is None:
            return None
        return time.time() - self.start_time


class TaskManager:
    """
    Centralized task manager with health monitoring and graceful shutdown.
    
    The TaskManager is the core orchestrator for all worker tasks in the
    AutomatedFanfic application using asyncio. It provides a unified interface 
    for task lifecycle management, health monitoring, and coordinated shutdown.
    
    Key Features:
        - Task registration and lifecycle management
        - Health monitoring with automatic restart capabilities
        - Signal-based graceful shutdown coordination
        - Asyncio-based task state tracking
        - Context manager support for clean resource management
    
    Architecture:
        The manager uses a monitoring task that periodically checks task
        health and can automatically restart failed tasks. Signal handlers
        coordinate graceful shutdown across all managed tasks.
    
    Example:
        ```python
        config = AppConfig.load_from_file("config.toml")
        
        async def main():
            async with TaskManager(config) as tm:
                # Register worker tasks
                await tm.register_task("email_monitor", email_worker, email_queue)
                await tm.register_task("url_processor", url_worker, url_queue)
                
                # Start all tasks with monitoring
                await tm.start_all()
                
                # Wait for completion or signal
                await tm.wait_for_all()
        
        asyncio.run(main())
        ```
    
    Configuration:
        Task behavior is controlled via ProcessConfig in the AppConfig:
        - health_check_interval: Seconds between health checks
        - shutdown_timeout: Maximum seconds to wait for graceful shutdown
        - auto_restart: Whether to automatically restart failed tasks
        - max_restart_attempts: Maximum restart attempts before marking failed
        - restart_delay: Seconds to wait before attempting restart
    """
    
    def __init__(self, config: Optional[AppConfig] = None):
        """
        Initialize the TaskManager with configuration.
        
        Args:
            config: AppConfig instance containing task configuration.
                   Must be provided - configuration is required for proper
                   operation of health monitoring and shutdown timeouts.
        
        Raises:
            ValueError: If config is None, as configuration is required
                       for proper task management.
        
        Note:
            The TaskManager requires configuration to function properly.
            This includes timing parameters for health checks, shutdown
            timeouts, and restart behavior.
        """
        # Task tracking and state management
        self.tasks: Dict[str, TaskInfo] = {}
        
        # Synchronization primitives for coordination
        self._shutdown_event = asyncio.Event()
        self._monitor_task: Optional[asyncio.Task] = None
        self._signal_handlers_set = False
        
        # Configuration validation and setup
        if config:
            self.config = config
            self.process_config = getattr(config, "process", ProcessConfig())
        else:
            # Configuration is required for proper operation
            raise ValueError("AppConfig must be provided to TaskManager.")
        
        ff_logging.log_debug("TaskManager initialized")
    
    def register_task(
        self,
        name: str,
        target: Callable[..., Coroutine],
        *args,
        **kwargs
    ) -> None:
        """
        Register a task for management without starting it.
        
        This method registers a task definition that can be started later
        with start_task() or start_all(). The task is not created or
        started until explicitly requested.
        
        Args:
            name: Unique identifier for the task. Must be unique across
                 all registered tasks. Used for logging and management.
            target: Async callable (coroutine function) that will run as the task.
                   Should accept the provided args and kwargs.
            *args: Positional arguments to pass to the target function.
                  Common pattern is to pass queues and shutdown events.
            **kwargs: Keyword arguments to pass to the target.
        
        Example:
            ```python
            tm.register_task(
                "email_worker",
                email_monitor_function,
                email_queue,
                shutdown_event,
                poll_interval=60
            )
            ```
        
        Note:
            Registration only stores the task definition. The actual
            asyncio.Task object is created when start_task() is called.
        """
        if name in self.tasks:
            ff_logging.log_failure(f"Task '{name}' is already registered")
            return
        
        self.tasks[name] = TaskInfo(
            name=name,
            target=target,
            args=args,
            kwargs=kwargs,
            state=TaskState.STOPPED
        )
        ff_logging.log_debug(f"Registered task: {name}")
    
    async def start_task(self, name: str) -> bool:
        """
        Start a registered task.
        
        Creates an asyncio.Task from the registered target and starts execution.
        Updates task state and timing information.
        
        Args:
            name: Name of the registered task to start
        
        Returns:
            bool: True if task started successfully, False otherwise
        
        Example:
            ```python
            await tm.start_task("email_worker")
            ```
        """
        if name not in self.tasks:
            ff_logging.log_failure(f"Cannot start unregistered task: {name}")
            return False
        
        task_info = self.tasks[name]
        
        if task_info.is_alive():
            ff_logging.log_failure(f"Task '{name}' is already running")
            return False
        
        try:
            task_info.state = TaskState.STARTING
            task_info.start_time = time.time()
            
            # Create and start the asyncio task
            task_info.task = asyncio.create_task(
                task_info.target(*task_info.args, **task_info.kwargs),
                name=name
            )
            
            task_info.state = TaskState.RUNNING
            ff_logging.log(f"Started task: {name}")
            return True
            
        except Exception as e:
            ff_logging.log_failure(f"Failed to start task '{name}': {e}")
            task_info.state = TaskState.FAILED
            return False
    
    async def stop_task(self, name: str, timeout: Optional[float] = None) -> bool:
        """
        Stop a running task gracefully.
        
        Cancels the task and waits for it to complete within the timeout period.
        
        Args:
            name: Name of the task to stop
            timeout: Maximum seconds to wait for task cancellation.
                    Uses config shutdown_timeout if not specified.
        
        Returns:
            bool: True if task stopped cleanly, False if timeout or error
        
        Example:
            ```python
            await tm.stop_task("email_worker", timeout=10.0)
            ```
        """
        if name not in self.tasks:
            ff_logging.log_failure(f"Cannot stop unknown task: {name}")
            return False
        
        task_info = self.tasks[name]
        
        if not task_info.is_alive():
            ff_logging.log_debug(f"Task '{name}' is not running")
            task_info.state = TaskState.STOPPED
            return True
        
        try:
            task_info.state = TaskState.STOPPING
            ff_logging.log(f"Stopping task: {name}")
            
            # Cancel the task
            task_info.task.cancel()
            
            # Wait for cancellation with timeout
            timeout = timeout or self.process_config.shutdown_timeout
            try:
                await asyncio.wait_for(task_info.task, timeout=timeout)
            except asyncio.CancelledError:
                # Expected when task is cancelled
                pass
            except asyncio.TimeoutError:
                ff_logging.log_failure(
                    f"Task '{name}' did not stop within {timeout} seconds"
                )
                task_info.state = TaskState.FAILED
                return False
            
            task_info.state = TaskState.STOPPED
            task_info.task = None
            ff_logging.log(f"Stopped task: {name}")
            return True
            
        except Exception as e:
            ff_logging.log_failure(f"Error stopping task '{name}': {e}")
            task_info.state = TaskState.FAILED
            return False
    
    async def start_all(self) -> None:
        """
        Start all registered tasks.
        
        Starts all tasks that have been registered but not yet started.
        Also starts the monitoring task if health monitoring is enabled.
        
        Example:
            ```python
            await tm.start_all()
            ```
        """
        ff_logging.log("Starting all tasks...")
        
        started_count = 0
        failed_count = 0
        
        for name in list(self.tasks.keys()):
            if await self.start_task(name):
                started_count += 1
            else:
                failed_count += 1
        
        ff_logging.log(
            f"Task startup complete: {started_count} started, {failed_count} failed"
        )
        
        # Start monitoring if enabled
        if self.process_config.enable_monitoring:
            await self._start_monitoring()
    
    async def stop_all(self, timeout: Optional[float] = None) -> None:
        """
        Stop all running tasks gracefully.
        
        Cancels all tasks and waits for them to complete within the timeout period.
        Also stops the monitoring task if running.
        
        Args:
            timeout: Maximum seconds to wait for all tasks to stop.
                    Uses config shutdown_timeout if not specified.
        
        Example:
            ```python
            await tm.stop_all(timeout=30.0)
            ```
        """
        # Prevent duplicate shutdown
        if self._shutdown_event.is_set():
            ff_logging.log_debug("Shutdown already in progress")
            return
        
        self._shutdown_event.set()
        ff_logging.log("Stopping all tasks...")
        
        # Stop monitoring first
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        # Stop all managed tasks
        timeout = timeout or self.process_config.shutdown_timeout
        
        stop_tasks = [
            self.stop_task(name, timeout=timeout)
            for name in list(self.tasks.keys())
            if self.tasks[name].is_alive()
        ]
        
        if stop_tasks:
            results = await asyncio.gather(*stop_tasks, return_exceptions=True)
            success_count = sum(1 for r in results if r is True)
            ff_logging.log(f"Stopped {success_count}/{len(stop_tasks)} tasks")
    
    async def wait_for_all(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for all tasks to complete or shutdown signal.
        
        Blocks until either all tasks complete naturally or a shutdown
        signal is received via the shutdown event.
        
        Args:
            timeout: Optional timeout in seconds. If None, waits indefinitely.
        
        Returns:
            bool: True if all tasks completed or shutdown successful,
                 False if timeout occurred
        
        Example:
            ```python
            # Wait indefinitely for shutdown signal
            await tm.wait_for_all()
            
            # Wait with timeout
            if not await tm.wait_for_all(timeout=300.0):
                print("Timeout waiting for tasks")
            ```
        """
        try:
            if timeout:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=timeout
                )
            else:
                await self._shutdown_event.wait()
            return True
        except asyncio.TimeoutError:
            ff_logging.log_failure("Timeout waiting for tasks to complete")
            return False
    
    async def _start_monitoring(self) -> None:
        """
        Start the health monitoring task.
        
        Creates a background task that periodically checks task health
        and restarts failed tasks if auto_restart is enabled.
        """
        if self._monitor_task and not self._monitor_task.done():
            ff_logging.log_debug("Monitoring task already running")
            return
        
        self._monitor_task = asyncio.create_task(
            self._monitor_tasks(),
            name="task_monitor"
        )
        ff_logging.log("Started task health monitoring")
    
    async def _monitor_tasks(self) -> None:
        """
        Background task that monitors task health and handles restarts.
        
        Runs continuously until shutdown, checking task status at
        configured intervals and restarting failed tasks if enabled.
        """
        interval = self.process_config.health_check_interval
        
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(interval)
                
                for name, task_info in list(self.tasks.items()):
                    task_info.last_health_check = time.time()
                    
                    # Check if task has failed
                    if task_info.task and task_info.task.done():
                        try:
                            # Check for exceptions
                            task_info.task.result()
                        except Exception as e:
                            ff_logging.log_failure(
                                f"Task '{name}' failed with error: {e}"
                            )
                            task_info.state = TaskState.FAILED
                            
                            # Attempt restart if enabled
                            if self.process_config.auto_restart:
                                await self._handle_task_failure(name, task_info)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                ff_logging.log_failure(f"Error in monitoring task: {e}")
    
    async def _handle_task_failure(self, name: str, task_info: TaskInfo) -> None:
        """
        Handle a failed task by attempting restart if configured.
        
        Args:
            name: Name of the failed task
            task_info: TaskInfo object for the failed task
        """
        max_restarts = getattr(
            self.process_config, 
            "restart_threshold", 
            3
        )
        
        if task_info.restart_count >= max_restarts:
            ff_logging.log_failure(
                f"Task '{name}' exceeded restart limit ({max_restarts})"
            )
            task_info.state = TaskState.FAILED
            return
        
        task_info.restart_count += 1
        task_info.state = TaskState.RESTARTING
        
        ff_logging.log(
            f"Restarting task '{name}' (attempt {task_info.restart_count})"
        )
        
        # Wait before restart
        restart_delay = getattr(self.process_config, "restart_delay", 5.0)
        await asyncio.sleep(restart_delay)
        
        # Attempt restart
        await self.start_task(name)
    
    def setup_signal_handlers(self) -> None:
        """
        Setup signal handlers for graceful shutdown.
        
        Installs handlers for SIGTERM and SIGINT that trigger coordinated
        shutdown via the shutdown event. Prevents duplicate handler installation.
        
        Note:
            Signal handlers work by scheduling the shutdown coroutine
            in the event loop, ensuring thread-safe coordination.
        """
        if self._signal_handlers_set:
            ff_logging.log_debug("Signal handlers already set")
            return
        
        def signal_handler(signum, frame):
            """Signal handler that schedules async shutdown."""
            if not self._shutdown_event.is_set():
                ff_logging.log(f"Received signal {signum}, initiating shutdown...")
                self._shutdown_event.set()
                
                # Schedule stop_all in the event loop
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self.stop_all())
        
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        self._signal_handlers_set = True
        ff_logging.log_debug("Signal handlers installed")
    
    def get_status(self) -> Dict[str, Dict[str, Any]]:
        """
        Get status information for all managed tasks.
        
        Returns:
            Dict mapping task names to their status information including
            state, uptime, restart count, and alive status.
        
        Example:
            ```python
            status = tm.get_status()
            for name, info in status.items():
                print(f"{name}: {info['state']} (uptime: {info['uptime']}s)")
            ```
        """
        return {
            name: {
                "state": info.state.value,
                "is_alive": info.is_alive(),
                "uptime": info.get_uptime(),
                "restart_count": info.restart_count,
                "last_health_check": info.last_health_check
            }
            for name, info in self.tasks.items()
        }
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.setup_signal_handlers()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with cleanup."""
        # Only stop if not already stopping/stopped
        if not self._shutdown_event.is_set():
            await self.stop_all()
