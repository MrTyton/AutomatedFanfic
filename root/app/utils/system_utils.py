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
import functools
import os
from pathlib import Path
import shutil
from tempfile import mkdtemp
lazy import ctypes
lazy import fanficfare
import gc

# Removed top-level import to avoid circular dependency with models.config_models
# from calibre_integration import calibre_info


@functools.lru_cache(maxsize=1)
def get_packaged_defaults_ini_path() -> str:
    """Return the filesystem path to the packaged FanFicFare defaults.ini.

    Checks the installed fanficfare package directory.

    Returns:
        str: Absolute path to the packaged defaults.ini file, or empty string if not found.
    """
    try:
        fff_ini = Path(fanficfare.__file__).resolve().parent / "defaults.ini"
        if fff_ini.is_file():
            return str(fff_ini)
    except Exception:
        pass

    return ""


def resolve_ini_path(path: str | None, default_filename: str) -> str:
    """Resolve an INI file path, appending the filename if the path is a directory.

    This utility ensures that a configured path pointing to a directory is
    resolved to the full file path by appending the expected filename.  If the
    path already ends with the filename it is returned unchanged.  This is the
    single source of truth for INI path resolution used by both CalibreInfo
    initialization and the web configuration routes.

    When resolving `defaults.ini` and no path is configured (None or empty),
    it automatically falls back to the packaged FanFicFare `defaults.ini`.

    Args:
        path: The configured path which may be a directory, a full file path,
            or None/empty.
        default_filename: The standard filename to append when the path is a
            directory (e.g., "defaults.ini", "personal.ini").

    Returns:
        The resolved file path, or an empty string if the input path was
        None or empty (except for defaults.ini which falls back to the packaged file).
    """
    if not path:
        if default_filename == "defaults.ini":
            return get_packaged_defaults_ini_path()
        return ""

    # If path doesn't already end with the expected filename, append it
    if not path.endswith(default_filename):
        return str(Path(path) / default_filename)

    return path


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
        full_path = str(Path(directory_path) / file)

        # Filter for files only (exclude directories) and check extension if specified
        if Path(full_path).is_file() and (
            file_extension is None or file.endswith(f"{file_extension}")
        ):
            # Add either full path or filename based on return_full_path setting
            files.append(full_path if return_full_path else file)

    return files


def reclaim_memory() -> None:
    """Trigger Python garbage collection and return freed heap memory to the OS.

    Executes gc.collect() to clear cyclic garbage (e.g. BeautifulSoup / lxml DOMs),
    and on Linux invokes glibc's malloc_trim(0) to release unfragmented free pages
    back to the operating system kernel.
    """
    gc.collect()
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception:
        pass
