"""
Process Manager for AutomatedFanfic

Provides centralized management of worker processes with health monitoring,
graceful shutdown, and automatic restart capabilities.
"""

import asyncio
import multiprocessing as mp
import signal
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import ff_logging
from config_models import AppConfig, ConfigManager, ProcessConfig, get_config


class ProcessState(Enum):
    """Process state enumeration."""

    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    RESTARTING = "restarting"


@dataclass
class ProcessInfo:
    """Information about a managed process."""

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
        """Check if the process is alive."""
        return self.process is not None and self.process.is_alive()

    def get_uptime(self) -> Optional[float]:
        """Get process uptime in seconds."""
        if self.start_time is None:
            return None
        return time.time() - self.start_time


class ProcessManager:
    """
    Centralized process manager with health monitoring and graceful shutdown.

    Features:
    - Process lifecycle management
    - Health monitoring with automatic restart
    - Graceful shutdown with configurable timeouts
    - Signal handling for clean termination
    - Process state tracking and monitoring
    """

    def __init__(self, config: Optional[AppConfig] = None):
        """
        Initialize the ProcessManager.

        Args:
            config: AppConfig instance to use. If None, must be provided elsewhere.
        """
        self.processes: Dict[str, ProcessInfo] = {}
        self.pool = None
        self._shutdown_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._signal_handlers_set = False

        # Use provided config
        if config:
            self.config = config
            self.process_config = getattr(config, "process", ProcessConfig())
        else:
            # This requires that configuration has been loaded elsewhere
            # (e.g., in main application startup)
            raise ValueError("AppConfig must be provided to ProcessManager.")

        ff_logging.log("ProcessManager initialized", "OKGREEN")

    def register_process(
        self,
        name: str,
        target: Callable,
        args: Tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Register a process for management.

        Args:
            name: Unique name for the process
            target: Target function to run in the process
            args: Arguments to pass to the target function
            kwargs: Keyword arguments to pass to the target function
        """
        if name in self.processes:
            ff_logging.log_failure(f"Process '{name}' is already registered")
            return

        kwargs = kwargs or {}
        process_info = ProcessInfo(name=name, target=target, args=args, kwargs=kwargs)

        self.processes[name] = process_info
        ff_logging.log(f"Registered process: {name}", "OKBLUE")

    def start_process(self, name: str) -> bool:
        """
        Start a registered process.

        Args:
            name: Name of the process to start

        Returns:
            bool: True if started successfully, False otherwise
        """
        if name not in self.processes:
            ff_logging.log_failure(f"Process '{name}' not registered")
            return False

        process_info = self.processes[name]

        if process_info.is_alive():
            ff_logging.log_failure(f"Process '{name}' is already running")
            return False

        try:
            process_info.state = ProcessState.STARTING
            process = mp.Process(
                target=process_info.target,
                args=process_info.args,
                kwargs=process_info.kwargs,
                name=name,
            )

            process.start()

            process_info.process = process
            process_info.pid = process.pid
            process_info.start_time = time.time()
            process_info.last_health_check = time.time()
            process_info.state = ProcessState.RUNNING

            ff_logging.log(f"Started process: {name} (PID: {process.pid})", "OKGREEN")
            return True

        except Exception as e:
            ff_logging.log_failure(f"Failed to start process '{name}': {e}")
            process_info.state = ProcessState.FAILED
            return False

    def stop_process(self, name: str, timeout: Optional[float] = None) -> bool:
        """
        Stop a process gracefully with timeout.

        Args:
            name: Name of the process to stop
            timeout: Timeout for graceful shutdown (uses config default if None)

        Returns:
            bool: True if stopped successfully, False otherwise
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

        timeout = timeout or self.process_config.shutdown_timeout
        process_info.state = ProcessState.STOPPING

        try:
            ff_logging.log(f"Stopping process: {name} (timeout: {timeout}s)", "WARNING")

            # Try graceful termination first
            process_info.process.terminate()
            process_info.process.join(timeout)

            if process_info.process.is_alive():
                # Force kill if still alive
                ff_logging.log_failure(f"Force killing process: {name}")
                process_info.process.kill()
                process_info.process.join(5)  # Wait briefly for kill to take effect

            process_info.state = ProcessState.STOPPED
            process_info.process = None
            process_info.pid = None
            process_info.start_time = None

            ff_logging.log(f"Stopped process: {name}", "OKGREEN")
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

        ff_logging.log(
            f"Restarting process: {name} (attempt {process_info.restart_count})",
            "WARNING",
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
        Wait for all processes to complete.

        Args:
            timeout: Maximum time to wait for all processes (None = wait indefinitely)

        Returns:
            bool: True if all processes completed, False if timeout exceeded
        """
        import time

        start_time = time.time()

        while True:
            # Check if all processes have stopped
            all_stopped = True
            for process_info in self.processes.values():
                if process_info.is_alive():
                    all_stopped = False
                    break

            if all_stopped:
                ff_logging.log("All processes have completed")
                return True

            # Check timeout
            if timeout is not None:
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    ff_logging.log_failure(
                        f"Timeout waiting for processes after {timeout}s"
                    )
                    return False

            # Brief sleep to avoid busy waiting
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
        ff_logging.log("Started process monitoring thread", "OKGREEN")

    def _monitor_processes(self) -> None:
        """Monitor process health and restart failed processes."""
        ff_logging.log("Process monitoring started", "OKBLUE")

        while not self._shutdown_event.is_set():
            try:
                current_time = time.time()

                for name, process_info in self.processes.items():
                    # Skip if monitoring is disabled
                    if not self.process_config.enable_monitoring:
                        continue

                    # Check if health check is due
                    if (
                        process_info.last_health_check is None
                        or current_time - process_info.last_health_check
                        >= self.process_config.health_check_interval
                    ):

                        self._health_check_process(name, process_info, current_time)

                # Sleep until next check
                self._shutdown_event.wait(
                    min(5.0, self.process_config.health_check_interval)
                )

            except Exception as e:
                ff_logging.log_failure(f"Error in process monitoring: {e}")
                self._shutdown_event.wait(5.0)

        ff_logging.log("Process monitoring stopped", "WARNING")

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
        """Setup signal handlers for graceful shutdown."""
        if self._signal_handlers_set:
            return

        def signal_handler(signum, frame):
            signal_name = signal.Signals(signum).name
            ff_logging.log(
                f"Received signal {signal_name}, initiating graceful shutdown...",
                "WARNING",
            )
            self.stop_all()
            # Don't call exit() here - let the application handle the shutdown flow
            # The signal will still interrupt the main loop in fanficdownload.py

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        self._signal_handlers_set = True
        ff_logging.log("Signal handlers configured", "OKGREEN")

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
            ff_logging.log(
                f"Created worker pool with {worker_count} workers", "OKGREEN"
            )
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
        self.stop_all()
