"""Calibre database interaction utilities for fanfiction management.

This module provides a client class for interacting with Calibre e-book databases
through the calibredb command-line interface. It handles story addition, export,
metadata queries, and library management operations with comprehensive error handling
and multiprocessing-safe locking mechanisms.
"""

import json
import re
import shlex
from subprocess import (
    check_output,
    PIPE,
    DEVNULL,
    CalledProcessError,
    TimeoutExpired,
    run,
)
from typing import Any

from . import calibre_info
from models import fanfic_info
from utils import ff_logging
from parsers import regex_parsing
from utils import system_utils


class CalibreCommandError(OSError):
    """Raised when a calibredb subprocess fails with captured output."""


class CalibreDBClient:
    """Client for interacting with the Calibre database.

    Encapsulates all interactions with the calibredb CLI, including authentication,
    library path management, and concurrency locking.
    """

    def __init__(self, cdb_info: calibre_info.CalibreInfo):
        """Initialize the CalibreDB client.

        Args:
            cdb_info: Configuration object containing library path, credentials, etc.
        """
        self.cdb_info = cdb_info

    @staticmethod
    def get_calibre_version() -> str:
        """Get the Calibre version by running calibredb --version.

        Returns:
            str: Calibre version string or error message if unavailable.
        """
        try:
            output = check_output(
                ["calibredb", "--version"], stderr=DEVNULL, timeout=10
            ).decode("utf-8")

            # Output format is typically "calibredb.exe (calibre X.X)" or "calibredb (calibre X.X.X)"
            output = output.strip()
            # Extract just the version number from the output
            if "calibre" in output:
                # Find version pattern like "X.X" or "X.X.X" inside parentheses
                version_match = re.search(r"calibre (\d+\.\d+(?:\.\d+)?)", output)
                if version_match:
                    return version_match.group(1)
                return output  # Return full output if pattern not found
            return output

        except (CalledProcessError, OSError, TimeoutExpired) as e:
            return f"Error: {e}"

    def _build_calibredb_command(self, command_args: str | list[str]) -> list[str]:
        """Build a safe calibredb argument list with configured library/auth args."""
        if isinstance(command_args, str):
            cmd = ["calibredb", *shlex.split(command_args)]
        else:
            cmd = ["calibredb", *command_args]

        # CalibreInfo currently exposes CLI args via __str__.
        return [*cmd, *shlex.split(str(self.cdb_info))]

    @staticmethod
    def _format_command_error(
        full_command: list[str],
        exc: Exception,
    ) -> str:
        """Build a readable calibredb error including captured stdout/stderr."""
        command_text = shlex.join(full_command)
        details = [f"Command failed: {command_text}"]

        if isinstance(exc, CalledProcessError):
            details.append(f"exit code {exc.returncode}")

            stderr = CalibreDBClient._decode_output(exc.stderr)
            stdout = CalibreDBClient._decode_output(exc.output)

            if stderr and stderr.strip():
                details.append(f"stderr: {stderr.strip()}")
            if stdout and stdout.strip():
                details.append(f"stdout: {stdout.strip()}")
        elif isinstance(exc, TimeoutExpired):
            details.append(f"timed out after {exc.timeout} seconds")
        else:
            details.append(str(exc))

        return " | ".join(details)

    @staticmethod
    def _decode_output(data: str | bytes | None) -> str:
        """Normalize subprocess output to text."""
        if isinstance(data, str):
            return data
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return data or ""

    def _execute_command(
        self,
        command_args: str | list[str],
        fanfic: fanfic_info.FanficInfo | None = None,
        timeout: int | None = None,
    ) -> None:
        """Execute a calibredb command with locking and error logging.

        This method executes a command solely for its side effects (return code).
        Stdout and stderr are captured so failures can surface the real calibre
        error text in logs and history records.

        Args:
            command_args: The arguments to pass to calibredb (e.g., 'add "/path/to/file"').
            fanfic: Optional context for logging (story ID).
            timeout: Optional timeout in seconds.
        """
        id_str = fanfic.calibre_id if fanfic and fanfic.calibre_id else ""
        full_command = self._build_calibredb_command(command_args)

        ff_logging.log_debug(
            f'\tCalling calibredb with command: \t"{command_args} {id_str}"'
        )

        try:
            with self.cdb_info.lock:
                run(
                    full_command,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=True,
                )
        except (CalledProcessError, OSError, TimeoutExpired) as e:
            message = self._format_command_error(full_command, e)
            ff_logging.log_failure(
                f'\tCommand "{command_args} {id_str}" failed: {message}'
            )
            raise CalibreCommandError(message) from e

    def _execute_command_with_output(
        self,
        command_args: str | list[str],
        fanfic: fanfic_info.FanficInfo | None = None,
        timeout: int | None = None,
    ) -> str:
        """Execute a calibredb command and return its output.

        Args:
            command_args: The arguments to pass to calibredb.
            fanfic: Optional context.
            timeout: Optional timeout.

        Returns:
            str: The command output (stdout).

        Raises:
            CalibreCommandError: If the command fails.
        """
        full_command = self._build_calibredb_command(command_args)

        ff_logging.log_debug(f'\tCalling calibredb with command: \t"{command_args}"')

        try:
            with self.cdb_info.lock:
                output = check_output(
                    full_command, stderr=PIPE, timeout=timeout, text=True
                )
            return output
        except (CalledProcessError, OSError, TimeoutExpired) as e:
            message = self._format_command_error(full_command, e)
            ff_logging.log_failure(f'\tCommand "{command_args}" failed: {message}')
            raise CalibreCommandError(message) from e

    def get_story_id(self, fanfic: fanfic_info.FanficInfo) -> str | None:
        """Check if a story exists in Calibre and return its ID.

        Args:
            fanfic: The fanfic info containing the URL to search for.

        Returns:
            Optional[str]: The Calibre ID if found, None otherwise.
        """
        # Search by URL source identifier source:site:id
        # FanFicFare stores the source URL identifier in the 'source' identifier field

        try:
            search_query = f"Identifiers:{fanfic.url}"

            output = self._execute_command_with_output(["search", search_query])

            # calibredb search returns a comma-separated list of IDs (e.g., "1, 2, 3")
            ids = [x.strip() for x in output.split(",") if x.strip()]

            if ids:
                fanfic.calibre_id = ids[0]
                return fanfic.calibre_id

            ff_logging.log(f"\t({fanfic.site}) Story not in Calibre")
            return None

        except (CalledProcessError, OSError) as e:
            ff_logging.log(f"\t({fanfic.site}) Story not in Calibre")
            ff_logging.log_debug(f"\tError checking story ID: {e}")
            return None

    def add_story(self, location: str, fanfic: fanfic_info.FanficInfo) -> None:
        """Add a story to Calibre from a directory.

        Args:
            location: Directory containing the EPUB file.
            fanfic: Fanfic metadata (title will be updated from filename).
        """
        file_to_add = self._find_epub_in_directory(location)
        if not file_to_add:
            ff_logging.log_failure("No EPUB files found in the specified location.")
            return

        fanfic.title = regex_parsing.extract_filename(file_to_add)
        ff_logging.log(f"\t({fanfic.site}) Adding {file_to_add} to Calibre")

        # -d checks for duplicates (though we rely on our own checks too)
        # -d checks for duplicates (though we rely on our own checks too)
        try:
            output = self._execute_command_with_output(
                ["add", "-d", file_to_add], fanfic
            )

            # Parse output for "Added book ids: 123"
            # Typical output: "Added book ids: 123" or "Added book ids: 123, 124"
            match = re.search(r"Added book ids: ([\d, ]+)", output)
            if match:
                ids_str = match.group(1)
                ids = [x.strip() for x in ids_str.split(",") if x.strip()]
                if ids:
                    fanfic.calibre_id = ids[0]
                    ff_logging.log_debug(
                        f"\t({fanfic.site}) Added story with ID: {fanfic.calibre_id}"
                    )
            else:
                ff_logging.log_debug(
                    f"\t({fanfic.site}) Could not parse ID from add output: {output.strip()}"
                )

        except (CalledProcessError, OSError) as e:
            ff_logging.log_failure(f"\t({fanfic.site}) Failed to add story: {e}")
            raise

    def remove_story(self, fanfic: fanfic_info.FanficInfo) -> None:
        """Remove a story from Calibre.

        Args:
            fanfic: Fanfic info with calibre_id to remove.
        """
        if not fanfic.calibre_id:
            ff_logging.log_failure("\tCannot remove story: no calibre_id")
            return

        self._execute_command(["remove", str(fanfic.calibre_id)], fanfic)
        fanfic.calibre_id = None

    def export_story(self, fanfic: fanfic_info.FanficInfo, location: str) -> None:
        """Export a story to a directory.

        Args:
            fanfic: Fanfic to export.
            location: Target directory.
        """
        if not fanfic.calibre_id:
            ff_logging.log_failure("\tCannot export story: no calibre_id")
            return

        command = [
            "export",
            str(fanfic.calibre_id),
            "--dont-save-cover",
            "--dont-write-opf",
            "--single-dir",
            "--to-dir",
            location,
        ]
        self._execute_command(command, fanfic)

    def add_format_to_existing_story(
        self, location: str, fanfic: fanfic_info.FanficInfo
    ) -> bool:
        """Replace the EPUB format for an existing story.

        Args:
            location: Directory containing the new EPUB.
            fanfic: Fanfic info with calibre_id.

        Returns:
            bool: True if successful.
        """
        if not fanfic.calibre_id:
            ff_logging.log_failure("\tCannot add format: story has no calibre_id")
            return False

        file_to_add = self._find_epub_in_directory(location)
        if not file_to_add:
            ff_logging.log_failure("No EPUB files found in the specified location.")
            return False

        ff_logging.log(
            f"\t({fanfic.site}) Replacing EPUB format for ID {fanfic.calibre_id}"
        )

        try:
            # add_format takes the ID as a positional argument BEFORE the file path in some versions,
            # or the command is `add_format ID file`.
            # Let's check the CLI usage. `calibredb add_format [options] id file`
            full_command_args = [
                "add_format",
                str(fanfic.calibre_id),
                file_to_add,
            ]

            self._execute_command(full_command_args, fanfic)

            ff_logging.log(f"\t({fanfic.site}) Successfully replaced EPUB format")
            return True
        except (OSError, TimeoutExpired) as e:
            ff_logging.log_failure(
                f"\t({fanfic.site}) Failed to replace EPUB format: {e}"
            )
            raise

    def get_metadata(self, fanfic: fanfic_info.FanficInfo) -> dict[str, Any]:
        """Get all metadata for a story.

        Args:
            fanfic: Fanfic info with calibre_id.

        Returns:
            Dict: Metadata dictionary.
        """
        if not fanfic.calibre_id:
            ff_logging.log_failure("\tCannot get metadata: story has no calibre_id")
            return {}

        try:
            # We search by ID to get the specific record
            output = self._execute_command_with_output(
                [
                    "list",
                    "--for-machine",
                    "--fields=all",
                    f"--search=id:{fanfic.calibre_id}",
                ],
                fanfic,
            )

            metadata_list = json.loads(output)
            if metadata_list and len(metadata_list) > 0:
                metadata = metadata_list[0]
                ff_logging.log_debug(
                    f"\t({fanfic.site}) Retrieved metadata for ID {fanfic.calibre_id}: "
                    f"{len(metadata)} fields"
                )
                return metadata
            else:
                ff_logging.log_failure(
                    f"\tNo metadata found for ID {fanfic.calibre_id}"
                )
                return {}

        except (CalledProcessError, OSError, json.JSONDecodeError) as e:
            ff_logging.log_failure(
                f"\tFailed to retrieve metadata for ID {fanfic.calibre_id}: {e}"
            )
            return {}

    def set_metadata_fields(
        self,
        fanfic: fanfic_info.FanficInfo,
        metadata: dict[str, Any],
        fields_to_restore: list[str] | None = None,
    ) -> None:
        """Restore custom metadata fields.

        Args:
            fanfic: Fanfic info.
            metadata: Full metadata dictionary.
            fields_to_restore: Optional list of fields (defaults to all starting with #).
        """
        if not fanfic.calibre_id:
            ff_logging.log_failure("\tCannot set metadata: story has no calibre_id")
            return

        if not metadata:
            return

        if fields_to_restore is None:
            fields_to_restore = [k for k in metadata.keys() if k.startswith("#")]

        if not fields_to_restore:
            return

        ff_logging.log_debug(
            f"\t({fanfic.site}) Attempting to restore {len(fields_to_restore)} metadata fields"
        )

        restored_count = 0
        for field_name in fields_to_restore:
            if field_name not in metadata:
                continue

            field_value = metadata[field_name]
            if field_value is None or field_value == "":
                continue

            try:
                if isinstance(field_value, list):
                    value_str = ",".join(str(v) for v in field_value)
                else:
                    value_str = str(field_value)

                command = [
                    "set_custom",
                    field_name,
                    value_str,
                    str(fanfic.calibre_id),
                ]
                self._execute_command(command, fanfic)

                restored_count += 1
            except (OSError, TimeoutExpired) as e:
                ff_logging.log_failure(f"\t  Failed to restore field {field_name}: {e}")

        ff_logging.log_debug(
            f"\t({fanfic.site}) Successfully restored {restored_count}/{len(fields_to_restore)} metadata fields"
        )

    def log_metadata_comparison(
        self,
        fanfic: fanfic_info.FanficInfo,
        old_metadata: dict[str, Any],
        new_metadata: dict[str, Any],
    ) -> None:
        """Log comparison of metadata (helper method)."""
        # This logic is pure calculation/logging, so it fits here as a utility method on the client
        # or could remain valid as a static helper.
        if not old_metadata and not new_metadata:
            return

        ff_logging.log_debug(f"\t({fanfic.site}) Metadata Comparison Report")

        changed = []
        lost = []

        for field, old_val in old_metadata.items():
            if field in new_metadata:
                new_val = new_metadata[field]
                if old_val != new_val:
                    changed.append((field, str(old_val)[:50], str(new_val)[:50]))
            else:
                lost.append(field)

        new_fields = [k for k in new_metadata.keys() if k not in old_metadata]

        if changed:
            ff_logging.log_debug(f"\t  Fields Changed: {len(changed)}")
            for field, old_val, new_val in changed:
                ff_logging.log_debug(f"\t    ~ {field}: '{old_val}' → '{new_val}'")

        if lost:
            ff_logging.log_debug(f"\t  Fields Lost: {len(lost)}")
            for field in lost:
                ff_logging.log_debug(f"\t    ✗ {field}")

        if new_fields:
            ff_logging.log_debug(f"\t  New Fields Added: {len(new_fields)}")
            for field in new_fields:
                ff_logging.log_debug(f"\t    + {field}")

    def _find_epub_in_directory(self, location: str) -> str | None:
        """Helper to find first EPUB in directory."""
        epub_files = system_utils.get_files(
            location, file_extension="epub", return_full_path=True
        )
        return epub_files[0] if epub_files else None
