"""
Process Manager for AutomatedFanfic

This module provides centralized management of worker processes for the AutomatedFanfic
multiprocessing application. It handles process lifecycle management, health monitoring,
graceful shutdown coordination, and automatic restart capabilities.

Key Features:
    - Multi-process lifecycle management with state tracking
    - Health monitoring with configurable intervals and automatic restart
    - Signal-based graceful shutdown with coordinated cleanup
    - Process pool management for CPU-bound tasks
    - Thread-safe operations with proper synchronization
    - Context manager support for resource cleanup

Architecture:
    The ProcessManager serves as a centralized coordinator for all worker processes
    in the application. It maintains process state, monitors health via a dedicated
    monitoring thread, and handles shutdown coordination to prevent Docker timeout
    issues and ensure clean termination.

Example:
    ```python
    from config_models import AppConfig
    from process_manager import ProcessManager
    
    config = AppConfig.load_from_file("config.toml")
    
    with ProcessManager(config) as pm:
        pm.register_process("email_monitor", email_worker_func, args=(queue,))
        pm.register_process("url_processor", url_worker_func, args=(url_queue,))
        
        pm.start_all()
        pm.wait_for_all()  # Blocks until shutdown signal received
    ```

Process States:
    - STARTING: Process is being initialized
    - RUNNING: Process is actively running and responsive
    - STOPPING: Process is being gracefully terminated
    - STOPPED: Process has terminated cleanly
    - FAILED: Process crashed or failed to start
    - RESTARTING: Process is being restarted after failure

Signal Handling:
    The manager installs signal handlers for SIGTERM and SIGINT that coordinate
    graceful shutdown across all managed processes. This prevents the 30-second
    Docker timeout by ensuring the main process exits cleanly.

Thread Safety:
    All operations are thread-safe using proper synchronization primitives.
    The monitoring thread runs independently and coordinates with the main
    thread via shared event objects.
"""

import asyncio
import multiprocessing as mp
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import ff_logging
from config_models import AppConfig, ConfigManager, ProcessConfig, get_config


class ProcessState(Enum):
    """
    Enumeration representing the lifecycle states of managed processes.
    
    States represent the complete lifecycle from initialization through
    termination, including error conditions and restart scenarios.
    
    Attributes:
        STARTING: Process is being initialized and started
        RUNNING: Process is actively running and responsive
        STOPPING: Process is being gracefully terminated
        STOPPED: Process has terminated cleanly
        FAILED: Process crashed, failed to start, or exceeded restart limits
        RESTARTING: Process is being restarted after a failure
    """

    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    RESTARTING = "restarting"


@dataclass
class ProcessInfo:
    """
    Information container for a managed process.
    
    This dataclass stores all metadata and state information for a process
    managed by the ProcessManager. It tracks the process lifecycle, timing
    information, restart attempts, and provides convenience methods for
    process state checking.
    
    Attributes:
        name: Unique identifier for the process
        process: The actual multiprocessing.Process instance (None when stopped)
        target: The callable function that runs in the process
        args: Positional arguments passed to the target function
        kwargs: Keyword arguments passed to the target function
        state: Current ProcessState of the process
        start_time: Unix timestamp when the process was last started
        last_health_check: Unix timestamp of the last health check
        restart_count: Number of times this process has been restarted
        pid: Process ID assigned by the operating system (None when stopped)
    
    Example:
        ```python
        info = ProcessInfo(
            name="email_worker",
            target=email_monitor_func,
            args=(email_queue, shutdown_event),
            kwargs={"poll_interval": 60}
        )
        ```
    """

    name: str
    process: Optional[mp.Process] = None
    target: Optional[Callable] = None
    args: Tuple = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    state: ProcessState = ProcessState.STOPPED
    start_time: Optional[float] = None
    last_health_check: Optional[float] = None
    restart_count: int = 0
    pid: Optional[int] = None

    def is_alive(self) -> bool:
        """
        Check if the process is currently alive and running.
        
        Returns:
            bool: True if process exists and is alive, False otherwise
            
        Note:
            This is a safe check that handles cases where the process
            object is None or has been cleaned up.
        """
        return self.process is not None and self.process.is_alive()

    def get_uptime(self) -> Optional[float]:
        """
        Calculate the current uptime of the process in seconds.
        
        Returns:
            Optional[float]: Uptime in seconds if process has been started,
                           None if process has never been started
                           
        Note:
            Returns the elapsed time since the process was last started,
            regardless of whether the process is currently running.
        """
        if self.start_time is None:
            return None
        return time.time() - self.start_time


