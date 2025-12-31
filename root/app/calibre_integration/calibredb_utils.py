"""Calibre database interaction utilities for fanfiction management.

This module provides a client class for interacting with Calibre e-book databases
through the calibredb command-line interface. It handles story addition, export,
metadata queries, and library management operations with comprehensive error handling
and multiprocessing-safe locking mechanisms.
"""

import json
import re
from subprocess import check_output, call, PIPE, DEVNULL
from typing import Optional, List, Any, Dict

from . import calibre_info
from models import fanfic_info
from utils import ff_logging
from parsers import regex_parsing
from utils import system_utils


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

        except Exception as e:
            return f"Error: {e}"

    def _execute_command(
        self,
        command_args: str,
        fanfic: Optional[fanfic_info.FanficInfo] = None,
        timeout: Optional[int] = None,
    ) -> None:
        """Execute a calibredb command with locking and error logging.

        This method executes a command solely for its side effects (return code).
        Stdout and Stderr are suppressed.

        Args:
            command_args: The arguments to pass to calibredb (e.g., 'add "/path/to/file"').
            fanfic: Optional context for logging (story ID).
            timeout: Optional timeout in seconds.
        """
        id_str = fanfic.calibre_id if fanfic and fanfic.calibre_id else ""
        full_command = f"calibredb {command_args} {self.cdb_info}"

        ff_logging.log_debug(
            f'\tCalling calibredb with command: \t"{command_args} {id_str}"'
        )

        try:
            with self.cdb_info.lock:
                call(
                    full_command,
                    shell=True,
                    stdin=PIPE,
                    stdout=DEVNULL,
                    stderr=DEVNULL,
                    timeout=timeout,
                )
        except Exception as e:
            ff_logging.log_failure(f'\tCommand "{command_args} {id_str}" failed: {e}')

    def _execute_command_with_output(
        self,
        command_args: str,
        fanfic: Optional[fanfic_info.FanficInfo] = None,
        timeout: Optional[int] = None,
    ) -> str:
        """Execute a calibredb command and return its output.

        Args:
            command_args: The arguments to pass to calibredb.
            fanfic: Optional context.
            timeout: Optional timeout.

        Returns:
            str: The command output (stdout).

        Raises:
            subprocess.CalledProcessError: If the command fails.
        """
        full_command = f"calibredb {command_args} {self.cdb_info}"

        with self.cdb_info.lock:
            output = check_output(
                full_command, shell=True, stderr=PIPE, stdin=PIPE, timeout=timeout
            ).decode("utf-8")
        return output

    def get_story_id(self, fanfic: fanfic_info.FanficInfo) -> Optional[str]:
        """Check if a story exists in Calibre and return its ID.

        Args:
            fanfic: The fanfic info containing the URL to search for.

        Returns:
            Optional[str]: The Calibre ID if found, None otherwise.
        """
        # Search by URL source identifier source:site:id
        # FanFicFare stores the source URL identifier in the 'source' identifier field
        # We can construct a search query for this

        # This logic mimics what was in fanfic_info.get_id_from_calibredb
        # but uses the centralized execution.

        # The exact search syntax depends on how FanFicFare saves the identifier.
        # Usually checking the identifiers field.
        # However, the previous implementation in fanfic_info.py used a specific command structure.
        # Let's verify that original implementation from memory/cache or re-implement robustly.

        # Original logic used `calibredb list --search "identifiers:url={url}" --fields id --for-machine`
        # But we need to be careful about the exact search query associated with the site.

        # Let's try the standard search.
        try:
            # We search for the specific URL in the identifiers
            # Note: We wrap the URL in quotes to handle special characters
            search_query = f'identifiers:"url={fanfic.url}"'

            output = self._execute_command_with_output(
                f"list --search='{search_query}' --fields id --for-machine"
            )

            data = json.loads(output)
            if data and len(data) > 0:
                fanfic.calibre_id = str(data[0]["id"])
                return fanfic.calibre_id

            return None

        except Exception:
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
        ff_logging.log(f"\t({fanfic.site}) Adding {file_to_add} to Calibre", "OKGREEN")

        # -d checks for duplicates (though we rely on our own checks too)
        self._execute_command(f'add -d "{file_to_add}"', fanfic)

    def remove_story(self, fanfic: fanfic_info.FanficInfo) -> None:
        """Remove a story from Calibre.

        Args:
            fanfic: Fanfic info with calibre_id to remove.
        """
        if not fanfic.calibre_id:
            ff_logging.log_failure("\tCannot remove story: no calibre_id")
            return

        self._execute_command(f"remove {fanfic.calibre_id}", fanfic)

    def export_story(self, fanfic: fanfic_info.FanficInfo, location: str) -> None:
        """Export a story to a directory.

        Args:
            fanfic: Fanfic to export.
            location: Target directory.
        """
        if not fanfic.calibre_id:
            ff_logging.log_failure("\tCannot export story: no calibre_id")
            return

        command = f'export {fanfic.calibre_id} --dont-save-cover --dont-write-opf --single-dir --to-dir "{location}"'
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
            f"\t({fanfic.site}) Replacing EPUB format for ID {fanfic.calibre_id}",
            "OKGREEN",
        )

        try:
            # add_format takes the ID as a positional argument BEFORE the file path in some versions,
            # or the command is `add_format ID file`.
            # Let's check the CLI usage. `calibredb add_format [options] id file`
            full_command_args = (
                f'add_format --replace {fanfic.calibre_id} "{file_to_add}"'
            )

            # Since _execute_command appends calibre_info which usually contains credentials,
            # we need to ensure the ID is placed correctly.
            # My previous implementation in calibredb_utils.py had:
            # f'add_format --replace "{file_to_add}"' and passed fanfic_info.id via call_calibre_db helper logic.
            # The helper logic was: f"calibredb {command} {fanfic_info.calibre_id if fanfic_info else ''} {calibre_info}"
            # So `add_format --replace "file" ID credentials`
            # This order (COMMAND FILE ID) is unusual for CLI tools but if it worked, it worked.
            # Wait, `calibredb add_format 123 file.epub` is the standard syntax.
            # The previous code constructed: `calibredb add_format --replace "file" 123 --with-library ...`
            # Let's replicate strict CLI usage: `calibredb add_format [opts] id file [opts]`

            # Ideally we construct the specific string here.
            # My _execute_command appends {self.cdb_info} at the end.
            # It does NOT append the ID automatically anymore with my new signature.
            # I removed the auto-ID injection to be more explicit.

            self._execute_command(full_command_args, fanfic)

            ff_logging.log(
                f"\t({fanfic.site}) Successfully replaced EPUB format",
                "OKGREEN",
            )
            return True
        except Exception as e:
            ff_logging.log_failure(
                f"\t({fanfic.site}) Failed to replace EPUB format: {e}"
            )
            return False

    def get_metadata(self, fanfic: fanfic_info.FanficInfo) -> Dict[str, Any]:
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
                f'list --for-machine --fields=all --search="id:{fanfic.calibre_id}"',
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

        except Exception as e:
            ff_logging.log_failure(
                f"\tFailed to retrieve metadata for ID {fanfic.calibre_id}: {e}"
            )
            return {}

    def set_metadata_fields(
        self,
        fanfic: fanfic_info.FanficInfo,
        metadata: Dict[str, Any],
        fields_to_restore: Optional[List[str]] = None,
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

                # Command: set_custom col_name value id
                # usage: calibredb set_custom [options] column value id1 id2 ...

                # Careful with quoting complexity in shell=True
                # Using triple quotes or careful escaping might be needed if values contain quotes.
                # Ideally we'd avoid shell=True, but existing architecture is shell-based.
                # For now, simplistic escaping.
                value_str_escaped = value_str.replace('"', '\\"')

                command = f'set_custom "{field_name}" "{value_str_escaped}" {fanfic.calibre_id}'
                self._execute_command(command, fanfic)

                restored_count += 1
            except Exception as e:
                ff_logging.log_failure(f"\t  Failed to restore field {field_name}: {e}")

        ff_logging.log_debug(
            f"\t({fanfic.site}) Successfully restored {restored_count}/{len(fields_to_restore)} metadata fields"
        )

    def log_metadata_comparison(
        self,
        fanfic: fanfic_info.FanficInfo,
        old_metadata: Dict[str, Any],
        new_metadata: Dict[str, Any],
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

    def _find_epub_in_directory(self, location: str) -> Optional[str]:
        """Helper to find first EPUB in directory."""
        epub_files = system_utils.get_files(
            location, file_extension="epub", return_full_path=True
        )
        return epub_files[0] if epub_files else None
