"""
FanFicFare Native Python API Wrapper

This module provides a native Python interface to FanFicFare functionality,
replacing subprocess CLI calls with direct Python API usage for improved
performance and better error handling.
            )
            ff_logging.log_debug(f"FanFicFare failed for {final_url}: {error_message}")
            return FanFicFareResult(
                success=False, error_message=error_message, output_text=output_textes FanFicFare's existing CLI dispatch infrastructure to provide the same
functionality as command-line execution but with direct Python function calls.
This approach leverages all existing CLI logic while avoiding subprocess overhead.
"""

import io
import os
import sys
import logging
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass
from typing import Optional, List

import fanficfare.cli as cli
import fanficfare.exceptions as exceptions
import fanficfare.adapters as adapters

import ff_logging
import calibre_info


class SuppressFanFicFareLogging:
    """Context manager to suppress FanFicFare logging output."""

    def __init__(self, level=logging.CRITICAL):
        self.level = level
        self.original_levels = {}

    def __enter__(self):
        # Suppress FanFicFare loggers
        fanficfare_loggers = [
            "fanficfare",
            "fanficfare.configurable",
            "fanficfare.adapters",
            "fanficfare.cli",
        ]

        for logger_name in fanficfare_loggers:
            logger = logging.getLogger(logger_name)
            self.original_levels[logger_name] = logger.level
            logger.setLevel(self.level)

        # Also suppress the root logger if it's being used
        root_logger = logging.getLogger()
        self.original_levels["root"] = root_logger.level
        if root_logger.level < self.level:
            root_logger.setLevel(self.level)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore original logging levels
        for logger_name, original_level in self.original_levels.items():
            if logger_name == "root":
                logging.getLogger().setLevel(original_level)
            else:
                logging.getLogger(logger_name).setLevel(original_level)


@dataclass
class FanFicFareResult:
    """
    Result object for FanFicFare operations.

    Attributes:
        success: Whether the operation completed successfully
        output_filename: Path to the generated story file (if successful)
        error_message: Error description (if failed)
        output_text: Raw output that would have been printed to stdout
        exception: Original exception object (if failed)
        chapter_count: Number of chapters in the story (if available)
    """

    success: bool
    output_filename: Optional[str] = None
    error_message: Optional[str] = None
    output_text: str = ""
    exception: Optional[Exception] = None
    chapter_count: Optional[int] = None


def create_configuration(url: str, work_dir: str, cdb: calibre_info.CalibreInfo):
    """
    Create FanFicFare configuration.

    Args:
        url: Story URL
        work_dir: Working directory with potential INI files
        cdb: Calibre database information

    Returns:
        FanFicFare configuration object
    """
    # Look for INI files in work directory and read their contents
    defaults_ini = None
    personal_ini = None

    defaults_path = os.path.join(work_dir, "defaults.ini")
    if os.path.exists(defaults_path):
        with open(defaults_path, "r") as f:
            defaults_ini = f.read()

    personal_path = os.path.join(work_dir, "personal.ini")
    if os.path.exists(personal_path):
        with open(personal_path, "r") as f:
            personal_ini = f.read()

    # Create basic options (this mimics what CLI would normally do)
    options = type(
        "Options",
        (),
        {
            "update": False,
            "updatealways": False,
            "force": False,
            "update_cover": True,
            "non_interactive": True,
            "format": "epub",  # Default format for stories
            "configfile": None,  # No additional config file
            "output_dir": None,  # Use default output behavior
            "normalize": False,  # Don't normalize
            "zip": False,  # Don't zip output
            "keep": False,  # Don't keep temp files
            "list": False,  # Not listing mode
            "options": None,  # No additional options
        },
    )()

    with SuppressFanFicFareLogging():
        return cli.get_configuration(url, defaults_ini, personal_ini, options)


def build_cli_args(
    url: str,
    work_dir: str,
    cdb: calibre_info.CalibreInfo,
    update_mode: str = "update",
    force: bool = False,
) -> List[str]:
    """
    Build command line arguments for FanFicFare CLI dispatch function.

    Args:
        url: Story URL to download
        work_dir: Working directory for output files
        cdb: Calibre database information
        update_mode: Update method (update, update_always, force, update_no_force)
        force: Whether to force update (overrides update_mode if True)

    Returns:
        List of command line arguments
    """
    args = []

    # Add update flags based on mode and force parameter
    if force or update_mode == "force":
        args.append("--force")
    elif update_mode == "update_always":
        args.append("-U")
    elif update_mode == "update":
        args.append("-u")
    elif update_mode == "update_no_force":
        args.append("-u")
    # No flag for download-only mode

    # Add the URL as the argument
    args.append(url)

    # Add other standard options
    args.extend(["--update-cover", "--non-interactive"])

    return args


