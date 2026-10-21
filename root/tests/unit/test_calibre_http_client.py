import base64
import json
import pickle
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
import pytest
import requests

from calibre_integration.calibre_info import CalibreInfo
from calibre_integration.client_interface import CalibreClient, build_url_search_query
from calibre_integration.http_client import CalibreHttpClient
from calibre_integration.models import (
    AddedBook,
    BookExport,
    CalibreAuthError,
    CalibreConnectionError,
    MetadataUpdateReport,
)
from config.config_store import ConfigStore
from models.fanfic_info import FanficInfo


def _make_mock_info(
    location: str = "http://calibre.local:8080/#Fanfic",
    username: str | None = None,
    password: str | None = None,
) -> MagicMock:
    info = MagicMock(spec=CalibreInfo)
    info.location = location
    info.username = username
    info.password = password
    info.lock = MagicMock()
    info.lock.__enter__ = MagicMock(return_value=None)
    info.lock.__exit__ = MagicMock(return_value=None)
    info.update_from_config_store.return_value = False
    return info


def _make_response(
    status_code: int = 200,
    json_data: Any = None,
    content: bytes = b"",
    headers: dict[str, str] | None = None,
    text: str = "",
) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    if json_data is not None:
        raw = json.dumps(json_data).encode("utf-8")
        resp.content = raw
        resp.text = raw.decode("utf-8")
        resp.json.side_effect = lambda **kw: json.loads(resp.text, **kw)
    else:
        resp.content = content
        resp.text = text or content.decode("utf-8", errors="replace")
        resp.json.side_effect = ValueError("No JSON")
    return resp


def test_http_client_implements_interface_and_parses_url() -> None:
    assert issubclass(CalibreHttpClient, CalibreClient)
    info = _make_mock_info("http://calibre.local:8080/#My%20Library")
    client = CalibreHttpClient(info, MagicMock(spec=ConfigStore))
    assert client.base_url == "http://calibre.local:8080"
    assert client.library_id == "My Library"


def test_http_client_without_library_fragment() -> None:
    info = _make_mock_info("http://calibre.local:8080/")
    client = CalibreHttpClient(info, MagicMock(spec=ConfigStore))
    assert client.base_url == "http://calibre.local:8080"
    assert client.library_id == ""


def test_http_client_is_picklable_for_multiprocessing() -> None:
    from models.config_models import CalibreConfig

    class _DummyManager:
        @staticmethod
        def Lock() -> None:
            return None

    cfg = CalibreConfig(
        path="http://calibre.local:8080/#Fanfic",
        username="user",
        password="pass",
    )
    info = CalibreInfo(cfg, _DummyManager())
    store = ConfigStore()
    client = CalibreHttpClient(info, store)
    _ = client._get_session()
    restored: CalibreHttpClient = pickle.loads(pickle.dumps(client))
    assert restored.base_url == "http://calibre.local:8080"
    assert restored.library_id == "Fanfic"
    assert restored._get_session() is not None


def test_http_client_refresh_if_changed_reparses_url_and_auth() -> None:
    info = _make_mock_info("http://old:8080/#OldLib", "u1", "p1")
    store = MagicMock(spec=ConfigStore)
    client = CalibreHttpClient(info, store)
    _ = client._get_session()

    info.location = "http://new:9090/#NewLib"
    info.username = "u2"
    info.password = "p2"
    info.update_from_config_store.return_value = True

    client.refresh_if_changed()
    assert client.base_url == "http://new:9090"
    assert client.library_id == "NewLib"


def test_http_client_digest_auth_and_basic_fallback() -> None:
    from requests.auth import HTTPBasicAuth, HTTPDigestAuth

    info = _make_mock_info("http://calibre.local:8080/#Fanfic", "alice", "secret")
    client = CalibreHttpClient(info, MagicMock(spec=ConfigStore))
    session = client._get_session()
    assert isinstance(session.auth, HTTPDigestAuth)

    # Simulate 401 with WWW-Authenticate: Basic triggering fallback retry
    r401 = _make_response(
        401, headers={"WWW-Authenticate": 'Basic realm="calibre"'}, text="Unauthorized"
    )
    r200 = _make_response(
        200,
        json_data={"default_library": "Fanfic"},
        headers={"Server": "calibre 9.16.0"},
    )
    session.request = MagicMock(side_effect=[r401, r200])  # type: ignore[method-assign]

    version = client.get_version()
    assert version == "9.16.0"
    assert isinstance(session.auth, HTTPBasicAuth)
    assert session.request.call_count == 2


