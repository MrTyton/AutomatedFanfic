"""
Test configuration and fixtures for the AutomatedFanfic test suite.

This conftest.py file automatically handles import path setup for all tests,
allowing direct imports of app modules without sys.path manipulation in individual test files.
"""

import sys
from pathlib import Path

# Add the app directory to the Python path so we can import modules directly
app_dir = Path(__file__).parent.parent / "app"
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))
