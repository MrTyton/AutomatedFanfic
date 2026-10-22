"""Calibre library configuration and command interface management.

This module provides the CalibreInfo class for managing Calibre e-book library
configuration, authentication, and command-line interface integration within
the AutomatedFanfic application. It handles both local library paths and remote
Calibre server connections with comprehensive credential management.

Key Features:
    - Direct initialization from validated Pydantic CalibreConfig models
    - Support for both local Calibre libraries and remote Calibre servers
    - Secure credential management for server authentication
    - Thread-safe configuration access via multiprocessing locks
    - Command-line argument formatting for Calibre operations
    - Live configuration synchronization via ConfigStore

Classes:
    CalibreInfo: Complete Calibre configuration management with validation

The CalibreInfo class serves as the primary interface between the AutomatedFanfic
multiprocessing system and Calibre library operations, ensuring proper authentication
and configuration consistency across all worker processes.
"""

import os
from pathlib import Path
from subprocess import call
from multiprocessing.managers import SyncManager
from typing import ContextManager, Protocol

from config.config_store import ConfigStore
from models.config_models import CalibreConfig
from utils import ff_logging  # Custom logging module for failure logging
from utils.system_utils import resolve_ini_path


class LockFactory(Protocol):
    def Lock(self) -> ContextManager[object] | None: ...


