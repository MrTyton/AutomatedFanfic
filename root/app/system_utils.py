"""
System Utilities for AutomatedFanfic

This module provides essential system-level utility functions for file system
operations, temporary directory management, and configuration file handling.
It serves as a lightweight abstraction layer over common OS operations needed
throughout the AutomatedFanfic application.

Key Features:
    - Safe temporary directory management with automatic cleanup
    - File system scanning and filtering by extension
    - Configuration file copying for Calibre integration
    - Context manager support for resource management

Design Philosophy:
    The utilities in this module follow the principle of "fail-safe" operations,
    ensuring that temporary resources are always cleaned up even in error
    conditions. This prevents disk space leaks and maintains system cleanliness.

Example:
    ```python
    from system_utils import temporary_directory, get_files

    # Safe temporary directory usage
    with temporary_directory() as temp_dir:
        # Directory automatically deleted when context exits
        epub_files = get_files(temp_dir, "epub", return_full_path=True)
        process_files(epub_files)

    # Directory is guaranteed to be cleaned up
    ```

Dependencies:
    - contextlib: For context manager implementation
    - tempfile: For temporary directory creation
    - shutil: For file and directory operations
    - calibre_info: For Calibre configuration structure

Thread Safety:
    All functions in this module are thread-safe for read operations.
    File system modifications should be coordinated by the caller when
    multiple threads access the same directory paths.
"""

from contextlib import contextmanager
import os
import shutil
from tempfile import mkdtemp

import calibre_info


@contextmanager
def temporary_directory():
    """
    Create and manage a temporary directory with automatic cleanup.

    This context manager provides a safe way to create and use temporary
    directories. The directory is automatically removed when the context
    exits, regardless of whether an exception occurred. This prevents
    temporary file system pollution and disk space leaks.

    Yields:
        str: Absolute path to the created temporary directory

    Example:
        ```python
        with temporary_directory() as temp_dir:
            # Create files in temp_dir
            temp_file = os.path.join(temp_dir, "work.txt")
            with open(temp_file, "w") as f:
                f.write("temporary work")

            # Process files...

        # temp_dir is automatically deleted here
        ```

    Note:
        The temporary directory is created using mkdtemp(), which creates
        a directory with permissions accessible only to the current user.
        All contents of the directory are recursively removed on cleanup.

    Thread Safety:
        Each call to this function creates a unique temporary directory,
        making it safe for concurrent use across multiple threads.
    """
    # Create a unique temporary directory with secure permissions
    temp_dir = mkdtemp()
    try:
        # Provide the directory path to the context block
        yield temp_dir
    finally:
        # Ensure cleanup happens even if an exception occurs
        shutil.rmtree(temp_dir)


def get_files(directory_path, file_extension=None, return_full_path=False):
    """
    Retrieve and optionally filter files from a directory.

    This function scans a directory for files, with optional filtering by
    file extension. It provides flexible output formatting to return either
    just filenames or full paths as needed by the caller.

    Args:
        directory_path (str): Path to the directory to scan. Must be a valid
                             directory path accessible to the current user.
        file_extension (str, optional): Filter files by this extension.
                                       Should be provided without the leading
                                       dot (e.g., "epub", "txt"). If None,
                                       all files are included.
        return_full_path (bool, optional): If True, returns full absolute paths.
                                          If False, returns only filenames.
                                          Defaults to False.

    Returns:
        list[str]: List of files matching the criteria. Content format depends
                  on return_full_path parameter:
                  - If return_full_path=True: ["/full/path/to/file1.ext", ...]
                  - If return_full_path=False: ["file1.ext", "file2.ext", ...]

    Example:
        ```python
        # Get all files in directory
        all_files = get_files("/path/to/dir")
        # Returns: ["file1.txt", "file2.epub", "file3.pdf"]

        # Get only EPUB files with full paths
        epub_files = get_files("/path/to/dir", "epub", return_full_path=True)
        # Returns: ["/path/to/dir/story1.epub", "/path/to/dir/story2.epub"]

        # Get text files (names only)
        txt_files = get_files("/path/to/dir", file_extension="txt")
        # Returns: ["notes.txt", "readme.txt"]
        ```

    Note:
        This function only returns regular files, not directories or special
        file system objects. Symbolic links to files are included if they
        point to valid files.

    Raises:
        OSError: If directory_path does not exist or is not accessible.
        PermissionError: If insufficient permissions to read the directory.
    """
    # Initialize list to collect matching files
    files = []

    # Scan all items in the specified directory
    for file in os.listdir(directory_path):
        # Build complete path for proper file type checking
        full_path = os.path.join(directory_path, file)

        # Filter for files only (exclude directories) and check extension if specified
        if os.path.isfile(full_path) and (
            file_extension is None or file.endswith(f"{file_extension}")
        ):
            # Add either full path or filename based on return_full_path setting
            files.append(full_path if return_full_path else file)

    return files


def copy_configs_to_temp_dir(cdb: calibre_info.CalibreInfo, temp_dir: str) -> None:
    """
    Copy Calibre configuration files to a temporary directory.

    This function safely copies Calibre's default and personal configuration
    files to a temporary directory, typically for use in isolated FanFicFare
    operations. Only existing configuration files are copied.

    Args:
        cdb (calibre_info.CalibreInfo): Calibre information object containing
                                       paths to configuration files. May have
                                       None values for missing config files.
        temp_dir (str): Destination directory path where configuration files
                       should be copied. Must be a valid, writable directory.

    Example:
        ```python
        from calibre_info import CalibreInfo

        calibre_info = CalibreInfo(library_path="/path/to/library")

        with temporary_directory() as temp_dir:
            copy_configs_to_temp_dir(calibre_info, temp_dir)
            # temp_dir now contains defaults.ini and personal.ini if they exist
            run_fanficfare_with_config(temp_dir)
        ```

    File Mapping:
        - cdb.default_ini -> {temp_dir}/defaults.ini
        - cdb.personal_ini -> {temp_dir}/personal.ini

    Note:
        This function silently skips copying any configuration files that
        don't exist (when cdb attributes are None). This allows for partial
        configuration setups where only some config files are available.

    Raises:
        OSError: If temp_dir is not writable or source files cannot be read.
        shutil.SameFileError: If source and destination are the same file.
    """
    # Copy default configuration if it exists
    if cdb.default_ini:
        shutil.copyfile(cdb.default_ini, os.path.join(temp_dir, "defaults.ini"))

    # Copy personal configuration if it exists
    if cdb.personal_ini:
        shutil.copyfile(cdb.personal_ini, os.path.join(temp_dir, "personal.ini"))
