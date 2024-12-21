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
        self.config = self._load_config(toml_path)
        self.location = self._get_config_value(
            "path", "Calibre library location not set in the config file."
        )
        self.username = self.config.get("username")
        self.password = self.config.get("password")
        self.default_ini = self._get_ini_file("default_ini", "defaults.ini")
        self.personal_ini = self._get_ini_file("personal_ini", "personal.ini")
        self.lock = manager.Lock()

    def _load_config(self, toml_path: str) -> dict:
        """
        Loads the configuration from a TOML file.

        Args:
            toml_path (str): Path to the TOML configuration file.

        Returns:
            dict: The loaded configuration.
        """
        try:
            with open(toml_path, "rb") as file:
                return tomllib.load(file).get("calibre", {})
        except (FileNotFoundError, tomllib.TOMLDecodeError) as e:
            message = f"Failed to load configuration from {toml_path}: {e}"
            ff_logging.log_failure(message)
            raise ValueError(message)

    def _get_config_value(self, key: str, error_message: str) -> str:
        """
        Retrieves a configuration value, raising an error if it is not found.

        Args:
            key (str): The configuration key to retrieve.
            error_message (str): The error message to log and raise if the key is not found.

        Returns:
            str: The configuration value.
        """
        value = self.config.get(key)
        if not value:
            ff_logging.log_failure(error_message)
            raise ValueError(error_message)
        return value

    def _get_ini_file(self, config_key: str, default_filename: str) -> str:
        """
        Retrieves the ini file path from the configuration, verifying its existence.

        Args:
            config_key (str): The key in the configuration for the ini file path.
            default_filename (str): The default filename to use if the path is not specified.

        Returns:
            str: The path to the ini file or an empty string if the file does not exist.
        """
        ini_file = self._append_filename(
            self.config.get(config_key), default_filename
        )
        if ini_file and not os.path.isfile(ini_file):
            ff_logging.log_failure(f"File {ini_file} does not exist.")
            return ""
        return ini_file

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
            return os.path.join(path, filename)
        return path

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
