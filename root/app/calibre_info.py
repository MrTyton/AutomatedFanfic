"""Calibre library configuration and command interface management.

This module provides the CalibreInfo class for managing Calibre e-book library
configuration, authentication, and command-line interface integration within
the AutomatedFanfic application. It handles both local library paths and remote
Calibre server connections with comprehensive credential management.

Key Features:
    - TOML-based configuration loading with Pydantic validation
    - Support for both local Calibre libraries and remote Calibre servers
    - Secure credential management for server authentication
    - Thread-safe configuration access via multiprocessing locks
    - Command-line argument formatting for Calibre operations
    - Path validation and library accessibility verification

Classes:
    CalibreInfo: Complete Calibre configuration management with validation

The CalibreInfo class serves as the primary interface between the AutomatedFanfic
multiprocessing system and Calibre library operations, ensuring proper authentication
and configuration consistency across all worker processes.
"""

import os
from subprocess import call
import ff_logging  # Custom logging module for failure logging
from config_models import ConfigManager, ConfigError, ConfigValidationError


class CalibreInfo:
    """Manages Calibre library information and configuration for fanfiction processing.

    This class handles loading Calibre configuration from TOML files, validating
    paths and credentials, and providing formatted command-line arguments for
    Calibre operations. It manages both library location and optional authentication
    credentials, with thread-safe access through multiprocessing locks.

    The class automatically validates configuration files, checks for required
    INI files (defaults.ini and personal.ini), and provides utilities for
    verifying Calibre installation status.

    Attributes:
        location (str): Path to the Calibre library directory or server URL.
        username (str): Optional username for Calibre server authentication.
        password (str): Optional password for Calibre server authentication.
        update_method (str): Method for updating stories ('update', 'force', etc.).
        default_ini (str): Path to defaults.ini file for FanFicFare configuration.
        personal_ini (str): Path to personal.ini file for FanFicFare configuration.
        lock (multiprocessing.Lock): Thread-safe lock for concurrent access.
    """

    def __init__(self, toml_path: str, manager):
        """Initializes the CalibreInfo object by loading and validating Calibre configuration.

        This constructor loads configuration from the specified TOML file, validates
        all required settings, and sets up INI file paths for FanFicFare integration.
        It establishes a multiprocessing lock for thread-safe access and performs
        comprehensive validation of the Calibre library path and authentication settings.

        Args:
            toml_path (str): Path to the TOML configuration file containing Calibre settings.
            manager: A multiprocessing.Manager object used to create shared resources
            like locks for concurrent access protection.

        Raises:
            ValueError: If the configuration file cannot be loaded, is invalid, or if
            the Calibre library location is not specified in the configuration.
        """
        try:
            config = ConfigManager.load_config(toml_path)
        except (ConfigError, ConfigValidationError) as e:
            message = f"Failed to load configuration from {toml_path}: {e}"
            ff_logging.log_failure(message)
            raise ValueError(message)

        self.location = config.calibre.path
        if not self.location:
            message = "Calibre library location not set in the config file."
            ff_logging.log_failure(message)
            raise ValueError(message)

        self.username = config.calibre.username
        self.password = config.calibre.password
        self.update_method = config.calibre.update_method
        self.default_ini = self._get_ini_file_from_config(
            config.calibre.default_ini, "defaults.ini"
        )
        self.personal_ini = self._get_ini_file_from_config(
            config.calibre.personal_ini, "personal.ini"
        )
        self.lock = manager.Lock()

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
        ini_file = self._append_filename(config_path, default_filename)

        # Verify the file exists before returning the path
        if ini_file and not os.path.isfile(ini_file):
            ff_logging.log_failure(f"File {ini_file} does not exist.")
            return ""
        return ini_file

    @staticmethod
    def _append_filename(path: str | None, filename: str) -> str:
        """Appends the filename to the path if it's not already included.

        This utility method ensures that a given filename is properly appended to a
        directory path. If the path already ends with the filename, it returns the
        path unchanged. This prevents double-appending and ensures consistent file
        path construction for INI configuration files.

        Args:
            path (str | None): The base directory path where the file should be located.
                Can be None, in which case an empty string is returned.
            filename (str): The filename to append to the path. Should include the
                file extension (e.g., "defaults.ini", "personal.ini").

        Returns:
            str: The complete file path with filename appended, or an empty string
                if the input path was None or empty.
        """
        # Handle None or empty path cases
        if not path:
            return ""

        # Check if filename is already at the end of the path
        if not path.endswith(filename):
            # Safely join path and filename using os.path.join
            return os.path.join(path, filename)

        # Return original path if filename already present
        return path

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
            with open(os.devnull, "w") as nullout:
                # Attempt to call calibredb with no arguments to test availability
                call(["calibredb"], stdout=nullout, stderr=nullout)
            return True
        except (OSError, Exception) as e:
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
