import ctypes
import datetime
from multiprocessing import Value


class bcolors:
    """
    Defines terminal color codes for different logging levels.
    """

    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


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

# Initialize a shared variable for the verbose flag
verbose = Value(ctypes.c_bool, False)


def set_verbose(value: bool) -> None:
    """
    Sets the verbose flag to the given value.

    Args:
        value (bool): The value to set the verbose flag to.
    """
    verbose.value = value


def log(msg: str, color: str = None) -> None:
    """
    Logs a message to the console with the specified color.

    Args:
        msg (str): The message to log.
        color (str, optional): The color name to use for the message. Defaults to
            None, which results in bold text.
    """

    # Use the specified color or default to bold
    using_col = color_map.get(color, bcolors.BOLD)
    # Format the current timestamp
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
    # Print the formatted log message
    print(f"{bcolors.BOLD}{timestamp}{bcolors.ENDC} - {using_col}{msg}{bcolors.ENDC}")


def log_failure(msg: str) -> None:
    """
    Logs a failure message in red.

    Args:
        msg (str): The failure message to log.
    """
    log(msg, "FAIL")


def log_debug(msg: str) -> None:
    """
    Logs a debug message in blue.

    Args:
        msg (str): The debug message to log.
    """
    if verbose:
        log(msg, "OKBLUE")
