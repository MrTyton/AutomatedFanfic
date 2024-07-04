import multiprocessing as mp
import os
from subprocess import call

import ff_logging  # Custom logging module for failure logging
import tomllib  # Module for parsing TOML files


class CalibreInfo:
    """
    Manages Calibre library information, including paths and credentials, by
    reading from a TOML configuration file. This class provides methods to load
    configuration from a TOML file, check if Calibre is installed, and generate
    command line arguments for Calibre based on the loaded configuration.
    """

    def __init__(self, toml_path: str, manager: mp.Manager):
        """
        Initializes the CalibreInfo object by loading the Calibre configuration from a
        TOML file.

        Args:
            toml_path (str): Path to the TOML configuration file.
            manager (mp.Manager): A multiprocessing.Manager object to manage shared
                resources like locks.
        """
        # Load configuration from TOML file
        with open(toml_path, "rb") as file:
            config = tomllib.load(file)

        # Extract Calibre configuration section
        calibre_config = config.get("calibre", {})

        # Ensure the Calibre library path is specified
        if not calibre_config.get("path"):
            message = "Calibre library location not set in the config file."
            ff_logging.log_failure(message)  # Log failure using custom logging module
            raise ValueError(message)  # Raise an exception if the path is not set

        # Store configuration details
        self.location = calibre_config.get("path")
        self.username = calibre_config.get("username")
        self.password = calibre_config.get("password")
        self.default_ini = self._get_ini_file(
            calibre_config, "default_ini", "defaults.ini"
        )
        self.personal_ini = self._get_ini_file(
            calibre_config, "personal_ini", "personal.ini"
        )
        self.lock = manager.Lock()  # Create a lock for thread/process safety

    @staticmethod
    def _append_filename(path: str, filename: str) -> str:
        """
        Appends the filename to the path if it's not already there.

        Args:
            path (str): The base path.
            filename (str): The filename to append to the path.

        Returns:
            str: The combined path with the filename appended.
        """
        if path and not path.endswith(filename):
            return os.path.join(
                path, filename
            )  # Use os.path.join to ensure correct path formatting
        return path

    def _get_ini_file(
        self, calibre_config: dict, config_key: str, default_filename: str
    ) -> str:
        """
        Retrieves the ini file path from the configuration, verifying its existence.

        Args:
            calibre_config (dict): The Calibre configuration section from the TOML file.
            config_key (str): The key in the configuration for the ini file path.
            default_filename (str): The default filename to use if the path is not
                specified.

        Returns:
            str: The path to the ini file or an empty string if the file does not exist.
        """
        ini_file = self._append_filename(
            calibre_config.get(config_key), default_filename
        )
        if ini_file and not os.path.isfile(ini_file):
            ff_logging.log_failure(
                f"File {ini_file} does not exist."
            )  # Log failure if file does not exist
            return ""
        return ini_file

    @staticmethod
    def check_installed() -> bool:
        """
        Checks if Calibre is installed by attempting to call calibredb.

        Returns:
            bool: True if Calibre is installed, False otherwise.
        """
        try:
            # Try to call calibredb
            with open(os.devnull, "w") as nullout:
                call(["calibredb"], stdout=nullout, stderr=nullout)
            return True
        except OSError:
            # Log failure if OSError is caught
            ff_logging.log_failure("Calibredb is not installed on this system.")
            return False
        except Exception as e:
            # Log any other exceptions
            ff_logging.log_failure(f"Error checking Calibre installation: {e}")
            return False

    def __str__(self) -> str:
        """
        Provides a string representation of the CalibreInfo object for command line
        arguments.

        Returns:
            str: A string for command line arguments specifying Calibre library details.
        """
        repr = f' --with-library "{self.location}"'  # Include library location
        if self.username:
            repr += f' --username "{self.username}"'  # Include username if specified
        if self.password:
            repr += f' --password "{self.password}"'  # Include password if specified
        return repr
