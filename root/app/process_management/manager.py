"""
Process Manager Implementation

This module provides the core ProcessManager class for centralized management
of worker processes, including lifecycle management, monitoring, and shutdown coordination.
"""

import multiprocessing as mp
import signal
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from utils import ff_logging
from models.config_models import AppConfig, ProcessConfig
from .state import ProcessInfo, ProcessState


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

        Args:
            name: Unique identifier for the process.
            target: Callable function that will run in the subprocess.
            args: Tuple of positional arguments to pass to the target function.
            kwargs: Dictionary of keyword arguments to pass to the target.
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

        Args:
            name: Name of the registered process to start.

        Returns:
            bool: True if the process started successfully.
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

        Args:
            name: Name of the registered process to stop
            timeout: Maximum seconds to wait for graceful shutdown.
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

            # Store reference to avoid race conditions
            process = process_info.process

            # Attempt graceful termination with SIGTERM
            process.terminate()
            process.join(timeout)

            # Force kill if process is still alive after timeout
            if process.is_alive():
                ff_logging.log_failure(f"Force killing process: {name}")
                try:
                    process.kill()
                    process.join(5)  # Wait briefly for kill to take effect
                except Exception as kill_error:
                    ff_logging.log_failure(
                        f"Error during force kill of '{name}': {kill_error}"
                    )

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
        Stop all processes gracefully with parallel shutdown.
        """
        self._shutdown_event.set()

        # Stop monitoring thread first
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
            self._monitor_thread = None

        # Stop worker pool if exists
        if self.pool:
            try:
                self.pool.terminate()
                self.pool.join()
                self.pool = None
            except Exception as e:
                ff_logging.log_failure(f"Error stopping pool: {e}")

        # Use configured timeout if none provided
        timeout = (
            timeout if timeout is not None else self.process_config.shutdown_timeout
        )
        if timeout is None:
            timeout = 30.0  # Fallback default if config is missing
        start_time = time.time()

        # Phase 1: Signal all processes to terminate (Parallel Shutdown)
        processes_to_stop = []
        for name, process_info in self.processes.items():
            if process_info.is_alive() and process_info.process:
                try:
                    ff_logging.log_debug(f"Sending SIGTERM to process: {name}")
                    process_info.process.terminate()
                    process_info.state = ProcessState.STOPPING
                    processes_to_stop.append((name, process_info))
                except Exception as e:
                    ff_logging.log_failure(f"Error terminating process '{name}': {e}")
            elif not process_info.is_alive():
                process_info.state = ProcessState.STOPPED

        # Phase 2: Wait for all processes to exit within timeout
        while processes_to_stop and (time.time() - start_time < timeout):
            still_running = []
            for name, process_info in processes_to_stop:
                if process_info.process.is_alive():
                    still_running.append((name, process_info))
                else:
                    process_info.state = ProcessState.STOPPED
                    ff_logging.log_debug(f"Process stopped gracefully: {name}")

            processes_to_stop = still_running
            if processes_to_stop:
                time.sleep(0.1)

        # Phase 3: Force kill any remaining processes
        success = True
        for name, process_info in processes_to_stop:
            ff_logging.log_failure(f"Process '{name}' timed out, force killing")
            try:
                if process_info.process.is_alive():
                    process_info.process.kill()
                    process_info.process.join(1)  # Brief wait for kill
                process_info.state = ProcessState.FAILED
                success = False
            except Exception as e:
                ff_logging.log_failure(f"Error force killing '{name}': {e}")
                success = False

        return success

    def wait_for_termination(self, timeout: float = 5.0) -> bool:
        """
        Wait for all processes to fully terminate after a stop operation.
        """
        start_wait = time.time()

        while (time.time() - start_wait) < timeout:
            all_terminated = True
            for process_info in self.processes.values():
                if process_info.is_alive():
                    all_terminated = False
                    break

            if all_terminated:
                return True

            time.sleep(0.1)  # Small delay before checking again

        return False

    def wait_for_all(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for all managed processes to complete or shutdown signal.
        """
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
