"""Calibre database interaction utilities for fanfiction management.

This module provides utility functions for interacting with Calibre e-book databases
through the calibredb command-line interface. It handles story addition, export,
metadata queries, and library management operations with comprehensive error handling
and multiprocessing-safe locking mechanisms.

Key Features:
    - Thread-safe calibredb command execution with multiprocessing locks
    - Story addition and update operations with automatic retry logic
    - File export functionality for story updates and processing
    - Metadata validation and error detection via regex parsing
    - Integration with FanficInfo and CalibreInfo configuration classes
    - Comprehensive logging for all database operations

Functions:
    call_calibre_db: Core calibredb command execution with locking
    add_fanfic: Add new fanfiction stories to Calibre library
    export_story: Export existing stories for update processing

This module serves as the primary interface between the AutomatedFanfic application
and Calibre database operations, ensuring data consistency and proper error handling
across all multiprocessing workflows.
"""

import fanfic_info
import calibre_info
import ff_logging
import regex_parsing
import system_utils
from subprocess import call, PIPE, DEVNULL
from typing import Optional


def call_calibre_db(
    command: str,
    calibre_info: calibre_info.CalibreInfo,
    fanfic_info: Optional[fanfic_info.FanficInfo] = None,
):
    """Executes a calibredb command with proper locking and error handling.

    This function provides a safe wrapper for executing calibredb commands by
    acquiring a lock to prevent concurrent database modifications and handling
    any exceptions that may occur during execution. It constructs the full
    command string and executes it with output suppression for clean operation.

    Args:
        command (str): The calibredb command to execute (e.g., "add", "remove",
            "export"). Should not include "calibredb" prefix as it's added automatically.
        calibre_info (calibre_info.CalibreInfo): Object containing Calibre library
            configuration including path, credentials, and other settings.
        fanfic_info (Optional[fanfic_info.FanficInfo], optional): Object containing
            fanfiction metadata including calibre_id. Defaults to None for commands
            that don't require specific story identification.

    Note:
        This function suppresses stdout and stderr to prevent console noise during
        batch operations. All output is redirected to DEVNULL.

    Raises:
        The function catches all exceptions and logs them rather than re-raising,
        ensuring that individual command failures don't crash the entire process.
    """
    # Log the full command for debugging purposes
    ff_logging.log_debug(
        f'\tCalling calibredb with command: \t"{command} {fanfic_info.calibre_id if fanfic_info else ""} {calibre_info}"'
    )
    try:
        # Lock the calibre database to prevent concurrent modifications
        with calibre_info.lock:
            # Construct and execute the full calibredb command
            # Output is suppressed to avoid console noise during batch operations
            call(
                f"calibredb {command} {fanfic_info.calibre_id if fanfic_info else ''} {calibre_info}",
                shell=True,
                stdin=PIPE,
                stdout=DEVNULL,
                stderr=DEVNULL,
            )
    except Exception as e:
        # Log any failures with the specific command that failed
        ff_logging.log_failure(
            f'\t"{command} {fanfic_info.calibre_id if fanfic_info else ""} {calibre_info}" failed: {e}'
        )


def export_story(
    *,
    fanfic_info: fanfic_info.FanficInfo,
    location: str,
    calibre_info: calibre_info.CalibreInfo,
) -> None:
    """Exports a story from the Calibre library to a specified directory.

    This function extracts a story from the Calibre library and saves it to the
    specified location. The export is configured to exclude cover images and OPF
    metadata files, placing all exported files in a single directory structure
    for simplified file management.

    Args:
        fanfic_info (fanfic_info.FanficInfo): Object containing the story's metadata
            and Calibre database ID needed to identify which story to export.
        location (str): Target directory path where the exported story files should
            be saved. The directory will be created if it doesn't exist.
        calibre_info (calibre_info.CalibreInfo): Object containing Calibre library
            configuration including database path and authentication credentials.

    Note:
        The export excludes cover images (--dont-save-cover) and OPF metadata files
        (--dont-write-opf) to reduce file size and complexity. All files are placed
        in a single directory (--single-dir) rather than maintaining Calibre's
        nested directory structure.
    """
    # Construct the export command with flags to exclude unnecessary files
    # and use a simplified directory structure
    command = (
        f'export --dont-save-cover --dont-write-opf --single-dir --to-dir "{location}"'
    )

    # Execute the export command using the shared calibredb wrapper
    call_calibre_db(command, calibre_info, fanfic_info)


def remove_story(
    fanfic_info: fanfic_info.FanficInfo, calibre_info: calibre_info.CalibreInfo
) -> None:
    """Removes a story from the Calibre library database.

    This function permanently deletes a story from the Calibre library using the
    story's unique Calibre database ID. The removal is irreversible and will
    delete both the story file and all associated metadata from the library.

    Args:
        fanfic_info (fanfic_info.FanficInfo): Object containing the story's metadata
            including the calibre_id field that uniquely identifies the story in
            the Calibre database.
        calibre_info (calibre_info.CalibreInfo): Object containing Calibre library
            configuration including database path and authentication credentials
            needed to access the library.

    Warning:
        This operation is permanent and cannot be undone. The story file and all
        associated metadata will be completely removed from the Calibre library.
    """
    # Execute the remove command using the calibre_id to identify the target story
    call_calibre_db("remove", calibre_info, fanfic_info)


def add_story(
    *,
    location: str,
    fanfic_info: fanfic_info.FanficInfo,
    calibre_info: calibre_info.CalibreInfo,
) -> None:
    """Adds a story to the Calibre library from a specified directory.

    This function searches for EPUB files in the given location and adds the first
    one found to the Calibre library. It automatically extracts the story title
    from the filename and logs the addition process. If no EPUB files are found,
    the operation is aborted with an appropriate error message.

    Args:
        location (str): Directory path containing the story file(s) to be added.
            The function will search this directory for EPUB files.
        fanfic_info (fanfic_info.FanficInfo): Object containing story metadata that
            will be updated with the extracted title from the filename.
        calibre_info (calibre_info.CalibreInfo): Object containing Calibre library
            configuration including database path and authentication credentials.

    Note:
        Only the first EPUB file found in the directory will be added. If multiple
        EPUB files exist, subsequent files will be ignored. The story title in
        fanfic_info will be updated based on the filename of the added EPUB.

    Raises:
        The function handles the case where no EPUB files are found by logging
        an error and returning early, but does not raise exceptions.
    """
    # Search for EPUB files in the specified location
    epub_files = system_utils.get_files(
        location, file_extension="epub", return_full_path=True
    )

    # Check if any EPUB files were found
    if not epub_files:
        ff_logging.log_failure("No EPUB files found in the specified location.")
        return

    # Use the first EPUB file found for addition
    file_to_add = epub_files[0]

    # Extract and update the fanfic title from the filename for proper cataloging
    fanfic_info.title = regex_parsing.extract_filename(file_to_add)

    # Log the addition attempt with color coding for visibility
    ff_logging.log(f"\t({fanfic_info.site}) Adding {file_to_add} to Calibre", "OKGREEN")

    # Construct the add command with the -d flag for duplicate detection
    command = f'add -d {calibre_info} "{file_to_add}"'

    # Execute the add command (no fanfic_info needed as we're adding, not updating)
    call_calibre_db(command, calibre_info, fanfic_info=None)
