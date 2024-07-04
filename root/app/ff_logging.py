import datetime


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
