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


class bcolors:
    """Terminal ANSI color codes for colored console output.

    Provides standardized color constants for different logging levels and text
    formatting options. These codes work with most modern terminals that support
    ANSI escape sequences for colored text display.

    The class serves as a namespace for color constants used throughout the
    logging system to provide visual distinction between different log message
    types and severity levels.

    Attributes:
        HEADER (str): Purple color code for header messages.
        OKBLUE (str): Blue color code for informational messages.
        OKGREEN (str): Green color code for success messages.
        WARNING (str): Yellow color code for warning messages.
        FAIL (str): Red color code for error/failure messages.
        ENDC (str): Reset code to end color formatting.
        BOLD (str): Bold text formatting code.
        UNDERLINE (str): Underline text formatting code.

    Example:
        >>> print(f"{bcolors.FAIL}Error message{bcolors.ENDC}")
        >>> print(f"{bcolors.OKGREEN}Success message{bcolors.ENDC}")
    """

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
    """Sets the global verbose logging flag for debug output control.

    Updates the shared multiprocessing-safe verbose flag that controls whether
    debug messages are displayed. This setting affects all processes in the
    multiprocessing application and persists until explicitly changed.

    Args:
        value (bool): True to enable verbose debug logging, False to disable.
                     When True, log_debug() calls will output messages.
                     When False, log_debug() calls are silently ignored.

    Example:
        >>> set_verbose(True)   # Enable debug logging
        >>> set_verbose(False)  # Disable debug logging
    """
    # Update the shared multiprocessing value atomically
    verbose.value = value


def log(msg: str, color: str = "") -> None:
    """Logs a timestamped message to console with optional color formatting.

    Core logging function that outputs messages with standardized timestamp
    formatting and optional ANSI color codes. All messages are prefixed with
    a bold timestamp in "YYYY-MM-DD HH:MM:SS AM/PM" format followed by the
    colored message content.

    Args:
        msg (str): The message content to log to console output.
        color (str, optional): Color name from color_map for message formatting.
                              Valid values: "HEADER", "OKBLUE", "OKGREEN",
                              "WARNING", "FAIL", "BOLD", "UNDERLINE".
                              Defaults to "" which results in bold text.

    Note:
        This function directly outputs to stdout and is thread-safe for
        multiprocessing environments. Invalid color names default to bold
        formatting without raising exceptions.

    Example:
        >>> log("Application started")  # Bold text
        >>> log("Success!", "OKGREEN")  # Green text
        >>> log("Warning!", "WARNING")  # Yellow text
    """
    # Map color name to ANSI code, defaulting to bold for unknown colors
    using_col = color_map.get(color, bcolors.BOLD)
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
        # Use the core log function with OKBLUE color for blue debug formatting
        log(msg, "OKBLUE")
