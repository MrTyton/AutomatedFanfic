from time import localtime, strftime


class bcolors:
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


# Logging Function
def log(msg, color=None) -> None:
    using_col = color_map.get(color, bcolors.BOLD)
    print(
        f'{bcolors.BOLD}{strftime("%Y-%m-%d %I:%M:%S %p", localtime())}{bcolors.ENDC} - {using_col}{msg}{bcolors.ENDC}'
    )


def log_failure(msg):
    log(msg, "FAIL")
