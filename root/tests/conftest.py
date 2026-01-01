"""
Test configuration and fixtures for the AutomatedFanfic test suite.

This conftest.py file automatically handles import path setup for all tests,
allowing direct imports of app modules without sys.path manipulation in individual test files.
"""
import sys
import os

# Get the absolute path to the directory containing this file (root/tests)
TEST_DIR = os.path.dirname(os.path.abspath(__file__))

# Calculate the path to the app directory (root/app)
APP_DIR = os.path.abspath(os.path.join(TEST_DIR, "../app"))

# Add root/app to sys.path if not already present
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
