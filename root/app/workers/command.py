"""
Command execution logic for FanFicFare integration.
"""

import sys
import shlex
import subprocess
from utils import ff_logging
from calibre_integration import calibre_info
from models import fanfic_info


def get_fanficfare_version() -> str:
    """Get the FanFicFare version by running python -m fanficfare.cli --version.

    Returns:
        str: FanFicFare version string or error message if unavailable.
    """
    try:
        # Use simple list args for safer execution
        cmd = [sys.executable, "-m", "fanficfare.cli", "--version"]
        version_output = execute_command(cmd)

        # Try to find version number pattern
        import re

        match = re.search(r"(\d+\.\d+\.\d+)", version_output)
        if match:
            return match.group(1)

        return version_output.strip()
    except Exception as e:
        ff_logging.log(f"Failed to get FanFicFare version: {e}", "WARNING")
        return f"Error: {e}"


def execute_command(command: list[str] | str, cwd: str | None = None) -> str:
    """
    Executes a shell command and returns its output.

    Args:
        command (list[str] | str): The command to execute. Should be a list of arguments.
        cwd (str, optional): The directory to execute the command in.

    Returns:
        str: The output of the command.

    Raises:
        subprocess.CalledProcessError: If the command fails.
    """
    debug_msg = f"Executing command: {command}"

    if isinstance(command, str):
        # Basic splitting, not robust for quoted args
        cmd_list = shlex.split(command)
    else:
        cmd_list = command

    if cwd:
        debug_msg += f" (in {cwd})"
    ff_logging.log_debug(debug_msg)

    # Use subprocess.run for safer and more robust execution
    # shell=False is safer and less error-prone with list args
    # capture_output=True captures stdout/stderr
    # text=True decodes output to string
    result = subprocess.run(
        cmd_list,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,  # Raises CalledProcessError on non-zero exit code
    )

    # helper for compatibility with old check_output return style (just stdout usually)
    # merged stdout/stderr was common with check_output(stderr=STDOUT)
    # here we join them if both exist, or just return stdout
    output = result.stdout
    if result.stderr:
        output += "\nSTDERR:\n" + result.stderr

    return output


def construct_fanficfare_command(
    cdb: calibre_info.CalibreInfo,
    fanfic: fanfic_info.FanficInfo,
    path_or_url: str,
) -> list[str]:
    """
    Construct the appropriate FanFicFare CLI command based on configuration and fanfic state.

    This function builds the FanFicFare command list dynamically based on the
    Calibre configuration's update method and the fanfiction's requested behavior.

    Args:
        cdb (calibre_info.CalibreInfo): Calibre configuration containing the update_method
                                       setting that controls how updates are performed.
        fanfic (fanfic_info.FanficInfo): Fanfiction info object which may contain
                                        request-specific behavior overrides (like "force").
        path_or_url (str): The target URL or filesystem path to update/download.

    Returns:
        list[str]: Complete FanFicFare command arguments ready for execution.
    """
    update_method = cdb.update_method

    # Base command structure
    # We use sys.executable to ensure we use the same python interpreter
    command = [sys.executable, "-m", "fanficfare.cli"]

    # Check if fanfiction specifically requests force behavior
    # But ONLY if the global update method isn't set to 'update_no_force'
    # 'update_no_force' overrides individual force requests to prevent
    # accidental overwrites in restricted modes
    is_force_behavior = (
        fanfic.behavior == "force" and update_method != "update_no_force"
    )

    # Determine flags based on update_method and behavior
    if update_method == "update_always" and not is_force_behavior:
        # Update existing ebook if it exists (-U in CLI)
        command.append("-U")
    elif (
        update_method == "force"
        or update_method == "force_override"
        or is_force_behavior
    ):
        # Force update and overwrite (-u --force)
        # This is destructive and ignores 'new chapters only' checks
        command.extend(["-u", "--force"])
    else:
        # Default behavior: Normal update check (-u)
        # This covers 'normal_update' and 'update_no_force' cases
        # Also serves as fallback for unknown update methods
        command.append("-u")

    # Add standard flags
    # --update-cover: Always try to update the cover image
    # --non-interactive: Prevent CLI from asking questions (stalling process)
    command.extend(["--update-cover", "--non-interactive"])

    # Add debug flag if verbose logging is enabled in the application
    if ff_logging.is_verbose():
        command.append("--debug")

    # Add the target path or URL as the final argument
    command.append(path_or_url)

    return command