def test_http_client_auth_and_connection_errors() -> None:
    info = _make_mock_info("http://calibre.local:8080/#Fanfic", "alice", "wrong")
    client = CalibreHttpClient(info, MagicMock(spec=ConfigStore))
    session = client._get_session()

    r403 = _make_response(403, text="Forbidden")
    session.request = MagicMock(return_value=r403)  # type: ignore[method-assign]
    with pytest.raises(CalibreAuthError):
        client._request("POST", "/cdb/delete-books/1/Fanfic", json_body={})

    session.request = MagicMock(
        side_effect=requests.ConnectionError("Connection refused")
    )  # type: ignore[method-assign]
    with pytest.raises(CalibreConnectionError):
        client._request("POST", "/cdb/delete-books/1/Fanfic", json_body={})


def test_get_story_id_unwraps_calibre_canary_set() -> None:
    info = _make_mock_info("http://calibre.local:8080/#Fanfic")
    client = CalibreHttpClient(info, MagicMock(spec=ConfigStore))
    session = client._get_session()

    canary_payload = {"result": {"jPoAv3zOyHvQ5JFNYg4hJ9": 1, "v": [42, 43]}}
    session.request = MagicMock(
        return_value=_make_response(200, json_data=canary_payload)
    )  # type: ignore[method-assign]

    fanfic = FanficInfo(site="ao3", url="https://archiveofourown.org/works/12345")
    book_id = client.get_story_id(fanfic)

    assert book_id == "42"
    assert fanfic.calibre_id == "42"
    call_kwargs = session.request.call_args.kwargs
    sent_query = json.loads(call_kwargs["data"])
    assert sent_query == [build_url_search_query(fanfic.url)]


def test_add_story_uploads_bytes_and_returns_added_book(tmp_path: Path) -> None:
    epub_file = tmp_path / "My Story - Author.epub"
    epub_file.write_bytes(b"FAKE_EPUB_CONTENT")

    info = _make_mock_info("http://calibre.local:8080/#Fanfic")
    client = CalibreHttpClient(info, MagicMock(spec=ConfigStore))
    session = client._get_session()

    session.request = MagicMock(
        return_value=_make_response(
            200,
            json_data={"book_id": 77, "title": "My Story", "authors": ["Author"]},
        )
    )  # type: ignore[method-assign]

    fanfic = FanficInfo(site="ao3", url="https://archiveofourown.org/works/77")
    added = client.add_story(str(tmp_path), fanfic)

    assert isinstance(added, AddedBook)
    assert added.calibre_id == "77"
    assert added.title == "My Story"
    assert fanfic.calibre_id == "77"
    assert fanfic.title == "My Story"


def test_export_story_writes_epub_and_returns_book_export(tmp_path: Path) -> None:
    info = _make_mock_info("http://calibre.local:8080/#Fanfic")
    client = CalibreHttpClient(info, MagicMock(spec=ConfigStore))
    session = client._get_session()

    session.request = MagicMock(
        return_value=_make_response(
            200,
            content=b"EXPORTED_EPUB_BYTES",
            headers={
                "Content-Disposition": 'attachment; filename="Exported Story - Author_77.epub"'
            },
        )
    )  # type: ignore[method-assign]

    fanfic = FanficInfo(
        site="ao3", url="https://archiveofourown.org/works/77", calibre_id="77"
    )
    export = client.export_story(fanfic, str(tmp_path))

    assert isinstance(export, BookExport)
    assert export.file_path.exists()
    assert export.file_path.read_bytes() == b"EXPORTED_EPUB_BYTES"
    assert export.size_bytes == len(b"EXPORTED_EPUB_BYTES")
    assert export.format == "EPUB"


