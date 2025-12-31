"""
Process State Definitions

This module defines the data structures and enumerations used to track
the state of managed processes within the application.
"""

import multiprocessing as mp
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple


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
        """
        return self.process is not None and self.process.is_alive()

    def get_uptime(self) -> Optional[float]:
        """
        Calculate the current uptime of the process in seconds.

        Returns:
            Optional[float]: Uptime in seconds if process has been started,
                           None if process has never been started
        """
        if self.start_time is None:
            return None
        return time.time() - self.start_time
