"""Calibre integration package providing CLI and HTTP clients for library management."""

from calibre_integration.calibre_info import CalibreInfo
from calibre_integration.calibredb_utils import CalibreDBClient
from calibre_integration.client_interface import CalibreClient
from calibre_integration.epub_utils import (
    extract_title_from_epub_path,
    log_epub_metadata,
)
from calibre_integration.factory import create_calibre_client, is_http_location
from calibre_integration.http_client import CalibreHttpClient

__all__ = [
    "CalibreInfo",
    "CalibreDBClient",
    "CalibreClient",
    "CalibreHttpClient",
    "extract_title_from_epub_path",
    "log_epub_metadata",
    "create_calibre_client",
    "is_http_location",
]
