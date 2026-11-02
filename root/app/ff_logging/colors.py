"""ANSI terminal colors and palette helpers for ff_logging."""


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
color_map: dict[str, str] = {
    "HEADER": bcolors.HEADER,
    "OKBLUE": bcolors.OKBLUE,
    "OKGREEN": bcolors.OKGREEN,
    "WARNING": bcolors.WARNING,
    "FAIL": bcolors.FAIL,
    "ENDC": bcolors.ENDC,
    "BOLD": bcolors.BOLD,
    "UNDERLINE": bcolors.UNDERLINE,
}

# Curated list of 35 high-visibility ANSI 256 colors
# manually interleaved to ensure high contrast between sequential workers.
SAFE_WORKER_COLORS: list[int] = [
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


def get_color_for_worker(index: int) -> str:
    """Generates a unique ANSI 256-color code for a worker index.

    Selects from a curated list of high-contrast colors suitable for dark backgrounds,
    ensuring readability and consistency across worker instances.
    """
    color_code = SAFE_WORKER_COLORS[index % len(SAFE_WORKER_COLORS)]
    return f"\033[38;5;{color_code}m"
