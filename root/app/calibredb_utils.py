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


def get_calibre_version() -> str:
    """Get the Calibre version by running calibredb --version.

    Returns:
        str: Calibre version string or error message if unavailable.
    """
    try:
        from subprocess import check_output

        output = check_output(
            ["calibredb", "--version"], stderr=DEVNULL, timeout=10
        ).decode("utf-8")

        # Output format is typically "calibredb.exe (calibre X.X)" or "calibredb (calibre X.X.X)"
        output = output.strip()
        # Extract just the version number from the output
        if "calibre" in output:
            # Find version pattern like "X.X" or "X.X.X" inside parentheses
            import re

            version_match = re.search(r"calibre (\d+\.\d+(?:\.\d+)?)", output)
            if version_match:
                return version_match.group(1)
            return output  # Return full output if pattern not found
        return output

    except Exception as e:
        return f"Error: {e}"


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


def find_epub_in_directory(location: str) -> Optional[str]:
    """Find the first EPUB file in the specified directory.

    Args:
        location (str): Directory path to search for EPUB files.

    Returns:
        Optional[str]: Full path to the first EPUB file found, or None if no EPUB files exist.
    """
    epub_files = system_utils.get_files(
        location, file_extension="epub", return_full_path=True
    )
    return epub_files[0] if epub_files else None


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
    # Search for EPUB file in the specified location
    file_to_add = find_epub_in_directory(location)

    # Check if any EPUB file was found
    if not file_to_add:
        ff_logging.log_failure("No EPUB files found in the specified location.")
        return

    # Extract and update the fanfic title from the filename for proper cataloging
    fanfic_info.title = regex_parsing.extract_filename(file_to_add)

    # Log the addition attempt with color coding for visibility
    ff_logging.log(f"\t({fanfic_info.site}) Adding {file_to_add} to Calibre", "OKGREEN")

    # Construct the add command with the -d flag for duplicate detection
    # Note: calibre_info parameters are added by call_calibre_db
    command = f'add -d "{file_to_add}"'

    # Execute the add command (no fanfic_info needed as we're adding, not updating)
    call_calibre_db(command, calibre_info, fanfic_info=None)


def get_metadata(
    fanfic_info: fanfic_info.FanficInfo, calibre_info: calibre_info.CalibreInfo
) -> dict:
    """Retrieves all metadata for a story from the Calibre database.

    Executes calibredb list command to get comprehensive metadata for the story,
    including both standard fields and custom columns. This data can be used to
    preserve metadata during story updates.

    Args:
        fanfic_info (fanfic_info.FanficInfo): Object containing story's calibre_id.
        calibre_info (calibre_info.CalibreInfo): Calibre library configuration.

    Returns:
        dict: Dictionary containing all metadata fields, or empty dict on failure.
            Keys include standard fields (title, authors, tags, etc.) and custom
            columns (prefixed with #).
    """
    from subprocess import check_output, CalledProcessError
    import json

    if not fanfic_info.calibre_id:
        ff_logging.log_failure("\tCannot get metadata: story has no calibre_id")
        return {}

    try:
        with calibre_info.lock:
            # Use --for-machine flag to get JSON output with all metadata
            output = check_output(
                f'calibredb list --for-machine --fields=all {calibre_info} --search="id:{fanfic_info.calibre_id}"',
                shell=True,
                stderr=PIPE,
                stdin=PIPE,
            ).decode("utf-8")

        # Parse JSON output
        metadata_list = json.loads(output)
        if metadata_list and len(metadata_list) > 0:
            metadata = metadata_list[0]
            ff_logging.log_debug(
                f"\t({fanfic_info.site}) Retrieved metadata for ID {fanfic_info.calibre_id}: "
                f"{len(metadata)} fields"
            )
            return metadata
        else:
            ff_logging.log_failure(
                f"\tNo metadata found for ID {fanfic_info.calibre_id}"
            )
            return {}

    except (CalledProcessError, json.JSONDecodeError, Exception) as e:
        ff_logging.log_failure(
            f"\tFailed to retrieve metadata for ID {fanfic_info.calibre_id}: {e}"
        )
        return {}


