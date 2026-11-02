"""
System Utilities for AutomatedFanfic

This module provides essential system-level utility functions for file system
operations and temporary directory management.
"""

from contextlib import contextmanager
import gc
import importlib.metadata
import os
from pathlib import Path
import platform
import shutil
from tempfile import mkdtemp

lazy import ctypes


@contextmanager
def temporary_directory():
    """
    Create and manage a temporary directory with automatic cleanup.

    Yields:
        str: Absolute path to the created temporary directory
    """
    temp_dir = mkdtemp()
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir)


def get_files(directory_path, file_extension=None, return_full_path=False):
    """
    Retrieve and optionally filter files from a directory.

    Args:
        directory_path (str): Path to the directory to scan.
        file_extension (str, optional): Filter files by this extension.
        return_full_path (bool, optional): If True, returns full absolute paths.

    Returns:
        list[str]: List of files matching the criteria.
    """
    files = []

    for file in os.listdir(directory_path):
        full_path = str(Path(directory_path) / file)

        if Path(full_path).is_file() and (
            file_extension is None or file.endswith(f"{file_extension}")
        ):
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


def is_docker_environment() -> bool:
    """Return True if executing inside a Docker container environment."""
    if os.path.exists("/.dockerenv") or os.environ.get("DOCKER_CONTAINER") == "true":
        return True
    cgroup = Path("/proc/1/cgroup")
    if cgroup.is_file():
        try:
            return "docker" in cgroup.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            pass
    return False


def get_installed_package_version(package_name: str) -> str:
    """Return installed package version via importlib.metadata or 'unknown'."""
    try:
        return importlib.metadata.version(package_name)
    except Exception:
        return "unknown"


def get_system_environment_summary() -> dict[str, str | bool]:
    """Return structured system, OS, and Python environment metadata."""
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "os": platform.system(),
        "arch": platform.machine(),
        "is_docker": is_docker_environment(),
    }
