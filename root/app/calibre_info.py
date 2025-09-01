import multiprocessing as mp
import os
from subprocess import call
import ff_logging  # Custom logging module for failure logging
from config_models import ConfigManager, ConfigError, ConfigValidationError


class CalibreInfo:
    """
    Manages Calibre library information, including paths and credentials, by
    reading from a TOML configuration file. This class provides methods to load
    configuration from a TOML file, check if Calibre is installed, and generate
    command line arguments for Calibre based on the loaded configuration.
    """

    def __init__(self, toml_path: str, manager):
        """
        Initializes the CalibreInfo object by loading the Calibre configuration from a
        TOML file.

        Args:
            toml_path (str): Path to the TOML configuration file.
            manager: A multiprocessing.Manager object to manage shared
                resources like locks.
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
        """
        Retrieves the ini file path from the configuration, verifying its existence.

        Args:
            config_path: The path from the configuration for the ini file.
            default_filename: The default filename to use if the path is not specified.

        Returns:
            str: The path to the ini file or an empty string if the file does not exist.
        """
        ini_file = self._append_filename(config_path, default_filename)
        if ini_file and not os.path.isfile(ini_file):
            ff_logging.log_failure(f"File {ini_file} does not exist.")
            return ""
        return ini_file

    @staticmethod
    def _append_filename(path: str | None, filename: str) -> str:
        """
        Appends the filename to the path if it's not already there.

        Args:
            path: The base path.
            filename: The filename to append to the path.

        Returns:
            str: The combined path with the filename appended.
        """
        if path and not path.endswith(filename):
            return os.path.join(path, filename)
        return path or ""

    @staticmethod
    def check_installed() -> bool:
        """
        Checks if Calibre is installed by attempting to call calibredb.

        Returns:
            bool: True if Calibre is installed, False otherwise.
        """
        try:
            with open(os.devnull, "w") as nullout:
                call(["calibredb"], stdout=nullout, stderr=nullout)
            return True
        except (OSError, Exception) as e:
            ff_logging.log_failure(f"Error checking Calibre installation: {e}")
            return False

    def __str__(self) -> str:
        """
        Provides a string representation of the CalibreInfo object for command line
        arguments.

        Returns:
            str: A string for command line arguments specifying Calibre library details.
        """
        parts = [f' --with-library "{self.location}"']
        if self.username:
            parts.append(f'--username "{self.username}"')
        if self.password:
            parts.append(f'--password "{self.password}"')
        return " ".join(parts)
