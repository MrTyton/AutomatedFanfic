"""Factory for constructing the appropriate CalibreClient implementation."""

from calibre_integration import calibredb_utils
from calibre_integration.calibre_info import CalibreInfo
from calibre_integration.client_interface import CalibreClient
from calibre_integration.http_client import CalibreHttpClient
from calibre_integration.models import CalibreConfigurationError
from config.config_store import ConfigStore


def is_http_location(location: str) -> bool:
    """Return True if the configured Calibre location is an HTTP/HTTPS URL."""
    if not isinstance(location, str):
        return False
    normalized = location.strip().lower()
    return normalized.startswith(("http://", "https://"))


def create_calibre_client(
    cdb_info: CalibreInfo,
    config_store: ConfigStore,
) -> CalibreClient:
    """Instantiate `CalibreHttpClient` for HTTP URLs or `CalibreDBClient` for local paths.

    Args:
        cdb_info: Initialized CalibreInfo configuration object.
        config_store: Shared ConfigStore for runtime hot-reload.

    Returns:
        CalibreClient: Either a `CalibreHttpClient` or `CalibreDBClient` instance.

    Raises:
        CalibreConfigurationError: If `cdb_info.location` is a local directory path
            and `calibredb` is not installed in the current environment.
    """
    if is_http_location(cdb_info.location):
        return CalibreHttpClient(cdb_info, config_store)

    if cdb_info.check_installed() and CalibreInfo.check_installed():
        return calibredb_utils.CalibreDBClient(cdb_info, config_store)

    raise CalibreConfigurationError(
        f"Calibre library path '{cdb_info.location}' is a local filesystem directory, "
        "but the 'calibredb' binary is not installed in this environment. "
        "Either configure a Calibre Content Server URL (http://...) or run the "
        "standalone container image ('automated-ffdl:standalone')."
    )
