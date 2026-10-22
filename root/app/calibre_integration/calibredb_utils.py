"""Calibre database interaction utilities for fanfiction management.

This module provides a client class for interacting with Calibre e-book databases
through the calibredb command-line interface. It handles story addition, export,
metadata queries, and library management operations with comprehensive error handling
and multiprocessing-safe locking mechanisms.
"""

import json
import re
import shlex
from pathlib import Path
from subprocess import (
    check_output,
    PIPE,
    DEVNULL,
    CalledProcessError,
    TimeoutExpired,
    run,
)

from . import calibre_info
from .client_interface import CalibreClient, CalibreMetadata, build_url_search_query
from .models import AddedBook, BookExport, CalibreOperationError, MetadataUpdateReport
from config.config_store import ConfigStore
from models import fanfic_info
from utils import ff_logging
from parsers import regex_parsing


class CalibreCommandError(CalibreOperationError):
    """Raised when a calibredb subprocess fails with captured output."""


class CalibreDBClient(CalibreClient):
    """Client for interacting with the Calibre database.

    Encapsulates all interactions with the calibredb CLI, including authentication,
    library path management, and concurrency locking.
    """

    def __init__(
        self,
        cdb_info: calibre_info.CalibreInfo,
        config_store: ConfigStore,
    ) -> None:
        """Initialize the CalibreDB client.

        Args:
            cdb_info (CalibreInfo): Configuration object containing library path,
                credentials, and lock.
            config_store (ConfigStore): Shared ConfigStore instance for hot-reloading
                Calibre settings before each CLI execution.
        """
        super().__init__(cdb_info, config_store)

    def get_version(self) -> str:
        """Return the Calibre version string via calibredb --version."""
        return self.get_calibre_version()

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
        # Hot-reload: sync calibre settings from ConfigStore before every call
        self.refresh_if_changed()

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
            if self.cdb_info.lock is not None:
                with self.cdb_info.lock:
                    run(
                        full_command,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        check=True,
                    )
            else:
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
            if self.cdb_info.lock is not None:
                with self.cdb_info.lock:
                    output = check_output(
                        full_command, stderr=PIPE, timeout=timeout, text=True
                    )
            else:
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
        try:
            search_query = build_url_search_query(fanfic.url)

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

    def add_story(
        self, location: str, fanfic: fanfic_info.FanficInfo
    ) -> AddedBook | None:
        """Add a story to Calibre from a directory.

        Args:
            location: Directory containing the EPUB file.
            fanfic: Fanfic metadata (title will be updated from filename).

        Returns:
            AddedBook | None: Added book record if added, None otherwise.
        """
        file_to_add = self._find_epub_in_directory(location)
        if not file_to_add:
            ff_logging.log_failure(
                f"\t({fanfic.site}) No EPUB file found in '{location}' for {fanfic.url}. "
                "FanFicFare may have failed silently — check the FanFicFare output above."
            )
            return None

        fanfic.title = regex_parsing.extract_filename(file_to_add)
        ff_logging.log(f"\t({fanfic.site}) Adding {file_to_add} to Calibre")

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
                    return AddedBook(
                        calibre_id=str(fanfic.calibre_id),
                        title=str(fanfic.title or ""),
                        formats=("EPUB",),
                    )
            ff_logging.log_debug(
                f"\t({fanfic.site}) Could not parse ID from add output: {output.strip()}"
            )
            return None

        except (CalledProcessError, OSError) as e:
            ff_logging.log_failure(f"\t({fanfic.site}) Failed to add story: {e}")
            raise

    def remove_story(self, fanfic: fanfic_info.FanficInfo) -> bool:
        """Remove a story from Calibre.

        Args:
            fanfic: Fanfic info with calibre_id to remove.

        Returns:
            bool: True if removed, False if calibre_id was missing.
        """
        if not fanfic.calibre_id:
            ff_logging.log_failure("\tCannot remove story: no calibre_id")
            return False

        self._execute_command(["remove", str(fanfic.calibre_id)], fanfic)
        fanfic.calibre_id = None
        return True

    def export_story(
        self, fanfic: fanfic_info.FanficInfo, location: str
    ) -> BookExport | None:
        """Export a story to a directory.

        Args:
            fanfic: Fanfic to export.
            location: Target directory.

        Returns:
            BookExport | None: Exported file record if exported, None otherwise.
        """
        if not fanfic.calibre_id:
            ff_logging.log_failure("\tCannot export story: no calibre_id")
            return None

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

        exported_file = self._find_epub_in_directory(location)
        if not exported_file:
            return None
        file_path = Path(exported_file)
        size_bytes = file_path.stat().st_size if file_path.exists() else 0
        return BookExport(file_path=file_path, format="EPUB", size_bytes=size_bytes)

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
            ff_logging.log_failure(
                f"\t({fanfic.site}) No EPUB file found in '{location}' for {fanfic.url}. "
                "FanFicFare may have failed silently — check the FanFicFare output above."
            )
            return False

        ff_logging.log(
            f"\t({fanfic.site}) Replacing EPUB format for ID {fanfic.calibre_id}"
        )

        try:
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

    def get_metadata(self, fanfic: fanfic_info.FanficInfo) -> CalibreMetadata:
        """Get all metadata for a story.

        Args:
            fanfic: Fanfic info with calibre_id.

        Returns:
            Dict: Metadata dictionary with custom columns normalized to `#` prefix.
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
                raw_metadata = metadata_list[0]
                metadata = {
                    ("#" + k[1:] if k.startswith("*") else k): v
                    for k, v in raw_metadata.items()
                }
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
        metadata: CalibreMetadata,
    ) -> MetadataUpdateReport:
        """Restore custom metadata fields.

        Args:
            fanfic: Fanfic info.
            metadata: Full metadata dictionary (restores all fields starting with #).

        Returns:
            MetadataUpdateReport: Report of updated and failed custom fields.
        """
        if not fanfic.calibre_id:
            ff_logging.log_failure("\tCannot set metadata: story has no calibre_id")
            return MetadataUpdateReport(updated_fields=(), failed_fields=())

        if not metadata:
            return MetadataUpdateReport(updated_fields=(), failed_fields=())

        fields_to_restore = [k for k in metadata.keys() if k.startswith("#")]

        if not fields_to_restore:
            return MetadataUpdateReport(updated_fields=(), failed_fields=())

        ff_logging.log_debug(
            f"\t({fanfic.site}) Attempting to restore {len(fields_to_restore)} metadata fields"
        )

        field_pairs: list[tuple[str, str]] = []
        for field_name in fields_to_restore:
            field_value = metadata[field_name]
            if field_value is None or field_value == "" or field_value == []:
                continue

            if isinstance(field_value, list):
                value_str = ",".join(str(v) for v in field_value)
            else:
                value_str = str(field_value)
            field_pairs.append((field_name, value_str))

        if not field_pairs:
            return MetadataUpdateReport(updated_fields=(), failed_fields=())

        updated_fields: list[str] = []
        failed_fields: list[str] = []
        batch_command = ["set_metadata", str(fanfic.calibre_id)]
        for field_name, value_str in field_pairs:
            batch_command.extend(["--field", f"{field_name}:{value_str}"])

        try:
            self._execute_command(batch_command, fanfic)
            updated_fields = [field_name for field_name, _ in field_pairs]
        except (OSError, TimeoutExpired) as batch_err:
            ff_logging.log_debug(
                f"\t({fanfic.site}) Batch set_metadata failed ({batch_err}), falling back to per-field set_custom"
            )
            for field_name, value_str in field_pairs:
                try:
                    command = [
                        "set_custom",
                        field_name.lstrip("#"),
                        str(fanfic.calibre_id),
                        value_str,
                    ]
                    self._execute_command(command, fanfic)
                    updated_fields.append(field_name)
                except (OSError, TimeoutExpired) as e:
                    failed_fields.append(field_name)
                    ff_logging.log_failure(
                        f"\t  Failed to restore field {field_name}: {e}"
                    )

        ff_logging.log_debug(
            f"\t({fanfic.site}) Successfully restored {len(updated_fields)}/{len(fields_to_restore)} metadata fields"
        )
        return MetadataUpdateReport(
            updated_fields=tuple(updated_fields),
            failed_fields=tuple(failed_fields),
        )