class ProcessManager:
    """
    Centralized process manager with health monitoring and graceful shutdown.
    
    The ProcessManager is the core orchestrator for all worker processes in the
    AutomatedFanfic application. It provides a unified interface for process
    lifecycle management, health monitoring, and coordinated shutdown.
    
    Key Features:
        - Process registration and lifecycle management
        - Health monitoring with automatic restart capabilities
        - Signal-based graceful shutdown coordination
        - Thread-safe process state tracking
        - Worker pool management for CPU-bound tasks
        - Context manager support for clean resource management
    
    Architecture:
        The manager uses a monitoring thread that periodically checks process
        health and can automatically restart failed processes. Signal handlers
        coordinate graceful shutdown across all managed processes to prevent
        Docker timeout issues.
    
    Thread Safety:
        All public methods are thread-safe. The internal monitoring thread
        coordinates with the main thread via threading.Event objects and
        proper synchronization primitives.
    
    Example:
        ```python
        config = AppConfig.load_from_file("config.toml")
        
        with ProcessManager(config) as pm:
            # Register worker processes
            pm.register_process("email_monitor", email_worker, (email_queue,))
            pm.register_process("url_processor", url_worker, (url_queue,))
            
            # Start all processes with monitoring
            pm.start_all()
            
            # Wait for completion or signal
            pm.wait_for_all()
        ```
    
    Configuration:
        Process behavior is controlled via ProcessConfig in the AppConfig:
        - health_check_interval: Seconds between health checks
        - shutdown_timeout: Maximum seconds to wait for graceful shutdown
        - auto_restart: Whether to automatically restart failed processes
        - max_restart_attempts: Maximum restart attempts before marking failed
        - restart_delay: Seconds to wait before attempting restart
    """

    def __init__(self, config: Optional[AppConfig] = None):
        """
        Initialize the ProcessManager with configuration.

        Args:
            config: AppConfig instance containing process configuration.
                   Must be provided - configuration is required for proper
                   operation of health monitoring and shutdown timeouts.
                   
        Raises:
            ValueError: If config is None, as configuration is required
                       for proper process management.
                       
        Note:
            The ProcessManager requires configuration to function properly.
            This includes timing parameters for health checks, shutdown
            timeouts, and restart behavior. The config must be loaded
            from the application's configuration system before creating
            the ProcessManager instance.
        """
        # Process tracking and state management
        self.processes: Dict[str, ProcessInfo] = {}
        self.pool = None  # Worker pool for CPU-bound tasks
        
        # Synchronization primitives for thread coordination
        self._shutdown_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._signal_handlers_set = False

        # Configuration validation and setup
        if config:
            self.config = config
            self.process_config = getattr(config, "process", ProcessConfig())
        else:
            # Configuration is required for proper operation
            raise ValueError("AppConfig must be provided to ProcessManager.")

        ff_logging.log_debug("ProcessManager initialized")

    def register_process(
        self,
        name: str,
        target: Callable,
        args: Tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Register a process for management without starting it.
        
        This method registers a process definition that can be started later
        with start_process() or start_all(). The process is not created or
        started until explicitly requested.

        Args:
            name: Unique identifier for the process. Must be unique across
                 all registered processes. Used for logging and management.
            target: Callable function that will run in the subprocess.
                   Should accept the provided args and kwargs.
            args: Tuple of positional arguments to pass to the target function.
                 Common pattern is to pass queues and shutdown events.
            kwargs: Dictionary of keyword arguments to pass to the target.
                   Will be merged with args during process creation.
                   
        Raises:
            None: Method logs failure for duplicate names but doesn't raise.
                 Check logs for registration conflicts.
                 
        Example:
            ```python
            pm.register_process(
                "email_worker",
                email_monitor_function,
                args=(email_queue, shutdown_event),
                kwargs={"poll_interval": 60}
            )
            ```
            
        Note:
            Registration only stores the process definition. The actual
            multiprocessing.Process object is created when start_process()
            is called. This allows for delayed process creation and restart
            scenarios.
        """
        if name in self.processes:
            ff_logging.log_failure(f"Process '{name}' is already registered")
            return

        kwargs = kwargs or {}
        process_info = ProcessInfo(name=name, target=target, args=args, kwargs=kwargs)

        self.processes[name] = process_info
        ff_logging.log_debug(f"Registered process: {name}")

    def start_process(self, name: str) -> bool:
        """
        Start a previously registered process.
        
        Creates and starts a new multiprocessing.Process instance for the
        registered process definition. Updates process state and timing
        information, and logs the startup event.

        Args:
            name: Name of the registered process to start. Must have been
                 previously registered with register_process().

        Returns:
            bool: True if the process started successfully, False if the
                 process was not registered, already running, or failed
                 to start.
                 
        Side Effects:
            - Creates new multiprocessing.Process instance
            - Updates ProcessInfo state to RUNNING
            - Records start time and PID
            - Logs startup event with PID information
            
        Example:
            ```python
            # Register first
            pm.register_process("worker", worker_func, (queue,))
            
            # Then start
            if pm.start_process("worker"):
                print("Worker started successfully")
            else:
                print("Failed to start worker")
            ```
            
        Note:
            If the process is already running, this method returns False
            and logs a failure message. Use restart_process() to restart
            a running process, or stop_process() first.
        """
        if name not in self.processes:
            ff_logging.log_failure(f"Process '{name}' not registered")
            return False

        process_info = self.processes[name]

        if process_info.is_alive():
            ff_logging.log_failure(f"Process '{name}' is already running")
            return False

        try:
            # Set state before starting to avoid race conditions
            process_info.state = ProcessState.STARTING
            
            # Create new process instance with registered parameters
            process = mp.Process(
                target=process_info.target,
                args=process_info.args,
                kwargs=process_info.kwargs,
                name=name,
            )

            # Start the process
            process.start()

            # Update process information with running state
            process_info.process = process
            process_info.pid = process.pid
            process_info.start_time = time.time()
            process_info.last_health_check = time.time()
            process_info.state = ProcessState.RUNNING

            ff_logging.log_debug(f"Started process: {name} (PID: {process.pid})")
            return True

        except Exception as e:
            ff_logging.log_failure(f"Failed to start process '{name}': {e}")
            process_info.state = ProcessState.FAILED
            return False

    def stop_process(self, name: str, timeout: Optional[float] = None) -> bool:
        """
        Stop a running process gracefully with configurable timeout.
        
        Attempts graceful termination first using SIGTERM, then forces
        termination with SIGKILL if the process doesn't respond within
        the timeout period. Updates process state and cleans up resources.

        Args:
            name: Name of the registered process to stop
            timeout: Maximum seconds to wait for graceful shutdown.
                    Uses process_config.shutdown_timeout if None.

        Returns:
            bool: True if process stopped successfully (or wasn't running),
                 False if process not registered or stop operation failed.
                 
        Process Flow:
            1. Check if process is registered and running
            2. Send SIGTERM for graceful shutdown
            3. Wait for timeout period
            4. Send SIGKILL if still running
            5. Clean up process resources and state
            
        Example:
            ```python
            # Stop with default timeout
            pm.stop_process("worker")
            
            # Stop with custom timeout
            pm.stop_process("worker", timeout=10.0)
            ```
            
        Note:
            This method handles the case where a process has already stopped
            gracefully. It will return True and update the state to STOPPED
            without attempting termination.
        """
        if name not in self.processes:
            ff_logging.log_failure(f"Process '{name}' not registered")
            return False

        process_info = self.processes[name]

        if not process_info.is_alive():
            ff_logging.log(f"Process '{name}' is not running", "WARNING")
            process_info.state = ProcessState.STOPPED
            return True

        if process_info.process is None:
            ff_logging.log_failure(f"Process '{name}' has no process object")
            return False

        # Use configured timeout if none provided
        timeout = timeout or self.process_config.shutdown_timeout
        process_info.state = ProcessState.STOPPING

        try:
            ff_logging.log_debug(f"Stopping process: {name} (timeout: {timeout}s)")

            # Attempt graceful termination with SIGTERM
            process_info.process.terminate()
            process_info.process.join(timeout)

            # Force kill if process is still alive after timeout
            if process_info.process.is_alive():
                ff_logging.log_failure(f"Force killing process: {name}")
                process_info.process.kill()
                process_info.process.join(5)  # Wait briefly for kill to take effect

            # Clean up process state and resources
            process_info.state = ProcessState.STOPPED
            process_info.process = None
            process_info.pid = None
            process_info.start_time = None

            ff_logging.log_debug(f"Stopped process: {name}")
            return True

        except Exception as e:
            ff_logging.log_failure(f"Error stopping process '{name}': {e}")
            process_info.state = ProcessState.FAILED
            return False

    def restart_process(self, name: str) -> bool:
        """
        Restart a process.

        Args:
            name: Name of the process to restart

        Returns:
            bool: True if restarted successfully, False otherwise
        """
        if name not in self.processes:
            ff_logging.log_failure(f"Process '{name}' not registered")
            return False

        process_info = self.processes[name]

        if process_info.restart_count >= self.process_config.max_restart_attempts:
            ff_logging.log_failure(
                f"Process '{name}' exceeded maximum restart attempts ({self.process_config.max_restart_attempts})"
            )
            process_info.state = ProcessState.FAILED
            return False

        process_info.state = ProcessState.RESTARTING
        process_info.restart_count += 1

        ff_logging.log_debug(
            f"Restarting process: {name} (attempt {process_info.restart_count})"
        )

        # Stop the process if it's still running
        if process_info.is_alive():
            self.stop_process(name)

        # Wait before restarting
        if self.process_config.restart_delay > 0:
            time.sleep(self.process_config.restart_delay)

        return self.start_process(name)

    def start_all(self) -> bool:
        """
        Start all registered processes.

        Returns:
            bool: True if all processes started successfully, False otherwise
        """
        success = True
        for name in self.processes:
            if not self.start_process(name):
                success = False

        # Start monitoring if enabled and processes were started
        if (
            success
            and self.process_config.enable_monitoring
            and not self._monitor_thread
        ):
            self._start_monitoring()

        return success

    def stop_all(self, timeout: Optional[float] = None) -> bool:
        """
        Stop all processes gracefully.

        Args:
            timeout: Timeout for each process shutdown

        Returns:
            bool: True if all processes stopped successfully, False otherwise
        """
        self._shutdown_event.set()

        # Stop monitoring
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
            self._monitor_thread = None

        # Stop pool if exists
        if self.pool:
            try:
                self.pool.terminate()
                self.pool.join()  # Pool.join() doesn't take timeout
                self.pool = None
            except Exception as e:
                ff_logging.log_failure(f"Error stopping pool: {e}")

        # Stop individual processes
        success = True
        for name in self.processes:
            if not self.stop_process(name, timeout):
                success = False

        return success

    def wait_for_all(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for all managed processes to complete or shutdown signal.
        
        This is the main blocking method that keeps the application running
        until either all processes complete naturally or a shutdown signal
        is received. Critical for proper application lifecycle management.

        Args:
            timeout: Maximum seconds to wait for all processes to complete.
                    None means wait indefinitely until signal or completion.

        Returns:
            bool: True if all processes completed or shutdown was requested,
                 False if timeout was exceeded before completion.
                 
        Behavior:
            - Blocks until shutdown event is set (via signal handler)
            - Monitors all processes for natural completion
            - Respects timeout if provided
            - Uses polling with brief sleep to avoid busy waiting
            
        Example:
            ```python
            with ProcessManager(config) as pm:
                pm.register_process("worker", worker_func, (queue,))
                pm.start_all()
                
                # This blocks until SIGTERM/SIGINT or all processes finish
                pm.wait_for_all()
            ```
            
        Signal Integration:
            This method coordinates with the signal handlers. When SIGTERM
            or SIGINT is received, the signal handler sets the shutdown event
            and this method returns True, allowing the main application to
            exit cleanly.
            
        Note:
            This is typically the last method called in the main application
            loop. It ensures the application stays running until shutdown
            is requested or all work is complete.
        """
        import time

        start_time = time.time()

        while True:
            # Check if shutdown was requested via signal handler
            if self._shutdown_event.is_set():
                ff_logging.log_debug("Shutdown event set, exiting wait loop")
                return True

            # Check if all processes have stopped naturally
            all_stopped = True
            for process_info in self.processes.values():
                if process_info.is_alive():
                    all_stopped = False
                    break

            if all_stopped:
                ff_logging.log_debug("All processes have completed")
                return True

            # Check timeout if specified
            if timeout is not None:
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    ff_logging.log_failure(
                        f"Timeout waiting for processes after {timeout}s"
                    )
                    return False

            # Brief sleep to avoid busy waiting and reduce CPU usage
            time.sleep(0.5)

    def get_status(self) -> Dict[str, Dict[str, Any]]:
        """
        Get status of all managed processes.

        Returns:
            Dict containing process status information
        """
        status = {}
        for name, process_info in self.processes.items():
            status[name] = {
                "state": process_info.state.value,
                "alive": process_info.is_alive(),
                "pid": process_info.pid,
                "uptime": process_info.get_uptime(),
                "restart_count": process_info.restart_count,
                "last_health_check": process_info.last_health_check,
            }
        return status

    def _start_monitoring(self) -> None:
        """Start the process monitoring thread."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        self._monitor_thread = threading.Thread(
            target=self._monitor_processes, name="ProcessMonitor", daemon=True
        )
        self._monitor_thread.start()
        ff_logging.log_debug("Started process monitoring thread")

    def _monitor_processes(self) -> None:
        """
        Main monitoring loop that runs in a dedicated thread.
        
        This method runs continuously in the monitoring thread, performing
        periodic health checks on all managed processes and handling
        automatic restart of failed processes based on configuration.
        
        Monitoring Behavior:
            - Runs until shutdown event is set
            - Performs health checks at configured intervals
            - Automatically restarts failed processes if enabled
            - Handles exceptions gracefully with error logging
            - Uses configurable sleep intervals to reduce CPU usage
            
        Health Check Process:
            1. Check if health check interval has elapsed
            2. Verify process is still alive and responsive
            3. Log health status and uptime information
            4. Trigger restart if process has failed and auto-restart is enabled
            5. Update last health check timestamp
            
        Thread Safety:
            This method is designed to run in a separate thread and coordinates
            with the main thread via the shutdown event. All process state
            modifications are thread-safe.
            
        Example Configuration:
            ```toml
            [process]
            enable_monitoring = true
            health_check_interval = 60.0
            auto_restart = true
            max_restart_attempts = 3
            ```
            
        Note:
            This method should never be called directly. It's automatically
            started by _start_monitoring() when process monitoring is enabled
            in the configuration.
        """
        ff_logging.log_debug("Process monitoring started")

        while not self._shutdown_event.is_set():
            try:
                current_time = time.time()

                # Iterate through all managed processes
                for name, process_info in self.processes.items():
                    # Skip monitoring if disabled in configuration
                    if not self.process_config.enable_monitoring:
                        continue

                    # Check if health check interval has elapsed
                    if (
                        process_info.last_health_check is None
                        or current_time - process_info.last_health_check
                        >= self.process_config.health_check_interval
                    ):
                        # Perform health check on this process
                        self._health_check_process(name, process_info, current_time)

                # Sleep until next monitoring cycle
                self._shutdown_event.wait(
                    min(5.0, self.process_config.health_check_interval)
                )

            except Exception as e:
                ff_logging.log_failure(f"Error in process monitoring: {e}")
                # Brief sleep before retrying to avoid rapid error loops
                self._shutdown_event.wait(5.0)

        ff_logging.log_debug("Process monitoring stopped")

    def _health_check_process(
        self, name: str, process_info: ProcessInfo, current_time: float
    ) -> None:
        """
        Perform health check on a single process.

        Args:
            name: Process name
            process_info: Process information
            current_time: Current timestamp
        """
        process_info.last_health_check = current_time

        # Check if process is alive
        if not process_info.is_alive() and process_info.state == ProcessState.RUNNING:
            ff_logging.log_failure(f"Process '{name}' died unexpectedly")
            process_info.state = ProcessState.FAILED

            # Attempt restart if enabled
            if self.process_config.auto_restart:
                self.restart_process(name)

        # Log health status periodically
        if process_info.is_alive():
            uptime = process_info.get_uptime()
            ff_logging.log_debug(
                f"Process '{name}' health check OK (uptime: {uptime:.1f}s)"
            )

    def setup_signal_handlers(self) -> None:
        """
        Configure signal handlers for graceful application shutdown.
        
        Installs signal handlers for SIGTERM and SIGINT that coordinate
        graceful shutdown across all managed processes. Critical for
        preventing Docker timeout issues and ensuring clean termination.
        
        Signal Handling Strategy:
            1. Prevent duplicate signal handling via shutdown event
            2. Log the received signal for debugging
            3. Set shutdown event to coordinate with other threads
            4. Stop all managed processes gracefully
            
        Signals Handled:
            - SIGTERM: Standard termination signal (Docker stop)
            - SIGINT: Interrupt signal (Ctrl+C)
            
        Example:
            ```python
            pm = ProcessManager(config)
            pm.setup_signal_handlers()  # Usually called automatically
            
            # Now SIGTERM/SIGINT will trigger graceful shutdown
            pm.start_all()
            pm.wait_for_all()  # Will exit cleanly on signal
            ```
            
        Note:
            This method is idempotent - calling it multiple times has no
            additional effect. Signal handlers are only installed once
            per ProcessManager instance to avoid conflicts.
            
        Docker Integration:
            These signal handlers are critical for Docker compatibility.
            Without them, Docker's stop command will wait 30 seconds for
            the container to exit before force-killing it. Proper signal
            handling ensures the main process exits quickly and cleanly.
        """
        if self._signal_handlers_set:
            return

        def signal_handler(signum, frame):
            # Prevent repeated signal handling - critical for clean shutdown
            if self._shutdown_event.is_set():
                ff_logging.log_debug("Signal already being handled, ignoring")
                return

            signal_name = signal.Signals(signum).name
            ff_logging.log(
                f"Received signal {signal_name}, initiating graceful shutdown...",
                "WARNING",
            )
            
            # Set shutdown event to coordinate with monitoring thread and main loop
            self._shutdown_event.set()

            # Stop all child processes gracefully
            self.stop_all()

        # Install handlers for common termination signals
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        self._signal_handlers_set = True
        ff_logging.log_debug("Signal handlers configured")

    def create_worker_pool(self, worker_count: Optional[int] = None):
        """
        Create a worker pool for CPU-bound tasks.

        Args:
            worker_count: Number of workers (uses config default if None)

        Returns:
            multiprocessing.Pool instance
        """
        if self.pool:
            ff_logging.log_failure("Worker pool already exists")
            return self.pool

        worker_count = worker_count or self.config.max_workers

        try:
            self.pool = mp.Pool(worker_count)
            ff_logging.log_debug(f"Created worker pool with {worker_count} workers")
            return self.pool

        except Exception as e:
            ff_logging.log_failure(f"Failed to create worker pool: {e}")
            raise

    def __enter__(self):
        """Context manager entry."""
        self.setup_signal_handlers()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup."""
        # Only stop if not already stopping/stopped
        if not self._shutdown_event.is_set():
            self.stop_all()