def execute_fanficfare(
    url_or_path: Optional[str] = None,
    work_dir: Optional[str] = None,
    cdb: Optional[calibre_info.CalibreInfo] = None,
    update_mode: str = "update",
    force: bool = False,
    update_always: bool = False,
    update_cover: bool = True,
    # Legacy positional parameter support
    url: Optional[str] = None,
) -> FanFicFareResult:
    """
    Execute FanFicFare using the CLI main function directly.

    This function replaces subprocess CLI calls with direct Python API usage
    for improved performance. It uses FanFicFare's main() function with
    command line arguments passed directly.

    Args:
        url_or_path: Story URL or path to download (new style)
        work_dir: Working directory for output files
        cdb: Calibre database information
        update_mode: Update method (update, update_always, force, update_no_force)
        force: Whether to force update (overrides update_mode if True)
        update_always: Whether to use update_always mode
        update_cover: Whether to update cover (not currently used)
        url: Legacy positional parameter for story URL

    Returns:
        FanFicFareResult object with operation results
    """
    # Handle both new keyword style and legacy positional style
    final_url = url_or_path if url_or_path is not None else url
    if final_url is None:
        raise ValueError("Either url_or_path or url must be provided")
    if work_dir is None:
        raise ValueError("work_dir must be provided")
    if cdb is None:
        raise ValueError("cdb must be provided")

    # Handle update_always parameter in update_mode
    if update_always:
        update_mode = "update_always"

    ff_logging.log_debug(f"Executing FanFicFare for URL: {final_url}")
    ff_logging.log_debug(f"Work directory: {work_dir}")
    ff_logging.log_debug(
        f"Update mode: {update_mode}, Force: {force}, Update always: {update_always}"
    )

    # Ensure work directory exists
    os.makedirs(work_dir, exist_ok=True)

    # Build CLI arguments (without 'fanficfare' program name)
    cli_args = build_cli_args(final_url, work_dir, cdb, update_mode, force)
    ff_logging.log_debug(f"CLI args: {cli_args}")

    # Change to work directory before executing (like original implementation)
    original_cwd = os.getcwd()

    try:
        os.chdir(work_dir)

        # Capture stdout and stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        # Execute FanFicFare main function with output capture and logging suppression
        ff_logging.log_debug("About to call cli.main() with args: " + str(cli_args))
        with redirect_stdout(stdout_capture), redirect_stderr(
            stderr_capture
        ), SuppressFanFicFareLogging():
            exit_code = cli.main(argv=cli_args)
        ff_logging.log_debug(f"cli.main() returned exit code: {exit_code}")

        # Get captured output
        output_text = stdout_capture.getvalue()
        error_text = stderr_capture.getvalue()
        print("exit code: ", exit_code)
        print("output_text: ", output_text)
        print("error_text: ", error_text)

        # Determine output filename from work directory
        output_filename = None
        if os.path.exists(work_dir):
            epub_files = [f for f in os.listdir(work_dir) if f.endswith(".epub")]
            if epub_files:
                # Use the most recently created file
                epub_files.sort(
                    key=lambda f: os.path.getctime(os.path.join(work_dir, f)),
                    reverse=True,
                )
                output_filename = os.path.join(work_dir, epub_files[0])

        # Check for success based on exit code
        success = (
            exit_code == 0 or exit_code is None
        )  # main() might return None on success

        if success:
            ff_logging.log_debug(f"FanFicFare completed successfully for {final_url}")
            return FanFicFareResult(
                success=True, output_filename=output_filename, output_text=output_text
            )
        else:
            error_message = (
                error_text if error_text else f"CLI returned exit code {exit_code}"
            )
            ff_logging.log_failure(f"FanFicFare failed for {url}: {error_message}")
            return FanFicFareResult(
                success=False, error_message=error_message, output_text=output_text
            )

    except exceptions.InvalidStoryURL as e:
        error_msg = f"Invalid story URL: {e}"
        ff_logging.log_failure(error_msg)
        return FanFicFareResult(success=False, error_message=error_msg, exception=e)

    except exceptions.StoryDoesNotExist as e:
        error_msg = f"Story does not exist: {e}"
        ff_logging.log_failure(error_msg)
        return FanFicFareResult(success=False, error_message=error_msg, exception=e)

    except exceptions.AccessDenied as e:
        error_msg = f"Access denied: {e}"
        ff_logging.log_failure(error_msg)
        return FanFicFareResult(success=False, error_message=error_msg, exception=e)

    except Exception as e:
        error_msg = f"Unexpected error during FanFicFare execution: {e}"
        ff_logging.log_failure(error_msg)
        return FanFicFareResult(success=False, error_message=error_msg, exception=e)

    finally:
        # Always restore original working directory
        os.chdir(original_cwd)


def get_update_mode_params(
    update_method: str, force_requested: bool
) -> tuple[str, bool, bool]:
    """
    Convert update method configuration to FanFicFare parameters.

    Args:
        update_method: Update method from config (update, update_always, force, update_no_force)
        force_requested: Whether force was explicitly requested

    Returns:
        Tuple of (update_mode, force, update_always) parameters
    """
    if update_method == "update_no_force":
        # Special case: ignore all force requests
        return ("update", False, False)
    elif force_requested or update_method == "force":
        # Use force when explicitly requested or configured
        return ("force", True, False)
    elif update_method == "update_always":
        # Always perform full refresh
        return ("update", False, True)
    else:  # Default to 'update' behavior
        # Normal update - only download new chapters
        return ("update", False, False)