def test_add_format_to_existing_story_uses_set_fields_base64(tmp_path: Path) -> None:
    epub_file = tmp_path / "Updated.epub"
    epub_file.write_bytes(b"NEW_EPUB_BYTES")

    info = _make_mock_info("http://calibre.local:8080/#Fanfic")
    client = CalibreHttpClient(info, MagicMock(spec=ConfigStore))
    session = client._get_session()
    session.request = MagicMock(return_value=_make_response(200, json_data={"77": {}}))  # type: ignore[method-assign]

    fanfic = FanficInfo(
        site="ao3", url="https://archiveofourown.org/works/77", calibre_id="77"
    )
    ok = client.add_format_to_existing_story(str(tmp_path), fanfic)

    assert ok is True
    sent_body = json.loads(session.request.call_args.kwargs["data"])
    expected_b64 = base64.b64encode(b"NEW_EPUB_BYTES").decode("ascii")
    assert sent_body == {
        "changes": {"added_formats": [{"ext": "EPUB", "data_url": expected_b64}]}
    }


def test_remove_story_calls_delete_books() -> None:
    info = _make_mock_info("http://calibre.local:8080/#Fanfic")
    client = CalibreHttpClient(info, MagicMock(spec=ConfigStore))
    session = client._get_session()
    session.request = MagicMock(return_value=_make_response(200, json_data={}))  # type: ignore[method-assign]

    fanfic = FanficInfo(
        site="ao3", url="https://archiveofourown.org/works/77", calibre_id="77"
    )
    removed = client.remove_story(fanfic)

    assert removed is True
    assert fanfic.calibre_id is None
    assert "/cdb/delete-books/77/Fanfic" in session.request.call_args.args[1]


def test_get_metadata_and_set_metadata_fields() -> None:
    info = _make_mock_info("http://calibre.local:8080/#Fanfic")
    client = CalibreHttpClient(info, MagicMock(spec=ConfigStore))
    session = client._get_session()

    list_payload = {
        "result": {
            "book_ids": [77],
            "data": {
                "title": {"77": "My Story"},
                "*mytag": {"77": "custom1"},
                "#status": {"77": "Complete"},
            },
        }
    }
    session.request = MagicMock(
        return_value=_make_response(200, json_data=list_payload)
    )  # type: ignore[method-assign]

    fanfic = FanficInfo(
        site="ao3", url="https://archiveofourown.org/works/77", calibre_id="77"
    )
    meta = client.get_metadata(fanfic)
    assert meta == {
        "id": 77,
        "title": "My Story",
        "#mytag": "custom1",
        "#status": "Complete",
    }

    # Now test set_metadata_fields batch + per-field fallback
    session.request = MagicMock(
        side_effect=[
            _make_response(400, json_data={"err": "batch error"}),
            _make_response(200, json_data={"77": {}}),
            _make_response(400, json_data={"err": "bad field"}),
        ]
    )  # type: ignore[method-assign]
    report = client.set_metadata_fields(fanfic, meta)
    assert isinstance(report, MetadataUpdateReport)
    assert report.updated_fields == ("#mytag",)
    assert report.failed_fields == ("#status",)
    assert report.is_success is False


def test_http_client_missing_calibre_id_and_empty_branches(tmp_path: Path) -> None:
    info = _make_mock_info("http://calibre.local:8080")
    client = CalibreHttpClient(info, MagicMock(spec=ConfigStore))
    session = client._get_session()

    fanfic = FanficInfo(site="ao3", url="https://archiveofourown.org/works/99")
    assert client.remove_story(fanfic) is False
    assert client.export_story(fanfic, str(tmp_path)) is None
    assert client.add_format_to_existing_story(str(tmp_path), fanfic) is False
    assert client.get_metadata(fanfic) == {}
    assert client.set_metadata_fields(fanfic, {"#tag": "v"}).is_success is True

    # No EPUB in tmp_path
    assert client.add_story(str(tmp_path), fanfic) is None
    fanfic.calibre_id = "99"
    assert client.add_format_to_existing_story(str(tmp_path), fanfic) is False
    assert client.set_metadata_fields(fanfic, {}).is_success is True
    assert client.set_metadata_fields(fanfic, {"title": "NoHash"}).is_success is True

    # get_story_id when not found or connection error
    session.request = MagicMock(
        return_value=_make_response(200, json_data={"result": []})
    )  # type: ignore[method-assign]
    assert client.get_story_id(fanfic) is None

    session.request = MagicMock(side_effect=requests.ConnectionError("down"))  # type: ignore[method-assign]
    assert client.get_story_id(fanfic) is None
    assert client.get_version().startswith("Error:")
    assert client.get_metadata(fanfic) == {}
