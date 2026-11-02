"""
Test configuration and fixtures for the AutomatedFanfic test suite.

This conftest.py file automatically handles import path setup for all tests,
allowing direct imports of app modules without sys.path manipulation in individual test files.
"""

import os
import sys

import pytest

# Get the absolute path to the directory containing this file (root/tests)
TEST_DIR = os.path.dirname(os.path.abspath(__file__))

# Calculate the path to the app directory (root/app)
APP_DIR = os.path.abspath(os.path.join(TEST_DIR, "../app"))

# Add root/app and root/tests to sys.path if not already present
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
if TEST_DIR not in sys.path:
    sys.path.insert(0, TEST_DIR)

import ff_logging  # noqa: E402


@pytest.fixture(autouse=True)
def reset_logging_state():
    """Ensure tests start and end with a clean logging state."""
    ff_logging.set_verbose(False)
    ff_logging.set_web_enabled(True)
    ff_logging.set_log_forward_queue(None)
    yield
    ff_logging.set_verbose(False)
    ff_logging.set_web_enabled(True)
    ff_logging.set_log_forward_queue(None)
