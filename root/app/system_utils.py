from contextlib import contextmanager
import os
from os.path import isfile, join
from shutil import copyfile, rmtree
from tempfile import mkdtemp

import calibre_info


@contextmanager
def temporary_directory():
    """
    Context manager for creating and automatically cleaning up a temporary
    directory.

    This function generates a temporary directory on the filesystem and ensures
    its removal after the context block exits, regardless of whether the block
    exits normally or throws an exception. This is useful for operations that
    require a temporary workspace that should not persist after the operation
    completes.

    Yields:
        str: The path to the temporary directory.
    """
    # Create a temporary directory
    temp_dir = mkdtemp()
    try:
        # Make the temporary directory available to the context block
        yield temp_dir
    finally:
        # Ensure the temporary directory is removed upon exiting the context
        rmtree(temp_dir)


def get_files(directory_path, file_extension=None, return_full_path=False):
    """
    Retrieves a list of files from the specified directory, optionally filtering by
    file extension.

    This function scans a given directory for files, optionally filtering the
    results to include only files with a specific extension. It can return either
    just the file names or the full paths to the files.

    Args:
        directory_path (str): The path of the directory to scan for files.
        file_extension (str, optional): If specified, filters the files to those
            ending with this extension. The extension should be provided without
            the leading dot ('.'). Defaults to None, which includes all files.
        return_full_path (bool, optional): Determines the format of the returned
            list. If True, each item in the list will be the full path to a file.
            If False, only the file names will be returned. Defaults to False.

    Returns:
        list of str: A list containing either the names or the full paths of the
            files found in the directory, depending on the value of
            `return_full_path`. If `file_extension` is specified, only files
            matching the extension will be included.
    """
    # Initialize an empty list to store the results
    files = []
    # Iterate over each file in the directory
    for file in os.listdir(directory_path):
        # Construct the full path of the file
        full_path = join(directory_path, file)

        # Check if the current item is a file and optionally if it matches the specified extension
        if isfile(full_path) and (
            file_extension is None or file.endswith(f"{file_extension}")
        ):
            # Depending on return_full_path, append either the full path or just the file name
            files.append(full_path if return_full_path else file)

    return files


def copy_configs_to_temp_dir(cdb: calibre_info.CalibreInfo, temp_dir: str) -> None:
    """
    Copies Calibre configuration files to a temporary directory.

    Args:
        cdb (calibre_info.CalibreInfo): The Calibre information object.
        temp_dir (str): The path to the temporary directory.
    """
    if cdb.default_ini:
        copyfile(cdb.default_ini, join(temp_dir, "defaults.ini"))
    if cdb.personal_ini:
        copyfile(cdb.personal_ini, join(temp_dir, "personal.ini"))