class CalibreInfo:
    """Manages Calibre library information and configuration for fanfiction processing.

    This class stores validated Calibre configuration settings, resolves INI file
    paths, and provides formatted command-line arguments for Calibre operations.
    It manages both library location and optional authentication credentials,
    with thread-safe access through multiprocessing locks.

    Attributes:
        location (str): Path to the Calibre library directory or server URL.
        username (str | None): Optional username for Calibre server authentication.
        password (str | None): Optional password for Calibre server authentication.
        update_method (str): Method for updating stories ('update', 'force', etc.).
        metadata_preservation_mode (str): Strategy for preserving metadata during updates.
        default_ini (str): Resolved path to defaults.ini file for FanFicFare configuration.
        personal_ini (str): Resolved path to personal.ini file for FanFicFare configuration.
        lock (multiprocessing.Lock): Process/thread-safe lock for concurrent access.
    """

    def __init__(
        self,
        calibre_config: CalibreConfig,
        manager: SyncManager | LockFactory,
    ) -> None:
        """Initializes the CalibreInfo object from a validated CalibreConfig.

        Args:
            calibre_config (CalibreConfig): Validated Calibre configuration section
                containing library path, credentials, update method, and INI paths.
            manager (SyncManager): A multiprocessing.SyncManager used to create a
                shared Lock for concurrent access protection.

        Raises:
            ValueError: If the Calibre library location (`calibre_config.path`) is empty.
        """
        self.location = calibre_config.path
        if not self.location:
            message = "Calibre library location not set in the config file."
            ff_logging.log_failure(message)
            raise ValueError(message)

        self.username = calibre_config.username
        self.password = calibre_config.password
        self.update_method = calibre_config.update_method
        self.metadata_preservation_mode = calibre_config.metadata_preservation_mode
        self._raw_default_ini = calibre_config.default_ini
        self._raw_personal_ini = calibre_config.personal_ini
        self.default_ini = self._get_ini_file_from_config(
            calibre_config.default_ini, "defaults.ini"
        )
        self.personal_ini = self._get_ini_file_from_config(
            calibre_config.personal_ini, "personal.ini"
        )
        self._last_config_version: int | None = None
        self.lock: ContextManager[object] | None = manager.Lock()

    def _get_ini_file_from_config(
        self, config_path: str | None, default_filename: str
    ) -> str:
        """Retrieves and validates the INI file path from configuration settings.

        This method takes a configuration path and ensures it points to a valid INI file
        by appending the default filename if necessary and verifying the file exists.
        It's used to locate FanFicFare configuration files (defaults.ini and personal.ini)
        that control story processing behavior.

        Args:
            config_path (str | None): The configured path to the INI file, which may be
                a directory path, full file path, or None for default behavior.
            default_filename (str): The standard filename to append if config_path is
                a directory or to use if config_path is None.

        Returns:
            str: The validated path to the INI file, or an empty string if the file
                does not exist or cannot be located.
        """
        # Combine the config path with default filename if needed
        ini_file = resolve_ini_path(config_path, default_filename)

        # Verify the file exists before returning the path
        if ini_file and not Path(ini_file).is_file():
            ff_logging.log_failure(f"File {ini_file} does not exist.")
            return ""
        return ini_file

    def update_from_config_store(self, config_store: ConfigStore) -> bool:
        """Synchronize Calibre settings from a shared ConfigStore.

        Called by CalibreDBClient before each calibredb operation so changes
        made via the web dashboard take effect without restarting workers.

        Args:
            config_store (ConfigStore): Shared ConfigStore instance holding live
                configuration values.

        Returns:
            bool: True if any field on this CalibreInfo instance changed, False otherwise.
        """
        store_version = config_store.get("__version__")
        version_unchanged = (
            isinstance(store_version, int)
            and getattr(self, "_last_config_version", None) == store_version
        )
        if version_unchanged and self.default_ini and self.personal_ini:
            return False

        changed = False
        if not version_unchanged:
            mapping = {
                "location": "calibre.path",
                "username": "calibre.username",
                "password": "calibre.password",
                "update_method": "calibre.update_method",
                "metadata_preservation_mode": "calibre.metadata_preservation_mode",
            }
            for attr, key in mapping.items():
                val = config_store.get(key)
                if val is not None and val != getattr(self, attr, None):
                    setattr(self, attr, val)
                    changed = True

        # INI paths require resolution: the config store holds the raw user value
        # (which may be a directory like "/config"), but self.default_ini /
        # self.personal_ini must be resolved full-file paths. Only re-run
        # _get_ini_file_from_config when the raw setting or file existence changes
        # so missing optional files don't log an error on every calibredb call.
        for attr, raw_attr, key, filename in (
            ("default_ini", "_raw_default_ini", "calibre.default_ini", "defaults.ini"),
            (
                "personal_ini",
                "_raw_personal_ini",
                "calibre.personal_ini",
                "personal.ini",
            ),
        ):
            current_resolved = getattr(self, attr, "")
            if version_unchanged and current_resolved:
                continue
            raw = (
                getattr(self, raw_attr, None)
                if version_unchanged
                else config_store.get(key)
            )
            if isinstance(raw, str):
                candidate_path = resolve_ini_path(raw, filename)
                candidate_exists = bool(
                    candidate_path and Path(candidate_path).is_file()
                )
                raw_changed = raw != getattr(self, raw_attr, None)
                existence_changed = bool(current_resolved) != candidate_exists
                if raw_changed or existence_changed:
                    setattr(self, raw_attr, raw)
                    resolved = self._get_ini_file_from_config(raw, filename)
                    if resolved != current_resolved:
                        setattr(self, attr, resolved)
                        changed = True

        if isinstance(store_version, int):
            self._last_config_version = store_version

        return changed

    @staticmethod
    def check_installed() -> bool:
        """Checks if Calibre is installed and accessible via the calibredb command.

        This method verifies that the Calibre e-book library management tool is
        properly installed on the system by attempting to execute the calibredb
        command. It redirects output to prevent console noise during the check.

        Returns:
            bool: True if Calibre is installed and the calibredb command executes
                successfully, False if Calibre is not found or an error occurs.

        Note:
            This check only verifies that the calibredb executable can be called,
            not that it's functioning correctly or that the library is accessible.
        """
        try:
            # Redirect output to null to suppress command output during check
            with open(os.devnull, "w", encoding="utf-8") as nullout:
                # Attempt to call calibredb with no arguments to test availability
                call(["calibredb"], stdout=nullout, stderr=nullout)
            return True
        except OSError as e:
            # Log the specific error for debugging purposes
            ff_logging.log_failure(f"Error checking Calibre installation: {e}")
            return False

    def __str__(self) -> str:
        """Provides a formatted command-line argument string for Calibre operations.

        This method constructs the appropriate command-line arguments needed to
        interact with the Calibre library, including library location and optional
        authentication credentials. The resulting string can be used directly in
        subprocess calls to calibredb or other Calibre command-line tools.

        Returns:
            str: A formatted string containing Calibre command-line arguments,
                including --with-library, --username, and --password flags as
                needed. Arguments are properly quoted for shell safety.

        Example:
            For a local library: ' --with-library "/path/to/library"'
            For a server with auth: ' --with-library "http://server:8080"
                                   --username "user" --password "pass"'
        """
        # Start with the required library location argument
        parts = [f' --with-library "{self.location}"']

        # Add optional authentication arguments if provided
        if self.username:
            parts.append(f'--username "{self.username}"')
        if self.password:
            parts.append(f'--password "{self.password}"')

        # Join all parts into a single command-line string
        return " ".join(parts)
