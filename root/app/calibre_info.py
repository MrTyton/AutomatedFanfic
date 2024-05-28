import multiprocessing as mp
import os
from subprocess import call

import ff_logging
import tomllib



class CalibreInfo:
    """
    This class represents the Calibre library information.
    It reads the configuration from a TOML file and provides access to the Calibre library details.
    """

    def __init__(self, toml_path: str, manager: mp.Manager):
        """
        Initialize the CalibreInfo object.

        Args:
            toml_path (str): The path to the TOML configuration file.
            manager (mp.Manager): A multiprocessing Manager instance.
        """
        # Open and load the TOML configuration file
        with open(toml_path, "rb") as file:
            config = tomllib.load(file)

        # Get the 'calibre' section from the configuration
        calibre_config = config.get("calibre", {})

        # If the 'path' key is not present in the 'calibre' section, log a failure and raise an exception
        if not calibre_config.get("path"):
            message = "Calibre library location not set in the config file. Cannot search the calibre library or update it."
            ff_logging.log_failure(message)
            raise ValueError(message)

        # Set the Calibre library details
        self.location = calibre_config.get("path")
        self.username = calibre_config.get("username")
        self.password = calibre_config.get("password")
        self.default_ini = self._get_ini_file(calibre_config, "default_ini", "defaults.ini")
        self.personal_ini = self._get_ini_file(calibre_config, "personal_ini", "personal.ini")
        # Create a lock for thread-safe operations
        self.lock = manager.Lock()

    @staticmethod
    def _append_filename(path: str, filename: str) -> str:
        """
        Append the filename to the path if it's not already there.

        Args:
            path (str): The original path.
            filename (str): The filename to append.

        Returns:
            str: The path with the filename appended.
        """
        # If the path is not None and does not already end with the filename, append the filename
        if path and not path.endswith(filename):
            return os.path.join(path, filename)
        return path
    
    
    def _get_ini_file(self, calibre_config: dict, config_key:str, default_filename: str):
        ini_file = self._append_filename(calibre_config.get(config_key), default_filename)
        if ini_file and not os.path.isfile(ini_file):
            ff_logging.log_failure(f"File {ini_file} does not exist.")
            ini_file = ""
        return ini_file

    # Check if Calibre is installed
    def check_installed(self) -> bool:
        try:
            # Try to call calibredb
            with open(os.devnull, "w") as nullout:
                call(["calibredb"], stdout=nullout, stderr=nullout)
            return True
        except OSError:
            # If calibredb is not found, log a failure and return False
            ff_logging.log_failure(
                "Calibredb is not installed on this system. Cannot search the calibre library or update it."
            )
            return False
        except Exception as e:
            # If any other error occurs, log a failure
            ff_logging.log_failure(f"Some other issue happened. {e}")
            return False

    # String representation of the object
    def __str__(self):
        repr = f' --with-library "{self.location}"'
        if self.username:
            repr += f' --username "{self.username}"'
        if self.password:
            repr += f' --password "{self.password}"'
        return repr