def set_metadata_fields(
    fanfic_info: fanfic_info.FanficInfo,
    calibre_info: calibre_info.CalibreInfo,
    metadata: dict,
    fields_to_restore: Optional[list] = None,
) -> None:
    """Restores specific metadata fields to a story in the Calibre database.

    Uses calibredb set_custom to restore previously saved metadata fields.
    Only restores fields that start with '#' (custom columns) as standard fields
    are typically embedded in the EPUB file itself.

    Args:
        fanfic_info (fanfic_info.FanficInfo): Object containing story's calibre_id.
        calibre_info (calibre_info.CalibreInfo): Calibre library configuration.
        metadata (dict): Dictionary of metadata fields to restore.
        fields_to_restore (list, optional): List of specific field names to restore.
            If None, restores all fields starting with '#'.

    Note:
        Standard fields like title, authors are typically embedded in the EPUB.
        This function focuses on custom columns which are database-only fields.
    """
    from subprocess import CalledProcessError

    if not fanfic_info.calibre_id:
        ff_logging.log_failure("\tCannot set metadata: story has no calibre_id")
        return

    if not metadata:
        ff_logging.log_debug("\tNo metadata to restore")
        return

    # Default to restoring fields that start with '#' (custom columns)
    if fields_to_restore is None:
        fields_to_restore = [k for k in metadata.keys() if k.startswith("#")]

    if not fields_to_restore:
        ff_logging.log_debug("\tNo restorable fields found")
        return

    ff_logging.log_debug(
        f"\t({fanfic_info.site}) Attempting to restore {len(fields_to_restore)} metadata fields"
    )

    # Restore each field individually
    restored_count = 0
    for field_name in fields_to_restore:
        if field_name not in metadata:
            continue

        field_value = metadata[field_name]
        if field_value is None or field_value == "":
            continue  # Skip empty values

        try:
            # Use set_custom to set custom column values
            # Format: calibredb set_custom <column> <value>
            # Extract column name (remove # prefix)
            column_name = field_name.lstrip("#")

            # Convert value to string, handling lists/arrays
            if isinstance(field_value, list):
                # For list fields, join with commas
                value_str = ",".join(str(v) for v in field_value)
            else:
                value_str = str(field_value)

            # Use call_calibre_db which properly handles library path and locking
            command = f'set_custom "{column_name}" "{value_str}"'
            call_calibre_db(command, calibre_info, fanfic_info)

            restored_count += 1
            ff_logging.log_debug(f"\t  Restored {field_name} = {value_str[:50]}...")

        except CalledProcessError as e:
            ff_logging.log_failure(f"\t  Failed to restore field {field_name}: {e}")
        except Exception as e:
            ff_logging.log_failure(f"\t  Unexpected error restoring {field_name}: {e}")

    ff_logging.log_debug(
        f"\t({fanfic_info.site}) Successfully restored {restored_count}/{len(fields_to_restore)} metadata fields"
    )


def log_metadata_comparison(
    fanfic_info: fanfic_info.FanficInfo,
    old_metadata: dict,
    new_metadata: dict,
) -> None:
    """Logs a comparison of metadata before and after an update operation.

    Provides detailed logging of metadata changes, showing which fields were
    changed, lost, or added. Preserved fields are not logged to reduce noise.
    All output is debug-only to avoid cluttering normal logs.

    Args:
        fanfic_info (fanfic_info.FanficInfo): Story information for logging context.
        old_metadata (dict): Metadata before the update operation.
        new_metadata (dict): Metadata after the update operation.
    """
    if not old_metadata and not new_metadata:
        ff_logging.log_debug("\tNo metadata to compare")
        return

    ff_logging.log_debug(f"\t({fanfic_info.site}) Metadata Comparison Report")

    # Find changed, lost, and new fields
    changed = []
    lost = []

    for field_name, old_value in old_metadata.items():
        if field_name in new_metadata:
            new_value = new_metadata[field_name]
            if old_value != new_value:
                changed.append((field_name, str(old_value)[:50], str(new_value)[:50]))
        else:
            lost.append(field_name)

    # Check new fields that weren't in old metadata
    new_fields = [k for k in new_metadata.keys() if k not in old_metadata]

    # Log changed fields
    if changed:
        ff_logging.log_debug(f"\t  Fields Changed: {len(changed)}")
        for field, old_val, new_val in changed:
            ff_logging.log_debug(f"\t    ~ {field}: '{old_val}' → '{new_val}'")

    # Log lost fields
    if lost:
        ff_logging.log_debug(f"\t  Fields Lost: {len(lost)}")
        for field in lost:
            ff_logging.log_debug(f"\t    ✗ {field}")

    # Log new fields
    if new_fields:
        ff_logging.log_debug(f"\t  New Fields Added: {len(new_fields)}")
        for field in new_fields:
            ff_logging.log_debug(f"\t    + {field}")

    # If nothing changed, say so
    if not changed and not lost and not new_fields:
        ff_logging.log_debug("\t  No metadata changes detected")


def add_format_to_existing_story(
    location: str,
    fanfic_info: fanfic_info.FanficInfo,
    calibre_info: calibre_info.CalibreInfo,
) -> bool:
    """Adds or replaces the EPUB format for an existing story in Calibre.

    Uses calibredb add_format to update just the file without touching metadata.
    This preserves all existing metadata and custom columns.

    Args:
        location (str): Directory containing the new EPUB file.
        fanfic_info (fanfic_info.FanficInfo): Story information with calibre_id.
        calibre_info (calibre_info.CalibreInfo): Calibre library configuration.

    Returns:
        bool: True if successful, False otherwise.
    """
    if not fanfic_info.calibre_id:
        ff_logging.log_failure("\tCannot add format: story has no calibre_id")
        return False

    # Find EPUB file in location
    file_to_add = find_epub_in_directory(location)

    if not file_to_add:
        ff_logging.log_failure("No EPUB files found in the specified location.")
        return False

    ff_logging.log(
        f"\t({fanfic_info.site}) Replacing EPUB format for ID {fanfic_info.calibre_id}",
        "OKGREEN",
    )

    # Use add_format with --replace to update the file
    # Note: calibre_id and calibre_info parameters are added by call_calibre_db
    command = f'add_format --replace "{file_to_add}"'

    try:
        call_calibre_db(command, calibre_info, fanfic_info)
        ff_logging.log(
            f"\t({fanfic_info.site}) Successfully replaced EPUB format",
            "OKGREEN",
        )
        return True
    except Exception as e:
        ff_logging.log_failure(
            f"\t({fanfic_info.site}) Failed to replace EPUB format: {e}"
        )
        return False
