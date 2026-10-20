from unittest.mock import MagicMock, patch
import pytest

from calibre_integration.calibre_info import CalibreInfo
from calibre_integration.calibredb_utils import CalibreDBClient
from calibre_integration.factory import create_calibre_client
from calibre_integration.http_client import CalibreHttpClient
from calibre_integration.models import CalibreConfigurationError
from config.config_store import ConfigStore


def _mock_info(location: str) -> MagicMock:
    info = MagicMock(spec=CalibreInfo)
    info.location = location
    info.username = None
    info.password = None
    info.lock = MagicMock()
    return info


def test_factory_returns_http_client_for_http_and_https_urls() -> None:
    store = MagicMock(spec=ConfigStore)

    http_client = create_calibre_client(_mock_info("http://localhost:8080/#Lib"), store)
    assert isinstance(http_client, CalibreHttpClient)

    https_client = create_calibre_client(
        _mock_info("https://calibre.example.com/#Lib"), store
    )
    assert isinstance(https_client, CalibreHttpClient)


@patch("calibre_integration.factory.CalibreInfo.check_installed", return_value=True)
def test_factory_returns_calibredb_client_for_local_path_when_installed(
    mock_check: MagicMock,
) -> None:
    store = MagicMock(spec=ConfigStore)
    client = create_calibre_client(_mock_info("/calibre/library"), store)
    assert isinstance(client, CalibreDBClient)
    mock_check.assert_called_once()


@patch("calibre_integration.factory.CalibreInfo.check_installed", return_value=False)
def test_factory_raises_configuration_error_when_calibredb_missing(
    mock_check: MagicMock,
) -> None:
    store = MagicMock(spec=ConfigStore)
    with pytest.raises(CalibreConfigurationError) as exc_info:
        create_calibre_client(_mock_info("/calibre/library"), store)
    assert "calibredb" in str(exc_info.value)
    assert "standalone" in str(exc_info.value)
    mock_check.assert_called_once()
