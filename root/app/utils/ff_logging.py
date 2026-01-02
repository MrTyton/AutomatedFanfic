"""Custom logging module for AutomatedFanfic application.

This module provides colored console logging functionality with multiprocessing support
for the AutomatedFanfic application. It includes terminal color code definitions,
timestamp formatting, and both standard and debug logging capabilities with shared
state management across processes.

Key Features:
    - ANSI color code support for different log levels
    - Thread-safe verbose logging control via multiprocessing.Value
    - Timestamp formatting for all log messages
    - Specialized logging functions for failures and debug output
    - Multiprocessing-compatible shared state management

Classes:
    bcolors: Terminal color code constants for different logging levels

Functions:
    set_verbose: Controls debug logging output globally
    log: Core logging function with color and timestamp support
    log_failure: Convenience function for error message logging
    log_debug: Conditional debug logging based on verbose flag

Example:
    >>> import ff_logging
    >>> ff_logging.set_verbose(True)
    >>> ff_logging.log("Application started")
    >>> ff_logging.log_failure("Connection failed")
    >>> ff_logging.log_debug("Debug information")
"""

import ctypes
import datetime
from multiprocessing import Value
import threading

# Thread-local storage for worker-specific logging context
_thread_local = threading.local()


class bcolors:
    """Terminal ANSI color codes for colored console output."""

    HEADER = "\033[95m"  # Purple color for headers
    OKBLUE = "\033[94m"  # Blue color for informational messages
    OKGREEN = "\033[92m"  # Green color for success messages
    WARNING = "\033[93m"  # Yellow color for warnings
    FAIL = "\033[91m"  # Red color for errors and failures
    ENDC = "\033[0m"  # Reset/end color formatting
    BOLD = "\033[1m"  # Bold text formatting
    UNDERLINE = "\033[4m"  # Underline text formatting


# Color name to ANSI code mapping for dynamic color selection
color_map = {
    "HEADER": bcolors.HEADER,
    "OKBLUE": bcolors.OKBLUE,
    "OKGREEN": bcolors.OKGREEN,
    "WARNING": bcolors.WARNING,
    "FAIL": bcolors.FAIL,
    "ENDC": bcolors.ENDC,
    "BOLD": bcolors.BOLD,
    "UNDERLINE": bcolors.UNDERLINE,
}

# Multiprocessing-safe shared variable for global verbose flag control
verbose = Value(ctypes.c_bool, False)


def set_verbose(value: bool) -> None:
    """Sets the global verbose logging flag for debug output control."""
    verbose.value = value


def is_verbose() -> bool:
    """Returns the current state of the global verbose logging flag."""
    return bool(verbose.value)


def set_thread_color(ansi_code: str) -> None:
    """Sets the color for the current thread's log output.

    Args:
        ansi_code: The ANSI escape sequence to use as the default color
                  for logs from this thread.
    """
    _thread_local.color = ansi_code


def get_color_for_worker(index: int) -> str:
    """Generates a unique ANSI 256-color code for a worker index.

    Selects from a curated list of high-contrast colors suitable for dark backgrounds,
    ensuring readability and consistency across worker instances.
    """
    # Curated list of 35 high-visibility ANSI 256 colors
    # selected for readability on dark backgrounds.
    # Includes: Blues, Cyans, Greens, Pinks, Purples, Oranges, Yellows
    # Curated list of 35 high-visibility ANSI 256 colors
    # manually interleaved to ensure high contrast between sequential workers.
    safe_colors = [
        210,  # Light Coral
        209,  # Salmon
        196,  # Red (Bright)
        39,  # Deep Sky Blue
        153,  # Light Cyan
        46,  # Green (Bright)
        201,  # Magenta
        51,  # Cyan
        118,  # Chartreuse
        226,  # Yellow
        141,  # Lavender
        49,  # Medium Spring Green
        75,  # Steel Blue
        220,  # Gold
        155,  # Pale Green
        213,  # Orchid
        81,  # Sky Blue
        99,  # Slate Blue
        219,  # Plum
        87,  # Dark Slate Gray (actually light cyan-ish)
        190,  # Yellow Green
        159,  # Pale Cyan
        207,  # Medium Orchid
        154,  # Green Yellow
        45,  # Turquoise
        86,  # Aquamarine
        123,  # Dark Sky Blue
        147,  # Light Steel Blue
        117,  # Light Blue
        85,  # Dark Sea Green
        208,  # Dark Orange
        192,  # Dark Olive Green (Light)
        120,  # Light Green
        212,  # Pink
        33,  # Dodger Blue
    ]

    # Cycle through the safe color list based on worker index
    color_code = safe_colors[index % len(safe_colors)]

    return f"\033[38;5;{color_code}m"


def log(msg: str, color: str = "") -> None:
    """Logs a timestamped message to console with optional color formatting."""

    # Determine color:
    # 1. Explicit argument mapped name (e.g. "FAIL")
    # 2. Explicit argument raw ANSI code (if not in map)
    # 3. Thread-local default color
    # 4. Default BOLD

    using_col = bcolors.BOLD

    if color:
        using_col = color_map.get(color, color)
    elif hasattr(_thread_local, "color"):
        using_col = _thread_local.color

    # Generate current timestamp in standardized format
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
    # Output formatted message with timestamp and color codes
    print(f"{bcolors.BOLD}{timestamp}{bcolors.ENDC} - {using_col}{msg}{bcolors.ENDC}")


def log_failure(msg: str) -> None:
    """Logs an error or failure message in red color.

    Convenience function for logging error conditions, failures, and critical
    issues. Automatically applies red color formatting to make error messages
    visually distinct from other log output types.

    Args:
        msg (str): The failure or error message to log. Should describe the
                  specific error condition, failure reason, or critical issue
                  that occurred during application execution.

    Example:
        >>> log_failure("Database connection failed")
        >>> log_failure("Configuration file not found")
        >>> log_failure("Process terminated unexpectedly")
    """
    # Use the core log function with FAIL color for red error formatting
    log(msg, "FAIL")


def log_debug(msg: str) -> None:
    """Logs a debug message in blue color when verbose mode is enabled.

    Conditional logging function that only outputs debug messages when the
    global verbose flag is True. This allows for detailed diagnostic output
    during development and troubleshooting while keeping production logs clean.
    Debug messages are formatted in blue color for visual distinction.

    The verbose flag is controlled globally via set_verbose() and affects all
    processes in the multiprocessing application through shared state.

    Args:
        msg (str): The debug message to log. Should contain detailed diagnostic
                  information, variable states, or execution flow details useful
                  for development and troubleshooting purposes.

    Note:
        Messages are silently ignored when verbose mode is disabled (False).
        This function checks the shared multiprocessing verbose flag atomically.

    Example:
        >>> set_verbose(True)
        >>> log_debug("Processing URL: https://example.com/story")  # Outputs
        >>> set_verbose(False)
        >>> log_debug("This will not be displayed")  # Silent
    """
    # Only log debug messages when verbose mode is globally enabled
    if verbose.value:
        # Use the core log function without explicit color to allow thread-local color
        log(msg)
