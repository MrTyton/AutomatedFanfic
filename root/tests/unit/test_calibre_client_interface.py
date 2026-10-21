import inspect
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
import pytest

from calibre_integration.calibre_info import CalibreInfo
from calibre_integration.client_interface import (
    CalibreClient,
    build_url_search_query,
    extract_story_base_url,
)
from calibre_integration.models import AddedBook, BookExport, MetadataUpdateReport
from config.config_store import ConfigStore
from models.fanfic_info import FanficInfo


class _DummyCalibreClient(CalibreClient):
    def __init__(self, cdb_info: CalibreInfo, config_store: ConfigStore) -> None:
        super().__init__(cdb_info, config_store)
        self.refreshed_count = 0

    def _on_config_refreshed(self) -> None:
        self.refreshed_count += 1

    def get_story_id(self, fanfic: FanficInfo) -> str | None:
        return "1"

    def add_story(self, location: str, fanfic: FanficInfo) -> AddedBook | None:
        return AddedBook(calibre_id="1", title="Test", formats=("EPUB",))

    def remove_story(self, fanfic: FanficInfo) -> bool:
        return True

    def export_story(self, fanfic: FanficInfo, location: str) -> BookExport | None:
        return BookExport(
            file_path=Path(f"{location}/1.epub"), format="EPUB", size_bytes=100
        )

    def add_format_to_existing_story(self, location: str, fanfic: FanficInfo) -> bool:
        return True

    def get_metadata(self, fanfic: FanficInfo) -> dict[str, Any]:
        return {"id": 1, "title": "Test"}

    def set_metadata_fields(
        self, fanfic: FanficInfo, metadata: dict[str, Any]
    ) -> MetadataUpdateReport:
        return MetadataUpdateReport(updated_fields=(), failed_fields=())

    def get_version(self) -> str:
        return "9.16.0"


def test_calibre_client_is_abstract() -> None:
    with pytest.raises(TypeError):
        CalibreClient(MagicMock(spec=CalibreInfo), MagicMock(spec=ConfigStore))  # type: ignore[abstract]


def test_calibre_client_abstract_methods() -> None:
    methods = {
        name
        for name, _ in inspect.getmembers(CalibreClient, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    expected_methods = {
        "get_story_id",
        "add_story",
        "remove_story",
        "export_story",
        "add_format_to_existing_story",
        "get_metadata",
        "set_metadata_fields",
        "get_version",
        "set_config_store",
        "refresh_if_changed",
        "log_metadata_comparison",
    }
    assert expected_methods.issubset(methods)


def test_extract_story_base_url_variations() -> None:
    # FFN chapter normalization (FanFicFare normalizes FFN stories to chapter 1: /s/<id>/1)
    assert (
        extract_story_base_url("https://www.fanfiction.net/s/12345/1/")
        == "fanfiction.net/s/12345/1"
    )
    assert (
        extract_story_base_url("https://m.fanfiction.net/s/12345/35/Some-Slug")
        == "fanfiction.net/s/12345/1"
    )
    assert (
        extract_story_base_url("fanfiction.net/s/12345") == "fanfiction.net/s/12345/1"
    )
    # AO3 chapter trimming
    assert (
        extract_story_base_url("https://archiveofourown.org/works/12345/chapters/67890")
        == "archiveofourown.org/works/12345"
    )
    # Royal Road chapter and slug trimming
    assert (
        extract_story_base_url("https://www.royalroad.com/fiction/12345/my-story")
        == "royalroad.com/fiction/12345"
    )
    # XenForo threads trimming
    assert (
        extract_story_base_url(
            "https://forums.spacebattles.com/threads/title.12345/page-2"
        )
        == "forums.spacebattles.com/threads/12345"
    )
    # eFiction query parameters
    assert (
        extract_story_base_url("https://site.com/viewstory.php?sid=1234&chapter=2")
        == "site.com/viewstory.php?sid=1234"
    )


def test_build_url_search_query_with_scheme() -> None:
    url = "https://archiveofourown.org/works/12345"
    query = build_url_search_query(url)
    assert (
        query
        == r'identifiers:"~(//|^)(www\d*\.|m\.)?archiveofourown\.org/works/12345([/&?#].*)?$"'
    )


def test_build_url_search_query_without_scheme() -> None:
    url = "royalroad.com/fiction/164248"
    query = build_url_search_query(url)
    assert (
        query
        == r'identifiers:"~(//|^)(www\d*\.|m\.)?royalroad\.com/fiction/164248([/&?#].*)?$"'
    )


def test_build_url_search_query_with_www_and_slash() -> None:
    url = "https://www.fanfiction.net/s/1234567/1/"
    query = build_url_search_query(url)
    assert (
        query
        == r'identifiers:"~(//|^)(www\d*\.|m\.)?fanfiction\.net/s/1234567/1([/&?#].*)?$"'
    )


def test_build_url_search_query_forum_thread() -> None:
    url = "https://forums.spacebattles.com/threads/title.12345/page-2"
    query = build_url_search_query(url)
    assert (
        query
        == r'identifiers:"~(//|^)(www\d*\.|m\.)?forums\.spacebattles\.com/threads/(.*\.)?12345([/&?#].*)?$"'
    )


def test_refresh_if_changed_invokes_hook_when_updated() -> None:
    mock_info = MagicMock(spec=CalibreInfo)
    mock_info.update_from_config_store.return_value = True
    mock_store = MagicMock(spec=ConfigStore)

    client = _DummyCalibreClient(mock_info, mock_store)
    client.refresh_if_changed()

    mock_info.update_from_config_store.assert_called_once_with(mock_store)
    assert client.refreshed_count == 1


@patch("calibre_integration.client_interface.ff_logging.log_debug")
def test_log_metadata_comparison(mock_log_debug: MagicMock) -> None:
    mock_info = MagicMock(spec=CalibreInfo)
    mock_store = MagicMock(spec=ConfigStore)
    client = _DummyCalibreClient(mock_info, mock_store)

    fanfic = FanficInfo(
        site="ao3", url="https://archiveofourown.org/works/1", calibre_id="1"
    )
    client.log_metadata_comparison(
        fanfic,
        {"#tag": "old", "#lost": "val", "same": "1"},
        {"#tag": "new", "#added": "val", "same": "1"},
    )
    assert mock_log_debug.called
